"""! @brief 같은 고정 개정에서 실제 도면, STEP, KiCad와 CAM 출력의 원본을 대조한다."""

from collections import defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from rfad.application.cad_jobs import CadRuntime
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.projects import ProjectService
from test_cad_worker_process import cad_request, status
from test_exchange_service import ExchangeFixture
from test_pcb_exchange_service import prepare, request as pcb_request


CAD_PYTHON = os.environ.get("RFAD_CAD_PYTHON")
EXCHANGE_PYTHON = os.environ.get("RFAD_EXCHANGE_PYTHON")
STEP_RECEIVER = os.environ.get("RFAD_STEP_RECEIVER")
ARTIFACT_DIR = os.environ.get("RFAD_EXCHANGE_REVISION_ARTIFACT_DIR")


def read_independent_step(path):
    """! @brief 제품 OCCT 경로와 분리된 CADability가 받은 닫힌 고체를 이름별로 모은다."""
    completed = subprocess.run(["dotnet", STEP_RECEIVER, str(path)], capture_output=True, check=True, timeout=60)
    report = json.loads(completed.stdout)
    grouped = defaultdict(list)
    for item in report["solids"]:
        grouped[item["name"]].append(item)
    return grouped, report["others"]


def assert_independent_bodies(test, path, bodies):
    """! @brief 출력 순서와 무관하게 각 제품 이름, 고체 수, 전체 외곽과 열린 모서리를 대조한다."""
    grouped, others = read_independent_step(path)
    test.assertFalse(others)
    test.assertEqual(set(grouped), {item["name"] for item in bodies})
    for source in bodies:
        solids = grouped[source["name"]]
        test.assertEqual(len(solids), source["metrics"]["solid_count"], source["name"])
        test.assertTrue(all(not solid["open_edges"] for solid in solids), source["name"])
        bounds = []
        for side, aggregate in (("minimum", min), ("maximum", max)):
            bounds.extend(aggregate(solid["extent"][side][axis] for solid in solids) for axis in range(3))
        for value, expected in zip(bounds, source["metrics"]["bbox_mm"], strict=True):
            test.assertAlmostEqual(value, expected, delta=1e-5, msg=source["name"])
    return grouped


@unittest.skipUnless(sys.platform == "win32" and CAD_PYTHON and EXCHANGE_PYTHON and STEP_RECEIVER,
                     "Windows CAD, 출력 Python 및 독립 STEP 수신기를 지정합니다.")
class WindowsExchangeRevisionTests(unittest.TestCase):
    """! @brief 여섯 출력의 동일 개정, STEP 간극과 재열기 결과를 비교한다."""

    def test_six_outputs_keep_one_revision_and_exact_step_gap(self):
        """! @brief 제작/물성/공구의 미정을 유지하며 1.5 mm 간극을 독립 CAD로 측정한다."""
        runtime = ExchangeRuntime(Path(EXCHANGE_PYTHON))
        f = ExchangeFixture(runtime)
        try:
            prepare(f)
            f.complete("project.save", {"expected_revision": f.revision})
            f.service.close()
            f.service = ProjectService(f.workspace, cad_runtime=CadRuntime(Path(CAD_PYTHON)),
                                       exchange_runtime=runtime, auto_run=False)
            snapshot = f.snapshot
            emitted = {}
            for format_name in ("pdf", "svg", "dxf", "kicad_pcb", "gerber_job"):
                data = f.data(format_name) if format_name in {"pdf", "svg", "dxf"} else pcb_request(f, format_name)
                preview = f.complete("export.preview", data)
                self.assertTrue(preview["can_build"], preview.get("issues"))
                task = f.service.mutate("export.build", f.request({**data, "review_hash": preview["review_hash"]}))
                self.assertTrue(f.service.exchange.run_next())
                record = f.read("export.get", {"job_id": task["job_id"]})
                self.assertEqual(record["state"], "completed", record)
                self.assertEqual(record["result"]["snapshot"], snapshot)
                source = next(artifact for artifact in record["result"]["artifacts"] if artifact["role"] == "source")
                self.assertEqual(json.loads(f.service.journal.read_artifact(source))["source_semantics"], f.document)
                self.assertFalse(record["report"]["manufacturing_verified"])
                emitted[task["job_id"]] = (format_name, record)

            task = f.service.mutate("export.build", cad_request(f.service, f.document, snapshot))
            self.assertTrue(f.service.cad.run_next())
            step = status(f.service, task["job_id"])
            self.assertEqual(step["state"], "completed", step)
            self.assertEqual(step["events"][-1]["operation_result"]["snapshot"], snapshot)
            artifacts = {item["role"]: item for item in step["artifacts"]}
            sidecar = json.loads(f.service.journal.read_artifact(artifacts["sidecar"]))
            self.assertEqual(sidecar["source_semantics"], f.document)
            step_path = f.workspace / artifacts["step"]["uri"]
            self.assertEqual(sha256(step_path.read_bytes()).hexdigest(), artifacts["step"]["sha256"])
            solids = assert_independent_bodies(self, step_path, sidecar["body_map"])

            positive_id = f.document["ports"][0]["positive_geometry_id"]
            reference_id = f.document["ports"][0]["reference_geometry_id"]
            signal, ground = (solids["conductor_" + entity][0]["extent"] for entity in (positive_id, reference_id))
            self.assertAlmostEqual(ground["minimum"][1] - signal["maximum"][1], 1.5, delta=1e-5)
            self.assertEqual(sha256(step_path.read_bytes()).hexdigest(), artifacts["step"]["sha256"])

            f.service.close()
            f.service = ProjectService(f.workspace, auto_run=False)
            self.assertEqual(f.service._load(f.service.journal.read()["projects"][f.project]), f.document)
            self.assertEqual(status(f.service, task["job_id"]), step)
            for job_id, (_, record) in emitted.items():
                self.assertEqual(f.read("export.get", {"job_id": job_id}), record)

            if ARTIFACT_DIR:
                destination = Path(ARTIFACT_DIR)
                destination.mkdir(parents=True)
                for format_name, record in emitted.values():
                    self.write_artifacts(f, destination / format_name, record["result"]["artifacts"])
                self.write_artifacts(f, destination / "step", step["artifacts"])
        finally:
            f.close()

    def write_artifacts(self, fixture, folder, references):
        """! @brief 명시 수신 경로에 봉인된 원래 파일의 같은 바이트를 복사한다."""
        folder.mkdir()
        for item in references:
            target = folder / Path(item["uri"]).name
            with target.open("xb") as output:
                output.write(fixture.service.journal.read_artifact(item))
