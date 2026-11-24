"""! @brief Smith 특이점과 비교 조건/실제 표본을 원본 불변 상태로 독립 검증한다."""

from copy import deepcopy
import math
from pathlib import Path
import unittest
from uuid import uuid4

from rfad.application.result_complex import compare_data, condition_differences, marker
from rfad.application.result_smith import project
from rfad.application.result_sources import solver_labels
from rfad.application.network_records import descriptor
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import make_dataset


def dataset(gammas, *, ports=1, **metadata):
    """! @brief 계산 규약을 명시한 해석식용 자료를 만들며 실측 주장은 하지 않는다."""
    values = [[[[float(gamma.real), float(gamma.imag)] if row == column else [0.0, 0.0]
                for column in range(ports)] for row in range(ports)] for gamma in gammas]
    arguments = {"z0_ohm": [[[50.0, 0.0] for _ in range(ports)] for _ in gammas],
        "wave_definition": "traveling", "phasor_convention": "exp(+j*omega*t)",
        "reference_planes": ["명시 시험 기준면"] * ports, "port_modes": ["single_ended"] * ports,
        "current_orientation": ["into_dut"] * ports, "sample_origin": ["computed"] * len(gammas),
        "conditions": {"manufacturing": None, "measurement": None}, "source_refs": ["해석식 경계 시험; 실측 아님"]}
    arguments.update(metadata)
    return make_dataset(parameter_kind="S", frequency_hz=[1e9 + i for i in range(len(gammas))],
        port_ids=[str(uuid4()) for _ in range(ports)], values_ri=values, **arguments)


def comparison(left, right, **options):
    """! @brief 같은 순서 포트 대응도 명시 요청으로 전달한다."""
    return compare_data(left, right, {"right_port_order": list(range(len(right["port_ids"]))),
        "row": 0, "column": 0, "offset": 0, "limit": 201, "frequency_policy": "exact_only", **options})


