"""! @brief 실제 Linux 자식과 손자 프로세스로 WSL guest 종료 및 복구를 검증한다."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


CODE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rfad_wsl_supervisor_test", CODE / "tools" / "wsl_supervisor.py")
SUPERVISOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPERVISOR)


@unittest.skipUnless(sys.platform.startswith("linux"), "실제 Linux process group과 pidfd가 필요합니다.")
class WslGuestTests(unittest.TestCase):
    """! @brief 무거운 solver 없이 실제 daemon/watchdog와 독립 제어 연결을 검사한다."""

    def setUp(self):
        """! @brief 전용 ext4 임시 루트와 frozen 소스 staging을 준비한다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="rfad-wsl-guest-")
        self.base = Path(self.temporary.name)
        self.stage = self.base / "host 한글 stage"
        self.stage.mkdir()
        self.root = self.base / "guest"
        self.run_id = str(uuid.uuid4())
        self.nonce = uuid.uuid4().hex
        self.payload = {"run_id": self.run_id, "nonce": self.nonce, "guest_root": str(self.root)}
        self.started = False

    def tearDown(self):
        """! @brief 테스트 실패에도 자신이 만든 실행만 취소하고 staging을 정리한다."""
        if self.started:
            try:
                SUPERVISOR.control(self.payload, "cancel")
                self.wait_terminal()
            except Exception:
                pass
        for path in self.base.rglob("*"):
            if path.is_dir():
                path.chmod(0o700)
        self.temporary.cleanup()

    def request(self, body, *, timeout=5, lease=3, limits=None):
        """! @brief 고정 stdin gate 뒤에만 시험 동작을 수행하는 fixture worker를 만든다."""
        shutil.copytree(CODE / "src" / "rfad", self.stage / "src" / "rfad", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (self.stage / "tools").mkdir()
        worker = ("import sys,json,os,time,subprocess\n"
                  "from pathlib import Path\n"
                  "gate=sys.stdin.buffer.readline(65537)\n"
                  "if not gate: raise SystemExit(19)\n"
                  "request=json.loads(Path('request.json').read_bytes())\n"
                  "value=json.loads(gate)\n"
                  "assert value['nonce']==request['nonce']\n" + body)
        (self.stage / "tools" / "openems_worker.py").write_text(worker, encoding="utf-8")
        (self.stage / "request.json").write_text(json.dumps(self.payload), encoding="utf-8")
        (self.stage / "runtime.json").write_text("{}", encoding="utf-8")
        files = []
        for path in sorted(self.stage.rglob("*")):
            if path.is_file():
                files.append({"path": path.relative_to(self.stage).as_posix(), "bytes": path.stat().st_size,
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return {**self.payload, "host_stage": str(self.stage), "files": files, "python": sys.executable,
                "supervisor_sha256": SUPERVISOR.digest(CODE / "tools" / "wsl_supervisor.py"),
                "timeout_seconds": timeout, "lease_seconds": lease,
                "limits": limits or {"max_output_bytes": 65536, "max_file_bytes": 65536,
                                     "max_directory_bytes": 131072, "max_files": 16}}

    def start(self, body, **options):
        """! @brief 준비한 소스를 ext4에 검증 복제한 실제 daemon을 시작한다."""
        result = SUPERVISOR.start(self.request(body, **options))
        self.started = True
        return result

    def wait_terminal(self, heartbeat=True):
        """! @brief 유한 deadline 안에서 권위 상태를 조회하고 terminal을 반환한다."""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            value = SUPERVISOR.control(self.payload, "heartbeat" if heartbeat else "status")
            if value["state"] in SUPERVISOR.TERMINAL:
                return value
            time.sleep(0.03)
        self.fail("guest terminal deadline exceeded")

    def wait_worker(self):
        """! @brief fixture가 native gate를 통과하여 소유 트리를 생성할 때까지 기다린다."""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            path = self.root / self.run_id / "output" / "ready.json"
            if path.exists():
                return SUPERVISOR.read_json(path)
            time.sleep(0.02)
        self.fail("worker did not become ready")

    def test_completed_export_and_readonly_staging(self):
        """! @brief guest에서 닫힌 결과와 불변 입력을 검증한 뒤 host로 복사한다."""
        self.start("Path('output/result.json').write_text(json.dumps({'ok':True}))\n")
        result = self.wait_terminal()
        self.assertEqual(result["state"], "completed")
        self.assertTrue(result["termination_confirmed"])
        self.assertEqual((self.root / self.run_id / "request.json").stat().st_mode & 0o222, 0)
        exported = SUPERVISOR.export(self.payload)
        self.assertEqual(len(exported["exported_files"]), 1)
        self.assertTrue(json.loads((self.stage / "output" / "result.json").read_text())["ok"])

    def test_wrong_nonce_and_mutated_input_fail_closed(self):
        """! @brief 잘못된 nonce의 취소와 hash가 달라진 frozen 입력을 거부한다."""
        request = self.request("time.sleep(30)\n")
        (self.stage / "runtime.json").write_text("[]")
        result = SUPERVISOR.start(request)
        self.assertEqual(result["state"], "failed")
        self.assertTrue(result["termination_confirmed"])
        with self.assertRaises(ValueError):
            SUPERVISOR.control({**self.payload, "nonce": "0" * 32}, "cancel")

    def gated_starter(self):
        """! @brief 실제 시작 프로세스를 복사 직전 멈춰 소유 잠금 경합을 재현한다."""
        request = self.request("Path('output/should-not-run').write_text('unexpected')\n")
        request_path = self.base / "startup-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        script = ("import importlib.util,json,sys,time\nfrom pathlib import Path\n"
                  "s=importlib.util.spec_from_file_location('guest',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
                  "original=m._copy_and_start\n"
                  "def gated(payload,path,manifest):\n"
                  " m.atomic(path/'fixture-start-ready.json',{'ready':True})\n"
                  " deadline=time.monotonic()+8\n"
                  " while not (path/'fixture-start-release').exists():\n"
                  "  if time.monotonic()>deadline: raise RuntimeError('fixture release timeout')\n"
                  "  time.sleep(.01)\n"
                  " return original(payload,path,manifest)\n"
                  "m._copy_and_start=gated\n"
                  "print(json.dumps(m.start(json.loads(Path(sys.argv[2]).read_bytes()))))\n")
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", script,
                                    str(CODE / "tools/wsl_supervisor.py"), str(request_path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not (self.root / self.run_id / "fixture-start-ready.json").exists():
            time.sleep(0.01)
        self.assertTrue((self.root / self.run_id / "fixture-start-ready.json").exists())
        self.started = True
        return process

    def test_sticky_cancel_during_input_copy_never_opens_worker_gate(self):
        """! @brief 초기 입력 복사 중 취소도 누락되지 않고 실제 미시작 종료를 확인한다."""
        process = self.gated_starter()
        status = SUPERVISOR.control(self.payload, "cancel")
        self.assertFalse(status["termination_confirmed"])
        (self.root / self.run_id / "fixture-start-release").write_text("release")
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, stderr)
        status = json.loads(stdout)
        self.assertEqual(status["state"], "cancelled")
        self.assertTrue(status["not_started"])
        self.assertFalse((self.root / self.run_id / "output/should-not-run").exists())

    def test_startup_launcher_loss_releases_only_proven_unstarted_run(self):
        """! @brief 시작 PID가 사라지고 잠금이 풀린 미인계 작업만 종료를 확정한다."""
        process = self.gated_starter()
        owner = SUPERVISOR.read_json(self.root / self.run_id / "starter.json")
        self.assertEqual(owner["identity"]["pid"], process.pid)
        process.kill()
        process.communicate(timeout=5)
        status = SUPERVISOR.control(self.payload, "status")
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["reason"], "startup_owner_lost")
        self.assertTrue(status["termination_confirmed"])
        self.assertTrue(status["not_started"])
        self.assertFalse(status["outcome_unknown"])
        self.assertGreater(status["guest_disk_bytes"], 0)

    def test_duplicate_daemon_does_not_release_existing_active_worker(self):
        """! @brief 중복 daemon 진입은 다른 PID가 소유한 활성 실행의 종료를 선언하지 않는다."""
        self.start("Path('output/ready.json').write_text(json.dumps({'pid':os.getpid()}))\ntime.sleep(30)\n")
        self.wait_worker()
        before = SUPERVISOR.control(self.payload, "status")
        SUPERVISOR.daemon(self.payload)
        after = SUPERVISOR.control(self.payload, "status")
        self.assertEqual(after["state"], before["state"])
        self.assertEqual(after["worker_pid"], before["worker_pid"])
        self.assertFalse(after["termination_confirmed"])
        SUPERVISOR.control(self.payload, "cancel")
        self.assertTrue(self.wait_terminal()["termination_confirmed"])

    def test_old_start_without_owner_evidence_remains_unknown(self):
        """! @brief 구형 시작 기록은 새 소유권 근거가 없으므로 종료를 소급 추정하지 않는다."""
        process = self.gated_starter()
        path = self.root / self.run_id
        specification = SUPERVISOR.read_json(path / "supervisor.json")
        specification.pop("startup_profile")
        SUPERVISOR.atomic(path / "supervisor.json", specification)
        process.kill()
        process.communicate(timeout=5)
        status = SUPERVISOR.control(self.payload, "status")
        self.assertEqual(status["state"], "starting")
        self.assertFalse(status["termination_confirmed"])
        self.assertTrue(status["outcome_unknown"])
        self.started = False

    def test_cancel_reaps_worker_and_grandchild(self):
        """! @brief 취소 ACK 뒤에 실제 worker와 손자 종료가 확인되어야 terminal이 된다."""
        self.start("child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
                   "Path('output/ready.json').write_text(json.dumps({'child':child.pid}))\n"
                   "time.sleep(30)\n")
        self.wait_worker()
        SUPERVISOR.control(self.payload, "cancel")
        result = self.wait_terminal()
        self.assertEqual(result["state"], "cancelled")
        self.assertTrue(result["termination_confirmed"])
        self.assertEqual(SUPERVISOR._owned_members(result["worker_pid"], self.nonce), [])

    def detached_worker(self, *, separate_session=False, stay_alive=True):
        """! @brief 새 process group 또는 session의 후손을 만드는 fixture를 반환한다."""
        option = "start_new_session=True" if separate_session else "process_group=0"
        return ("child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL," + option + ")\n"
                "Path('output/ready.json').write_text(json.dumps({'child':child.pid}))\n"
                + ("time.sleep(30)\n" if stay_alive else ""))

    def assert_dead(self, pid):
        """! @brief PID가 없어졌거나 실행하지 않는 zombie 상태인지 직접 확인한다."""
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
            self.assertIn(state, {"Z", "X"})
        except FileNotFoundError:
            pass

    def test_cancel_reaps_descendant_in_different_process_group(self):
        """! @brief 원래 group과 다른 group의 후손까지 종료한 뒤 취소를 확정한다."""
        self.start(self.detached_worker())
        ready = self.wait_worker()
        active = SUPERVISOR.control(self.payload, "status")
        self.assertNotEqual(os.getpgid(ready["child"]), active["worker_pid"])
        self.assertEqual(os.getsid(ready["child"]), active["worker_pid"])
        SUPERVISOR.control(self.payload, "cancel")
        result = self.wait_terminal()
        self.assertEqual(result["state"], "cancelled")
        self.assertTrue(result["termination_confirmed"])
        self.assert_dead(ready["child"])

    def test_normal_exit_reaps_descendant_in_different_process_group(self):
        """! @brief worker 정상 종료 뒤에도 다른 group의 후손을 남긴 채 결과를 공개하지 않는다."""
        self.start(self.detached_worker(stay_alive=False))
        ready = self.wait_worker()
        result = self.wait_terminal()
        self.assertEqual(result["state"], "completed")
        self.assertTrue(result["termination_confirmed"])
        self.assert_dead(ready["child"])

    def test_timeout_reaps_descendant_in_different_process_group(self):
        """! @brief guest timeout도 전체 실행 후손 회수를 마친 다음 확정한다."""
        self.start(self.detached_worker(), timeout=0.3)
        ready = self.wait_worker()
        result = self.wait_terminal()
        self.assertEqual(result["state"], "timeout", result)
        self.assertTrue(result["termination_confirmed"])
        self.assert_dead(ready["child"])

    def test_cancel_reaps_nonce_inheriting_descendant_after_setsid(self):
        """! @brief 별도 session으로 이탈해도 상속된 실행 nonce로 해당 후손만 회수한다."""
        self.start(self.detached_worker(separate_session=True))
        ready = self.wait_worker()
        active = SUPERVISOR.control(self.payload, "status")
        self.assertNotEqual(os.getsid(ready["child"]), active["worker_pid"])
        SUPERVISOR.control(self.payload, "cancel")
        result = self.wait_terminal()
        self.assertEqual(result["state"], "cancelled")
        self.assertTrue(result["termination_confirmed"])
        self.assert_dead(ready["child"])

    def test_unverifiable_session_member_preserves_unknown_outcome(self):
        """! @brief 회수 소유권 검사 예외를 종료 성공으로 승격하거나 잘못된 후손을 죽이지 않는다."""
        self.start("environment=dict(os.environ)\nenvironment.pop('RFAD_WSL_RUN_TOKEN',None)\n"
                   "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],env=environment,"
                   "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,process_group=0)\n"
                   "Path('output/ready.json').write_text(json.dumps({'child':child.pid}))\ntime.sleep(30)\n")
        ready = self.wait_worker()
        descriptor = os.pidfd_open(ready["child"])
        try:
            SUPERVISOR.control(self.payload, "cancel")
            result = self.wait_terminal()
            self.assertEqual(result["state"], "failed")
            self.assertFalse(result["termination_confirmed"])
            self.assertTrue(result["outcome_unknown"])
            self.assertIn("identity", result["recovery_error"])
            with self.assertRaises(ValueError):
                SUPERVISOR.export(self.payload)
        finally:
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            os.close(descriptor)

    def test_timeout_and_host_death_lease_expiry(self):
        """! @brief guest 시간 상한과 heartbeat 중단이 각각 실제 종료를 일으킨다."""
        self.start("time.sleep(30)\n", timeout=0.3)
        result = self.wait_terminal()
        self.assertEqual(result["state"], "timeout", result)
        self.assertTrue(result["termination_confirmed"])

    def test_heartbeat_loss_reaps_group(self):
        """! @brief host 사망을 흉내 낸 lease 만료 후 종료 증거와 원인을 보존한다."""
        self.start("time.sleep(30)\n", lease=0.25)
        result = self.wait_terminal(heartbeat=False)
        self.assertEqual(result["state"], "cancelled", result)
        self.assertEqual(result["reason"], "lease_expired", result)
        self.assertTrue(result["termination_confirmed"])

    def test_supervisor_death_watchdog_reaps_owned_tree(self):
        """! @brief supervisor SIGKILL 후에도 독립 watchdog가 해당 세션만 회수한다."""
        self.start("child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
                   "Path('output/ready.json').write_text(json.dumps({'child':child.pid}))\n"
                   "time.sleep(30)\n")
        self.wait_worker()
        active = SUPERVISOR.control(self.payload, "status")
        unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True)
        descriptor = os.pidfd_open(active["supervisor_pid"])
        try:
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            result = self.wait_terminal()
            self.assertEqual(result["reason"], "supervisor_lost")
            self.assertTrue(result["termination_confirmed"])
            self.assertEqual(SUPERVISOR._owned_members(active["worker_pid"], self.nonce), [])
            self.assertIsNone(unrelated.poll())
        finally:
            os.close(descriptor)
            unrelated.terminate()
            unrelated.wait(timeout=3)

    def test_output_limit_is_guest_enforced(self):
        """! @brief host 연결과 독립적으로 guest 출력 파일 폭주를 차단한다."""
        self.start("Path('output/large').write_bytes(b'x'*100000)\ntime.sleep(30)\n")
        result = self.wait_terminal()
        self.assertEqual(result["state"], "output_limit")
        self.assertTrue(result["termination_confirmed"])
        with self.assertRaises(ValueError):
            SUPERVISOR.export(self.payload)


if __name__ == "__main__":
    unittest.main()
