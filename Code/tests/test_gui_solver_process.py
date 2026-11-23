"""! @brief 실제 wxWidgets에서 원형 PCB 생성과 해석 준비 및 결과 수명을 확인한다."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import xml.etree.ElementTree as ET

from rfad.application.projects import ProjectService
from rfad.domain.project import new_project
from test_cad_worker_process import register_fixture
from test_pcb_solver import fixture_document, SETTINGS
from test_pcb_voids import drilled_board, polygon_board
from test_pcb_surfaces import add_mask, rectangle


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")
WINDOWS_RUNTIME = os.environ.get("RFAD_TEST_WINDOWS_SOLVER") == "1"
AUDIT = ".local/openems-windows/native-audit.json" if WINDOWS_RUNTIME else ".local/wsl/native-audit.json"
HAS_RUNTIME = (ROOT / AUDIT).is_file()
RUN_NATIVE = WINDOWS_RUNTIME or os.environ.get("RFAD_TEST_WSL") == "1"


@unittest.skipUnless(sys.platform == "win32" and GUI and HAS_RUNTIME, "Windows GUI와 고정 해석 환경 감사가 필요합니다.")
class GuiSolverProcessTests(unittest.TestCase):
    """! @brief GUI의 표시/상태 검증과 실제 안테나의 물리 정확도 판정을 구분한다."""

    def run_gui(self, directory, document, *, settings=None, invalid=False, active_cancel=False):
        """! @brief 실제 서비스를 등록된 작업 영역으로 열고 GUI가 API 사슬을 수행하게 한다."""
        workspace = directory / "한글 PCB 해석 작업"
        with ProjectService(workspace, auto_run=False) as service:
            register_fixture(service, document)
        report = directory / "GUI solver 검증.json"
        smoke_switch = "--solver-active-cancel-smoke-test" if active_cancel else "--solver-smoke-test"
        args = [str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                smoke_switch, "--smoke-report", str(report)]
        if not WINDOWS_RUNTIME:
            args.append("--openems-wsl")
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
            self.assertEqual(result["solver_cancel_trace"], {})
            self.assertFalse(list(workspace.rglob("normalized.json")))
            with ProjectService(workspace, auto_run=False) as service:
                project = service.journal.read()["projects"][result["project_id"]]
                board = service._load(project)["board"]["outline"]
                self.assertEqual(board["kind"], "circle")
                self.assertAlmostEqual(board["radius"]["value_si"], 0.02)

    @unittest.skipUnless(RUN_NATIVE, "실제 계산 환경은 RFAD_TEST_WINDOWS_SOLVER 또는 RFAD_TEST_WSL로 선택합니다.")
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
            cancel = result["solver_cancel_trace"]
            self.assertEqual(cancel["control"]["state"], "cancel_requested")
            self.assertFalse(cancel["control"]["button_enabled"])
            self.assertGreaterEqual(cancel["receipt"]["elapsed_ms"], cancel["control"]["elapsed_ms"])
            self.assertGreaterEqual(cancel["terminal"]["elapsed_ms"], cancel["control"]["elapsed_ms"])
            self.assertGreaterEqual(cancel["terminal"]["events_cursor"], cancel["receipt"]["events_cursor"])
            with ProjectService(workspace, auto_run=False) as service:
                job = service.journal.read()["jobs"][cancel["job_id"]]
                self.assertIn(job["state"], ("cancelled", "completed"))
                self.assertEqual(job["state"], cancel["terminal"]["state"])
                self.assertEqual(len(job["events"]), cancel["terminal"]["events_cursor"])

    @unittest.skipUnless(RUN_NATIVE, "실제 계산 환경은 RFAD_TEST_WINDOWS_SOLVER 또는 RFAD_TEST_WSL로 선택합니다.")
    def test_active_analysis_cancel_acknowledgement_and_restore(self):
        """! @brief 스냅샷이 아니라 실행 중인 해석을 취소하고 영속 종료와 결과 재열기를 대조한다."""
        with TemporaryDirectory(prefix="TraceWave GUI PCB active cancel ") as temporary:
            workspace, result = self.run_gui(Path(temporary), fixture_document(circle=True, arc=True),
                                             settings=SETTINGS, active_cancel=True)
            cancel = result["solver_cancel_trace"]
            self.assertEqual(cancel["phase_before"], "analysis")
            self.assertEqual(cancel["state_before"], "running")
            self.assertIs(cancel["guest_worker_attached"], True)
            self.assertFalse(cancel["control"]["button_enabled"])
            self.assertIn(cancel["receipt"]["state"], ("cancel_requested", "cancelled"))
            self.assertEqual(cancel["terminal"]["state"], "cancelled")
            self.assertIs(cancel["terminal"]["termination_confirmed"], True)
            self.assertIs(cancel["terminal"]["outcome_unknown"], False)
            self.assertIn("restart_restores_result", result["solver_checks"])
            self.assertTrue(result["solver_result"]["artifact_id"])
            with ProjectService(workspace, auto_run=False) as service:
                job = service.journal.read()["jobs"][cancel["job_id"]]
                self.assertEqual(job["kind"], "em_analysis")
                self.assertEqual(job["state"], "cancelled")
                self.assertEqual(len(job["events"]), cancel["terminal"]["events_cursor"])
                self.assertIs(job["solver"]["guest_worker_attached"], True)
                self.assertIsNot(job["solver"]["process_outcome"].get("not_started"), True)

    @unittest.skipUnless(RUN_NATIVE, "실제 계산 환경은 RFAD_TEST_WINDOWS_SOLVER 또는 RFAD_TEST_WSL로 선택합니다.")
    def test_radiation_pages_display_with_snapshot_and_restart(self):
        """! @brief 실제 NF2FF 결과를 wx 화면에서 페이지로 읽고 phi/지표를 전환한다."""
        settings = {**SETTINGS, "air_padding_mm": 8,
                    "radiation": {"frequency_hz": [10e9], "theta_step_deg": 15, "phi_step_deg": 15}}
        with TemporaryDirectory(prefix="TraceWave GUI NF2FF ") as temporary:
            _, result = self.run_gui(Path(temporary), fixture_document(circle=True, arc=True), settings=settings)
            self.assertIn("radiation_paged_view_and_phi_metric_selection", result["solver_checks"])
            self.assertIn("restart_restores_result", result["solver_checks"])
            self.assertFalse(result["solver_result"]["radiation_summary"]["physics_validated"])

    @unittest.skipUnless(RUN_NATIVE, "실제 계산 환경은 RFAD_TEST_WINDOWS_SOLVER 또는 RFAD_TEST_WSL로 선택합니다.")
    def test_mechanical_voids_actual_execution_and_reopen(self):
        """! @brief 홀, 슬롯, 내부 절삭의 실제 재료 소비와 Windows 재열기를 확인한다."""
        self.verify_mechanical_board(drilled_board(), "box")

    @unittest.skipUnless(RUN_NATIVE, "실제 계산 환경은 RFAD_TEST_WINDOWS_SOLVER 또는 RFAD_TEST_WSL로 선택합니다.")
    def test_concave_board_masks_and_cutouts_actual_execution_and_reopen(self):
        """! @brief 오목 기판의 실제 외곽을 마스크와 관통부까지 적용한다."""
        document = polygon_board(drilled_board())
        mask = add_mask(document)
        mask["openings"] = [rectangle(6, 4, 4, 4)]
        self.verify_mechanical_board(document, "linear_polygon")

    def verify_mechanical_board(self, document, primitive):
        """! @brief 봉인 준비의 native 기판 종류와 기계 원본을 Windows 결과에 대응시킨다."""
        with TemporaryDirectory(prefix="TraceWave PCB voids ") as temporary:
            workspace, result = self.run_gui(Path(temporary), document, settings=SETTINGS)
            self.assertIn("restart_restores_result", result["solver_checks"])
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                record = state["solver_results"][result["solver_result"]["artifact_id"]]
                prepared = state["prepared_plans"][record["prepared_plan_id"]]
                reference = next(item["artifact"] for item in prepared["files"] if item["role"] == "consumption_report")
                report = json.loads(service.journal.read_artifact(reference))
                self.assertEqual(report["board_native_primitive"], primitive)
                mappings = report["mechanical_source_mapping"]
                self.assertEqual({item["kind"] for item in mappings}, {"circle", "capsule", "polygon"})
                self.assertTrue(all(item["vacuum_point_checked"] for item in mappings))
                stored = service._load(state["projects"][result["project_id"]])
                self.assertEqual(stored["pcb"], document["pcb"])
                self.assertEqual(stored["board"]["cutouts"], document["board"]["cutouts"])
                self.assertEqual(stored["board"]["outline"], document["board"]["outline"])
                if primitive == "linear_polygon":
                    fragment = next(item["artifact"] for item in prepared["files"] if item["role"] == "native_input")
                    xml = ET.fromstring(service.journal.read_artifact(fragment))
                    layer = document["stackup"][0]["id"]
                    self.assertIsNotNone(xml.find(f".//Material[@Name='dielectric_{layer}']/Primitives/LinPoly"))
                    self.assertEqual(report["surface_source_mapping"][0]["openings_checked"], 1)


if __name__ == "__main__":
    unittest.main()
