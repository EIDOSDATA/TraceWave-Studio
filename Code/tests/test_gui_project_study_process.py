"""! @brief 실제 wxWidgets 연구 폼에서 미정 물성을 보완하지 않고 실행을 차단하는지 검사한다."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application.projects import ProjectService
from rfad.domain.project import new_project
from test_cad_worker_process import register_fixture


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


@unittest.skipUnless(sys.platform == "win32" and GUI and (ROOT / ".local/wsl/native-audit.json").is_file(),
                     "Windows GUI와 기존 WSL 감사 기록이 필요합니다.")
class GuiProjectStudyTests(unittest.TestCase):
    """! @brief GUI는 source preflight를 우회하거나 기하/물성 기본값을 생성하지 않는다."""

    def test_missing_physics_keeps_original_and_creates_no_native_job(self):
        """! @brief 일반 프로젝트에서 연구 생성 실패와 원본/이력 불변을 확인한다."""
        with TemporaryDirectory(prefix="TraceWave 연구 GUI ") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            with ProjectService(workspace, auto_run=False) as service:
                original, _ = register_fixture(service, new_project("미정 조건 연구"))
            report = root / "gui-study.json"
            args = [str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                    "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증", "--openems-wsl",
                    "--study-smoke-test", "--study-expect-failure", "--smoke-report", str(report)]
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=150, check=False)
            self.assertTrue(report.exists(), result.stderr)
            smoke = json.loads(report.read_bytes())
            self.assertEqual(result.returncode, 0, smoke)
            self.assertTrue(smoke["passed"], smoke)
            self.assertIn("missing_physics_not_filled_or_executed", smoke["study_checks"])
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                self.assertFalse(state["studies"])
                self.assertFalse(any("solver" in job for job in state["jobs"].values()))
                self.assertEqual(service._load(state["projects"][original["project_id"]]), original)


if __name__ == "__main__":
    unittest.main()
