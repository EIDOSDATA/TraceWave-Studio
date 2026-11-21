"""! @brief Windows wxWidgets에서 실제 규칙 편집/검사와 저장 재열기를 검증한다."""

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application.projects import ProjectService
from rfad.domain.units import Quantity
from rfad.domain.pcb_features import empty_pcb
from test_cad_worker_process import register_fixture
from test_design_rules import scenario
from test_pcb_features import hole_record


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


@unittest.skipUnless(sys.platform == "win32" and GUI, "RFAD_GUI_EXE로 Windows GUI를 지정합니다.")
class GuiDesignRulesTests(unittest.TestCase):
    def test_constraints_connectivity_drc_sources_after_reopen(self):
        """! @brief UI 변경을 실행하고 재시작한 서비스에서 원래 출처와 미정 수량을 비교한다."""
        with TemporaryDirectory(prefix="TraceWave 설계 규칙 ") as temporary:
            workspace = Path(temporary) / "작업 영역"
            original = scenario()
            original["pcb"] = {**empty_pcb(), "holes": [hole_record(original, x=3, y=2)]}
            substrate = next(row for row in original["materials"] if row["name"] == "Explicit test substrate")
            substrate["tan_delta"] = Quantity(None, "dimensionless", "1", "missing", ["자료상 사용 대역 Df 미정"]).to_dict()
            with ProjectService(workspace, auto_run=False) as service:
                _, snapshot = register_fixture(service, original)
            report_path = Path(temporary) / "검사 기록.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([
                str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                "--design-rules-smoke-test", "--smoke-report", str(report_path)],
                stdin=subprocess.DEVNULL, capture_output=True, startupinfo=startup, timeout=210, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            output = os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR")
            if output:
                path = Path(output) / "design-rules.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertIn("design_rules_apply_and_overlay", report["setup_checks"])
            self.assertIn("design_rules_saved_reopen_and_recheck", report["setup_checks"])
            self.assertIn("mechanical_clearance_preserves_unaffected_trace_width", report["setup_checks"])
            with ProjectService(workspace, auto_run=False) as service:
                journal = service.journal.read()
                stored = service._load(journal["projects"][original["project_id"]])
                self.assertEqual(stored["revision_id"], report["saved_revision"])
                for key in ("board", "materials", "stackup", "geometry", "ports", "manufacturing_profiles", "extensions", "pcb"):
                    self.assertEqual(stored[key], original[key], key)
                before, after = original["targets"][0], stored["targets"][0]
                for key in ("band", "criteria", "port_id", "reference_impedance", "source_refs"):
                    self.assertEqual(after[key], before[key], key)
                for key in ("board_width_max", "board_thickness_max"):
                    expected = before["constraints"][key]
                    if key == "board_width_max":
                        expected = {**expected, "display_unit":"um"}
                    self.assertEqual(after["constraints"][key], expected)
                self.assertEqual(stored["connections"][0]["kind"], "connected")
                self.assertEqual(stored["connections"][0]["source_refs"][0], original["connections"][0]["source_refs"][0])
                sealed = workspace / snapshot["artifact"]["uri"]
                self.assertEqual(hashlib.sha256(sealed.read_bytes()).hexdigest(), snapshot["artifact"]["sha256"])
                self.assertTrue(all("solver" not in job for job in journal["jobs"].values()))
