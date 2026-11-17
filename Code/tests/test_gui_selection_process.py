"""! @brief 실제 Windows 후보 채택 화면과 별도 사본의 저장/재열기를 검증한다.

@details 표본은 명시 합성 저장 계약 fixture이며 이 시험은 FDTD나 안테나 성능 검증이 아니다.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.result_sources import resolve
from rfad.domain.sweep_selection import KEY
import test_sweep_selection as selection_fixtures

ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


def fixture(workspace):
    """! @brief 별도 시험 저장소로 복사하고 원문 해시와 실제 서비스 문맥을 함께 보존한다."""
    source = selection_fixtures.SelectionFixture()
    try:
        source.seal()
        data, preview = source.preview()
        if not preview["can_apply"]:
            raise AssertionError(preview)
        state = source.service.journal.read()
        document = deepcopy(source.document)
        inputs = {"project_id": source.project, "revision_id": document["revision_id"], "study_id": source.study,
                  "axis_id": source.axis_id, "context": source.context(), "preview": preview,
                  "fixture_scope": "synthetic storage contract only; no FDTD"}
        files = {str(path.relative_to(source.workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in source.workspace.rglob("*") if path.is_file() and path.name != ".writer.lock"
                 and str(path.relative_to(source.workspace)).startswith("projects")}
        source.service.close()
        shutil.copytree(source.workspace, workspace)
        (workspace / "selection-smoke-fixture.json").write_bytes(canonical_bytes(inputs))
        return document, state, files, inputs
    finally:
        source.close()


@unittest.skipUnless(sys.platform == "win32" and GUI, "RFAD_GUI_EXE로 Windows GUI를 지정합니다.")
class GuiSelectionTests(unittest.TestCase):
    """! @brief native 입력/원자 생성/명시 열기와 원본 보존을 실제 프로세스로 검사한다."""

    def test_native_copy_review_undo_save_restart_preserves_original_and_selected_sources(self):
        """! @brief 계산 재사용 행과 선택 행을 구별하고 기존 원본/결과를 변경하지 않는다."""
        with TemporaryDirectory(prefix="TraceWave 후보 채택 화면 ") as directory:
            workspace = Path(directory) / "작업 영역"
            document, before, files, inputs = fixture(workspace)
            project_id = document["project_id"]
            source = Path(directory) / "조회 오류 시험 진입점"
            package = source / "rfad"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(
                f"__path__.append({str(ROOT / 'src' / 'rfad')!r})\n__version__ = '0.1.0.dev0'\n", encoding="utf-8")
            program = '''"""! @brief 시험용 새 사본의 표시 조회 두 번만 거절하고 실제 서비스를 실행한다."""
import importlib.util
import json
from pathlib import Path
from rfad.application import rpc
original_dispatch = rpc._dispatch
def fault_once(request, service=None, catalog=None):
    method = request.get("method") if isinstance(request, dict) else None
    project = request.get("params", {}).get("context", {}).get("project_id") if isinstance(request, dict) else None
    if project and project != ORIGINAL_PROJECT and method in ("editor.get", "canvas.get"):
        marker = Path(MARKER_DIRECTORY) / ("fault-" + method + ".json")
        if not marker.exists():
            marker.write_text(json.dumps({"method": method, "project_id": project}), encoding="utf-8")
            return rpc._error(request.get("id"), rpc.APPLICATION_ERRORS.get("E_IO", 1099),
                              "GUI 시험의 명시적인 일회 표시 조회 오류", "E_IO")
    return original_dispatch(request, service, catalog)
rpc._dispatch = fault_once
spec = importlib.util.spec_from_file_location("real_rfad_main", REAL_MAIN)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
raise SystemExit(module.main())
'''
            constants = (f"ORIGINAL_PROJECT = {project_id!r}\nMARKER_DIRECTORY = {str(Path(directory))!r}\n"
                         f"REAL_MAIN = {str(ROOT / 'src' / 'rfad' / '__main__.py')!r}\n")
            (package / "__main__.py").write_text(constants + program, encoding="utf-8")
            report_path = Path(directory) / "후보 채택 화면 시험.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(source),
                "--workspace", str(workspace), "--open-project", before["projects"][project_id]["path"], "--selection-smoke-test",
                "--smoke-report", str(report_path)], stdin=subprocess.DEVNULL, capture_output=True,
                startupinfo=startup, timeout=210, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                destination = Path(output) / "selection.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertGreaterEqual(report["service_sessions"], 2)
            self.assertEqual(set(report["setup_checks"]), {
                "selection_late_draft_uncertain_receipt_lifetime", "selection_recovery_key_epoch_persisted",
                "selection_editor_canvas_owner_gate_and_refresh",
                "selection_required_reason_rejection_recovers", "selection_native_candidate_units_sources_and_layout",
                "selection_conditions_do_not_inherit_validation", "selection_review_invalidates_on_input_change",
                "selection_single_copy_keeps_original_open", "selection_explicit_open_and_single_undo",
                "selection_actual_editor_canvas_failure_recovery",
                "selection_copy_undo_redo_native", "selection_saved_copy_service_restart"})
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                self.assertEqual(state["projects"][project_id], before["projects"][project_id])
                self.assertEqual(service._load(state["projects"][project_id]), document)
                self.assertEqual(state["sweeps"], before["sweeps"])
                self.assertEqual(state["solver_results"], before["solver_results"])
                self.assertEqual(state["snapshots"], before["snapshots"])
                created = set(state["projects"]) - set(before["projects"])
                self.assertEqual(len(created), 1)
                identity = created.pop()
                for method in ("editor.get", "canvas.get"):
                    fault = json.loads((Path(directory) / ("fault-" + method + ".json")).read_text(encoding="utf-8"))
                    self.assertEqual(fault, {"method": method, "project_id": identity})
                project = state["projects"][identity]
                self.assertEqual(project["path"], "projects/채택 화면 검증 사본")
                self.assertEqual(project["current"], project["saved"])
                copied = service._load(project)
                self.assertEqual(copied["metadata"]["name"], "채택 화면 검증 사본")
                self.assertEqual(copied["materials"], document["materials"])
                self.assertTrue(any(item["epsilon_r"]["value_si"] is None for item in copied["materials"]))
                origin = copied["extensions"][KEY]["records"][0]
                self.assertEqual((origin["index"], origin["calculated_ordinal"]), (1, 0))
                self.assertEqual(origin["source_pin"], inputs["context"]["source_pin"])
                self.assertEqual(origin["scope"], "editing_copy_only")
                self.assertEqual(origin["reason"], "검토 후 수정한 채택 사유; 출처 유지")
                self.assertEqual(copied["parameters"][inputs["axis_id"]]["quantity"]["source_refs"], ["test:선택한 중복 행 원문"])
                self.assertEqual(copied["parameters"][inputs["axis_id"]]["quantity"]["display_unit"], "um")
                self.assertEqual(len(project["history"]["undo"]), 1)
                receipts = [row for row in state["receipts"].values() if row["method"] == "sweep.selection.apply"]
                self.assertEqual(len(receipts), 1)
                self.assertEqual(receipts[0]["response"]["new_project_id"], identity)
                current_source = resolve(service, {"project_id": project_id}, inputs["context"]["source"])
                self.assertEqual(current_source["pin"], inputs["context"]["source_pin"])
                self.assertEqual(current_source["states"]["physics"], "not_established")
                for uri, expected in files.items():
                    self.assertEqual(hashlib.sha256((workspace / uri).read_bytes()).hexdigest(), expected, uri)


if __name__ == "__main__":
    unittest.main()
