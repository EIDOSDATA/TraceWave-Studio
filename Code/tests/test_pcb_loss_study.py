"""! @brief 독립 손실 연구의 PTH 계획, 단일 변화 축과 구형 호환성을 검사한다."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from rfad.application.pcb_loss_study import validate_study, plan_guard
from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan, validate_settings
from rfad.application.pcb_loss_components import validate_components, via_resolution
from rfad.application.pcb_mesh import mesh_lines
from rfad.domain.errors import ProjectError
from test_pcb_ifa import via_document
from test_pcb_solver import runtime_identity, snapshot_for


CODE_ROOT = Path(__file__).resolve().parents[1]


class LossStudyContractTests(unittest.TestCase):
    """! @brief 제조 물성 추정 없이 실제 원본에서 새 손실 조건을 계획한다."""

    def test_pth_all_levels_preserve_hole_material_and_fixed_boundaries(self):
        """! @brief PTH 체적 분할을 허용하고 같은 원본의 임계 구간 세 수준을 비교한다."""
        study = json.loads((CODE_ROOT / "fixtures/pth_loss_reference_study.json").read_text(encoding="utf-8"))
        validate_study(study)
        document = via_document()
        snapshot = snapshot_for(document)
        plans = [build_pcb_plan(document, snapshot, runtime_identity(), case["settings"]) for case in study["cases"]]
        for plan in plans:
            validate_pcb_plan(plan)
            self.assertTrue(plan["case"]["loss_recording"]["volume_conductor_supported"])
            self.assertEqual(plan["source_semantics"], document)
            self.assertAlmostEqual(plan["case"]["vias"][0]["inner_radius_mm"], 0.3)
            diagnostics = via_resolution(plan["case"], mesh_lines(plan["case"]))
            self.assertFalse(diagnostics[0]["skin_depth_loss_validated"])
            self.assertFalse(diagnostics[0]["frequencies"][0]["three_cells_per_skin_depth_condition_met"])
        for a, b in zip(plans, plans[1:]):
            self.assertTrue(plan_guard(a, b, "local_mesh")["passed"])

    def test_four_axis_manifest_and_invalid_joint_changes(self):
        """! @brief 사전 기준/순서/다중 변경을 native 시작 전에 검증한다."""
        study = json.loads((CODE_ROOT / "fixtures/pcb_loss_precision_study.json").read_text(encoding="utf-8"))
        validate_study(study)
        altered = deepcopy(study)
        altered["cases"][1]["settings"]["end_criterion"] = 1e-8
        with self.assertRaises(ProjectError):
            validate_study(altered)

    def test_feature_subdivision_rejects_bool_nan_and_excess(self):
        """! @brief 국부 격자 요청을 정수 예산과 최소 간격으로 한정한다."""
        study = json.loads((CODE_ROOT / "fixtures/pth_loss_study.json").read_text(encoding="utf-8"))
        for value in (True, 0, 9, 2.5, float("nan")):
            with self.subTest(value=value), self.assertRaises(ProjectError):
                validate_settings({**study["cases"][0]["settings"], "feature_subdivisions": value})

    def test_via_duplicate_sum_or_missing_identity_is_rejected(self):
        """! @brief 같은 비아 전력을 sheet 또는 유전체에 다시 더한 결과를 거절한다."""
        plan = {"case": {"vias": [{"id": "v"}], "layers": [{"id": "d", "role": "dielectric"}]}}
        row = {"sheet_loss_w_s2": 2.0, "via_loss_w_s2": 3.0, "conductor_loss_w_s2": 5.0, "dielectric_loss_w_s2": 4.0,
               "via_components": [{"entity_id": "v", "loss_w_s2": 3.0}], "dielectric_components": [{"entity_id": "d", "loss_w_s2": 4.0}]}
        validate_components(plan, row)
        for key, value in (("conductor_loss_w_s2", 8.0), ("dielectric_loss_w_s2", 7.0), ("via_components", [])):
            with self.subTest(key=key), self.assertRaises(ProjectError):
                validate_components(plan, {**row, key: value})

    def test_previous_plan_and_result_still_validate(self):
        """! @brief 구형 planar 계획/결과를 새 손실 필드로 덮어쓰지 않는다."""
        from test_pcb_power import power_plan, synthetic_result
        from rfad.application.pcb_power import validate_result

        plan = power_plan()
        self.assertEqual(plan["case"]["loss_recording"]["schema"], "rfad.pcb-loss-recording/0.1")
        result, radiation = synthetic_result(plan)
        validate_pcb_plan(plan)
        validate_result(plan, result, radiation)


if __name__ == "__main__":
    unittest.main()
