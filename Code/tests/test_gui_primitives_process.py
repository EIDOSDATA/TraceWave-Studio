"""! @brief 실제 Windows GUI에서 면/패드/비아의 좌표와 미정 입력을 검증한다."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


@unittest.skipUnless(sys.platform == "win32" and GUI, "Windows GUI 실행 파일을 RFAD_GUI_EXE로 지정합니다.")
class GuiPrimitivesTests(unittest.TestCase):
    """! @brief 실제 이벤트와 서비스 명령을 사용하고 물리 정확도를 대신 판정하지 않는다."""

    def run_gui(self, flag):
        """! @brief 실제 GUI 실행을 통해 생성부터 재열기까지 완료한 보고서를 읽는다."""
        with TemporaryDirectory(prefix="TraceWave GUI 면 패드 비아 ") as temporary:
            directory = Path(temporary)
            report = directory / "실제 GUI 결과.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 1
            process = subprocess.run([str(Path(GUI).resolve()), "--python", sys.executable,
                "--source", str(ROOT / "src"), "--workspace", str(directory / "한글 작업 영역"),
                flag, "--smoke-report", str(report)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=90, startupinfo=startup, check=False)
            self.assertTrue(report.is_file(), (process.returncode, process.stderr))
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(process.returncode, 0, result)
            self.assertTrue(result["passed"], result)
            self.assertEqual(result["primitives_stage"], 22)
            self.assertEqual(result["service_sessions"], 2)
            self.assertEqual(result["saved_revision"], result["revision_id"])
            self.assertTrue(result["snapshot_id"])
            self.assertFalse(result["physics_tested"])
            return result

    def test_polygon_holes_pads_via_properties_and_history(self):
        """! @brief 수치/마우스 편집, 구멍 선택 제외, 층 가시성 및 재열기를 함께 확인한다."""
        result = self.run_gui("--primitives-smoke-test")
        self.assertEqual(result["primitives_checks"], ["polygon_holes_and_pad_via_display",
            "via_pad_multichoice_and_undo", "rotated_pad_selection_and_properties",
            "polygon_drag_single_command_and_history", "via_visibility_uses_full_layer_span",
            "via_missing_inputs_edit_and_undo", "save_snapshot_restart_preserves_primitives"])

    def test_64_point_coordinate_table_with_history_and_restart(self):
        """! @brief 최대 꼭짓점의 속성 조회와 좌표 변경이 제한된 GUI 프레임 안에서 동작한다."""
        result = self.run_gui("--coordinate-table-smoke-test")
        self.assertEqual(result["primitives_checks"], ["64_point_coordinate_table_edit", "coordinate_table_undo",
            "save_snapshot_restart_preserves_primitives"])


if __name__ == "__main__":
    unittest.main()
