"""! @brief 공통 상태 전이가 늦은 완료/실패 및 취소 경쟁에서 이력을 보존하는지 확인한다."""

from copy import deepcopy
import unittest

from rfad.application.job_state import append_event
from rfad.domain.errors import ProjectError


class JobStateTests(unittest.TestCase):
    """! @brief 작업 실행 없이 상태 순서와 원자적 실패 경계를 검증한다."""

    def job(self, *states):
        """! @brief 실제 초기 작업과 같은 event 없는 레코드에서 시작한다."""
        job = {"run_id": "test-run", "events": [], "artifacts": []}
        for number, state in enumerate(states):
            append_event(job, state, 1000.0 + number)
        return job

    def test_late_completion_cannot_replace_cancelled_or_interrupted_history(self):
        """! @brief 취소/중단 뒤 도착한 완료 결과는 terminal 이력과 예약을 바꾸지 못한다."""
        for terminal in ("cancelled", "interrupted"):
            job = self.job("queued", "running", "cancel_requested", terminal)
            job["solver"] = {"resource_reserved": terminal == "interrupted"}
            original = deepcopy(job)
            with self.subTest(terminal=terminal), self.assertRaises(ProjectError) as error:
                append_event(job, "completed", 1010.0, operation_result={"artifact_id": "late"})
            self.assertEqual(error.exception.code, "E_CONFLICT")
            self.assertEqual(job, original)

    def test_success_cannot_be_overwritten_by_late_failure_or_restart(self):
        """! @brief 성공한 불변 결과는 늦은 오류 또는 재실행 상태로 되돌아가지 않는다."""
        job = self.job("queued", "running", "postprocessing")
        append_event(job, "completed", 1010.0, operation_result={"artifact_id": "sealed"})
        original = deepcopy(job)
        for state in ("failed", "running", "queued", "completed"):
            with self.subTest(state=state), self.assertRaises(ProjectError):
                append_event(job, state, 1020.0)
            self.assertEqual(job, original)

    def test_cancel_intent_cannot_become_success(self):
        """! @brief 취소가 먼저 commit되면 이후 성공을 직접 게시할 수 없다."""
        job = self.job("queued", "preparing", "cancel_requested")
        original = deepcopy(job)
        with self.assertRaises(ProjectError):
            append_event(job, "completed", 1010.0)
        self.assertEqual(job, original)
        append_event(job, "cancelled", 1011.0, termination_confirmed=True)
        self.assertEqual(job["events"][-1]["termination_confirmed"], True)

    def test_preparation_postprocessing_only_and_cancel_before_start_keep_order(self):
        """! @brief 서로 다른 합법 실행 경로도 같은 순서/식별 계약을 유지한다."""
        for states in (("queued", "preparing", "completed"), ("queued", "postprocessing", "completed"),
                       ("queued", "cancel_requested", "cancelled"), ("queued", "running", "failed")):
            job = self.job(*states)
            self.assertEqual([item["seq"] for item in job["events"]], list(range(1, len(states) + 1)))
            self.assertEqual([item["state"] for item in job["events"]], list(states))
            self.assertTrue(all(item["run_id"] == job["run_id"] for item in job["events"]))

    def test_extra_details_cannot_forge_event_identity(self):
        """! @brief 호출자의 부가 데이터가 event의 순서/실행 식별을 바꾸지 못한다."""
        for details in ({"seq": 99}, {"run_id": "other"}, {"phase": "completed"}, {"progress_basis": "estimated"}):
            job = self.job("queued")
            original = deepcopy(job)
            with self.subTest(details=details), self.assertRaises(ProjectError):
                append_event(job, "running", 1010.0, **details)
            self.assertEqual(job, original)

    def test_unknown_and_skipped_initial_states_preserve_job(self):
        """! @brief 알 수 없는 상태나 접수 생략을 검출해 부분 변경을 남기지 않는다."""
        for initial, following in ((None, "completed"), ("unknown", "running"), ("queued", "completed")):
            job = {"run_id": "test-run", "events": []}
            if initial is not None:
                job["state"] = initial
            original = deepcopy(job)
            with self.subTest(initial=initial, following=following), self.assertRaises(ProjectError):
                append_event(job, following, 1000.0)
            self.assertEqual(job, original)


if __name__ == "__main__":
    unittest.main()
