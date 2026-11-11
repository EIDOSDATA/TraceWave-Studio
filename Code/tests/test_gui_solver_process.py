"""! @brief 실제 wxWidgets에서 원형 PCB 생성과 해석 준비 및 결과 수명을 확인한다."""

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
from test_pcb_solver import fixture_document, SETTINGS


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")
HAS_RUNTIME = (ROOT / ".local/wsl/native-audit.json").is_file()


@unittest.skipUnless(sys.platform == "win32" and GUI and HAS_RUNTIME, "Windows GUI와 고정 WSL 런타임 감사가 필요합니다.")
class GuiSolverProcessTests(unittest.TestCase):
    """! @brief GUI의 표시/상태 검증과 실제 안테나의 물리 정확도 판정을 구분한다."""

    def run_gui(self, directory, document, *, settings=None, invalid=False):
        """! @brief 실제 서비스를 등록된 작업 영역으로 열고 GUI가 API 사슬을 수행하게 한다."""
        workspace = directory / "한글 PCB 해석 작업"
        with ProjectService(workspace, auto_run=False) as service:
            register_fixture(service, document)
        report = directory / "GUI solver 검증.json"
        args = [str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                "--openems-wsl", "--solver-smoke-test", "--smoke-report", str(report)]
        if invalid:
            args.append("--solver-expect-failure")
        if settings is not None:
            settings_path = directory / "해석 조건.json"
            settings_path.write_text(json.dumps(settings), encoding="utf-8")
            args.extend(["--solver-settings", str(settings_path)])
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        # @brief 결과 그래프의 실제 paint 이벤트를 관측하고 종료 시 창을 회수한다.
        startup.wShowWindow = 1
        process = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 timeout=630, startupinfo=startup, check=False)
        self.assertTrue(report.is_file(), (process.returncode, process.stderr))
        result = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(process.returncode, 0, result)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["solver_stage"], 7, result)
        return workspace, result

    def test_create_circle_then_reject_missing_physics(self):
        """! @brief 원형 외곽 생성은 지원하고 필수 물성/급전 누락은 해석 성공으로 표시하지 않는다."""
        with TemporaryDirectory(prefix="TraceWave GUI 원형 PCB ") as temporary:
            workspace, result = self.run_gui(Path(temporary), new_project("원형 PCB 입력 검사"), invalid=True)
            self.assertEqual(result["solver_checks"], ["circular_board_created", "circular_board_display", "invalid_physics_not_published"])
            self.assertFalse(result["solver_result"])
            self.assertEqual(result["solver_sample_count"], 0)
            self.assertFalse(list(workspace.rglob("normalized.json")))
            with ProjectService(workspace, auto_run=False) as service:
                project = service.journal.read()["projects"][result["project_id"]]
                board = service._load(project)["board"]["outline"]
                self.assertEqual(board["kind"], "circle")
                self.assertAlmostEqual(board["radius"]["value_si"], 0.02)

    @unittest.skipUnless(os.environ.get("RFAD_TEST_WSL") == "1", "실제 WSL 계산은 RFAD_TEST_WSL=1로 명시합니다.")
    def test_circle_arc_native_results_save_cancel_and_restart(self):
        """! @brief 원형/원호 PCB의 실제 결과 표시와 편집 독립성을 확인하되 RF 정확도를 판정하지 않는다."""
        with TemporaryDirectory(prefix="TraceWave GUI PCB native ") as temporary:
            workspace, result = self.run_gui(Path(temporary), fixture_document(circle=True, arc=True), settings=SETTINGS)
            self.assertEqual(result["solver_checks"], ["circular_board_display", "editing_enabled_during_solver",
                "snapshot_fixed_and_stale_label", "bounded_results_rendered", "save_during_solver",
                "cancel_preserves_previous_result", "restart_restores_result"])
            self.assertEqual(result["solver_sample_count"], SETTINGS["frequency_hz"]["count"])
            self.assertGreater(result["solver_frames"], 0)
            self.assertTrue(result["solver_result"]["artifact_id"])
            self.assertTrue(list(workspace.rglob("normalized.json")))

    @unittest.skipUnless(os.environ.get("RFAD_TEST_WSL") == "1", "실제 WSL 계산은 RFAD_TEST_WSL=1로 명시합니다.")
    def test_radiation_pages_display_with_snapshot_and_restart(self):
        """! @brief 실제 NF2FF 결과를 wx 화면에서 페이지로 읽고 phi/지표를 전환한다."""
        settings = {**SETTINGS, "air_padding_mm": 8,
                    "radiation": {"frequency_hz": [10e9], "theta_step_deg": 15, "phi_step_deg": 15}}
        with TemporaryDirectory(prefix="TraceWave GUI NF2FF ") as temporary:
            _, result = self.run_gui(Path(temporary), fixture_document(circle=True, arc=True), settings=settings)
            self.assertIn("radiation_paged_view_and_phi_metric_selection", result["solver_checks"])
            self.assertIn("restart_restores_result", result["solver_checks"])
            self.assertFalse(result["solver_result"]["radiation_summary"]["physics_validated"])


if __name__ == "__main__":
    unittest.main()
