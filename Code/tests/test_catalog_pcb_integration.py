"""! @brief 통합 도구가 누락 입력과 부분 완료를 성공으로 오인하지 않는지 확인한다."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from catalog_pcb_verification.runner import run
from catalog_pcb_verification.common import publish_report
from test_design import quantity, unknown
import test_pcb_selection_service as selection_fixture


class CatalogPcbIntegrationTests(unittest.TestCase):
    """! @brief 실제 공개 선택/저장을 사용하며 native worker 실행 여부만 감시한다."""

    def setUp(self):
        """! @brief 선택 출처가 있는 미정 물성 2층 시험 프로젝트를 저장한다."""
        self.fixture = selection_fixture.PcbSelectionServiceTests()
        self.fixture.setUp()
        specification = selection_fixture.manual_specification()
        specification["catalog_id"] = self.fixture.catalog_id
        specification["materials"] = [selection_fixture.manual_material(catalog=True)]
        self.fixture.apply(self.fixture.selection(specification))
        document = self.fixture.document()
        net_id = str(uuid4())
        self.fixture.command("net.set", {"net": {"id": net_id, "name": "통합 검사 시험 net"}})
        self.fixture.command("geometry.set", {"geometry": {
            "id": str(uuid4()), "kind": "line_path", "role": "radiator",
            "frame_id": document["frames"]["board"]["id"], "layer_id": document["stackup"][-1]["id"], "net_id": net_id,
            "material_ref": None, "source_ref": None, "include_in_em": True, "include_in_export": True,
            "start": [quantity(-5, "mm"), quantity(0, "mm")],
            "end": [quantity(5, "mm"), quantity(0, "mm")], "width": quantity(1, "mm"),
        }})
        self.report = self.fixture.root / "report.json"

    def tearDown(self):
        """! @brief 시험이 소유한 서비스와 임시 경로만 닫는다."""
        self.fixture.tearDown()

    def prepare(self, *, save=True):
        """! @brief worker가 없는 검증 도구에 저장소 소유권을 넘긴다."""
        self.document = self.fixture.document()
        if save:
            self.fixture.complete("project.save", self.fixture.request({"expected_revision": self.document["revision_id"]}))
        self.fixture.service.close()

    def execute(self, **options):
        """! @brief 동일한 저장 프로젝트에서 검증 보고서를 생성한다."""
        return run(self.fixture.workspace, "projects/test", self.report, **options)

    def test_missing_properties_block_full_run_without_runtime_or_mutation(self):
        """! @brief 미정 입력이면 native 호출 없이 이유와 재열기 결과를 기록한다."""
        layer = deepcopy(self.fixture.document()["stackup"][1])
        layer["thickness"] = unknown("length", "mm")
        self.fixture.command("layer.set", {"layer": layer})
        self.prepare()
        with patch("catalog_pcb_verification.runner.verify_cad") as cad, patch("catalog_pcb_verification.runner.verify_solver") as solver:
            report = self.execute(mode="full")
        self.assertEqual(report["status"], "needs_inputs")
        self.assertTrue(report["project_unchanged"])
        self.assertTrue(report["restored_without_catalog_or_workers"])
        self.assertEqual(report["checks"]["em"]["input_status"], "blocked")
        self.assertGreater(report["checks"]["em"]["diagnostic_count"], 0)
        cad.assert_not_called()
        solver.assert_not_called()
        self.assertNotIn("solver", report)
        self.assertEqual(json.loads(self.report.read_bytes()), report)

    def test_inspection_does_not_require_worker_or_invent_properties(self):
        """! @brief 재료 누락을 보존하고 카탈로그 DB 없이 검사한다."""
        self.prepare()
        self.fixture.database.unlink()
        report = self.execute()
        self.assertEqual(report["status"], "needs_inputs")
        self.assertEqual(report["checks"]["geometry"]["input_status"], "valid")
        self.assertFalse(report["physics_validated"])
        self.assertTrue(report["project_unchanged"])

    def test_cad_requires_explicit_runtime_and_failure_is_preserved(self):
        """! @brief 형상 입력이 있어도 실행 파일 미지정은 검증 성공으로 기록하지 않는다."""
        self.prepare()
        with patch("catalog_pcb_verification.runner.verify_cad", return_value={"status": "passed"}) as cad, \
             patch("catalog_pcb_verification.runner.restore_cad") as restore, \
             patch("catalog_pcb_verification.runner.verify_solver") as solver:
            report = self.execute(mode="full", cad_runtime=None)
            self.assertEqual(report["status"], "failed")
            cad.assert_not_called()
            restore.assert_not_called()
            solver.assert_not_called()

    def test_revision_conflict_and_unsaved_revision_fail_before_snapshot(self):
        """! @brief 사용자 편집을 암묵적으로 저장하거나 다른 개정으로 실행하지 않는다."""
        self.prepare(save=False)
        report = self.execute()
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("snapshot", report)
        self.assertIn("먼저 저장", report["error"]["message"])

    def test_existing_report_is_not_overwritten(self):
        """! @brief 재실행은 기존 증거 파일을 덮어쓸 수 없다."""
        self.prepare()
        self.report.write_text("previous evidence", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(self.report.read_text(encoding="utf-8"), "previous evidence")

    def test_expected_revision_mismatch_is_reported(self):
        """! @brief 잘못된 개정 요청을 worker 시작 전에 거절한다."""
        self.prepare()
        report = self.execute(expected_revision="not-the-current-revision")
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("snapshot", report)

    def test_report_publish_failure_preserves_previous_json(self):
        """! @brief 마지막 파일 교체 실패가 이전 검증 증거를 손상하지 않는다."""
        previous = {"status": "running", "mode": "full"}
        self.report.write_text(json.dumps(previous), encoding="utf-8")
        with patch("catalog_pcb_verification.common.os.replace", side_effect=OSError("시험 교체 실패")):
            with self.assertRaises(OSError):
                publish_report(self.report, {"status": "passed"})
        self.assertEqual(json.loads(self.report.read_bytes()), previous)
        self.assertEqual(list(self.report.parent.glob("report.json.*.tmp")), [])

    def test_inspect_ignores_configured_native_runtimes(self):
        """! @brief 입력 검사에서는 주어진 native 실행 객체도 연결하지 않는다."""
        self.prepare()
        from rfad.application.projects import ProjectService
        with patch("catalog_pcb_verification.runner.ProjectService", wraps=ProjectService) as factory:
            report = self.execute(cad_runtime=object(), solver_runtime=object())
        self.assertEqual(report["status"], "needs_inputs")
        self.assertIsNone(factory.call_args_list[0].kwargs["cad_runtime"])
        self.assertIsNone(factory.call_args_list[0].kwargs["solver_runtime"])


if __name__ == "__main__":
    unittest.main()
