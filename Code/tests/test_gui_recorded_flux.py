"""! @brief 실제 봉인된 E/H 체적을 Windows 결과 화면에서 열어 방향과 면 경계를 조작한다."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application import result_service
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from test_result_field_flux import BOX, PLANE


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_GUI_EXE") and os.environ.get("RFAD_FLUX_WORKSPACE")
                     and os.environ.get("RFAD_FLUX_ARTIFACT"), "Windows GUI 및 같은 급전의 실제 E/H 체적 작업 공간 필요")
class GuiFluxTests(unittest.TestCase):
    def test_real_rectangle_and_closed_box(self):
        """! @brief 실제 면별 입력 컨트롤로 얻은 합계와 재개방한 원본의 SHA256을 대조한다."""
        with TemporaryDirectory(prefix="TraceWave 면 적분 ") as directory:
            workspace = Path(directory) / "실제 필드"
            shutil.copytree(Path(os.environ["RFAD_FLUX_WORKSPACE"]), workspace)
            source = {"kind": "solver", "artifact_id": os.environ["RFAD_FLUX_ARTIFACT"]}
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                record = state["solver_results"][source["artifact_id"]]
                project = state["projects"][record["project_id"]]
                revision = service._load(project)["revision_id"]
                envelope = {"contract_version": "rfad.api/2.0", "context": {"project_id": record["project_id"]},
                            "input": {"source": source}}
                pin = result_service.read(service, "result.describe", envelope)["pin"]
                items, refs = [], []
                for surface in (PLANE, BOX):
                    request = {**envelope, "input": {"source": source, "pin": pin, "frequency_index": 0, "surface": surface}}
                    result = result_service.read(service, "result.field.flux", request)
                    items.append({"bounds_mm": surface["bounds_mm"], "total": result["total_flux_w_s2"]})
                    refs = [result["electric_ref"], result["magnetic_ref"]]
            (workspace / "results-smoke-fixture.json").write_bytes(canonical_bytes(
                {"field_source": source, "pin": pin, "revision_id": revision, "flux_surfaces": items}))
            report = Path(directory) / "면 적분.json"
            root = Path(__file__).resolve().parents[1]
            proc = subprocess.run([os.environ["RFAD_GUI_EXE"], "--python", sys.executable, "--source", str(root / "src"),
                "--workspace", str(workspace), "--open-project", project["path"], "--results-smoke-test",
                "--smoke-report", str(report)], capture_output=True, stdin=subprocess.DEVNULL, timeout=185, check=False)
            self.assertTrue(report.is_file(), (proc.returncode, proc.stderr))
            evidence = json.loads(report.read_bytes())
            if destination := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                Path(destination).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(report, Path(destination) / "field-flux.json")
            self.assertEqual(proc.returncode, 0, evidence)
            self.assertEqual(evidence["setup_checks"], ["field_flux_rectangle", "field_flux_box_six_faces"])
            for ref in refs:
                self.assertEqual(hashlib.sha256((workspace / ref["uri"]).read_bytes()).hexdigest(), ref["sha256"])
