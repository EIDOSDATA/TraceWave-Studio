"""! @brief 실제 stdio 서비스 재시작을 거치는 프로젝트 사용 흐름을 검증한다."""

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from uuid import uuid4


class ProjectProcessTests(unittest.TestCase):
    """! @brief 프로세스 경계를 통해 durable 응답과 재열기를 확인한다."""

    def start(self, workspace):
        """! @brief JSON 전용 출력을 읽는 실제 서비스 프로세스를 시작한다."""
        code = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(code / "src"))
        self.process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "rfad", "serve", "--workspace", str(workspace)], cwd=code, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.responses = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.responses.put(line)
            self.responses.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def stop(self, *, kill=False):
        """! @brief 시간 제한 안에서 종료하고 테스트 자원을 닫는다."""
        if getattr(self, "process", None) is None:
            return
        process = self.process
        try:
            if kill:
                process.kill()
            else:
                process.stdin.close()
            process.wait(timeout=5)
        except (subprocess.TimeoutExpired, BrokenPipeError):
            process.kill()
            process.wait(timeout=5)
        finally:
            self.reader.join(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            self.process = None

    def rpc(self, method, params):
        """! @brief 실제 JSON-RPC 요청과 동일 ID의 응답을 대조한다."""
        request_id = "요청-" + str(uuid4())
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
        self.process.stdin.flush()
        line = self.responses.get(timeout=8)
        self.assertIsNotNone(line, "service exited before response")
        response = json.loads(line)
        self.assertEqual(response["id"], request_id)
        self.assertNotIn("error", response, response)
        return response["result"]

    def params(self, data, *, project=None, mutation=True):
        """! @brief 변경과 조회의 요청 필드를 명시적으로 분리한다."""
        result = {"contract_version": "rfad.api/2.0", "context": {} if project is None else {"project_id": project}, "input": data}
        if mutation:
            result.update(request_key=str(uuid4()), request_key_epoch=self.epoch)
        return result

    def finish(self, task):
        """! @brief 접수 결과와 terminal 결과를 별도로 검사한다."""
        self.assertEqual(task["state"], "queued")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status = self.rpc("job.status", self.params({"job_id": task["job_id"]}, mutation=False))
            if status["state"] in {"completed", "failed", "interrupted", "cancelled"}:
                self.assertEqual(status["state"], "completed", status)
                return status["events"][-1]["operation_result"]
            time.sleep(0.01)
        self.fail("Job completion timeout")

    def test_project_roundtrip_and_replay_after_real_process_termination(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "실제 서비스 저장소"
            try:
                self.start(workspace)
                capability = self.rpc("capabilities.get", self.params({}, mutation=False))
                self.epoch = capability["idempotency_policy"]["request_key_epoch"]
                self.assertEqual(capability["profile"], "rfad.projects/0.2")
                created = self.finish(self.rpc("project.open", self.params({"open_mode": "create", "path": "projects/실제 IFA", "name": "첫 설계"})))
                command = self.params({"expected_revision": created["revision_id"], "command_id": str(uuid4()), "type": "metadata.rename", "payload": {"name": "저장된 설계"}}, project=created["project_id"])
                changed = self.rpc("project.apply_command", command)
                snapshot = self.finish(self.rpc("snapshot.create", self.params({"expected_revision": changed["new_revision"]}, project=created["project_id"])))
                saved = self.finish(self.rpc("project.save", self.params({"expected_revision": changed["new_revision"]}, project=created["project_id"])))
                sealed = (workspace / snapshot["artifact"]["uri"]).read_bytes()
                self.stop(kill=True)
                self.start(workspace)
                capability = self.rpc("capabilities.get", self.params({}, mutation=False))
                self.assertEqual(capability["idempotency_policy"]["request_key_epoch"], self.epoch)
                self.assertEqual(self.rpc("project.apply_command", command), changed)
                reopened = self.finish(self.rpc("project.open", self.params({"open_mode": "recover", "path": "projects/실제 IFA"})))
                self.assertEqual(reopened["document"]["metadata"]["name"], "저장된 설계")
                self.assertEqual(reopened["revision_id"], saved["saved_revision"])
                self.assertEqual((workspace / snapshot["artifact"]["uri"]).read_bytes(), sealed)
            finally:
                self.stop()


if __name__ == "__main__":
    unittest.main()
