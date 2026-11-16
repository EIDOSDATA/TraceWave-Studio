"""! @brief 정밀 편집/복소 자료 출처를 보존한 설계가 같은 PCB 물리 입력으로 계획되는지 확인한다."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application import network_service, precision_service
from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.network_library import KEY as NETWORK_KEY
from rfad.domain.precision_command import EXTENSION_KEY as PRECISION_KEY, MAX_ORIGIN_BYTES, record_hash
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture
from test_network_service import import_parameters
from test_pcb_solver import SETTINGS, fixture_document, runtime_identity, snapshot_for


class NetworkPlanCompatibilityTests(unittest.TestCase):
    """! @brief 실제 서비스가 저장한 출처를 solver 입력에서 제거하거나 임의 소비하지 않는다."""

    def setUp(self):
        """! @brief 물리 입력이 명시된 시험 기판에 실제 정밀 편집과 자료 가져오기를 적용한다."""
        self.temporary = TemporaryDirectory()
        self.service = ProjectService(Path(self.temporary.name), auto_run=False)
        original = fixture_document()
        metal = next(row for row in original["materials"] if row["id"] == original["stackup"][1]["material_id"])
        metal["epsilon_r"] = Quantity.missing("dimensionless", "1").to_dict()
        metal["tan_delta"] = Quantity.missing("dimensionless", "1").to_dict()
        original, _ = register_fixture(self.service, original)
        self.project = original["project_id"]
        radiator = next(row for row in original["geometry"] if row["role"] == "radiator")
        data = {"expected_revision": original["revision_id"], "selection_ids": [radiator["id"]],
                "operation": "dimension_set", "values": {"dimension_key": "line.length", "value": 4.6, "unit": "mm"}}
        preview = precision_service.read(self.service, "precision.preview", self.request(data))
        self.assertTrue(preview["can_apply"], preview)
        self.service.mutate("precision.apply", self.request({**data, "command_id": str(uuid4()),
                            "review_hash": preview["review_hash"], "reason": "내부 호환 시험; 실측 아님"}, mutation=True))
        current = self.document()
        data = {"expected_revision": current["revision_id"], "operation": "import", "parameters": import_parameters(declared=False)}
        preview = network_service.read(self.service, "network.preview", self.request(data))
        self.assertTrue(preview["can_apply"], preview)
        self.service.mutate("network.apply", self.request({**data, "command_id": str(uuid4()),
                            "review_hash": preview["review_hash"]}, mutation=True))

    def tearDown(self):
        """! @brief 시험이 소유한 저장소만 닫고 임시 파일을 회수한다."""
        self.service.close()
        self.temporary.cleanup()

    def request(self, data, *, mutation=False):
        """! @brief 공개 서비스의 프로젝트/영수증 경계를 그대로 사용한다."""
        value = {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": data}
        if mutation:
            value.update(request_key=str(uuid4()), request_key_epoch=self.service.policy()["request_key_epoch"])
        return value

    def document(self):
        """! @brief 서비스의 현재 영구 원본을 읽는다."""
        return self.service._load(self.service.journal.read()["projects"][self.project])

    def test_real_saved_metadata_preserves_source_and_same_physical_plan(self):
        """! @brief 저장된 복소 자료와 기하 편집 사본을 포함해도 물리 투영은 동일하다."""
        document = self.document()
        self.assertIn(NETWORK_KEY, document["extensions"])
        self.assertIn(PRECISION_KEY, document["extensions"])
        before = canonical_bytes(document)
        original_state = self.service.journal.read()
        entry = document["extensions"][NETWORK_KEY]["datasets"][0]
        raw = self.service.journal.read_artifact(entry["raw"])
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        validate_pcb_plan(plan)
        bare = deepcopy(document)
        bare["extensions"].pop(NETWORK_KEY)
        bare["extensions"].pop(PRECISION_KEY)
        comparison = build_pcb_plan(bare, snapshot_for(bare), runtime_identity(), SETTINGS)
        for field in ("case", "normalization", "resource_estimate", "model_report", "validation_policy"):
            self.assertEqual(plan[field], comparison[field], field)
        self.assertEqual(plan["source_semantics"], document)
        self.assertEqual(canonical_bytes(document), before)
        self.assertEqual(self.service.journal.read(), original_state)
        self.assertEqual(self.service.journal.read_artifact(entry["raw"]), raw)
        self.assertTrue(any(row["epsilon_r"]["value_si"] is None for row in plan["source_semantics"]["materials"]))

    def test_unknown_or_malformed_metadata_remains_rejected(self):
        """! @brief 알려진 이름만 붙인 잘못된 사본과 미지 확장을 통과시키지 않는다."""
        for change in ("unknown", "network_version", "origin_hash"):
            with self.subTest(change=change):
                document = self.document()
                if change == "unknown":
                    document["extensions"]["unknown.physical_model"] = {"fabrication": None}
                elif change == "network_version":
                    document["extensions"][NETWORK_KEY]["schema"] = "rfad.network-library/999"
                else:
                    document["extensions"][PRECISION_KEY]["records"][0]["record_hash"] = "0" * 64
                before = canonical_bytes(document)
                with self.assertRaises(ProjectError) as caught:
                    build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
                self.assertEqual(caught.exception.code, {"unknown": "E_UNSUPPORTED", "network_version": "E_VERSION",
                                                         "origin_hash": "E_HASH"}[change])
                self.assertEqual(canonical_bytes(document), before)

    def test_large_valid_origin_keeps_existing_plan_budget(self):
        """! @brief 유효한 큰 출처도 삭제하지 않으며 기존 256 KiB 계획 한계에서 차단한다."""
        document = self.document()
        origin = document["extensions"][PRECISION_KEY]
        record = origin["records"][0]
        notes = record["values"]["preserved_notes"] = []
        while len(canonical_bytes(origin)) < 248 * 1024:
            notes.append("x" * 4096)
        record["record_hash"] = record_hash(record)
        self.assertLessEqual(len(canonical_bytes(origin)), MAX_ORIGIN_BYTES)
        validate_project(document)
        before = canonical_bytes(document)
        with self.assertRaisesRegex(ProjectError, "256 KiB") as caught:
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        self.assertEqual(canonical_bytes(document), before)


if __name__ == "__main__":
    unittest.main()
