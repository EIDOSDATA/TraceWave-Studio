"""! @brief Windows wxWidgets/OCCT의 물리 설정과 실제 파일 왕복을 검증한다."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
import unittest

from rfad.application.projects import ProjectService
from rfad.domain.physical_setup import setup, step_bytes
from test_cad_worker_process import register_fixture
from test_physical_setup import fixture, load


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")
CAD = os.environ.get("RFAD_CAD_PYTHON", "")


def write_step_fixture(path):
    """! @brief 외부 CAD에서 제공된 독립 기계 형상을 시험 데이터로 만든다."""
    subprocess.run([CAD, "-I", "-c", "import cadquery as cq, sys; "
                    "cq.exporters.export(cq.Workplane().box(2,3,4, centered=(False,False,False)), sys.argv[1])", str(path)],
                   capture_output=True, check=True, timeout=45)


@unittest.skipUnless(sys.platform == "win32" and GUI and CAD, "RFAD_GUI_EXE와 RFAD_CAD_PYTHON으로 Windows wxWidgets/OCCT를 지정합니다.")
class GuiPhysicalSetupTests(unittest.TestCase):
    def test_surface_and_external_step_native_reopen(self):
        """! @brief Windows 폼에서 실제 저장한 결과와 과거 스냅샷을 서비스 재시작 뒤 검사한다."""
        with TemporaryDirectory(prefix="TraceWave 물리 설정 ") as temporary:
            root = Path(temporary)
            workspace, step = root / "작업 영역", root / "fixture.step"
            write_step_fixture(step)
            raw = step.read_bytes()
            with ProjectService(workspace, auto_run=False) as service:
                original, snapshot = register_fixture(service, fixture())
            report_path = root / "검증.json"
            saved_signal = report_path.with_suffix(".json.saved")
            command = [GUI, "--python", sys.executable, "--source", str(ROOT / "src"), "--workspace", str(workspace),
                "--cad-python", str(Path(CAD).resolve()), "--open-project", "projects/CAD 한글 교환 검증", "--physical-setup-smoke-test",
                "--smoke-report", str(report_path)]
            with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                finish = time.monotonic() + 210
                try:
                    while process.poll() is None and time.monotonic() < finish:
                        if saved_signal.is_file():
                            step.rename(root / "moved-original.step")
                            break
                        time.sleep(0.25)
                    _, error = process.communicate(timeout=max(1, finish - time.monotonic()))
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=10)
            self.assertTrue(report_path.is_file(), (process.returncode, error))
            report = json.loads(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertIn("physical_setup_surface_and_step_applied", report["setup_checks"])
            self.assertIn("physical_setup_native_opengl_clearance", report["setup_checks"])
            self.assertIn("physical_setup_step_visibility_independent", report["setup_checks"])
            self.assertIn("physical_setup_saved_reopen_sources_and_missing", report["setup_checks"])
            self.assertIn("physical_setup_rebuild_from_embedded_step", report["setup_checks"])
            self.assertFalse(step.exists())
            with ProjectService(workspace, auto_run=False) as service:
                stored = load(service, original)
                self.assertEqual(stored["revision_id"], report["saved_revision"])
                for key in ("board", "materials", "stackup", "geometry", "ports", "targets", "source_references",
                            "assumptions", "measurement_sets"):
                    self.assertEqual(stored[key], original[key], key)
                model = setup(stored)
                self.assertEqual(model["scenarios"], setup(original)["scenarios"])
                self.assertIn(setup(original)["parts"][0], model["parts"])
                part = next(item for item in model["parts"] if item["kind"] == "step")
                self.assertEqual(step_bytes(part["step"]), raw)
                self.assertIsNone(part["material_id"])
                self.assertIsNone(part["depth"]["value_si"])
                self.assertEqual(len(model["surfaces"][0]["openings"]), 1)
                self.assertIsNone(model["surfaces"][0]["material_id"])
                self.assertEqual(hashlib.sha256(service.journal.read_artifact(snapshot["artifact"])).hexdigest(), snapshot["artifact"]["sha256"])
                jobs = service.journal.read()["jobs"].values()
                views = {job["operation_method"]: job for job in jobs if "cad" in job}
                for method, purpose in (("geometry.build", "geometry"), ("export.build", "step")):
                    job = views[method]
                    self.assertEqual(job["state"], "completed")
                    side = next(item for item in job["artifacts"] if item["role"] == "sidecar")
                    payload = json.loads(service.journal.read_artifact(side))
                    self.assertEqual(payload["projection_purpose"], purpose)
                    external = [body for body in payload["body_map"] if body["role"] == "environment"]
                    self.assertEqual(len(external), int(purpose == "geometry"))
                    mask = next(body for body in payload["body_map"] if body["role"] == "surface")
                    self.assertAlmostEqual(mask["metrics"]["volume_mm3"], (60.0 * 40.0 - 4.0 * 5.0) * 0.02)
                    if external:
                        box = external[0]["metrics"]["bbox_mm"]
                        for actual, expected in zip(box, [5, 4, 5, 8, 6, 9]):
                            self.assertAlmostEqual(actual, expected, places=6)
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                path = Path(output) / "physical-setup.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(report_path.read_bytes())
