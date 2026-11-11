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
