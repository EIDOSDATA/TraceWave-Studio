"""! @brief 독립 손실 입력, 기존 호환성과 전력 합계/부호를 검사한다."""

from copy import deepcopy
import math
import unittest

from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan, validate_settings
from rfad.application.pcb_power import SCHEMA, NAMES, balance_rows, validate_result
from rfad.application.pcb_radiation import raw_names
from rfad.domain.errors import ProjectError
from test_pcb_radiation import radiation_plan, field_result
from test_pcb_solver import runtime_identity


def power_plan():
    """! @brief 실제 제조품과 구분되는 기존 합성 gap fixture를 사용한다."""
    original = radiation_plan()
    settings = deepcopy(original["case"]["settings"])
    settings["power_balance"] = {"max_relative_residual": 0.03}
    return build_pcb_plan(original["source_semantics"], original["snapshot"], runtime_identity(), settings)


def synthetic_result(plan, *, dielectric=0.05, conductor=0.05):
    """! @brief 독립 손실의 합계 계약을 검사하는 합성값이며 물리 증거가 아니다."""
    radiation = field_result(plan)
    entities = plan["case"]["shapes"]
    components = [{"entity_id": item["id"], "loss_w_s2": conductor / len(entities) * 1e-24} for item in entities]
    losses = [{"dielectric_loss_w_s2": dielectric * 1e-24, "conductor_loss_w_s2": conductor * 1e-24, "sheet_components": components}]
    recording = plan["case"]["loss_recording"]
    rows = balance_rows(recording, radiation, losses, 0.03)
    result = {"schema": SCHEMA, "analysis_plan_id": plan["plan_id"], "recording": deepcopy(recording),
              "frequencies": rows, "max_relative_residual": 0.03,
              "full_energy_closure": "within_initial_numerical_budget" if all(row["status"] == "within_initial_numerical_budget" for row in rows) else "requires_review",
              "power_unit": "W*s^2", "absolute_power_w": None,
              "physics_validated": False, "fabrication_validated": False, "measurement_validated": False}
    return result, radiation


class PowerContractTests(unittest.TestCase):
    """! @brief 임의 미정 물성을 채우지 않는 선택적 계약과 실패 상태를 확인한다."""

    def test_opt_in_retains_previous_plan(self):
        """! @brief 요청하지 않은 기존 방사에 기록/출력 파일을 추가하지 않는다."""
        old, plan = radiation_plan(), power_plan()
        self.assertNotIn("loss_recording", old["case"])
        self.assertEqual(set(raw_names(plan)) - set(raw_names(old)), set(NAMES))
        self.assertEqual(plan["case"]["loss_recording"]["dump_mode"], 0)
        validate_pcb_plan(plan)

    def test_recording_contains_whole_layer_with_air_and_resource_limit(self):
        """! @brief 필드 기록이 물체 전체를 감싸고 처음부터 크기 예산을 지킨다."""
        plan = power_plan()
        recording = plan["case"]["loss_recording"]
        self.assertLess(recording["start_mm"][2], 0)
        self.assertGreater(recording["stop_mm"][2], 1.035)
        self.assertLessEqual(recording["estimated_field_bytes"], 48 * 1024 * 1024)

    def test_invalid_threshold_and_absent_radiation_are_rejected(self):
        """! @brief bool/NaN/누락/과도한 tolerance를 허용하지 않는다."""
        settings = power_plan()["case"]["settings"]
        for value in (None, True, {}, {"max_relative_residual": True}, {"max_relative_residual": math.nan},
                      {"max_relative_residual": 0}, {"max_relative_residual": 0.11}, {"max_relative_residual": 0.03, "extra": 1}):
            with self.subTest(value=value), self.assertRaises(ProjectError):
                validate_settings({**settings, "power_balance": value})
        bad = deepcopy(settings)
        del bad["radiation"]
        with self.assertRaises(ProjectError):
            validate_settings(bad)

    def test_interpolated_port_frequency_is_rejected(self):
        """! @brief 방사 주파수가 포트 직접 표본과 다르면 수지를 만들지 않는다."""
        settings = deepcopy(power_plan()["case"]["settings"])
        settings["radiation"]["frequency_hz"] = [10.01e9]
        with self.assertRaises(ProjectError):
            validate_settings(settings)

    def test_independent_loss_closes_synthetic_balance(self):
        """! @brief 방사/유전체/도체의 분리 합계와 단위를 보존한다."""
        plan = power_plan()
        result, radiation = synthetic_result(plan)
        validate_result(plan, result, radiation)
        row = result["frequencies"][0]
        self.assertAlmostEqual(row["relative_residual"], 0, places=12)
        self.assertEqual(result["full_energy_closure"], "within_initial_numerical_budget")
        self.assertFalse(result["physics_validated"])

    def test_signed_excess_is_not_clipped(self):
        """! @brief 손실 초과/음수 독립 손실은 그대로 보존하며 검토 필요로 판정한다."""
        plan = power_plan()
        for dielectric, conductor in ((0.2, 0.1), (-0.02, 0.12)):
            result, radiation = synthetic_result(plan, dielectric=dielectric, conductor=conductor)
            validate_result(plan, result, radiation)
            self.assertEqual(result["full_energy_closure"], "requires_review")
        self.assertLess(synthetic_result(plan, dielectric=0.2, conductor=0.1)[0]["frequencies"][0]["residual_w_s2"], 0)

    def test_tampering_summary_or_components_is_rejected(self):
        """! @brief 다른 원본/손실 합계/단위/잔차/합격 승격을 차단한다."""
        plan = power_plan()
        result, radiation = synthetic_result(plan)
        for key, value in (("analysis_plan_id", "wrong"), ("power_unit", "W"), ("physics_validated", True), ("max_relative_residual", 0.1)):
            altered = deepcopy(result)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ProjectError):
                validate_result(plan, altered, radiation)
        for key in ("conductor_loss_w_s2", "dielectric_loss_w_s2", "relative_residual", "frequency_hz"):
            altered = deepcopy(result)
            altered["frequencies"][0][key] += 1
            with self.subTest(key=key), self.assertRaises(ProjectError):
                validate_result(plan, altered, radiation)


if __name__ == "__main__":
    unittest.main()
