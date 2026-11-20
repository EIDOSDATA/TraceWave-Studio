"""! @brief 명시적으로 선택한 Windows GUI 실행 파일과 실제 서비스 연결을 검증한다."""

import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest


_GUI = os.environ.get("RFAD_GUI_EXE", "")
_SOURCE = Path(__file__).resolve().parents[1] / "src"
_STARTUP_TOOL = _SOURCE.parent / "tools" / "measure_windows_startup.ps1"
_PWSH = shutil.which("pwsh")


@unittest.skipUnless(sys.platform == "win32" and _GUI, "RFAD_GUI_EXE로 Windows GUI 실행 파일을 지정해야 합니다.")
class GuiProcessTests(unittest.TestCase):
    """! @brief 실제 wx 이벤트 루프에서 저장 복구와 비정상 pipe 응답을 확인한다."""

    def run_gui(self, directory: Path, *, source: Path = _SOURCE, python: Path | None = None, editor: bool = False, canvas: bool = False) -> tuple[int, dict]:
        """! @brief 공백과 한글이 포함된 작업 영역으로 smoke를 실행하고 결과를 읽는다."""
        report = directory / "한글 결과 smoke.json"
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        started = time.monotonic()
        process = subprocess.run(
            [str(Path(_GUI).resolve()), "--python", str(python or Path(sys.executable)),
             "--source", str(source), "--workspace", str(directory / "한글 작업 영역"),
             "--canvas-smoke-test" if canvas else ("--editor-smoke-test" if editor else "--smoke-test"), "--smoke-report", str(report)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=90, startupinfo=startup, check=False,
        )
        self.assertTrue(report.is_file(), f"GUI did not write its report: exit={process.returncode}, stderr={process.stderr!r}")
        result = json.loads(report.read_text(encoding="utf-8"))
        result["process_elapsed_seconds"] = time.monotonic() - started
        return process.returncode, result

    def source_stub(self, directory: Path, program: str) -> Path:
        """! @brief 실제 Python 프로세스에서 pipe 장애를 만드는 작은 rfad 진입점을 준비한다."""
        source = directory / "한글 source with spaces"
        package = source / "rfad"
        package.mkdir(parents=True)
        initialization = f"__path__.append({str(_SOURCE / 'rfad')!r})\n"
        initialization += "__version__ = '0.1.0.dev0'\n"
        (package / "__init__.py").write_text(initialization, encoding="utf-8")
        (package / "__main__.py").write_text(program, encoding="utf-8")
        return source

    @unittest.skipUnless(_PWSH, "F0 수집에 PowerShell 7이 필요합니다.")
    def test_f0_startup_records_real_display_and_editor_ready(self):
        """! @brief 첫 캔버스와 새 프로젝트 준비의 서로 다른 실제 시점을 검증한다."""
        with TemporaryDirectory(prefix="rfad F0 시작 ") as temporary:
            report = Path(temporary) / "시작 기록.json"
            command = [_PWSH, "-NoProfile", "-File", str(_STARTUP_TOOL), "-Gui", str(Path(_GUI).resolve()),
                       "-Python", sys.executable, "-Source", str(_SOURCE), "-SampleCount", "1", "-Output", str(report)]
            result = subprocess.run(command, capture_output=True, timeout=100, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            original = report.read_bytes()
            overwrite = subprocess.run(command, capture_output=True, timeout=30, check=False)
            self.assertNotEqual(overwrite.returncode, 0)
            self.assertEqual(report.read_bytes(), original)
            self.assertFalse(list(Path(str(report) + ".workspace").rglob("*.rfad")))
        data = json.loads(original)
        self.assertTrue(data["warmup"]["ok"])
        self.assertEqual(data["summary"]["sample_count"], 1)
        self.assertTrue(data["summary"]["complete"])
        self.assertIsNone(data["summary"]["timing_ms"]["first_window_ms"]["within_target"])
        sample, = data["samples"]
        paint = sample["probe"]["canvas_painted_qpc"]
        ready = sample["probe"]["service_ready_qpc"]
        scale = 1000 / data["qpc_frequency"]
        self.assertGreater(sample["first_window_ms"], 0)
        self.assertAlmostEqual(sample["first_window_ms"], (paint - sample["launch_qpc"]) * scale)
        self.assertAlmostEqual(sample["new_project_ready_ms"], (max(paint, ready) - sample["launch_qpc"]) * scale)

    @unittest.skipUnless(_PWSH, "F0 수집에 PowerShell 7이 필요합니다.")
    def test_f0_startup_fails_when_service_disconnects(self):
        """! @brief 창만 그려지고 서비스가 종료하는 경우 합격값을 만들지 않는다."""
        with TemporaryDirectory(prefix="rfad F0 오류 ") as temporary:
            directory = Path(temporary)
            source = self.source_stub(directory, "raise SystemExit(1)\n")
            report = directory / "실패.json"
            result = subprocess.run(
                [_PWSH, "-NoProfile", "-File", str(_STARTUP_TOOL), "-Gui", str(Path(_GUI).resolve()),
                 "-Python", sys.executable, "-Source", str(source), "-SampleCount", "1", "-Output", str(report)],
                capture_output=True, timeout=100, check=False)
            self.assertNotEqual(result.returncode, 0)
            data = json.loads(report.read_bytes())
        self.assertFalse(data["warmup"]["probe"]["ok"])
        self.assertFalse(data["summary"]["complete"])
        self.assertIsNone(data["summary"]["timing_ms"]["new_project_ready_ms"]["p95"])

    @unittest.skipUnless(_PWSH, "F0 합산에 PowerShell 7이 필요합니다.")
    def test_f0_cold_summary_requires_distinct_matching_boot_records(self):
        """! @brief 합성 표본으로 동일 부팅 거절과 소표본 p95 산식을 검사한다."""
        with TemporaryDirectory(prefix="rfad F0 합산 ") as temporary:
            directory = Path(temporary)
            records = []
            for index, elapsed in enumerate((1000, 2000, 2200, 2300, 3100), start=1):
                record = directory / f"cold-{index}.json"
                record.write_text(json.dumps({
                    "schema": "rfad.windows-startup-measurement/0.1", "mode": "Cold",
                    "boot_started_utc": f"2026-01-{index:02}T00:00:00Z",
                    "cold_first_launch_asserted_by_operator": True, "fixture": {"profile": "synthetic"},
                    "samples": [{"ok": True, "first_window_ms": elapsed, "new_project_ready_ms": elapsed + 900}],
                }), encoding="utf-8")
                records.append(str(record))
            command = [_PWSH, "-NoProfile", "-Command", "& $env:RFAD_F0_TOOL "
                       "-ColdReports (Get-ChildItem -LiteralPath $env:RFAD_F0_FIXTURES -Filter 'cold-*.json').FullName "
                       "-Output $env:RFAD_F0_OUTPUT"]
            output = directory / "합산.json"
            environment = dict(os.environ, RFAD_F0_TOOL=str(_STARTUP_TOOL), RFAD_F0_FIXTURES=temporary,
                               RFAD_F0_OUTPUT=str(output))
            result = subprocess.run(command, capture_output=True, timeout=30, env=environment, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(output.read_bytes())["summary"]
            self.assertEqual(summary["sample_count"], 5)
            self.assertEqual(summary["timing_ms"]["first_window_ms"]["median"], 2200)
            self.assertEqual(summary["timing_ms"]["first_window_ms"]["p95"], 3100)
            self.assertFalse(summary["timing_ms"]["first_window_ms"]["within_target"])
            self.assertTrue(summary["timing_ms"]["new_project_ready_ms"]["within_target"])

            duplicate = directory / "cold-duplicate.json"
            shutil.copyfile(records[0], duplicate)
            environment["RFAD_F0_OUTPUT"] = str(directory / "중복.json")
            result = subprocess.run(command, capture_output=True, timeout=30, env=environment, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(Path(environment["RFAD_F0_OUTPUT"]).exists())

    def test_real_service_save_snapshot_restart_and_korean_paths(self):
        """! @brief 두 서비스 세션 사이에서 변경 내용과 저장 기준점이 보존되는지 검증한다."""
        with TemporaryDirectory(prefix="rfad GUI 한글 ") as temporary:
            code, result = self.run_gui(Path(temporary))
        self.assertEqual(code, 0, result)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["stage"], 5)
        self.assertEqual(result["service_sessions"], 2)
        self.assertEqual(result["revision_id"], result["saved_revision"])
        self.assertTrue(result["snapshot_id"])
        self.assertFalse(result["physics_tested"])
        self.assertFalse(result["frame_budget_tested"])

    def test_editor_controls_expression_error_history_and_restart(self):
        """! @brief 실제 속성 폼에서 의존식 편집, 오류 보존과 서버 이력 재시작을 확인한다."""
        with TemporaryDirectory(prefix="rfad GUI 편집 ") as temporary:
            code, result = self.run_gui(Path(temporary), editor=True)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["editor_stage"], 11)
        self.assertEqual(result["service_sessions"], 2)
        self.assertEqual(result["revision_id"], result["saved_revision"])
        self.assertTrue(result["snapshot_id"])
        self.assertEqual(set(result["editor_checks"]), {
            "parameter_created", "expression_bound", "dependency_recalculated",
            "invalid_input_preserved", "undo_recalculated", "redo_recalculated", "restart_preserved",
        })
        self.assertEqual(set(result["ux_checks"]), {
            "saved_state", "loading_and_recovery_separated", "redo_aliases_registered", "blank_parameter_apply_disabled",
            "missing_value_hidden", "expression_fields_visible", "expression_error_localized",
            "unnamed_parameter_apply_disabled", "draft_state_and_apply_enabled",
            "applied_state_and_apply_disabled", "unchanged_input_apply_disabled",
            "unit_change_explained",
            "rejected_draft_stays_editable", "saved_after_apply", "saved_after_restart",
        })
        self.assertEqual(result["editor_ui_state"], "saved")
        self.assertFalse(result["apply_enabled"])
        self.assertFalse(result["physics_tested"])
        self.assertFalse(result["frame_budget_tested"])

    def test_canvas_mouse_line_arc_drag_properties_history_and_restart(self):
        """! @brief 실제 마우스 처리기와 서비스에서 선/원호의 편집 및 복구를 확인한다."""
        with TemporaryDirectory(prefix="rfad GUI 2D ") as temporary:
            code, result = self.run_gui(Path(temporary), canvas=True)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["canvas_stage"], 15)
        self.assertEqual(result["service_sessions"], 2)
        self.assertEqual(result["revision_id"], result["saved_revision"])
        self.assertTrue(result["snapshot_id"])
        self.assertEqual(set(result["canvas_checks"]), {
            "docking_shell", "wide_compact_visibility_separated", "drawing_icons_keep_logical_size_and_mask",
            "escape_cancels_preview", "two_click_line",
            "three_click_arc_and_hit_test", "selection_sync", "drag_one_command",
            "drag_undo_redo", "property_to_canvas", "delete_undo", "save_snapshot_restart",
            "input_check_not_simulation",
            "display_limits_preserve_valid_shapes", "view_controls_do_not_edit",
            "rejected_gesture_restores_selection", "grid_and_endpoint_snap",
            "endpoint_escape_then_one_command", "endpoint_undo_redo", "arc_endpoint_fixed_radius",
            "endpoint_noop_omits_command",
        })
        self.assertFalse(result["physics_tested"])
        self.assertFalse(result["frame_budget_tested"])

    def test_stderr_flood_does_not_displace_protocol(self):
        """! @brief 긴 로그와 로그 폭주 중에도 stdout 응답과 전체 smoke가 처리되는지 확인한다."""
        with TemporaryDirectory(prefix="rfad GUI logs ") as temporary:
            directory = Path(temporary)
            program = "import sys, runpy\n"
            program += "sys.stderr.write('x' * 80000 + '\\n')\n"
            program += "sys.stderr.write('log flood\\n' * 4000)\n"
            program += "sys.stderr.flush()\n"
            program += f"runpy.run_path({str(_SOURCE / 'rfad' / '__main__.py')!r}, run_name='__main__')\n"
            source = self.source_stub(directory, program)
            code, result = self.run_gui(directory, source=source)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["passed"], result)

    def test_oversized_protocol_frame_fails_without_hanging(self):
        """! @brief 1 MiB를 넘는 stdout 프레임을 제한된 오류로 종료한다."""
        with TemporaryDirectory(prefix="rfad GUI frame ") as temporary:
            directory = Path(temporary)
            source = self.source_stub(directory, "import sys, time\nsys.stdout.write('x' * 1048577)\nsys.stdout.flush()\ntime.sleep(120)\n")
            code, result = self.run_gui(directory, source=source)
        self.assertEqual(code, 2, result)
        self.assertFalse(result["passed"])
        self.assertIn("1 MiB", result["error"])
        self.assertLess(result["process_elapsed_seconds"], 10.0, result)

    def test_service_exit_is_reported(self):
        """! @brief 응답 전에 종료한 자식 프로세스를 정상 성공으로 처리하지 않는다."""
        with TemporaryDirectory(prefix="rfad GUI exit ") as temporary:
            directory = Path(temporary)
            source = self.source_stub(directory, "raise SystemExit(7)\n")
            code, result = self.run_gui(directory, source=source)
        self.assertEqual(code, 2, result)
        self.assertFalse(result["passed"])
        self.assertIn("closed", result["error"])

    def test_missing_python_executable_is_reported(self):
        """! @brief 잘못된 실행 경로를 오류 보고서와 실패 종료 코드로 반환한다."""
        with TemporaryDirectory(prefix="rfad GUI missing ") as temporary:
            directory = Path(temporary)
            code, result = self.run_gui(directory, python=directory / "missing python.exe")
        self.assertEqual(code, 2, result)
        self.assertFalse(result["passed"])
        self.assertIn("Cannot start Python", result["error"])


if __name__ == "__main__":
    unittest.main()
