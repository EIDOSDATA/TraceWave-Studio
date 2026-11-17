"""! @brief 격리 출력 프로세스의 종료/취소/변조 경계를 실제 자식 프로세스로 검증한다."""
from pathlib import Path
import json
import sys
import threading
import time
import unittest

from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.domain.errors import ProjectError
from test_exchange_service import ExchangeFixture

WORKER = '''"""! @brief 형식을 생성하지 않고 실제 프로세스 수명만 시험한다."""
import json, os, sys, time
from pathlib import Path
root = Path(__file__).resolve().parents[1]
request = json.loads(sys.stdin.buffer.readline())
(root / "started.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
mode = MODE
if mode == "sleep":
    time.sleep(60)
if mode == "crash":
    raise SystemExit(7)
result={"schema":"rfad.exchange-worker-result/0.1","run_id":request["run_id"],
        "nonce":"wrong-nonce" if mode == "wrong_nonce" else request["nonce"],
        "input_sha256":request["input_sha256"],"error":{"code":"E_GEOMETRY","message_ko":"명시적인 시험 worker 실패"}}
(root / "result.json").write_text(json.dumps(result), encoding="utf-8")
raise SystemExit(1)
'''


class ExchangeWorkerBoundaryTests(unittest.TestCase):
    """! @brief 성공한 형식 파일을 꾸미지 않고 실패 시 원본/완료 게시를 보호한다."""
    def setUp(self):
        self.fixture = ExchangeFixture()
        self.entry = Path(self.fixture.temporary.name) / "실행 수명 시험.py"
        self.manifest = self.entry.with_suffix(".json")
        self.manifest.write_text(json.dumps({"schema": "rfad.runtime.python/0.1", "profile_id": "test-only-process-lifetime",
                                            "qt_allowed": False, "packages": [], "fonts": []}), encoding="utf-8")
        self.runners = []

    def tearDown(self):
        self.fixture.service.exchange.cancel.set()
        for runner in self.runners:
            runner.join(timeout=10)
        self.fixture.close()

    def prepare(self, mode, timeout=10):
        """! @brief 호스트가 정한 시험 진입점만 소스 묶음에 넣는다."""
        self.entry.write_text("MODE = " + repr(mode) + "\n" + WORKER, encoding="utf-8")
        runtime = ExchangeRuntime(Path(sys.executable), entry=self.entry, manifest=self.manifest, timeout_seconds=timeout)
        f = self.fixture
        f.service.exchange.runtime = runtime
        data = f.data()
        preview = f.complete("export.preview", data)
        task = f.service.mutate("export.build", f.request({**data, "review_hash": preview["review_hash"]}))
        return task

    def test_bad_nonce_and_crash_never_publish_a_package(self):
        """! @brief 잘못된 실행 응답과 프로세스 종료를 정상 출력으로 사용하지 않는다."""
        for mode in ("wrong_nonce", "crash", "explicit_failure"):
            with self.subTest(mode=mode):
                task = self.prepare(mode)
                self.assertTrue(self.fixture.service.exchange.run_next())
                job = self.fixture.service.journal.read()["jobs"][task["job_id"]]
                self.assertEqual(job["state"], "failed")
                self.assertFalse(job["exchange"]["resource_reserved"])
                self.assertFalse(job.get("artifacts"))
                self.assertFalse(any(self.fixture.workspace.rglob("exchange-artifacts")))
        self.assertEqual(self.fixture.service._load(self.fixture.service.journal.read()["projects"][self.fixture.project]), self.fixture.document)

    def test_running_cancel_waits_for_owned_child_exit(self):
        """! @brief 살아 있는 자식을 취소 완료로 먼저 표시하지 않는다."""
        task = self.prepare("sleep")
        errors = []
        def execute():
            try:
                self.fixture.service.exchange.run_next()
            except Exception as error:
                errors.append(error)
        runner = threading.Thread(target=execute)
        self.runners.append(runner)
        runner.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = self.fixture.service.journal.read()["jobs"][task["job_id"]]
            if "process" in job["exchange"]:
                break
            time.sleep(.02)
        self.assertIn("process", job["exchange"])
        response = self.fixture.service.mutate("job.cancel", self.fixture.request({"job_id": task["job_id"], "reason": "실제 자식 종료 시험"}, {}))
        self.assertEqual(response["state"], "cancel_requested")
        runner.join(timeout=10)
        self.assertFalse(runner.is_alive())
        self.assertFalse(errors)
        job = self.fixture.service.journal.read()["jobs"][task["job_id"]]
        self.assertEqual(job["state"], "cancelled")
        self.assertFalse(job["exchange"]["resource_reserved"])
        from test_cad_jobs import _alive
        self.assertFalse(_alive(job["exchange"]["process"]["pid"]))

    def test_source_changed_after_admission_is_not_executed(self):
        """! @brief 접수 후 바뀐 구현을 같은 원본 출력으로 실행하지 않는다."""
        task = self.prepare("sleep")
        self.entry.write_text(self.entry.read_text(encoding="utf-8") + "\n# 변경된 시험 진입점\n", encoding="utf-8")
        self.fixture.service.exchange.run_next()
        job = self.fixture.service.journal.read()["jobs"][task["job_id"]]
        self.assertEqual(job["state"], "failed")
        self.assertNotIn("process", job["exchange"])
        self.assertFalse(any(self.fixture.workspace.rglob("started.json")))


if __name__ == "__main__":
    unittest.main()
