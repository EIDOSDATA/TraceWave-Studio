"""! @brief 조정기 스레드 시작 실패에서도 서비스 정리를 완료할 수 있는지 확인한다."""

import unittest
from unittest.mock import patch

from rfad.application.cad_jobs import CadCoordinator
from rfad.application.solver_jobs import SolverCoordinator


class WorkerLifecycleTests(unittest.TestCase):
    """! @brief 시작되지 않은 스레드를 join하여 원래 오류를 가리지 않는다."""

    def test_thread_start_failure_can_close_each_coordinator(self):
        """! @brief OS 스레드 시작 실패 후 CAD/해석 조정기의 정리를 반복할 수 있다."""
        for coordinator_type in (CadCoordinator, SolverCoordinator):
            coordinator = coordinator_type(None, object())
            with self.subTest(coordinator=coordinator_type.__name__):
                with patch("threading.Thread.start", side_effect=RuntimeError("test start failure")):
                    with self.assertRaisesRegex(RuntimeError, "test start failure"):
                        coordinator.start()
                coordinator.close()
                coordinator.close()
                self.assertIsNone(coordinator.thread)
                self.assertTrue(coordinator.stop.is_set())
                self.assertTrue(coordinator.cancel.is_set())

    def test_unconfigured_coordinator_close_needs_no_native_runtime(self):
        """! @brief 조회 전용 서비스의 정리는 native 설치나 실행을 요구하지 않는다."""
        for coordinator_type in (CadCoordinator, SolverCoordinator):
            coordinator = coordinator_type(None, None)
            coordinator.start()
            coordinator.close()
            self.assertIsNone(coordinator.thread)


if __name__ == "__main__":
    unittest.main()
