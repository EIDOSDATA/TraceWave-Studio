"""! @brief 개정과 객체의 기록 검색, 보고서 소유 범위 및 빈 결과의 이동을 확인한다."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application import project_activity
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture, request
from test_pcb_solver import SETTINGS, fixture_document


class ProjectActivityTests(unittest.TestCase):
    def test_named_condition_and_report_keep_the_old_object_after_rename(self):
        """! @brief 보존된 개정/객체만 검색하고 결과가 없는 기록은 다른 결과에 연결하지 않는다."""
        with TemporaryDirectory() as folder, ProjectService(Path(folder), auto_run=False) as service:
            document, snapshot = register_fixture(service, fixture_document(arc=True))
            project, old_revision = document["project_id"], document["revision_id"]
            context = {"project_id": project}
            original_feed = document["ports"][0]
            condition = str(uuid4())
            stored = service.mutate("solver.conditions.save", request(service, project, {
                "expected_revision": old_revision, "command_id": condition, "name": "원호 시험 조건", "settings": SETTINGS,
            }))
            changed = service.mutate("project.apply_command", request(service, project, {
                "expected_revision": stored["new_revision"], "command_id": str(uuid4()), "type": "port.set",
                "payload": {"port": {**original_feed, "name": "현재 급전"}},
            }))

            def activity(action, **data):
                """! @brief 서비스 같은 프로젝트와 고정 원본 선택을 전달한다."""
                return project_activity.read(service, {"contract_version": "rfad.api/2.0", "context": context,
                                                       "input": {"page": action, **data}})

            def search(**data):
                """! @brief 필터와 페이지를 함께 전달한다."""
                return activity("search", **{"category": "all", "revision": "", "object": "",
                                             "offset": 0, "limit": 20, "catalog_hash": None, **data})

            publish = {"snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
                       "records": [], "inclusion": "design_and_report", "rights_confirmed": False}
            from rfad.application.handoff_service import read as handoff
            preview = handoff(service, "package.preview", {"contract_version": "rfad.api/2.0", "context": context,
                                                          "input": publish})
            package = service.mutate("package.build", request(service, project, {
                **publish, "review_hash": preview["review_hash"],
            }))
            state = service.journal.read()
            page = search(revision=old_revision[:8].upper(), object=original_feed["name"].upper(), limit=1)
            self.assertEqual(page["current_revision_id"], changed["new_revision"])
            self.assertEqual(page["total"], 2)
            next_page = search(revision=old_revision[:8].upper(), object=original_feed["name"].upper(), limit=1,
                               offset=1, catalog_hash=page["catalog_hash"])
            self.assertEqual({page["items"][0]["id"], next_page["items"][0]["id"]}, {condition, package["package_id"]})
            self.assertEqual(search(object="현재 급전")["total"], 0)
            self.assertEqual(search(category="run", revision=old_revision)["total"], 0)
            self.assertEqual(search(category="settings", revision=stored["new_revision"])["items"][0]["id"], condition)
            self.assertEqual(search(category="report", object=original_feed["id"],
                                    revision=snapshot["snapshot_id"])["items"][0]["id"], package["package_id"])
            report = activity("detail", kind="handoff_report", id=package["package_id"])
            self.assertEqual(report["body"]["content_hash"], snapshot["content_hash"])
            self.assertEqual(report["body"]["package"]["artifact"], package["artifact"])
            self.assertEqual(report["links"], [])
            details = activity("detail", kind="condition", id=condition)
            self.assertEqual(details["body"]["settings"], SETTINGS)
            self.assertEqual(details["links"], [])
            self.assertEqual(activity("origin", kind="condition", id=condition)["document"], document)
            with self.assertRaises(ProjectError) as wrong_result:
                activity("pin", kind="condition", id=condition, artifact_id=str(uuid4()))
            self.assertEqual(wrong_result.exception.code, "E_MISSING_ARTIFACT")
            with self.assertRaises(ProjectError) as changed_query:
                search(offset=1, limit=1, catalog_hash="0" * 64)
            self.assertEqual(changed_query.exception.code, "E_CONFLICT")
            with self.assertRaises(ProjectError) as wrong_kind:
                activity("detail", kind="rf_report", id=package["package_id"])
            self.assertEqual(wrong_kind.exception.code, "E_MISSING_ARTIFACT")
            self.assertEqual(service.journal.read(), state)
