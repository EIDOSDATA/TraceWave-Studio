"""! @brief 실제 문헌/초기식 폼과 작업 영역을 적용/이력/저장/재열기까지 검사한다."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application.projects import ProjectService
from rfad.templates.printed_references import IFA_08MM, MONOPOLE
from test_cad_worker_process import register_fixture
from test_template_candidates import base_document, IFA


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


@unittest.skipUnless(sys.platform == "win32" and GUI, "RFAD_GUI_EXE로 Windows GUI를 지정합니다.")
class GuiPrintedSeedTests(unittest.TestCase):
    """! @brief geometry-only 시험이며 RF/실측 또는 프레임 예산 합격을 주장하지 않는다."""

    def test_printed_modes_scope_history_and_workspace(self):
        """! @brief 실제 이벤트와 서비스 결과에서 조건 제한과 원본 보존을 확인한다."""
        with TemporaryDirectory(prefix="TraceWave 문헌 초기식 ") as temporary:
            directory = Path(temporary)
            workspace = directory / "작업 영역"
            original = base_document(IFA, missing=True)
            with ProjectService(workspace, auto_run=False) as service:
                register_fixture(service, original)
            report_path = directory / "문헌 초기식 GUI.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([
                str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                "--printed-seed-smoke-test", "--smoke-report", str(report_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                startupinfo=startup, timeout=210, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            artifact_root = os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR", "")
            if artifact_root:
                artifacts = Path(artifact_root)
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / "printed-seed-workspace.json").write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertEqual(report["setup_stage"], 35, report)
            self.assertTrue({"workspace_navigation_and_layer_visibility_without_mutation",
                             "seed_recipe_only_change_requires_discard_confirmation",
                             "source_stackup_conflict_visible_without_default",
                             "seed_scope_block_and_separate_mode_drafts",
                             "estimated_seed_and_late_preview_invalidation",
                             "three_printed_cards_applied_without_physical_defaults",
                             "printed_seed_atomic_undo_redo", "printed_seed_saved_reopen"}
                            <= set(report["setup_checks"]), report)
            self.assertFalse(report["physics_tested"])
            self.assertFalse(report["frame_budget_tested"])
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                stored = service._load(state["projects"][original["project_id"]])
                for key in ("board", "materials", "stackup", "targets", "ports"):
                    self.assertEqual(stored[key], original[key])
                self.assertEqual(len(stored["geometry"]), 7)
                origins = stored["extensions"]["rfad.template-origin"]["instances"]
                self.assertEqual(len(origins), 3)
                seed = next(row for row in origins if row["card"]["template_id"] == MONOPOLE)
                self.assertEqual(seed["initial_estimate"]["length"]["status"], "estimated")
                self.assertFalse(seed["initial_estimate"]["conditions_verified"])
                conflict = next(row for row in origins if row["card"]["template_id"] == IFA_08MM)
                self.assertIn("0.8636", conflict["card"]["evidence"]["source_conflicts"][0])
                self.assertEqual(stored["revision_id"], report["saved_revision"])
                self.assertFalse(any("solver" in row for row in state["jobs"].values()))
            if artifact_root:
                shutil.copytree(workspace, Path(artifact_root) / "printed-visual-workspace", dirs_exist_ok=True)


if __name__ == "__main__":
    unittest.main()
