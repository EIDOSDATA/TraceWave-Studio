"""! @brief 실제 wxWidgets 대화 상자의 PCB 검색, 입력, 적용과 지연 응답을 검증한다."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.catalog.build import build_catalog
from test_catalog_build import make_package


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


@unittest.skipUnless(sys.platform == "win32" and GUI, "Windows GUI 실행 파일을 RFAD_GUI_EXE로 지정합니다.")
class GuiPcbSelectionTests(unittest.TestCase):
    """! @brief 작은 실제 DB와 공개 서비스로 화면을 구동하며 물리 정확도를 승인하지 않는다."""

    def catalog_fixture(self, directory: Path) -> Path:
        """! @brief 명시적인 2층 관측을 가진 독립 시험용 카탈로그를 만든다."""
        package = directory / "시험 원문"
        make_package(package, [{
            "record_id": "PCB056952", "source_id": "S1", "manufacturer": "OSH Park",
            "product": "2 layer 1.6 mm / GUI fixture", "dataset_role": "fabricator_published_parameter",
            "record_kind": "published_stackup_layer", "material_form": "core", "layer": "L1-L2",
            "stackup_id": "OSH_2L_1.6", "copper_layer_count": 2, "nominal_board_thickness_mm": 1.6,
            "thickness_mm": 1.524, "dk": 4.5, "df": None, "frequency_ghz": 0.01,
            "value_type": "fabricator_stackup", "source_file": "originals/source.txt",
            "notes": "GUI 동작 검증 전용 fixture이며 실제 제작 조건이나 물성의 근거가 아니다.",
        }])
        database = directory / "시험 카탈로그.sqlite"
        build_catalog(package, database)
        return database

    def delayed_source(self, directory: Path) -> Path:
        """! @brief 실제 서비스 처리는 유지하고 조회 응답만 늦춰 화면 이벤트 진행을 확인한다."""
        source = directory / "지연 응답 source"
        package = source / "rfad"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            f"__path__.append({str(ROOT / 'src' / 'rfad')!r})\n__version__ = '0.1.0.dev0'\n", encoding="utf-8")
        program = "import json, runpy, time\nfrom rfad.application import rpc\n_original = rpc.handle_frame\n"
        program += "def delayed(frame, service=None, catalog=None):\n"
        program += "    request = json.loads(frame)\n"
        program += "    if isinstance(request, dict) and request.get('method') in ('catalog.search', 'catalog.stackup_draft', 'catalog.stackup_suggestions', 'pcb.selection.preview'):\n"
        program += "        time.sleep(0.4)\n"
        program += "    return _original(frame, service, catalog)\n"
        program += "rpc.handle_frame = delayed\n"
        program += f"runpy.run_path({str(ROOT / 'src' / 'rfad' / '__main__.py')!r}, run_name='__main__')\n"
        (package / "__main__.py").write_text(program, encoding="utf-8")
        return source

    def run_gui(self, *, catalog: bool, delayed: bool = False) -> dict:
        """! @brief 자식 프로세스를 제한 시간 안에 회수하고 실제 GUI 보고서와 DB 불변을 확인한다."""
        with TemporaryDirectory(prefix="TraceWave GUI PCB 한글 ") as temporary:
            directory = Path(temporary)
            report = directory / "PCB 화면 결과.json"
            database = self.catalog_fixture(directory) if catalog else None
            before = hashlib.sha256(database.read_bytes()).hexdigest() if database is not None else None
            source = self.delayed_source(directory) if delayed else ROOT / "src"
            command = [str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(source),
                       "--workspace", str(directory / "한글 작업 영역"), "--pcb-selection-smoke-test",
                       "--smoke-report", str(report)]
            if database is not None:
                command.extend(("--catalog", str(database)))
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, timeout=90, startupinfo=startup, check=False)
            artifact_root = os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR", "")
            if artifact_root:
                artifacts = Path(artifact_root)
                artifacts.mkdir(parents=True, exist_ok=True)
                label = ("delayed" if delayed else ("catalog" if catalog else "manual")) + "-" + uuid4().hex[:8]
                if report.is_file():
                    (artifacts / (label + ".json")).write_bytes(report.read_bytes())
                (artifacts / (label + ".stdout.log")).write_bytes(process.stdout)
                (artifacts / (label + ".stderr.log")).write_bytes(process.stderr)
            self.assertTrue(report.is_file(), (process.returncode, process.stderr))
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(process.returncode, 0, result)
            self.assertTrue(result["passed"], result)
            self.assertFalse(result["physics_tested"])
            self.assertFalse(result["frame_budget_tested"])
            self.assertEqual(result["pcb_stage"], 35, result)
            self.assertEqual(result["saved_revision"], result["revision_id"])
            if database is not None:
                self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
            return result

    def assert_common_checks(self, result: dict) -> None:
        """! @brief 조회/변경 분리, 기존 설계 보존과 원자 이력을 공통으로 요구한다."""
        self.assertTrue({"circular_outline_and_pattern_fixture", "layer_grid_input_and_explicit_mapping",
                         "preview_is_read_only", "preview_invalidated_on_input_change",
                         "single_apply_preserves_outline_and_pattern", "single_step_undo_redo",
                         "saved_selection_dialog_reopened", "material_layer_assignment_preview",
                         "saved_material_values_and_provenance", "parent_close_veto_during_apply",
                         "parent_close_during_lookup_safe_shutdown"} <= set(result["pcb_checks"]), result)

    def test_catalog_controls_preview_apply_and_history(self):
        """! @brief 실제 검색/선택/격자 입력으로 원형 기판과 패턴 참조를 유지한다."""
        result = self.run_gui(catalog=True)
        self.assert_common_checks(result)
        self.assertTrue({"search_controls_and_source_selection", "late_search_response_ignored",
                         "close_during_request_and_reopen", "material_form_catalog_dk_user_df_conductivity",
                         "stackup_suggestions_published_and_missing", "explicit_suggestion_use_preserves_missing_and_model",
                         "suggestion_duplicate_does_not_overwrite", "suggestion_model_preserved_after_manual_edit",
                         "suggestion_page_preserves_dirty_input_and_layers",
                         "suggestion_previous_page_preserves_material_assignment",
                         "accepted_suggestion_display_survives_page_change"}
                        <= set(result["pcb_checks"]), result)

    def test_direct_input_without_catalog(self):
        """! @brief 카탈로그 미설정에서도 수동 두께 입력과 검토/적용을 완료한다."""
        result = self.run_gui(catalog=False)
        self.assert_common_checks(result)
        self.assertIn("manual_input_without_catalog", result["pcb_checks"])
        self.assertIn("material_form_direct_values", result["pcb_checks"])

    def test_delayed_queries_keep_gui_events_and_discard_stale_responses(self):
        """! @brief 서비스 지연 중에도 UI timer가 진행되고 폐기한 검색 응답을 적용하지 않는다."""
        result = self.run_gui(catalog=True, delayed=True)
        self.assert_common_checks(result)
        self.assertGreaterEqual(result["pcb_request_ticks"], 5, result)
        self.assertIn("late_search_response_ignored", result["pcb_checks"])
        self.assertIn("close_during_request_and_reopen", result["pcb_checks"])


if __name__ == "__main__":
    unittest.main()
