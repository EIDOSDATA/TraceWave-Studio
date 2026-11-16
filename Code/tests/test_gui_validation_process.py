"""! @brief 실제 Windows 검증 화면이 실행 없는 불변 보고서와 미정 상태를 보존하는지 검사한다.

@details 새 FDTD를 수행하지 않으며 계산되지 않은 수치나 물리 합격을 시험용으로 만들지 않는다.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.rf_validation_records import read
from rfad.domain.project import new_project
from test_cad_worker_process import register_fixture, request


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


def fixture(workspace):
    """! @brief 실제 공개 서비스로 미실행 계획과 두 개의 별도 미평가 보고서만 만든다."""
    with ProjectService(workspace, auto_run=False) as service:
        document, original_snapshot = register_fixture(service, new_project("독립 RF 기록 화면 - 계산 미실행"))
        project = document["project_id"]

        def query(method, **data):
            """! @brief 원본 프로젝트 문맥으로 읽기 전용 검증 API를 호출한다."""
            return read(service, method, {"contract_version": "rfad.api/2.0",
                "context": {"project_id": project}, "input": data})

        name = "명시 판정 선택 / 미실행 PEC와 급전 차단"
        preview = query("rf.validation.preview", expected_revision=document["revision_id"], name=name)
        created = service.mutate("rf.validation.create", request(service, project, {
            "expected_revision": document["revision_id"], "name": name, "review_hash": preview["review_hash"]}))
        identity = created["validation_id"]
        reports = [service.mutate("rf.validation.assess", request(service, project, {"validation_id": identity}))
                   for _ in range(2)]
        views = [query("rf.validation.get", validation_id=identity, report_id=report["report_id"])
                 for report in reports]
        plan = query("rf.validation.get", validation_id=identity, report_id=None)
        record = deepcopy(service.journal.read()["rf_validations"][identity])
        files = {ref["uri"]: service.journal.read_artifact(ref) for ref in
                 (original_snapshot["artifact"], created["snapshot"]["artifact"], record["definition"],
                  *(report["artifact"] for report in reports))}
        inputs = {"project_id": project, "revision_id": document["revision_id"], "validation_id": identity,
            "plan": plan, "first": views[0], "second": views[1],
            "catalog": query("rf.validation.list", offset=0, limit=25),
            "reports": query("rf.validation.reports", validation_id=identity, offset=0, limit=25)}
        (workspace / "validation-smoke-fixture.json").write_bytes(canonical_bytes(inputs))
        return document, record, files, inputs


class ValidationFixtureTests(unittest.TestCase):
    """! @brief 화면 자료도 실제 공개 계약으로 재열기하며 미실행 상태를 보존한다."""

    def test_unexecuted_reports_are_distinct_read_only_and_keep_unknowns(self):
        """! @brief 판정 두 개의 불변성과 null 계획 선택을 해석 runtime 없이 검사한다."""
        with TemporaryDirectory(prefix="TraceWave 검증 원본 ") as directory:
            workspace = Path(directory)
            document, record, files, inputs = fixture(workspace)
            self.assertNotEqual(inputs["first"]["report_id"], inputs["second"]["report_id"])
            self.assertIsNone(inputs["plan"]["report_id"])
            self.assertEqual(inputs["plan"]["rows"], [])
            with ProjectService(workspace, auto_run=False) as service:
                before = service.journal.read()
                for key in ("plan", "first", "second"):
                    viewed = read(service, "rf.validation.get", {"contract_version": "rfad.api/2.0",
                        "context": {"project_id": document["project_id"]},
                        "input": {"validation_id": record["validation_id"], "report_id": inputs[key]["report_id"]}})
                    self.assertEqual(viewed, inputs[key])
                    self.assertIsNone(viewed["manufacturing"])
                    self.assertIsNone(viewed["measurement"])
                    self.assertEqual(sum(case["blocked_reason"] is not None for case in viewed["cases"]), 6)
                    self.assertTrue(all(case["source"] is None and case["pin"] is None for case in viewed["cases"]))
                self.assertEqual(service.journal.read(), before)
                self.assertEqual(service._load(before["projects"][document["project_id"]]), document)
                for uri, raw in files.items():
                    self.assertEqual((workspace / uri).read_bytes(), raw)


@unittest.skipUnless(sys.platform == "win32" and GUI, "RFAD_GUI_EXE로 Windows GUI를 지정합니다.")
class GuiValidationTests(unittest.TestCase):
    """! @brief 실제 native 목록/선택/스크롤 및 저장 후 서비스 재시작을 검증한다."""

    def test_native_plan_and_immutable_reports_save_restart_preserve_unknowns(self):
        """! @brief 계획을 최신 판정으로 대체하지 않고 명시 선택과 원문을 다시 읽는다."""
        with TemporaryDirectory(prefix="TraceWave RF 검증 화면 ") as directory:
            workspace = Path(directory) / "작업 영역"
            document, record, files, inputs = fixture(workspace)
            report_path = Path(directory) / "검증 화면 시험.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증", "--validation-smoke-test",
                "--smoke-report", str(report_path)], stdin=subprocess.DEVNULL, capture_output=True,
                startupinfo=startup, timeout=180, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                destination = Path(output) / "validation.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertGreaterEqual(report["service_sessions"], 2)
            self.assertEqual(set(report["setup_checks"]), {
                "validation_late_selection_reset_destroy_safe", "validation_named_catalog_and_explicit_report",
                "validation_pinned_source_catalog_and_hash",
                "validation_plan_never_substitutes_report", "validation_original_report_hash",
                "validation_unexecuted_blocked_and_no_source", "validation_unknowns_sources_and_collapsed_raw",
                "validation_visible_tables_and_scroll", "validation_saved_restart_report_preserved",
                "validation_return_design_preserves_selection"})
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                self.assertEqual(state["rf_validations"][record["validation_id"]], record)
                self.assertEqual(service._load(state["projects"][document["project_id"]]), document)
                for key in ("first", "second"):
                    viewed = read(service, "rf.validation.get", {"contract_version": "rfad.api/2.0",
                        "context": {"project_id": document["project_id"]},
                        "input": {"validation_id": record["validation_id"], "report_id": inputs[key]["report_id"]}})
                    self.assertEqual(viewed, inputs[key])
                for uri, raw in files.items():
                    self.assertEqual((workspace / uri).read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
