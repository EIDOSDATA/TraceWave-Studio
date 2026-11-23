"""! @brief WSL host 제어가 실행 소유권과 불확실한 종료를 보수적으로 보존하는지 확인한다."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from rfad.application.wsl_process import BOOTSTRAP, PROTOCOL, WslRuntime, _run_control
from rfad.domain.errors import ProjectError


class WslProcessTests(unittest.TestCase):
    """! @brief guest 종료 증거와 launcher 응답을 구분하는 host 계약을 검사한다."""

    def setUp(self):
        """! @brief 실행별로 독립적인 UUID와 nonce 및 고정 구성 객체를 만든다."""
        self.run_id = str(uuid.uuid4())
        self.nonce = uuid.uuid4().hex
        self.runtime = WslRuntime(poll_seconds=0.001)
        readiness = patch.object(self.runtime, "prepare", return_value={"status": "ready", "worker_started": False})
        readiness.start()
        self.addCleanup(readiness.stop)

    def stage(self, directory):
        """! @brief 사용자 코드가 아닌 고정 worker 파일 묶음의 최소 fixture를 만든다."""
        path = Path(directory)
        (path / "tools").mkdir()
        (path / "tools" / "openems_worker.py").write_text("pass\n", encoding="utf-8")
        (path / "request.json").write_text(json.dumps({"run_id": self.run_id, "nonce": self.nonce}), encoding="utf-8")
        (path / "runtime.json").write_text("{}", encoding="utf-8")
        return path

    def status(self, state="completed", confirmed=True, **extra):
        """! @brief 알려진 실행 소유권을 가진 권위 상태 fixture를 반환한다."""
        return {"protocol": PROTOCOL, "run_id": self.run_id, "nonce": self.nonce, "state": state,
                "termination_confirmed": confirmed, "outcome_unknown": not confirmed, "cursor": 1, **extra}

    def test_identity_is_pure_and_freezes_supervisor(self):
        """! @brief 계획용 descriptor 조회는 WSL 프로세스를 시작하지 않는다."""
        with patch("rfad.application.wsl_process._run_control") as launcher:
            self.assertEqual(self.runtime.identity()["supervisor_sha256"], self.runtime.identity()["supervisor_sha256"])
            self.assertEqual(self.runtime.identity()["protocol"], PROTOCOL)
            launcher.assert_not_called()

    def test_command_uses_fixed_argv_and_stdin_not_shell(self):
        """! @brief UUID와 nonce는 stdin 데이터이며 임의 실행 명령이 되지 않는다."""
        response = subprocess.CompletedProcess([], 0, json.dumps(self.status()).encode(), b"")
        with patch("rfad.application.wsl_process._run_control", return_value=response) as launcher:
            self.runtime.inspect(self.run_id, self.nonce)
        args, kwargs = launcher.call_args
        self.assertEqual(args[0][:7], ["wsl.exe", "--distribution", "TraceWave-Dev", "--user", "tracewave", "--exec", "/usr/bin/python3"])
        self.assertNotIn(self.nonce, " ".join(args[0]))
        self.assertIsInstance(args[1], bytes)

    def test_wrong_nonce_response_is_not_accepted(self):
        """! @brief 다른 실행의 terminal 응답도 소유권이 다르면 거부한다."""
        response = subprocess.CompletedProcess([], 0, json.dumps(self.status(nonce="0" * 32)).encode(), b"")
        with patch("rfad.application.wsl_process._run_control", return_value=response), self.assertRaises(ProjectError) as caught:
            self.runtime.inspect(self.run_id, self.nonce)
        self.assertEqual(caught.exception.code, "E_HASH")

    def test_large_start_and_export_use_bounded_startup_timeout(self):
        """! @brief 소스 복사/출력 교환은 짧은 상태 조회 timeout과 구분하되 유한하다."""
        response = subprocess.CompletedProcess([], 0, json.dumps(self.status()).encode(), b"")
        with patch("rfad.application.wsl_process._run_control", return_value=response) as launcher:
            for command in ("start", "export"):
                self.runtime._invoke(command, {"run_id": self.run_id, "nonce": self.nonce}, bootstrap=command == "start")
                self.assertEqual(launcher.call_args.args[2], self.runtime.startup_timeout_seconds)
            self.runtime.inspect(self.run_id, self.nonce)
            self.assertEqual(launcher.call_args.args[2], self.runtime.control_timeout_seconds)

    def test_ack_loss_reconnects_without_starting_again(self):
        """! @brief 시작 응답 유실 시 같은 실행을 조회하며 solve를 중복 실행하지 않는다."""
        commands = []
        def invoke(command, payload, **kwargs):
            commands.append(command)
            if command == "start":
                raise ProjectError("E_RESOURCE", "lost launcher", details={"outcome_unknown": True})
            return self.status(exported_files=[])
        with tempfile.TemporaryDirectory() as directory, patch.object(self.runtime, "_invoke", side_effect=invoke):
            result = self.runtime.execute(self.stage(directory), run_id=self.run_id, nonce=self.nonce, cancel=threading.Event())
        self.assertEqual(commands, ["start", "status", "export"])
        self.assertTrue(result["termination_confirmed"])

    def test_slow_file_transfer_uses_an_independent_deadline(self):
        """! @brief 고정 입력의 복사 예산을 늘려도 WSL 준비 및 상태 조회 기한은 유지한다."""
        runtime = WslRuntime(transfer_timeout_seconds=240.0)
        self.assertEqual(runtime.startup_timeout_seconds, 60.0)
        response = subprocess.CompletedProcess([], 0, json.dumps(self.status()).encode(), b"")
        with patch("rfad.application.wsl_process._run_control", return_value=response) as launcher:
            for command in ("start", "export", "status"):
                runtime._invoke(command, {"run_id": self.run_id, "nonce": self.nonce}, bootstrap=command == "start")
                self.assertEqual(launcher.call_args.args[2], 10.0 if command == "status" else 240.0)
        with self.assertRaises(ProjectError):
            WslRuntime(transfer_timeout_seconds=float("inf"))

    def test_slow_start_preserves_the_full_guest_execution_budget(self):
        """! @brief 느린 전송과 시작 응답 유실 뒤에도 완료 및 guest 자체 시간 초과를 구분한다."""
        for acknowledgement_lost in (False, True):
            for outcome in ("completed", "timeout"):
                with self.subTest(acknowledgement_lost=acknowledgement_lost, outcome=outcome):
                    elapsed = 0
                    commands = []
                    active = self.status("active", False, worker_pid=37)

                    def invoke(command, payload, **kwargs):
                        """! @brief 시간 축 하나에서 30초 전송, 10초 인계, 899초 실행을 재현한다."""
                        nonlocal elapsed
                        commands.append(command)
                        if command == "start":
                            self.assertEqual(payload["timeout_seconds"], 900)
                            elapsed = 30
                            if acknowledgement_lost:
                                raise ProjectError("E_RESOURCE", "시작 응답 유실")
                            return self.status("starting", False)
                        if command == "status":
                            return self.status("starting", False)
                        if command == "heartbeat":
                            if elapsed == 30:
                                elapsed = 40
                                return active
                            if elapsed == 40:
                                elapsed = 939
                                return active
                            elapsed = 940
                            return self.status(outcome)
                        if command == "export":
                            return self.status(outcome, exported_files=[])
                        self.fail("예상하지 않은 제어 명령 " + command)

                    with tempfile.TemporaryDirectory() as directory, patch.object(self.runtime, "_invoke", side_effect=invoke), \
                            patch("rfad.application.wsl_process.time.monotonic", side_effect=lambda: elapsed):
                        result = self.runtime.execute(self.stage(directory), run_id=self.run_id, nonce=self.nonce,
                                                      cancel=threading.Event(), timeout_seconds=900)
                    self.assertTrue(result["termination_confirmed"])
                    self.assertEqual(result["state"], outcome)
                    self.assertNotIn("transport_error", result)
                    self.assertEqual(commands.count("start"), 1)
                    self.assertEqual(commands.count("status"), int(acknowledgement_lost))
                    self.assertEqual(commands.count("export"), int(outcome == "completed"))

    def test_nonterminal_guest_cannot_extend_start_or_execution_deadlines(self):
        """! @brief worker PID가 없는 준비 정체와 실제 작업 후의 무응답을 각각 한 번만 취소한다."""
        for worker_pid, expected_message in ((None, "작업 시작 확인"), (37, "종료 확인")):
            with self.subTest(worker_pid=worker_pid):
                elapsed = 0
                commands = []
                status = self.status("active", False, worker_pid=worker_pid)

                def invoke(command, payload, **kwargs):
                    """! @brief 같은 상태를 계속 반환해 heartbeat마다 기한이 갱신되는 오류를 검출한다."""
                    nonlocal elapsed
                    commands.append(command)
                    if command == "cancel":
                        return self.status("cancelled")
                    if command == "heartbeat":
                        elapsed += 10
                    if len(commands) > 20:
                        self.fail("작업이 유한한 시간 안에 정리되지 않았습니다.")
                    return status

                with tempfile.TemporaryDirectory() as directory, patch.object(self.runtime, "_invoke", side_effect=invoke), \
                        patch("rfad.application.wsl_process.time.monotonic", side_effect=lambda: elapsed):
                    result = self.runtime.execute(self.stage(directory), run_id=self.run_id, nonce=self.nonce,
                                                  cancel=threading.Event(), timeout_seconds=3)
                self.assertIn(expected_message, result["transport_error"])
                self.assertTrue(result["termination_confirmed"])
                self.assertEqual(commands.count("cancel"), 1)
                self.assertEqual(elapsed, 30 if worker_pid else 70)

    def test_confirmed_unstarted_job_has_no_output_to_export(self):
        """! @brief 인계 전 종료한 작업에서 없는 출력 폴더를 복사하지 않고 최초 사유를 보존한다."""
        failed = self.status("failed", not_started=True, reason="startup_owner_lost")
        with tempfile.TemporaryDirectory() as directory, patch.object(self.runtime, "_invoke", return_value=failed) as invoke:
            result = self.runtime.execute(self.stage(directory), run_id=self.run_id, nonce=self.nonce, cancel=threading.Event())
        self.assertEqual(invoke.call_count, 1)
        self.assertEqual(result["reason"], "startup_owner_lost")
        self.assertNotIn("export_error", result)

    def test_unconfirmed_guest_is_not_exported(self):
        """! @brief launcher 종료나 terminal 이름만으로 출력 공개나 자원 해제를 허용하지 않는다."""
        with tempfile.TemporaryDirectory() as directory, patch.object(self.runtime, "_invoke", return_value=self.status("failed", False)) as invoke:
            result = self.runtime.execute(self.stage(directory), run_id=self.run_id, nonce=self.nonce, cancel=threading.Event())
        self.assertTrue(result["outcome_unknown"])
        self.assertEqual(invoke.call_count, 1)
        self.assertNotIn("output_directory", result)

    def test_already_cancelled_does_not_read_stage_or_start_guest(self):
        """! @brief 대기 중 취소는 입력 복사와 WSL 실행 이전에 확정 종료된다."""
        cancel = threading.Event()
        cancel.set()
        with patch.object(self.runtime, "_manifest") as manifest, patch.object(self.runtime, "_invoke") as invoke:
            result = self.runtime.execute(Path("missing-stage"), run_id=self.run_id, nonce=self.nonce, cancel=cancel)
        manifest.assert_not_called()
        invoke.assert_not_called()
        self.assertEqual(result["state"], "cancelled")
        self.assertTrue(result["termination_confirmed"])
        self.assertTrue(result["not_started"])
        self.assertFalse(result["outcome_unknown"])

    def test_cancel_wakes_heartbeat_wait_and_reports_terminal_without_sleep(self):
        """! @brief heartbeat 대기에서 취소 신호를 받고 실제 종료 확인은 다음 지연 없이 처리한다."""
        cancel = threading.Event()
        commands, observed = [], []
        active = self.status("active", False)
        cancelled = self.status("cancelled")
        cancelled["cursor"] = 3

        def invoke(command, payload, **kwargs):
            commands.append(command)
            if command == "heartbeat":
                return {**active, "cursor": 2}
            if command == "cancel":
                return cancelled
            return active

        def wait_for_cancel(timeout):
            self.assertEqual(timeout, self.runtime.poll_seconds)
            cancel.set()
            return True

        with tempfile.TemporaryDirectory() as directory, patch.object(self.runtime, "_invoke", side_effect=invoke), \
                patch.object(cancel, "wait", side_effect=wait_for_cancel) as wait, \
                patch("rfad.application.wsl_process.time.sleep") as sleep:
            result = self.runtime.execute(self.stage(directory), run_id=self.run_id, nonce=self.nonce,
                                          cancel=cancel, on_state=lambda state: observed.append(state["cursor"]))
        wait.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(commands, ["start", "heartbeat", "cancel"])
        self.assertEqual(observed, [1, 2, 3])
        self.assertEqual(result["state"], "cancelled")
        self.assertTrue(result["termination_confirmed"])

    def test_transport_failure_preserves_unknown_outcome(self):
        """! @brief 연결과 취소 재접속이 모두 실패하면 종료 성공을 추측하지 않는다."""
        with tempfile.TemporaryDirectory() as directory, patch.object(self.runtime, "_invoke", side_effect=ProjectError("E_RESOURCE", "offline")):
            result = self.runtime.execute(self.stage(directory), run_id=self.run_id, nonce=self.nonce, cancel=threading.Event())
        self.assertFalse(result["termination_confirmed"])
        self.assertTrue(result["outcome_unknown"])

    def test_export_failure_does_not_erase_termination_evidence(self):
        """! @brief 출력 복사 실패는 실패 결과이며 이미 확인한 guest 종료는 보존한다."""
        def invoke(command, payload, **kwargs):
            if command == "export":
                raise ProjectError("E_RESOURCE", "copy failed")
            return self.status()
        with tempfile.TemporaryDirectory() as directory, patch.object(self.runtime, "_invoke", side_effect=invoke):
            result = self.runtime.execute(self.stage(directory), run_id=self.run_id, nonce=self.nonce, cancel=threading.Event())
        self.assertEqual(result["state"], "failed")
        self.assertTrue(result["termination_confirmed"])
        self.assertIn("export_error", result)

    def test_input_allowlist_and_nonpositive_limits(self):
        """! @brief 프로젝트가 Python 진입점이나 셸 스크립트를 추가할 수 없게 한다."""
        with tempfile.TemporaryDirectory() as directory:
            stage = self.stage(directory)
            (stage / "user.sh").write_text("exit 0", encoding="utf-8")
            with self.assertRaises(ProjectError) as caught:
                self.runtime.execute(stage, run_id=self.run_id, nonce=self.nonce, cancel=threading.Event())
            self.assertTrue(caught.exception.details["not_started"])
            self.assertTrue(caught.exception.details["termination_confirmed"])
            self.assertFalse(caught.exception.details["outcome_unknown"])
        with self.assertRaises(ProjectError):
            WslRuntime(distribution="TraceWave-Dev;whoami")
        with self.assertRaises(ProjectError):
            WslRuntime(guest_root="/mnt/c/runtime")
        with self.assertRaises(ProjectError):
            self.runtime.inspect("../run", self.nonce)

    def test_control_capture_has_live_output_and_time_bounds(self):
        """! @brief 실제 프로세스의 제어 응답 폭주와 무응답을 유한하게 회수한다."""
        for body, timeout in (("import os;os.write(1,b'x'*1048576)", 3), ("import time;time.sleep(30)", 0.05)):
            with self.subTest(body=body), self.assertRaises(ProjectError) as caught:
                _run_control([sys.executable, "-I", "-B", "-c", body], b"{}", timeout)
            self.assertTrue(caught.exception.details["outcome_unknown"])


@unittest.skipUnless(os.name == "nt" and os.environ.get("RFAD_TEST_WSL") == "1",
                     "RFAD_TEST_WSL=1과 승인된 실제 TraceWave-Dev WSL 환경이 필요합니다.")
class WslLiveTransportTests(unittest.TestCase):
    """! @brief 실제 Windows launcher와 Linux supervisor의 독립 수명을 검증한다."""

    def setUp(self):
        """! @brief 호스트 한글 경로와 guest ext4의 실행별 staging을 만든다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="rfad WSL 한글 ")
        self.stage = Path(self.temporary.name)
        self.run_id = str(uuid.uuid4())
        self.nonce = uuid.uuid4().hex
        self.runtime = WslRuntime(poll_seconds=0.1, lease_seconds=5)
        self.code = Path(__file__).resolve().parents[1]
        shutil.copytree(self.code / "src" / "rfad", self.stage / "src" / "rfad",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (self.stage / "tools").mkdir()
        (self.stage / "runtime.json").write_text("{}", encoding="utf-8")
        (self.stage / "request.json").write_text(json.dumps({"run_id": self.run_id, "nonce": self.nonce}), encoding="utf-8")

    def tearDown(self):
        """! @brief 실패 시에도 자신의 UUID/nonce 실행만 취소하고 호스트 임시 파일을 정리한다."""
        try:
            status = self.runtime.cancel(self.run_id, self.nonce)
            deadline = time.monotonic() + 8
            while not status.get("termination_confirmed") and time.monotonic() < deadline:
                time.sleep(0.1)
                status = self.runtime.inspect(self.run_id, self.nonce)
        except ProjectError:
            pass
        self.temporary.cleanup()

    def worker(self, body):
        """! @brief stdin 소유권 gate 뒤에서만 실행되는 native 대역 fixture를 쓴다."""
        (self.stage / "tools" / "openems_worker.py").write_text(
            "import sys,json,time,subprocess\nfrom pathlib import Path\n"
            "gate=sys.stdin.buffer.readline()\nif not gate: raise SystemExit(19)\n" + body, encoding="utf-8")

    def test_windows_host_exports_verified_guest_result(self):
        """! @brief 실제 WSL argv와 Windows 한글 경로에서 결과 해시를 검증한다."""
        self.worker("Path('output/result.json').write_text(json.dumps({'ok':True}))\n")
        result = self.runtime.execute(self.stage, run_id=self.run_id, nonce=self.nonce,
                                      cancel=threading.Event(), timeout_seconds=10)
        self.assertEqual(result["state"], "completed", result)
        self.assertTrue(result["termination_confirmed"])
        self.assertTrue(json.loads((self.stage / "output" / "result.json").read_text())["ok"])

    def test_owned_worker_timeout_is_reported_by_the_guest(self):
        """! @brief 실제 Windows와 WSL의 인계 뒤 계산 시간 초과를 guest 종료 원인으로 읽는다."""
        self.worker("time.sleep(30)\n")
        result = self.runtime.execute(self.stage, run_id=self.run_id, nonce=self.nonce,
                                      cancel=threading.Event(), timeout_seconds=2)
        self.assertEqual(result["state"], "timeout", result)
        self.assertEqual(result["native"]["termination"], "timeout")
        self.assertTrue(result["termination_confirmed"])
        self.assertFalse(result["outcome_unknown"])
        self.assertNotIn("transport_error", result)

    def test_cancel_active_guest_while_worker_writes_one_thousand_log_lines_per_second(self):
        """! @brief 같은 WSL 감독기의 고속 로그와 세션을 옮긴 시험 후손을 함께 회수한다."""
        self.worker(
            "import os\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'], start_new_session=True)\n"
            "batch = b'rfad log output row for transport fixture\\n' * 10\n"
            "started = time.monotonic()\n"
            "progress = Path('progress.tmp')\n"
            "progress.write_text(json.dumps({'phase':'running'}), encoding='utf-8')\n"
            "progress.replace('progress.json')\n"
            "for index in range(1, 1001):\n"
            "    os.write(1, batch)\n"
            "    time.sleep(max(0, started + index / 100 - time.monotonic()))\n"
            "    if index == 200:\n"
            "        print(json.dumps({'lines':2000, 'seconds':time.monotonic()-started, 'child':child.pid}), file=sys.stderr, flush=True)\n"
        )
        cancel = threading.Event()
        timer = threading.Timer(3.0, cancel.set)
        observed = []

        def on_state(value):
            """! @brief 실제 guest 실행 단계가 확인된 뒤 취소 대기를 시작한다."""
            if value.get("phase") == "running" and value.get("worker_pid") and not observed:
                observed.append(value["worker_pid"])
                timer.start()

        try:
            result = self.runtime.execute(self.stage, run_id=self.run_id, nonce=self.nonce,
                                          cancel=cancel, timeout_seconds=15, on_state=on_state)
        finally:
            timer.cancel()
        self.assertEqual(result["state"], "cancelled", result)
        self.assertTrue(cancel.is_set() and result["termination_confirmed"])
        self.assertFalse(result["outcome_unknown"])
        self.assertEqual(len(observed), 1)
        self.assertEqual(result["worker_pid"], observed[0])
        native = result["native"]
        rate = json.loads(native["stderr_tail"])
        self.assertEqual(rate["lines"], 2000)
        self.assertGreaterEqual(rate["lines"] / rate["seconds"], 950)
        line = b"rfad log output row for transport fixture\n"
        self.assertGreater(native["stdout_bytes"], rate["lines"] * len(line))
        self.assertEqual(native["stdout_bytes"] % len(line), 0)
        self.assertLessEqual(len(native["stdout_tail"].encode("utf-8")), 16 * 1024)
        self.assertEqual(native["output_limit_reason"], "")
        recovered = self.runtime.inspect(self.run_id, self.nonce)
        self.assertEqual((recovered["state"], recovered["cursor"]), (result["state"], result["cursor"]))
        self.assertFalse((self.stage / "output").exists())

    def test_killed_wsl_launcher_reconnects_and_cancels_guest(self):
        """! @brief Windows launcher를 강제 종료해도 실행 상태는 guest에서 독립 조회한다."""
        self.worker("child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\ntime.sleep(30)\n")
        payload = {**self.runtime.identity(), "host_stage": self.runtime._linux_path(self.stage),
                   "run_id": self.run_id, "nonce": self.nonce, "files": self.runtime._manifest(self.stage),
                   "timeout_seconds": 20, "limits": {"max_output_bytes": 65536, "max_file_bytes": 65536,
                                                      "max_directory_bytes": 131072, "max_files": 16}}
        # @brief 시험 전용 launcher는 ACK 뒤 연결을 유지하여 실제 wsl.exe 강제 종료를 재현한다.
        argv = ["wsl.exe", "--distribution", self.runtime.distribution, "--user", self.runtime.user,
                "--exec", "/usr/bin/python3", "-I", "-B", "-c", BOOTSTRAP + ";__import__('time').sleep(60)",
                self.runtime._linux_path(self.runtime._source), self.runtime.identity()["supervisor_sha256"], "start"]
        launcher = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            launcher.stdin.write(base64.b64encode(json.dumps(payload).encode("utf-8")))
            launcher.stdin.close()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    status = self.runtime.heartbeat(self.run_id, self.nonce)
                    if status.get("worker_pid"):
                        break
                except ProjectError:
                    pass
                time.sleep(0.1)
            else:
                self.fail("guest did not start")
            launcher.kill()
            launcher.wait(timeout=3)
            recovered = self.runtime.inspect(self.run_id, self.nonce)
            self.assertEqual(recovered["worker_pid"], status["worker_pid"])
            self.assertFalse(recovered["termination_confirmed"])
            self.runtime.cancel(self.run_id, self.nonce)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = self.runtime.inspect(self.run_id, self.nonce)
                if result.get("termination_confirmed"):
                    break
                time.sleep(0.1)
            self.assertEqual(result["state"], "cancelled", result)
            self.assertTrue(result["termination_confirmed"])
        finally:
            if launcher.poll() is None:
                launcher.kill()
                launcher.wait(timeout=3)
            if not launcher.stdin.closed:
                launcher.stdin.close()


if __name__ == "__main__":
    unittest.main()
