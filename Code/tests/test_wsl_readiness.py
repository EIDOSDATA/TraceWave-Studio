"""! @brief WSL 준비 대기와 계산 접수의 경계 및 취소를 검사한다."""

import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from rfad.application.wsl_process import WslRuntime, _run_control
from rfad.domain.errors import ProjectError


class WslReadinessTests(unittest.TestCase):
    """! @brief cold start용 준비는 계산을 접수하지 않는 고정 명령이다."""

    def test_fixed_probe_has_separate_startup_budget(self):
        """! @brief 준비에는 긴 시작 예산을 주고 기존 제어 예산은 유지한다."""
        runtime = WslRuntime(control_timeout_seconds=10, startup_timeout_seconds=60)
        response = subprocess.CompletedProcess([], 0, b"rfad.wsl-ready/0.1", b"")
        with patch("rfad.application.wsl_process._run_control", return_value=response) as launcher:
            result = runtime.prepare(threading.Event())
        self.assertFalse(result["worker_started"])
        self.assertEqual(launcher.call_args.args[2], 60)
        self.assertEqual(runtime.control_timeout_seconds, 10)
        self.assertIn(runtime.python, launcher.call_args.args[0])

    def test_failure_is_known_not_started(self):
        """! @brief 준비 단계 실패는 접수 여부 불명인 solve로 기록하지 않는다."""
        failure = ProjectError("E_RESOURCE", "timeout", details={"outcome_unknown": True})
        with patch("rfad.application.wsl_process._run_control", side_effect=failure), self.assertRaises(ProjectError) as caught:
            WslRuntime().prepare(threading.Event())
        self.assertTrue(caught.exception.details["not_started"])
        self.assertFalse(caught.exception.details["outcome_unknown"])

    def test_control_can_cancel_a_real_silent_launcher(self):
        """! @brief 응답 없는 준비 프로세스도 취소 신호로 회수한다."""
        cancel = threading.Event()
        timer = threading.Timer(0.1, cancel.set)
        timer.start()
        try:
            with self.assertRaises(ProjectError) as caught:
                _run_control([sys.executable, "-I", "-c", "import time;time.sleep(30)"], b"", 10, cancel=cancel)
            self.assertEqual(caught.exception.details["reason"], "cancelled")
        finally:
            timer.cancel()
