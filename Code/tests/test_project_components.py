"""! @brief 분리된 프로젝트 기능의 transaction 경계와 실패 시 자원 보존을 검증한다."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.projects import ProjectService


def request(service, data, project_id=None):
    """! @brief 공개 명령 계약으로 영속 요청을 구성한다."""
    return {
        "contract_version": "rfad.api/2.0",
        "context": {} if project_id is None else {"project_id": project_id},
        "input": data,
        "request_key": str(uuid4()),
        "request_key_epoch": service.policy()["request_key_epoch"],
    }


def create(service, name):
    """! @brief 공개 생성 작업을 완료하고 실제 프로젝트 식별자를 반환한다."""
    task = service.mutate("project.open", request(service, {
        "open_mode": "create", "path": "projects/" + name, "name": name,
    }))
    service.run_next()
    job = service.journal.read()["jobs"][task["job_id"]]
    if job["state"] != "completed":
        raise AssertionError(job)
    return job["events"][-1]["operation_result"]


class ProjectComponentTests(unittest.TestCase):
    """! @brief 모듈 분리 이후에도 작업/명령/저장소가 하나의 원자적 상태를 공유한다."""

    def test_thread_start_failure_preserves_error_and_releases_workspace(self):
        """! @brief thread 시작 자체의 실패를 join 예외로 가리지 않고 writer 잠금을 반환한다."""
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            service = ProjectService.__new__(ProjectService)
            try:
                with patch("threading.Thread.start", side_effect=RuntimeError("injected thread start failure")):
                    with self.assertRaisesRegex(RuntimeError, "injected thread start failure"):
                        service.__init__(workspace)
                with ProjectService(workspace, auto_run=False) as reopened:
                    self.assertTrue(reopened.policy()["mutations_enabled"])
            finally:
                service._thread = None
                service.close()

    def test_partial_start_failure_joins_started_thread_and_releases_workspace(self):
        """! @brief coordinator 시작 실패 뒤 자료 처리 thread와 writer 잠금이 남지 않는다."""
        for owner in ("CadCoordinator", "SolverCoordinator"):
            captured = []

            def fail_start(coordinator):
                """! @brief 실제 자료 처리 thread가 시작된 뒤 연결 실패를 주입한다."""
                captured.append((coordinator.service, coordinator.service._thread))
                raise RuntimeError("injected coordinator start failure")

            with self.subTest(owner=owner), TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                try:
                    with patch("rfad.application.projects." + owner + ".start", fail_start):
                        with self.assertRaisesRegex(RuntimeError, "injected coordinator"):
                            ProjectService(workspace)
                    self.assertEqual(len(captured), 1)
                    self.assertFalse(captured[0][1].is_alive())
                    with ProjectService(workspace, auto_run=False) as reopened:
                        self.assertTrue(reopened.policy()["mutations_enabled"])
                finally:
                    for service, _ in captured:
                        service.close()

    def test_snapshot_rejects_hash_valid_but_noncanonical_captured_document(self):
        """! @brief SHA가 맞아도 정규 문서가 아닌 captured 바이트를 snapshot으로 게시하지 않는다."""
        with TemporaryDirectory() as temporary, ProjectService(Path(temporary), auto_run=False) as service:
            project = create(service, "정규 문서")
            task = service.mutate("snapshot.create", request(service, {
                "expected_revision": project["revision_id"],
            }, project["project_id"]))
            raw = json.dumps(project["document"], ensure_ascii=False, indent=2).encode("utf-8")
            reference = service.journal.put_immutable("test-artifacts/noncanonical.json", raw)
            service.journal.transaction(
                lambda state: state["jobs"][task["job_id"]].update(captured=reference)
            )
            self.assertTrue(service.run_next())
            state = service.journal.read()
            job = state["jobs"][task["job_id"]]
            self.assertEqual(job["state"], "failed")
            self.assertEqual(job["events"][-1]["error"]["code"], "E_HASH")
            self.assertEqual(state["snapshots"], {})
            self.assertEqual(service.journal.read_artifact(reference), raw)

    def test_unknown_data_operation_does_not_create_a_snapshot(self):
        """! @brief 내부 작업 종류가 손상되면 알 수 없는 분기를 snapshot으로 실행하지 않는다."""
        with TemporaryDirectory() as temporary, ProjectService(Path(temporary), auto_run=False) as service:
            project = create(service, "명시적 작업")
            task = service.mutate("snapshot.create", request(service, {
                "expected_revision": project["revision_id"],
            }, project["project_id"]))
            service.journal.transaction(
                lambda state: state["jobs"][task["job_id"]].update(operation_method="project.unknown")
            )
            service.run_next()
            state = service.journal.read()
            job = state["jobs"][task["job_id"]]
            self.assertEqual(job["state"], "failed")
            self.assertEqual(job["events"][-1]["error"]["code"], "E_UNSUPPORTED")
            self.assertEqual(state["snapshots"], {})

    def test_legacy_history_index_preserves_independent_projects(self):
        """! @brief 프로젝트별 색인으로 복원한 undo가 다른 프로젝트의 명령을 소비하지 않는다."""
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with ProjectService(workspace, auto_run=False) as service:
                first, second = create(service, "첫 보드"), create(service, "둘째 보드")
                latest = {}
                for project in (first, second):
                    changed = service.mutate("project.apply_command", request(service, {
                        "expected_revision": project["revision_id"], "command_id": str(uuid4()),
                        "type": "metadata.rename", "payload": {"name": "변경 " + project["document"]["metadata"]["name"]},
                    }, project["project_id"]))
                    latest[project["project_id"]] = changed["new_revision"]

                def remove_histories(state):
                    """! @brief 초기 profile과 같은 이력 미포함 journal 상태를 구성한다."""
                    for project in state["projects"].values():
                        project.pop("history")

                service.journal.transaction(remove_histories)
            with ProjectService(workspace, auto_run=False) as service:
                service.mutate("project.undo", request(service, {
                    "expected_revision": latest[first["project_id"]], "command_id": str(uuid4()),
                }, first["project_id"]))
                state = service.journal.read()
                first_document = service._load(state["projects"][first["project_id"]])
                second_document = service._load(state["projects"][second["project_id"]])
                self.assertEqual(first_document["metadata"]["name"], "첫 보드")
                self.assertEqual(second_document["metadata"]["name"], "변경 둘째 보드")
                self.assertEqual(second_document["revision_id"], latest[second["project_id"]])


if __name__ == "__main__":
    unittest.main()
