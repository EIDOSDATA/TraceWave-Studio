"""! @brief 복소 자료 최종 검토에서 확인한 포트 대응과 선택 엔진 없는 복구를 검증한다."""

import base64
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from rfad.adapters import network_backend, network_hdf5
import test_network_service as fixtures


@unittest.skipUnless(network_backend.installation_metadata()["installed"] == network_backend.VERSIONS
                    and network_hdf5.installation_metadata()["version_matches"], "고정 선택 네트워크 환경이 필요함")
class NetworkReviewTests(unittest.TestCase):
    """! @brief 원본/영수증/읽기 경계를 실제 불변 저장소와 함께 확인한다."""

    def setUp(self):
        """! @brief 공용 fixture를 상속하지 않아 다른 시험을 중복 수집하지 않는다."""
        self.fixture = fixtures.NetworkServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def _two_port(self, reverse=False):
        """! @brief 비대칭 전달계수와 포트별 Z0/기준면을 함께 뒤집은 원문을 만든다."""
        parameters = fixtures.import_parameters()
        row = "0.4 0.04 0.2 0.02 0.3 0.03 0.1 0.01" if reverse else "0.1 0.01 0.3 0.03 0.2 0.02 0.4 0.04"
        reference = "75 50" if reverse else "50 75"
        raw = ("[Version] 2.1\n# Hz S RI R 50\n[Number of Ports] 2\n[Two-Port Data Order] 21_12\n"
               "[Number of Frequencies] 1\n[Reference] " + reference + "\n[Matrix Format] Full\n[Network Data]\n1e9 " + row + "\n[End]\n").encode("ascii")
        parameters.update(name="반대 순서" if reverse else "원래 순서", file_name="two.s2p", source_base64=base64.b64encode(raw).decode("ascii"))
        parameters["declarations"].update(reference_planes=["면 B", "면 A"] if reverse else ["면 A", "면 B"],
            port_modes=["single_ended"] * 2, current_orientation=["into_dut"] * 2)
        return self.fixture.apply("import", parameters)

    def test_explicit_two_port_permutation_applies_to_both_matrix_axes_and_z0(self):
        """! @brief 비대칭 S12/S21를 혼동하지 않고 두 축과 포트 조건을 같이 대응한다."""
        fixture = self.fixture
        left, right = self._two_port(), self._two_port(True)
        values = {"left_id": left, "right_id": right, "offset": 0, "limit": 201, "row": 0, "column": 1}
        compared = fixture.read("network.compare", **values, right_port_order=[1, 0])
        self.assertEqual(compared["points"][0]["difference_ri"], [0.0, 0.0])
        self.assertEqual(compared["points"][0]["status"], "comparable")
        refused = fixture.read("network.compare", **values, right_port_order=[0, 1])
        self.assertEqual(refused["points"][0]["status"], "not_comparable")
        self.assertIn("reference_planes_unknown_or_mismatch", refused["points"][0]["reasons"])

    def test_port_count_mismatch_is_reported_without_indexing_missing_port(self):
        """! @brief 다른 포트 수를 묵시적으로 축소하거나 예외로 중단하지 않는다."""
        fixture = self.fixture
        left = self._two_port()
        right = fixture.apply("import", fixtures.import_parameters())
        compared = fixture.read("network.compare", left_id=left, right_id=right, right_port_order=[0, 1], offset=0, limit=201, row=1, column=0)
        self.assertEqual(compared["points"][0]["reasons"], ["port_count_mismatch"])
        self.assertIsNone(compared["points"][0]["difference_ri"])

    def test_saved_network_and_undo_redo_reopen_do_not_require_native_engine(self):
        """! @brief 계산 엔진이 없어도 원본과 저장한 결과를 재열고 이력을 복원한다."""
        fixture = self.fixture
        source = fixture.apply("import", fixtures.import_parameters())
        circuit = fixture.apply("circuit_save", {"name": "저장 회로", "definition": fixtures.circuit_definition()})
        derived = fixture.apply("circuit_apply", {"name": "저장 결과", "dataset_id": source, "circuit_id": circuit})
        expected = fixture.read("network.get", dataset_id=derived, offset=0, limit=201, row=0, column=0)
        with patch.object(network_backend, "runtime", side_effect=AssertionError("불필요한 RF 엔진 로딩")), \
                patch.object(network_hdf5, "_runtime", side_effect=AssertionError("불필요한 HDF5 엔진 로딩")):
            fixture.history("undo")
            fixture.history("redo")
            fixture.save_reopen()
            actual = fixture.read("network.get", dataset_id=derived, offset=0, limit=201, row=0, column=0)
            self.assertEqual(actual, expected)
            self.assertEqual(len(fixture.read("network.library")["circuits"]), 1)

    def test_wrong_target_port_context_is_rejected_before_any_publish(self):
        """! @brief 자료 포트와 원본 목표 포트의 명시 대응을 바꿔치기할 수 없다."""
        fixture = self.fixture
        target = deepcopy(fixture.document()["targets"][0])
        source = fixture.apply("import", fixtures.import_parameters())
        view = fixture.read("network.get", dataset_id=source, offset=0, limit=201, row=0, column=0)
        parameters = {"name": "잘못된 목표 포트", "dataset_id": source, "target_id": target["id"],
                      "context": {"port_id": view["descriptor"]["port_ids"][0], "target_port_id": view["descriptor"]["port_ids"][0],
                                  "reference_plane": "시험 기준면", "frequency_policy": "exact_only"}}
        preview = fixture.preview("evaluate", parameters)
        self.assertFalse(preview["can_apply"])
        self.assertEqual(preview["issues"][0]["code"], "E_CONFLICT")
        self.assertEqual(fixture.read("network.library")["assessments"], [])

    def test_renormalization_preserves_reference_quantity_and_original_input(self):
        """! @brief 기준 임피던스의 원문/단위/추정 상태/출처를 SI 배열과 별도로 보존한다."""
        fixture = self.fixture
        source = fixture.apply("import", fixtures.import_parameters())
        quantity = {"value_si": 75.0, "dimension": "impedance", "display_unit": "kohm",
                    "status": "estimated", "source_refs": ["검토한 기준 임피던스 가정; 실제 측정 미정"]}
        for reference in (quantity, {"text": "0.075", "unit": "kohm", "source_refs": ["사용자가 입력한 원문 근거"]}):
            options = {"operation": "renormalize", "reference": deepcopy(reference)}
            identity = fixture.apply("transform", {"name": "기준 임피던스 사본", "dataset_id": source, "options": options})
            view = fixture.read("network.get", dataset_id=identity, offset=0, limit=201, row=0, column=0)
            raw = fixture.service.journal.read_artifact(view["entry"]["dataset"])
            dataset = json.loads(raw)
            operation = dataset["provenance"]["network_operations"][-1]
            self.assertEqual(operation["original_options"], options)
            self.assertEqual(operation["reference_quantity"]["value_si"], 75.0)
            self.assertEqual(operation["reference_quantity"]["display_unit"], "kohm")
            self.assertEqual(operation["reference_quantity"]["source_refs"], reference["source_refs"])
            self.assertEqual(operation["reference_quantity"]["status"], reference.get("status", "user_entered"))
            self.assertEqual(dataset["z0_ohm"], [[[75.0, 0.0]]] * 3)
            fixture.history("undo")
            fixture.history("redo")
            fixture.save_reopen()
            self.assertEqual(fixture.service.journal.read_artifact(view["entry"]["dataset"]), raw)


if __name__ == "__main__":
    unittest.main()
