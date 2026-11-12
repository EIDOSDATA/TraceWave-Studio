"""! @brief 실제 목표/템플릿 화면에서 출처와 최신 개정, 닫기 및 미정 상태를 검증한다."""

import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application.projects import ProjectService
from rfad.domain.project import new_project
from test_cad_worker_process import register_fixture
from test_targets import frequency, set_target, target_input


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


@unittest.skipUnless(sys.platform == "win32" and GUI, "RFAD_GUI_EXE로 Windows GUI를 지정합니다.")
class GuiTargetTemplateTests(unittest.TestCase):
    """! @brief UI에 넣은 수치는 시험용이며 실제 안테나 성능이나 제작 입력이 아니다."""

    def delayed_source(self, directory):
        """! @brief 권위 서비스는 유지하고 설정 조회 응답만 늦춘다."""
        source = directory / "지연 서비스"
        package = source / "rfad"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            f"__path__.append({str(ROOT / 'src' / 'rfad')!r})\n__version__ = '0.1.0.dev0'\n", encoding="utf-8")
        program = "import json, runpy, time\nfrom rfad.application import rpc\n_original = rpc.handle_frame\n"
        program += "def delayed(frame, service=None, catalog=None):\n"
        program += "    request = json.loads(frame)\n"
        program += "    if request.get('method') in ('target.editor.get', 'template.context', 'template.synthesize'):\n"
        program += "        time.sleep(0.25)\n"
        program += "    return _original(frame, service, catalog)\n"
        program += "rpc.handle_frame = delayed\n"
        program += f"runpy.run_path({str(ROOT / 'src' / 'rfad' / '__main__.py')!r}, run_name='__main__')\n"
        (package / "__main__.py").write_text(program, encoding="utf-8")
        return source

    def run_workflow(self, delayed):
        """! @brief 1001개 명시 표본과 근사 출처를 가진 원본에서 실제 GUI 작업을 수행한다."""
        with TemporaryDirectory(prefix="TraceWave 목표 템플릿 ") as temporary:
            directory = Path(temporary)
            workspace = directory / "작업 영역"
            target = target_input()
            samples = [frequency(2.4e9 + index * 1e5, "Hz") for index in range(1001)]
            samples[500]["status"] = "estimated"
            samples[500]["source_refs"] = ["시험용 근사 주파수 / 실측 미확정"]
            target["band"]["sampling"] = {"kind": "explicit", "frequencies": samples}
            original = set_target(new_project("목표와 카드 GUI 검증"), target)[0]
            with ProjectService(workspace, auto_run=False) as service:
                register_fixture(service, original)
                small = set_target(new_project("GUI 카드 형상 검증"), target_input())[0]
                def register_small(state):
                    """! @brief 작은 별도 원본에서 두 카드의 정상 적용을 검증한다."""
                    path = "projects/GUI 카드 형상 검증"
                    reference = service._store_document(path, small)
                    state["projects"][small["project_id"]] = {
                        "path": path, "current": reference, "saved": reference,
                        "revisions": {small["revision_id"]: reference},
                        "history": {"undo": [], "redo": [], "head_revision": small["revision_id"]},
                    }
                    state["paths"][path] = small["project_id"]
                service.journal.transaction(register_small)
            report_path = directory / "설정 화면 결과.json"
            source = self.delayed_source(directory) if delayed else ROOT / "src"
            arguments = [str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(source),
                         "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                         "--design-setup-smoke-test", "--smoke-report", str(report_path)]
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, startupinfo=startup, timeout=210, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            artifact_root = os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR", "")
            if artifact_root:
                artifacts = Path(artifact_root)
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / ("target-template-delayed.json" if delayed else "target-template.json")).write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertEqual(report["setup_stage"], 35, report)
            self.assertFalse(report["physics_tested"])
            self.assertFalse(report["frame_budget_tested"])
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                stored = service._load(state["projects"][original["project_id"]])
                preserved = next(item for item in stored["targets"] if item["id"] == target["id"])
                self.assertEqual(preserved["band"], original["targets"][0]["band"])
                self.assertEqual(preserved["criteria"], original["targets"][0]["criteria"])
                self.assertTrue(set(original["targets"][0]["source_refs"]).issubset(preserved["source_refs"]))
                self.assertEqual(preserved["name"], "GUI 원본 출처 유지")
                self.assertEqual(len(stored["targets"]), 2)
                self.assertEqual(stored["geometry"], [])
                self.assertNotIn("rfad.template-origin", stored["extensions"])
                stored = service._load(state["projects"][small["project_id"]])
                self.assertEqual(len(stored["targets"]), 1)
                self.assertEqual(len(stored["geometry"]), 7)
                self.assertEqual(stored["ports"], [])
                self.assertEqual(stored["materials"], [])
                self.assertIsNone(stored["stackup"][0]["thickness"]["value_si"])
                self.assertEqual(stored["revision_id"], report["saved_revision"])
                self.assertFalse(any("solver" in job for job in state["jobs"].values()))
            if artifact_root and not delayed:
                shutil.copytree(workspace, Path(artifact_root) / "visual-workspace", dirs_exist_ok=True)
            return report

    def test_target_crud_sources_templates_history_and_reopen(self):
        """! @brief 실제 폼/명령으로 다중 목표와 두 카드의 전체 저장 흐름을 검증한다."""
        report = self.run_workflow(False)
        self.assertTrue({"new_target_has_no_physical_defaults", "parent_close_veto_during_target_apply",
                         "target_add_edit_select_remove", "explicit_1001_samples_and_origins_preserved",
                         "unit_only_change_preserves_si_and_missing_conditions", "invalid_target_preserves_draft_and_revision",
                         "latest_target_revision_returned_to_frame", "target_undo_redo", "late_preview_invalidated_by_edit",
                         "completed_changes_reloaded_after_dialog_disconnect",
                         "arc_card_preview_apply_without_physics_defaults", "ifa_card_preview_apply_latest_revision",
                         "template_single_command_undo_redo", "saved_reopen_preserves_geometry",
                         "late_response_close_and_destroy_are_safe", "definitive_rejection_keeps_draft_editable",
                         "uncertain_mutation_requires_reload", "dirty_close_requires_explicit_discard",
                         "failed_target_selection_restores_authoritative_identity",
                         "post_apply_query_failure_locks_without_duplicate_create",
                         "template_card_drafts_and_close_confirmation",
                         "oversized_template_origin_blocks_without_mutation"} <= set(report["setup_checks"]), report)

    def test_delayed_queries_preserve_input_and_latest_selection(self):
        """! @brief 지연한 실제 응답이 수정한 입력이나 닫힌 화면을 덮지 않는다."""
        report = self.run_workflow(True)
        self.assertGreater(report["setup_pending_ticks"], 25, report)


if __name__ == "__main__":
    unittest.main()
