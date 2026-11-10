"""! @brief 실제 Python worker로 native 감독의 취소와 제한 및 트리 회수를 확인한다."""

from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from rfad.application.native_process import run_native, TAIL_BYTES
from rfad.domain.errors import ProjectError


class NativeProcessTests(unittest.TestCase):
    """! @brief native import 전 stdin 접수 규약을 갖는 실제 subprocess를 사용한다."""

    def run_worker(self, body, *, directory=None, **kwargs):
        """! @brief 별도 한글/공백 작업 폴더에서 같은 감독 API를 실행한다."""
        program = "import sys, json, os, time, subprocess\nrequest=sys.stdin.buffer.readline()\nif not request: raise SystemExit(19)\n" + body
        if directory is None:
            with tempfile.TemporaryDirectory(prefix="rfad native 한글 ") as temporary:
                return self.run_worker(body, directory=Path(temporary), **kwargs)
        return run_native([sys.executable, "-I", "-X", "utf8", "-c", program], directory,
                          b'{"kind":"test"}\n', kwargs.pop("cancel", threading.Event()), **kwargs)

    def test_normal_nonzero_and_unicode_path(self):
        """! @brief 정상 결과와 실패 종료 코드를 바꾸지 않으며 한글 경로를 처리한다."""
        result = self.run_worker("print('완료'); print('진단',file=sys.stderr)")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["termination"], "completed")
        self.assertIn("완료", result["stdout_tail"])
        self.assertIn("진단", result["stderr_tail"])
        self.assertEqual(result["stdout_bytes"], len("완료\n".encode("utf-8")) + (1 if sys.platform == "win32" else 0))
        failed = self.run_worker("print('failed',file=sys.stderr); raise SystemExit(7)")
        self.assertEqual(failed["returncode"], 7)
        self.assertEqual(failed["termination"], "completed")

    def test_output_limit_and_bounded_tail(self):
        """! @brief stderr 폭주를 동시에 비우고 출력 상한 초과를 종료한다."""
        result = self.run_worker("while True: os.write(2,b'x'*8192)", max_output_bytes=65536)
        self.assertEqual(result["termination"], "output_limit")
        self.assertGreater(result["stderr_bytes"], 65536)
        self.assertLessEqual(len(result["stderr_tail"].encode()), TAIL_BYTES)

    def test_invalid_utf8_tail_stays_bounded_after_decoding(self):
        """! @brief native의 비 UTF-8 출력도 대체 표시하며 byte 상한을 지킨다."""
        result = self.run_worker("os.write(1,b'\\xff'*20000)")
        self.assertEqual(result["termination"], "completed")
        self.assertEqual(result["stdout_bytes"], 20000)
        self.assertTrue(result["stdout_tail"])
        self.assertLessEqual(len(result["stdout_tail"].encode("utf-8")), TAIL_BYTES)

    def test_timeout(self):
        """! @brief 응답하지 않는 worker를 유한 시간에 회수한다."""
        started = time.monotonic()
        result = self.run_worker("time.sleep(30)", timeout_seconds=0.2)
        self.assertEqual(result["termination"], "timeout")
        self.assertLess(time.monotonic() - started, 7)

    def test_output_file_growth_is_stopped(self):
        """! @brief stdout가 조용해도 출력 파일이 상한을 넘으면 트리를 회수한다."""
        cases = [
            ("open('output/large.bin','wb').write(b'x'*65536); time.sleep(30)", "file_size", {"max_file_bytes": 32768}),
            ("open('output/a','wb').write(b'x'*20000); open('output/b','wb').write(b'x'*20000)", "directory_size", {"max_directory_bytes": 32768}),
            ("[open('output/'+str(i),'w').close() for i in range(17)]", "file_count", {}),
            ("open('target','w').close(); os.link('target','output/link')", "unsafe_path", {}),
        ]
        for program, reason, limits in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory(prefix="rfad native files ") as temporary:
                result = self.run_worker("os.mkdir('output'); " + program, directory=Path(temporary),
                                         output_directory=Path("output"), **limits)
                self.assertEqual(result["termination"], "output_limit")
                self.assertEqual(result["output_limit_reason"], reason)
                self.assertTrue(result["file_monitor"]["overshoot_between_polls_possible"])

    def test_cancel_after_ownership_before_request(self):
        """! @brief 소유권 callback의 취소가 native 시작용 요청을 보내지 않는다."""
        cancel = threading.Event()
        seen = []
        def start(metadata):
            """! @brief durable 접수 도중 들어온 취소 경합을 재현한다."""
            seen.append(metadata)
            cancel.set()
        result = self.run_worker("print('unexpected-request')", cancel=cancel, on_started=start)
        self.assertEqual(result["termination"], "cancelled")
        self.assertEqual(result["stdout_bytes"], 0)
        self.assertEqual(seen[0]["pid"], result["pid"])

    def test_callback_failure_does_not_deliver_request(self):
        """! @brief 영속 시작 기록 실패 시 native 입력 전달 없이 프로세스를 회수한다."""
        with tempfile.TemporaryDirectory(prefix="rfad native callback ") as temporary:
            marker = Path(temporary) / "should-not-exist"
            def fail(_):
                """! @brief coordinator의 시작 기록 실패를 유도한다."""
                raise ValueError("start journal failed")
            with self.assertRaisesRegex(ValueError, "start journal failed"):
                self.run_worker(f"open({str(marker)!r},'w').write('bad')", directory=Path(temporary), on_started=fail)
            self.assertFalse(marker.exists())

    def test_cancel_reaps_descendant_and_inherited_pipes(self):
        """! @brief 자식이 pipe를 상속해도 취소 후 지연 marker를 쓰지 못한다."""
        with tempfile.TemporaryDirectory(prefix="rfad native child ") as temporary:
            directory = Path(temporary)
            ready, marker = directory / "ready", directory / "late-child"
            cancel = threading.Event()
            child = f"import time; time.sleep(1.0); open({str(marker)!r},'w').write('alive'); time.sleep(30)"
            body = f"subprocess.Popen([sys.executable,'-I','-c',{child!r}]); open({str(ready)!r},'w').write('ready'); time.sleep(30)"
            def request_cancel():
                """! @brief 실제 후손 생성 확인 후에 취소를 요청한다."""
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                cancel.set()
            thread = threading.Thread(target=request_cancel)
            thread.start()
            try:
                result = self.run_worker(body, directory=directory, cancel=cancel)
            finally:
                thread.join(timeout=6)
            self.assertTrue(ready.exists())
            self.assertEqual(result["termination"], "cancelled")
            time.sleep(1.1)
            self.assertFalse(marker.exists())

    def test_normal_exit_reaps_descendant_holding_pipes(self):
        """! @brief 정상 종료한 worker의 남은 자식 때문에 출력 회수가 멈추지 않는다."""
        result = self.run_worker("subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)']); print('parent-done')")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["termination"], "completed")
        self.assertIn("parent-done", result["stdout_tail"])

    @unittest.skipUnless(sys.platform == "win32", "Windows Job Object의 부모 crash 회수 시험")
    def test_windows_parent_crash_closes_job_and_kills_worker(self):
        """! @brief 감독 프로세스가 강제 종료되어도 소유 worker가 늦은 결과를 쓰지 못한다."""
        with tempfile.TemporaryDirectory(prefix="rfad native parent crash ") as temporary:
            directory = Path(temporary)
            ready, marker = directory / "ready", directory / "late-worker"
            worker = ("import sys,time; request=sys.stdin.buffer.readline(); "
                      "sys.exit(19) if not request else None; "
                      f"open({str(ready)!r},'w').write('ready'); time.sleep(1.0); "
                      f"open({str(marker)!r},'w').write('alive'); time.sleep(30)")
            program = ("from pathlib import Path; import sys,threading; "
                       "from rfad.application.native_process import run_native; "
                       f"run_native([sys.executable,'-I','-c',{worker!r}], Path({str(directory)!r}), "
                       "b'{}\\n', threading.Event())")
            driver = subprocess.Popen([sys.executable, "-X", "utf8", "-c", program],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and driver.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                driver.kill()
                driver.wait(timeout=5)
                time.sleep(1.1)
                self.assertFalse(marker.exists())
            finally:
                if driver.poll() is None:
                    driver.kill()
                    driver.wait(timeout=5)
                driver.stdout.close()
                driver.stderr.close()

    def test_stdin_backpressure_does_not_block_timeout(self):
        """! @brief stdin을 읽지 않는 비정상 worker도 별도 writer로 timeout 처리한다."""
        with tempfile.TemporaryDirectory() as temporary:
            result = run_native([sys.executable, "-I", "-c", "import time; time.sleep(30)"], Path(temporary),
                                b"x" * 65535 + b"\n", threading.Event(), timeout_seconds=0.2)
        self.assertEqual(result["termination"], "timeout")

    def test_rejects_invalid_limits_and_relative_executable(self):
        """! @brief 셸 검색이나 무한 자원 상한을 native 실행 전에 거절한다."""
        with tempfile.TemporaryDirectory() as temporary:
            for argv, request, timeout, limit in [
                (["python"], b"{}\n", 1, 100),
                ([sys.executable], b"{}", 1, 100),
                ([sys.executable], b"{}\n", float("inf"), 100),
                ([sys.executable], b"{}\n", 1, True),
            ]:
                with self.subTest(argv=argv, timeout=timeout, limit=limit), self.assertRaises(ProjectError):
                    run_native(argv, Path(temporary), request, threading.Event(), timeout_seconds=timeout, max_output_bytes=limit)


if __name__ == "__main__":
    unittest.main()
