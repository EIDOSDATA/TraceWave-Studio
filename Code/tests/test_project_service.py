"""! @brief 명령, 저장, 스냅샷과 재접수의 영속 경계를 검증한다."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from rfad.application.projects import ProjectService, RETENTION_SECONDS
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity


class ProjectServiceTests(unittest.TestCase):
    """! @brief 실제 임시 파일 저장소를 이용해 정상/실패 경로를 확인한다."""

    def setUp(self):
        """! @brief 한국어와 공백을 포함한 작업 영역을 생성한다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "설계 저장소"
        self.now = 1_800_000_000.0
        self.service = ProjectService(self.path, clock=lambda: self.now, auto_run=False)

    def tearDown(self):
        """! @brief worker와 파일 잠금을 해제한다."""
        self.service.close()
        self.temporary.cleanup()

    def request(self, data, project_id=None, *, key=None, epoch=None):
        """! @brief 현재 profile의 명시적 멱등 키를 가진 요청을 만든다."""
        return {"contract_version": "rfad.api/2.0", "context": {} if project_id is None else {"project_id": project_id}, "input": data, "request_key": key or str(uuid4()), "request_key_epoch": epoch or self.service.policy()["request_key_epoch"]}

    def status(self, job_id, cursor=0):
        """! @brief 저장된 작업 상태를 조회한다."""
        return self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": job_id, "cursor": cursor}})

    def complete(self, method, params):
        """! @brief 접수와 실행 결과를 별개 단계로 검사한다."""
        task = self.service.mutate(method, params)
        self.assertEqual(task["state"], "queued")
        self.assertTrue(self.service.run_next())
        status = self.status(task["job_id"])
        self.assertEqual(status["state"], "completed", status)
        return status["events"][-1]["operation_result"]

    def create(self, path="projects/IFA 보드"):
        """! @brief 물성을 임의 생성하지 않는 빈 프로젝트를 만든다."""
        return self.complete("project.open", self.request({"open_mode": "create", "path": path, "name": "IFA 시작"}))

    def rename(self, project, name="변경된 이름"):
        """! @brief 명시한 revision에서 이름 변경 명령을 보낸다."""
        return self.request({"expected_revision": project["revision_id"], "command_id": str(uuid4()), "type": "metadata.rename", "payload": {"name": name}}, project["project_id"])

    def test_create_apply_save_reopen_after_service_restart(self):
        project = self.create()
        self.assertEqual(project["document"]["materials"], [])
        parameter_id = str(uuid4())
        quantity = Quantity.from_value(40, "mm", source_refs=("사용자 입력",)).to_dict()
        params = self.request({"expected_revision": project["revision_id"], "command_id": str(uuid4()), "type": "parameter.set", "payload": {"id": parameter_id, "name": "보드 폭", "quantity": quantity}}, project["project_id"])
        changed = self.service.mutate("project.apply_command", params)
        saved = self.complete("project.save", self.request({"expected_revision": changed["new_revision"]}, project["project_id"]))
        self.assertEqual(saved["saved_revision"], changed["new_revision"])
        self.service.close()
        self.service = ProjectService(self.path, clock=lambda: self.now, auto_run=False)
        reopened = self.complete("project.open", self.request({"open_mode": "open", "path": "projects/IFA 보드"}))
        self.assertEqual(reopened["project_id"], project["project_id"])
        self.assertEqual(reopened["saved_revision"], changed["new_revision"])
        self.assertEqual(reopened["document"]["parameters"][parameter_id]["quantity"], quantity)
        self.assertEqual(self.service.mutate("project.apply_command", params), changed)

    def test_stale_and_invalid_commands_leave_revision_and_receipts_unchanged(self):
        project = self.create()
        self.service.mutate("project.apply_command", self.rename(project))
        before = self.service.journal.read()
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("project.apply_command", self.rename(project, "stale"))
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        self.assertEqual(self.service.journal.read(), before)

    def test_same_key_conflict_and_command_id_cannot_bypass_receipts(self):
        project = self.create()
        params = self.rename(project)
        changed = self.service.mutate("project.apply_command", params)
        count = len(list((self.path / "commits").iterdir()))
        self.assertEqual(self.service.mutate("project.apply_command", params), changed)
        self.assertEqual(len(list((self.path / "commits").iterdir())), count)
        different = deepcopy(params)
        different["input"]["payload"]["name"] = "다른 요청"
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("project.apply_command", different)
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        different["request_key"] = str(uuid4())
        different["input"]["expected_revision"] = changed["new_revision"]
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("project.apply_command", different)
        self.assertEqual(caught.exception.code, "E_CONFLICT")

    def test_existing_receipt_outlives_epoch_but_not_its_own_expiry(self):
        epoch = self.service.policy()["request_key_epoch"]
        self.now += RETENTION_SECONDS - 10
        params = self.request({"open_mode": "create", "path": "projects/expiry", "name": "expiry"}, epoch=epoch)
        task = self.service.mutate("project.open", params)
        self.now += 20
        self.assertEqual(self.service.mutate("project.open", params), task)
        fresh = deepcopy(params)
        fresh["request_key"] = "new-key"
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("project.open", fresh)
        self.assertEqual(caught.exception.code, "E_IDEMPOTENCY_EXPIRED")
        self.now += RETENTION_SECONDS
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("project.open", params)
        self.assertEqual(caught.exception.code, "E_IDEMPOTENCY_EXPIRED")

    def test_snapshot_stays_sealed_after_edit_and_save(self):
        project = self.create()
        request = self.request({"expected_revision": project["revision_id"], "description": "초기"}, project["project_id"])
        first = self.complete("snapshot.create", request)
        original = self.service.journal.read_artifact(first["artifact"])
        second = self.complete("snapshot.create", self.request({"expected_revision": project["revision_id"]}, project["project_id"]))
        self.assertNotEqual(first["snapshot_id"], first["revision_id"])
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual(first["content_hash"], second["content_hash"])
        changed = self.service.mutate("project.apply_command", self.rename(project))
        self.complete("project.save", self.request({"expected_revision": changed["new_revision"]}, project["project_id"]))
        self.assertEqual(self.service.journal.read_artifact(first["artifact"]), original)

    def test_pending_snapshot_uses_captured_revision_and_stale_save_fails(self):
        project = self.create()
        snapshot = self.service.mutate("snapshot.create", self.request({"expected_revision": project["revision_id"]}, project["project_id"]))
        save = self.service.mutate("project.save", self.request({"expected_revision": project["revision_id"]}, project["project_id"]))
        self.service.mutate("project.apply_command", self.rename(project))
        while self.service.run_next():
            pass
        snap = self.status(snapshot["job_id"])["events"][-1]["operation_result"]
        self.assertEqual(snap["revision_id"], project["revision_id"])
        self.assertEqual(self.status(save["job_id"])["state"], "failed")

    def test_failed_publish_does_not_commit_command_or_receipt(self):
        project = self.create()
        params = self.rename(project)
        before = self.service.journal.read()
        def fail(stage):
            if stage == "before_publish":
                raise OSError("injected disk failure")
        self.service.journal.fault_hook = fail
        with self.assertRaises(ProjectError):
            self.service.mutate("project.apply_command", params)
        self.service.journal.fault_hook = None
        self.assertEqual(self.service.journal.read(), before)
        result = self.service.mutate("project.apply_command", params)
        self.assertNotEqual(result["new_revision"], project["revision_id"])

    def test_existing_directory_is_preserved_and_open_corruption_is_reported(self):
        existing = self.path / "projects" / "기존 파일"
        existing.mkdir(parents=True)
        sentinel = existing / "important.txt"
        sentinel.write_text("보존", encoding="utf-8")
        task = self.service.mutate("project.open", self.request({"open_mode": "create", "path": "projects/기존 파일", "name": "새 프로젝트"}))
        self.service.run_next()
        self.assertEqual(self.status(task["job_id"])["state"], "failed")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "보존")
        project = self.create()
        reference = self.service.journal.read()["projects"][project["project_id"]]["current"]
        artifact = self.path / reference["uri"]
        artifact.write_bytes(b"corrupt")
        task = self.service.mutate("project.open", self.request({"open_mode": "open", "path": "projects/IFA 보드"}))
        self.service.run_next()
        self.assertEqual(self.status(task["job_id"])["events"][-1]["error"]["code"], "E_HASH")
        self.assertEqual(artifact.read_bytes(), b"corrupt")

    def test_cancel_is_durable_and_first_terminal_wins(self):
        params = self.request({"open_mode": "create", "path": "projects/cancel", "name": "취소"})
        task = self.service.mutate("project.open", params)
        cancelled = self.service.mutate("job.cancel", self.request({"job_id": task["job_id"], "reason": "사용자 취소"}))
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertFalse(self.service.run_next())
        self.assertFalse((self.path / "projects/cancel").exists())
        self.assertEqual(self.service.mutate("project.open", params), task)
        self.assertEqual(self.status(task["job_id"])["state"], "cancelled")

    def test_rpc_mutating_notification_and_batch_do_not_execute(self):
        params = self.request({"open_mode": "create", "path": "projects/no-side-effect", "name": "금지"})
        request = {"jsonrpc": "2.0", "method": "project.open", "params": params}
        before = self.service.journal.read()
        self.assertIsNone(handle_frame(json.dumps(request).encode(), self.service))
        request["id"] = 1
        response = handle_frame(json.dumps([request]).encode(), self.service)
        self.assertEqual(response["error"]["data"]["domain_code"], "E_UNSUPPORTED")
        self.assertEqual(self.service.journal.read(), before)

    def test_background_worker_executes_real_async_jobs(self):
        self.service.close()
        self.service = ProjectService(self.path)
        task = self.service.mutate("project.open", self.request({"open_mode": "create", "path": "projects/async", "name": "비동기"}))
        deadline = time.monotonic() + 5
        while self.status(task["job_id"])["state"] not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.01)
        status = self.status(task["job_id"])
        self.assertEqual(status["state"], "completed", status)
        self.assertEqual([event["seq"] for event in status["events"]], [1, 2, 3])

    def test_epoch_refresh_does_not_interrupt_live_job(self):
        task = self.service.mutate("project.open", self.request({"open_mode": "create", "path": "projects/live", "name": "진행 중"}))
        self.service.journal.transaction(lambda state: self.service._event(state["jobs"][task["job_id"]], "running"))
        self.now += RETENTION_SECONDS + 1
        self.service.policy()
        self.assertEqual(self.status(task["job_id"])["state"], "running")
        self.service.close()
        self.service = ProjectService(self.path, clock=lambda: self.now, auto_run=False)
        self.assertEqual(self.status(task["job_id"])["state"], "interrupted")

    def test_invalid_batch_method_is_structured_error(self):
        for method in ([], {}):
            response = handle_frame(json.dumps([{"jsonrpc": "2.0", "id": 1, "method": method}]).encode(), self.service)
            self.assertEqual(response[0]["error"]["code"], -32600)

    def test_post_publish_failure_replays_committed_command(self):
        project = self.create()
        params = self.rename(project)
        def fail(stage):
            if stage == "after_publish":
                raise OSError("ack lost after commit")
        self.service.journal.fault_hook = fail
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("project.apply_command", params)
        self.assertTrue(caught.exception.details["committed"])
        self.service.journal.fault_hook = None
        state = self.service.journal.read()
        result = self.service.mutate("project.apply_command", params)
        self.assertEqual(self.service.journal.read(), state)
        self.assertNotEqual(result["new_revision"], project["revision_id"])


if __name__ == "__main__":
    unittest.main()
