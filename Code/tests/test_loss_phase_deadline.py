"""! @brief 장시간 손실 연구의 native 예산과 상위 단계 조회 한도를 함께 검증한다."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import verify_ifa_convergence as workflow


class LossPhaseDeadlineTests(unittest.TestCase):
    """! @brief 기존 420초 동작과 확장 900초 작업의 실제 완료 상태 판독을 구분한다."""

    def execute_after_500_seconds(self, budget):
        """! @brief 오래 실행한 동일 작업을 새로 접수하지 않고 상태만 조회한다."""
        data = {"budget": {"timeout_seconds": budget}}
        entry = {"phases": {"analysis": {"method": "job.submit", "input": deepcopy(data), "task": {"job_id": "original-job"}}}}
        status = {"state": "completed", "events": [{"state": "running"}, {"state": "completed", "operation_result": {"original": True}}]}
        with patch.object(workflow.time, "monotonic", side_effect=[0, 500]), patch.object(workflow, "call", return_value=status) as read:
            with patch.object(workflow, "save_report"):
                result = workflow.execute_phase(None, {}, Path("unused.json"), entry, "analysis", "job.submit", data, {})
            read.assert_called_once_with(None, "job.status", {"job_id": "original-job"})
        return result

    def test_extended_budget_is_not_cut_by_old_420_second_wait(self):
        """! @brief 500초에 완료한 900초 요청은 원래 작업의 성공 결과로 조회한다."""
        self.assertEqual(self.execute_after_500_seconds(900), {"original": True})

    def test_default_budget_keeps_previous_wait_limit(self):
        """! @brief 기본 300초 요청의 조회 한도까지 무제한으로 늘리지 않는다."""
        with self.assertRaisesRegex(RuntimeError, "제한 시간"):
            self.execute_after_500_seconds(300)


if __name__ == "__main__":
    unittest.main()