class ResultMathTests(unittest.TestCase):
    """! @brief 표시에 필요한 복소 계산만 검증하고 RF/실측 수용으로 확대하지 않는다."""

    def test_smith_match_open_short_and_active_preserve_original(self):
        """! @brief 정확한 Γ=0/1/-1 및 능동영역을 서로 다른 상태로 반환한다."""
        source = dataset([0j, 1 + 0j, -1 + 0j, 2 + 0j])
        before = deepcopy(source)
        rows = project(source)["points"]
        self.assertEqual(rows[0]["input_impedance_ohm_ri"], [50.0, 0.0])
        self.assertEqual(rows[0]["input_admittance_siemens_ri"], [0.02, 0.0])
        self.assertEqual(rows[1]["impedance_state"], "infinite")
        self.assertIsNone(rows[1]["input_impedance_ohm_ri"])
        self.assertEqual(rows[1]["input_admittance_siemens_ri"], [0.0, 0.0])
        self.assertEqual(rows[2]["input_impedance_ohm_ri"], [0.0, 0.0])
        self.assertEqual(rows[2]["admittance_state"], "infinite")
        self.assertEqual(rows[3]["gamma_ri"], [2.0, 0.0])
        self.assertEqual(rows[3]["passivity_region"], "active_region")
        self.assertEqual(rows[3]["input_impedance_ohm_ri"], [-150.0, 0.0])
        self.assertEqual(source, before)

    def test_smith_twoport_driving_input_is_not_z_matrix_diagonal(self):
        """! @brief 다른 포트 정합 조건의 입력 Z를 Z행렬 대각이라고 표시하지 않는다."""
        source = dataset([0.2 + 0.1j], ports=2)
        source["values_ri"][0][0][1] = [0.8, 0.0]
        source["values_ri"][0][1][0] = [0.7, 0.0]
        result = project(source)
        expected = 50 * (1 + complex(.2, .1)) / (1 - complex(.2, .1))
        self.assertAlmostEqual(result["points"][0]["input_impedance_ohm_ri"][0], expected.real)
        self.assertEqual(result["impedance_meaning"], "driving_point_input_not_z_matrix_diagonal")
        self.assertIn("matched", result["termination"])

    def test_smith_missing_basis_complex_z0_and_masks_never_supply_defaults(self):
        """! @brief 미정과 복소Z0를 50ohm이나 알려진 규약으로 대체하지 않는다."""
        cases = ({"wave_definition": "unknown"}, {"phasor_convention": "unknown"}, {"z0_ohm": None},
            {"z0_ohm": [[[50, 1]]]}, {"z0_ohm": [[[0, 0]]]}, {"port_modes": ["unknown"]})
        for change in cases:
            with self.subTest(change=change):
                source = dataset([.2j], **change)
                row = project(source)["points"][0]
                self.assertFalse(row["smith_valid"])
                self.assertIsNone(row["input_impedance_ohm_ri"])
                self.assertEqual(row["gamma_ri"], [0.0, .2])
        source = dataset([.2j], valid_mask=[[[False]]], sample_status=[[["singular"]]])
        self.assertIn("masked_sample", project(source)["points"][0]["reasons"])

    def test_smith_near_poles_and_overflow_are_not_exact_poles(self):
        """! @brief 작은 분모 및 매우 큰 결과를 정확한 개방/단락이나 0으로 바꾸지 않는다."""
        source = dataset([math.nextafter(1, 0) + 0j, complex(1e308, 1e308)])
        rows = project(source)["points"]
        self.assertEqual(rows[0]["impedance_state"], "finite")
        self.assertGreater(rows[0]["input_impedance_ohm_ri"][0], 1e17)
        self.assertTrue(rows[1]["smith_valid"])
        self.assertNotEqual(rows[1]["impedance_state"], "infinite")
        tiny = dataset([0j], z0_ohm=[[[math.ulp(0.0), 0.0]]])
        result = project(tiny)["points"][0]
        self.assertEqual(result["admittance_state"], "nonfinite")
        self.assertEqual(result["projection_status"], "nonfinite_projection")

    def test_compare_geometry_and_manufacturing_differences_do_not_block_math(self):
        """! @brief 설계 차이는 비교 목적이며 수학 전제와 물리 확인 상태를 분리한다."""
        left, right = dataset([.1j]), dataset([.2j], conditions={"manufacturing": {"roughness": "다른 가정"}})
        result = comparison(left, right)
        self.assertEqual(result["points"][0]["difference_ri"], [0.0, .1])
        self.assertEqual(result["difference_definition"], "right_minus_left")
        self.assertEqual(result["physical_comparability"]["status"], "not_established")
        def resolved(source, radius):
            return {"dataset": source, "descriptor": descriptor(source), "source_revision": {"label": "과거 입력"},
                    "selection_values": [], "source_document": {"geometry": [{"radius": radius}], "materials": [], "parameters": []}}
        changes = condition_differences(resolved(left, 1), resolved(right, 2))
        self.assertEqual(next(item for item in changes if item["field"] == "design.geometry")["difference"], "different")
        self.assertFalse(next(item for item in changes if item["field"] == "design.geometry")["affects_math"])
        self.assertEqual(next(item for item in changes if item["field"] == "conditions.measurement")["difference"], "both_unknown")
        self.assertEqual(next(item for item in changes if item["field"] == "z0_ohm")["left_display"], "50 ohm")

    def test_compare_explicit_port_mapping_and_exact_frequency(self):
        """! @brief 포트 순서를 명시하고 같은 실제 Hz가 없는 표본은 보간하지 않는다."""
        left, right = dataset([.1j, .2j], ports=2), dataset([.1j, .2j], ports=2)
        right["values_ri"][0][1][1] = [.4, 0.0]
        right["frequency_hz"][1] += 1
        result = comparison(left, right, right_port_order=[1, 0])
        self.assertEqual(result["points"][0]["difference_ri"], [.4, -.1])
        self.assertIsNone(result["points"][1]["difference_ri"])
        self.assertEqual(result["points"][1]["reasons"], ["frequency_missing"])
        self.assertFalse(marker(right, frequency_hz=1e9 + 1, row=0, column=0)["found"])
        self.assertTrue(marker(right, frequency_hz=1e9 + 2, row=0, column=0)["found"])

    def test_compare_unknown_basis_masked_and_overflow_return_reason(self):
        """! @brief 비교 불가를 유효한0차이나 같은조건으로 표시하지 않는다."""
        left = dataset([complex(1e308, 0)])
        right = dataset([complex(-1e308, 0)])
        self.assertIn("nonfinite_difference", comparison(left, right)["points"][0]["reasons"])
        for change in ({"reference_planes": [None]}, {"z0_ohm": None}, {"z0_ohm": [[[50, 2]]]},
                       {"wave_definition": "unknown"}):
            with self.subTest(change=change):
                self.assertIsNone(comparison(dataset([0j]), dataset([0j], **change))["points"][0]["difference_ri"])
        source = dataset([0j], valid_mask=[[[False]]], sample_status=[[["missing"]]])
        self.assertIn("masked_sample", comparison(source, dataset([0j]))["points"][0]["reasons"])

    def test_projection_bounds_are_strict(self):
        """! @brief bool 순번과 임의 주파수 정책, 큰 페이지를 명시 오류로 반환한다."""
        source = dataset([0j])
        for arguments in ({"offset": True}, {"limit": 202}, {"port": True}, {"chart": "fake"}):
            with self.subTest(arguments=arguments), self.assertRaises(ProjectError):
                project(source, **arguments)
        with self.assertRaises(ProjectError):
            comparison(source, source, frequency_policy="linear")
        with self.assertRaises(ProjectError):
            comparison(source, source, right_port_order=[True])

    def test_same_solver_description_uses_recorded_time_without_inventing_it(self):
        """! @brief 같은 설명도 순번으로 구분하고 완료/입력 봉인/시각 미정을 혼합하지 않는다."""
        ids = [str(uuid4()) for _ in range(3)]
        records = {identity: {"project_id": "owner", "snapshot": {"description": "같은 설명", "sealed_at": stamp},
                   "normalized": {"uri": identity}} for identity, stamp in zip(ids, (100, 200, None))}
        records[ids[0]]["metadata"] = {"installation_name": "사용자 설치 / 기준"}
        state = {"solver_results": records, "jobs": {"job": {"context": {"project_id": "owner"}, "events": [{
            "state": "completed", "timestamp": 150, "operation_result": {"artifact_id": ids[0],
            "normalized_result": records[ids[0]]["normalized"], "snapshot": records[ids[0]]["snapshot"]}}]}}}
        before = deepcopy(state)
        labels = solver_labels(state, "owner")
        self.assertEqual(len({item["label"] for item in labels.values()}), 3)
        self.assertEqual(len({item["short_label"] for item in labels.values()}), 3)
        self.assertIn("(사용자 설치 / 기준)", labels[ids[0]]["label"])
        self.assertNotIn(" / ", labels[ids[0]]["short_label"])
        self.assertNotIn(" / ", labels[ids[1]]["label"])
        self.assertEqual(labels[ids[0]]["source_time"], 150)
        self.assertEqual(labels[ids[0]]["source_time_kind"], "calculation_completed")
        self.assertEqual(labels[ids[1]]["source_time_kind"], "snapshot_sealed")
        self.assertIsNone(labels[ids[2]]["source_time"])
        self.assertIn("시각 미정", labels[ids[2]]["label"])
        self.assertEqual(state, before)


if __name__ == "__main__":
    unittest.main()
