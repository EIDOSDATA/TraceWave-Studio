"""! @brief 전력 표시의 표현 범위 초과와 미기록을 구분하고 봉인 원본을 보존한다."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_power import balance_rows, validate_result as validate_balance
from rfad.application.pcb_radiation import summary, validate_result
from rfad.application.radiation import spectral_power_metrics
from rfad.application.result_metrics import metrics
from rfad.domain.errors import ProjectError
from test_result_radiation import fixture


def bounded_fixture(radiated, accepted, incident, directivity, *, power=False):
    """! @brief 실제 검증기를 통과하는 합성 전력과 원문을 만들며 물리 검증으로 사용하지 않는다."""
    service, params, resolved, blobs, radiation = fixture(power=power)
    plan = resolved["normalized"]["provenance"]["analysis_plan"]
    for row in radiation["frequencies"]:
        row["metrics"] = spectral_power_metrics(radiated, accepted, incident, directivity)
        row["directivity"] = [[value * directivity for value in line] for line in row["normalized_power"]]
    validate_result(plan, radiation)
    resolved["normalized"]["radiation_summary"] = summary(radiation)
    blobs["radiation"] = canonical_bytes(radiation)
    if power:
        balance = resolved["normalized"]["power_balance"]
        losses = [{key: row[key] for key in ("dielectric_loss_w_s2", "conductor_loss_w_s2", "sheet_components")}
                  for row in balance["frequencies"]]
        balance["frequencies"] = balance_rows(plan["case"]["loss_recording"], radiation, losses,
                                             balance["max_relative_residual"])
        balance["full_energy_closure"] = "requires_review"
        validate_balance(plan, balance, radiation)
        blobs["balance"] = canonical_bytes(balance)
    return service, params, resolved, blobs


class ResultMetricsBoundsTests(unittest.TestCase):
    """! @brief 개별 표시 overflow가 다른 표본과 원본 조회를 막지 않는지 검사한다."""

    def checked_result(self, values):
        """! @brief 읽기 후 원본 객체와 봉인 바이트의 동일성을 공통 확인한다."""
        service, params, resolved, blobs = values
        before = deepcopy((resolved, blobs))
        with patch("rfad.application.result_metrics.resolve", return_value=resolved):
            result = metrics(service, params)
        self.assertEqual((resolved, blobs), before)
        self.assertEqual(result["source"], resolved["source"])
        self.assertEqual(result["pin"], resolved["pin"])
        self.assertIsNone(result["states"]["manufacturing"])
        self.assertIsNone(result["states"]["measurement"])
        self.assertFalse(result["physics_validated"])
        canonical_bytes(result)
        return result, {row["key"]: row for row in result["table_rows"]}

    def test_total_efficiency_overflow_keeps_other_metrics_and_originals(self):
        """! @brief 양의 유한 분모로 계산한 표현 범위 초과를 미기록과 구분한다."""
        result, table = self.checked_result(bounded_fixture(1.0, 1.0, 1e-310, 1e-300))
        row = result["rows"][0]
        self.assertIsNone(row["total_efficiency"])
        self.assertEqual(row["total_efficiency_state"], "overflow")
        self.assertEqual((table["total_efficiency"]["value"], table["total_efficiency"]["state"]), (None, "overflow"))
        self.assertEqual(table["total_efficiency"]["denominator"], "incident")
        self.assertEqual((table["residual"]["value"], table["residual"]["state"]), (None, "not_recorded"))
        self.assertEqual(row["incident"], 1e-310)
        self.assertEqual(row["radiated"], 1.0)
        self.assertEqual(table["radiation_efficiency"]["value"], 100.0)
        self.assertEqual(row["power_order_status"], "requires_review")
        self.assertTrue(any("표현 범위" in reason for reason in row["reasons"]))

    def test_percentage_overflow_retains_finite_ratio_and_nearby_finite_value(self):
        """! @brief 백분율로 바꿀 때만 넘친 비율을 원래 유한 값에서 지우지 않는다."""
        for ratio, state in ((1e305, "computed_unvalidated"), (1e307, "overflow")):
            with self.subTest(ratio=ratio):
                result, table = self.checked_result(bounded_fixture(ratio, 1.0, 1.0, 1e-307))
                row = result["rows"][0]
                self.assertEqual(row["radiation_efficiency"], ratio)
                self.assertEqual(row["total_efficiency"], ratio)
                self.assertEqual(row["total_efficiency_state"], "computed_unvalidated")
                for key in ("radiation_efficiency", "total_efficiency"):
                    self.assertEqual(table[key]["state"], state)
                    self.assertEqual(table[key]["value"], None if state == "overflow" else ratio * 100)
                self.assertEqual(row["power_order_status"], "requires_review")

    def test_signed_relative_residual_percentage_overflow_preserves_balance(self):
        """! @brief 큰 음의 잔차 비율과 독립 손실의 원문 및 검토 상태를 보존한다."""
        values = bounded_fixture(1.0, 1e-307, 1.0, 1e-307, power=True)
        original = deepcopy(values[2]["normalized"]["power_balance"]["frequencies"][0])
        result, table = self.checked_result(values)
        row = result["rows"][0]
        self.assertEqual(row["relative_residual"], original["relative_residual"])
        self.assertLess(row["relative_residual"], -1e306)
        self.assertEqual(row["residual"], original["residual_w_s2"])
        self.assertEqual(row["numerical_balance_status"], "requires_review")
        self.assertEqual((table["relative_residual"]["value"], table["relative_residual"]["state"]), (None, "overflow"))
        self.assertEqual(table["relative_residual"]["denominator"], "accepted")
        self.assertEqual(row["independent_losses"][0]["value"], original["dielectric_loss_w_s2"])

    def test_invalid_denominator_is_still_rejected_before_display(self):
        """! @brief 표시 overflow 처리가 원본의 0 또는 음수 전력 오류를 숨기지 않는다."""
        import json

        for incident in (0.0, -1.0):
            with self.subTest(incident=incident):
                service, params, resolved, blobs = bounded_fixture(1.0, 1.0, 1.0, 1.0)
                radiation = json.loads(blobs["radiation"])
                radiation["frequencies"][0]["metrics"]["incident_power_w_s2"] = incident
                blobs["radiation"] = canonical_bytes(radiation)
                resolved["normalized"]["radiation_summary"] = summary(radiation)
                before = deepcopy((resolved, blobs))
                with patch("rfad.application.result_metrics.resolve", return_value=resolved), self.assertRaises(ProjectError) as error:
                    metrics(service, params)
                self.assertEqual(error.exception.code, "E_SOLVER")
                self.assertEqual((resolved, blobs), before)
