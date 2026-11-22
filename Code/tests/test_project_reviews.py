"""! @brief 화면의 출처와 해석 사전 검토가 보존 개정과 실행 이력을 바꾸지 않는지 확인한다."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import project_evidence, solver_preview
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture, request
from test_pcb_solver import fixture_document, runtime_identity, SETTINGS
from test_targets import target_input


def read_params(document, **values):
    """! @brief 조회에는 mutation key를 발급하지 않는다."""
    return {"contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]},
            "input": {"expected_revision": document["revision_id"], **values}}


class ProjectReviewTests(unittest.TestCase):
    def test_selected_target_history_and_saved_revision_are_read_only(self):
        """! @brief 목표 ID를 따라가며 저장본과 적용 개정, 미정값을 분리해 표시한다."""
        with TemporaryDirectory() as root, ProjectService(Path(root), auto_run=False) as service:
            document, _ = register_fixture(service, fixture_document())
            saved = document["revision_id"]
            target = target_input()
            other = target_input(start=5.0, end=5.2)
            for value in (target, other):
                service.mutate("project.apply_command", request(service, document["project_id"], {
                    "expected_revision": document["revision_id"], "command_id": str(uuid4()),
                    "type": "target.set", "payload": {"target": value},
                }))
                service.run_next()
                document = service._load(service.journal.read()["projects"][document["project_id"]])
            state = service.journal.read()
            result = project_evidence.read(service, read_params(document, target_id=target["id"]))
            self.assertEqual(result["saved_revision"], saved)
            self.assertEqual(result["history_total"], 1)
            self.assertEqual(result["history"][0][3], target["id"])
            self.assertIn("미정", result["records"][0]["values"][1][3])
            self.assertIn("사용자 정합 목표", result["records"][0]["source"])
            self.assertEqual(service.journal.read(), state)
            with self.assertRaises(ProjectError):
                project_evidence.read(service, read_params({**document, "revision_id": saved}))

    def test_solver_preview_uses_real_plan_without_publishing_snapshot(self):
        """! @brief 실제 계획의 자원값을 사용하고 조회 뒤 파일과 journal을 그대로 보존한다."""
        with TemporaryDirectory() as root, ProjectService(Path(root), auto_run=False) as service:
            document, _ = register_fixture(service, fixture_document())
            state = service.journal.read()
            files = sorted(path.relative_to(root) for path in Path(root).rglob("*"))
            with patch.object(service.solver, "runtime", SimpleNamespace(identity=runtime_identity())):
                result = solver_preview.read(service, read_params(document, settings=SETTINGS))
            self.assertGreater(result["estimated"]["estimated_grid_points"], 0)
            self.assertEqual(result["settings"]["grid_mm"], SETTINGS["grid_mm"])
            self.assertEqual(service.journal.read(), state)
            self.assertEqual(sorted(path.relative_to(root) for path in Path(root).rglob("*")), files)
