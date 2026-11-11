"""! @brief 독립 사례 후속 실행은 실패한 native를 재접수하거나 합격으로 바꾸지 않는다."""

from types import SimpleNamespace
import unittest

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_loss_convergence import initial_profile
from pcb_loss_execution import blocked_job, assess_available


class IndependentContinuationTests(unittest.TestCase):
    """! @brief 명시적 후속 진행에서도 종료 미확인과 누락 결과를 그대로 차단한다."""

    def test_only_confirmed_terminal_job_can_be_skipped(self):
        """! @brief 작업 ID/실패 상태/종료 근거를 유지하고 슬롯 예약 중에는 진행하지 않는다."""
        job = {"job_id": "j", "run_id": "r", "state": "failed", "events": [{"termination_confirmed": True, "outcome_unknown": False}], "solver": {"resource_reserved": False}}
        service = SimpleNamespace(journal=SimpleNamespace(read=lambda: {"jobs": {"j": job}}))
        entry = {"phases": {"analysis": {"task": {"job_id": "j"}}}}
        self.assertEqual(blocked_job(service, entry)["job_id"], "j")
        for target in ("reservation", "unknown"):
            job["solver"]["resource_reserved"] = target == "reservation"
            job["events"][-1]["outcome_unknown"] = target == "unknown"
            with self.subTest(target=target), self.assertRaises(ValueError):
                blocked_job(service, entry)

    def test_unsubmitted_case_does_not_create_a_job(self):
        """! @brief 실패 조회는 읽기만 하며 새 요청이나 대체 ID를 생성하지 않는다."""
        service = SimpleNamespace(journal=SimpleNamespace(read=lambda: {"jobs": {}}))
        self.assertIsNone(blocked_job(service, {"status": "pending"}))

    def test_missing_level_remains_unestablished_other_axis_can_be_assessed(self):
        """! @brief 완료한 종료 축과 미완료 격자 축을 섞어 전체 합격으로 선언하지 않는다."""
        cases = [{"label": str(index), "axis": "mesh", "settings": {"grid_mm": grid}} for index, grid in enumerate((0.5, 0.4, 0.3))]
        cases += [{"label": "t" + str(index), "axis": "termination", "settings": {"end_criterion": value}} for index, value in enumerate((1e-5, 1e-6, 1e-7))]
        power = {"full_energy_closure": "within_initial_numerical_budget", "frequencies": [{"frequency_hz": 2.4e9, "accepted_power_w_s2": 1.0,
                 "dielectric_loss_w_s2": 0.01, "conductor_loss_w_s2": 0.01, "sheet_components": [{"entity_id": "s", "loss_w_s2": 0.01}]}]}
        runs = {canonical_hash(case["settings"]): {"status": "completed", "power_balance": power} for case in cases}
        runs[canonical_hash(cases[2]["settings"])] = {"status": "blocked"}
        result = assess_available({"cases": cases, "acceptance_profile": initial_profile()}, runs)
        self.assertEqual(result["status"], "not_established")
        self.assertEqual(result["axes"]["termination"]["status"], "passed")
        self.assertEqual(result["axes"]["mesh"]["missing_cases"], ["2"])


if __name__ == "__main__":
    unittest.main()
