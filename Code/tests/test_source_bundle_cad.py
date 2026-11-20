"""! @brief 봉인된 전이 소스만 실행하는 실제 CAD에서 구멍/비아/외부 STEP을 검증한다."""

import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application.cad_jobs import CadRuntime
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.application.source_bundle import CAD, verify_stage
from rfad.domain.physical_setup import setup
from rfad.domain.project import validate_project
from test_cad_copper_features import copper_document
from test_cad_native import identity
from test_cad_worker_process import cad_request, register_fixture, request, status
from test_design import quantity, unknown
from test_physical_setup import fixture, load, parameters


CAD_PYTHON = os.environ.get("RFAD_CAD_PYTHON", "")
CODE_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "win32" and CAD_PYTHON, "RFAD_CAD_PYTHON으로 실제 Windows CAD 환경을 지정해야 합니다.")
class SourceBundleCadTests(unittest.TestCase):
    """! @brief 단순 native import가 아닌 공개 작업/staging/worker/봉인/재열기를 통과시킨다."""

    def complete(self, service, method, document, data):
        """! @brief 저장과 snapshot 작업의 최종 권위 결과를 읽는다."""
        task = service.mutate(method, request(service, document["project_id"], data))
        self.assertTrue(service.run_next())
        done = status(service, task["job_id"])
        self.assertEqual(done["state"], "completed", done)
        return done["events"][-1]["operation_result"]

    def export(self, service, document, snapshot):
        """! @brief 실제 격리 자식의 전체 source closure와 출력 원본을 함께 확인한다."""
        task = service.mutate("export.build", cad_request(service, document, snapshot))
        self.assertTrue(service.cad.run_next())
        done = status(service, task["job_id"])
        self.assertEqual(done["state"], "completed", done)
        job = service.journal.read()["jobs"][task["job_id"]]
        runtime = job["cad"]["runtime"]
        self.assertEqual(runtime["source_bundle"]["profile"], CAD)
        self.assertLessEqual(len(runtime["code_files"]), 192)
        self.assertLess(len(runtime["code_files"]), len(list((CODE_ROOT / "src/rfad").rglob("*.py"))))
        stage = service.journal._safe_path("cad-staging/" + job["run_id"])
        verified = verify_stage(stage, runtime["source_bundle"], runtime["code_files"])
        self.assertEqual(verified["code_files"], runtime["code_files"])
        self.assertFalse(list(stage.rglob("*.pyc")))
        result = done["events"][-1]["operation_result"]
        self.assertEqual(result["status"], "generated_unverified")
        self.assertFalse(result["physics_verified"])
        self.assertFalse(result["manufacturing_verified"])
        artifacts = {entry["role"]: entry for entry in done["artifacts"]}
        sidecar = json.loads(service.journal.read_artifact(artifacts["sidecar"]))
        self.assertEqual(sidecar["source_semantics"], document)
        self.assertEqual(sidecar["snapshot"], snapshot)
        self.assertGreater(artifacts["step"]["bytes"], 0)
        self.assertGreater(result["solid_count"], 0)
        self.assertEqual(service.journal.read_artifact(snapshot["artifact"]), canonical_bytes(document))
        return {"job_id": task["job_id"], "result": result, "artifacts": done["artifacts"],
                "source_bundle": runtime["source_bundle"], "code_files": runtime["code_files"]}

    def reopen(self, workspace, document, original_snapshot, original, evidence):
        """! @brief CAD runtime 없는 새 서비스에서 원본/미정/과거출력의 바이트를 대조한다."""
        with ProjectService(workspace, auto_run=False) as reopened:
            self.assertIsNone(reopened.cad.runtime)
            self.assertEqual(load(reopened, document), document)
            self.assertEqual(reopened.journal.read_artifact(original_snapshot["artifact"]), canonical_bytes(original))
            reply = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": 1, "method": "cad.latest", "params": {
                "contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]}, "input": {}}}), reopened)
            self.assertNotIn("error", reply, reply)
            latest = reply["result"]
            self.assertEqual(latest["result"], evidence["result"])
            self.assertFalse(reopened.cad.run_next())
            for reference in evidence["artifacts"]:
                path = reopened.journal._safe_path(reference["uri"])
                self.assertEqual(path.stat().st_size, reference["bytes"])
                with path.open("rb") as stream:
                    self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), reference["sha256"])
        report = os.environ.get("RFAD_SOURCE_BUNDLE_CAD_REPORT")
        if report:
            path = Path(report)
            records = json.loads(path.read_bytes()) if path.exists() else {"cases": []}
            records["cases"].append({"test": self._testMethodName, **evidence,
                "source_and_missing_preserved": True, "runtime_free_reopen": True,
                "artifacts_retained_after_test": False})
            path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_real_staged_region_hole_pads_and_pth_preserve_source(self):
        """! @brief region 구멍과 중공 PTH를 실제 STEP으로 내보내도 미정 tool 치수는 채우지 않는다."""
        document = copper_document()
        via = next(item for item in document["geometry"] if item["kind"] == "via")
        via["tool_hole_diameter"] = unknown("length", "mm")
        via["tool_hole_diameter"]["source_refs"] = ["공구 직경 자료 미확보; 기하 검수 전용"]
        pad = next(item for item in document["geometry"] if item["kind"] == "pad")
        region = {key: deepcopy(value) for key, value in pad.items()
                  if key not in {"pad_shape", "center", "size", "rotation"}}
        region.update(id=identity("bundle-region"), kind="planar_region", source_ref="explicit-bundle-region-hole",
            outer=[[quantity(v, "mm") for v in point] for point in ((1, 1), (1, 10), (10, 10), (10, 1))],
            holes=[[[quantity(v, "mm") for v in point] for point in ((3, 3), (4, 3), (4, 4), (3, 4))]])
        document["geometry"].append(region)
        document["geometry"].sort(key=lambda item: item["id"])
        validate_project(document)
        with TemporaryDirectory(prefix="봉인 CAD 비아 구멍 ") as workspace:
            with ProjectService(workspace, auto_run=False, cad_runtime=CadRuntime(Path(CAD_PYTHON))) as service:
                original, snapshot = register_fixture(service, document)
                evidence = self.export(service, original, snapshot)
                self.complete(service, "project.save", original, {"expected_revision": original["revision_id"]})
                self.assertEqual(load(service, original), original)
            self.reopen(workspace, original, snapshot, original, evidence)

    def test_real_staged_surface_and_embedded_step_inspection(self):
        """! @brief 표면 개구와 실제 읽은 외부 STEP만 채택하며 별도 미정 참고 물체를 유지한다."""
        with TemporaryDirectory(prefix="봉인 CAD 표면 외부 ") as directory:
            root = Path(directory)
            source_path = root / "기하 시험 상자.step"
            program = "import cadquery as cq,sys; cq.exporters.export(cq.Workplane('XY').box(2,3,4),sys.argv[1])"
            generated = subprocess.run([CAD_PYTHON, "-I", "-B", "-X", "utf8", "-c", program, str(source_path)],
                capture_output=True, timeout=60, check=False)
            self.assertEqual(generated.returncode, 0, generated.stderr.decode("utf-8", errors="replace"))
            raw = source_path.read_bytes()
            encoded = base64.b64encode(raw).decode("ascii")
            self.assertLessEqual(len(raw), 48 * 1024)
            workspace = root / "저장소"
            with ProjectService(workspace, auto_run=False, cad_runtime=CadRuntime(Path(CAD_PYTHON))) as service:
                original, original_snapshot = register_fixture(service, fixture())
                service.mutate("physical.setup.apply", parameters(service, original, "surface", {
                    "name": "기하 시험 피복; RF 물성 미정", "offset": "0", "thickness": ".02",
                    "openings": "2 3 4 5", "include_in_export": True}))
                current = load(service, original)
                preview = service.physical_setup.read("physical.step.preview", {
                    "contract_version": "rfad.api/2.0", "context": {"project_id": current["project_id"]},
                    "input": {"expected_revision": current["revision_id"], "name": source_path.name,
                              "chunks": [encoded[i:i + 4096] for i in range(0, len(encoded), 4096)]}})
                self.assertEqual(preview["sha256"], hashlib.sha256(raw).hexdigest())
                service.mutate("physical.setup.apply", parameters(service, current, "part", {
                    "name": "명시 기하 상자; 제작 실물 아님", "kind": "step", "x": "45", "y": "5", "z": "10", "yaw": "15",
                    "scenario_id": setup(current)["active_scenario_id"], "include_in_export": True},
                    step_token=preview["preview_token"]))
                saved = load(service, original)
                self.assertEqual(saved["materials"], original["materials"])
                self.assertEqual(saved["stackup"], original["stackup"])
                self.assertEqual(saved["measurement_sets"], original["measurement_sets"])
                self.assertIn(setup(original)["parts"][0], setup(saved)["parts"])
                embedded = next(item for item in setup(saved)["parts"] if item["kind"] == "step")
                self.assertEqual(base64.b64decode("".join(embedded["step"]["chunks"])), raw)
                self.assertIsNone(embedded["material_id"])
                self.assertFalse(embedded["include_in_em"])
                snapshot = self.complete(service, "snapshot.create", saved, {"expected_revision": saved["revision_id"]})
                evidence = self.export(service, saved, snapshot)
                evidence["external_step_inspection"] = preview
                self.complete(service, "project.save", saved, {"expected_revision": saved["revision_id"]})
            self.reopen(workspace, saved, original_snapshot, original, evidence)

    def test_real_large_step_publishes_large_display_profile(self):
        """! @brief 큰 표시 자료는 원본 STEP과 미정값을 유지하며 별도 profile로 봉인한다."""
        with TemporaryDirectory(prefix="rfad 실제 대형 표시 ") as temporary:
            root = Path(temporary)
            source = root / "토러스 시험 기하.step"
            program = ("import sys, cadquery as cq; "
                       "cq.exporters.export(cq.Solid.makeTorus(700, 150), sys.argv[1])")
            generated = subprocess.run([CAD_PYTHON, "-I", "-X", "utf8", "-c", program, str(source)],
                                       capture_output=True, timeout=60, check=False)
            self.assertEqual(generated.returncode, 0, generated.stderr.decode("utf-8", errors="replace"))
            raw = source.read_bytes()
            self.assertLessEqual(len(raw), 48 * 1024)
            encoded = base64.b64encode(raw).decode("ascii")
            workspace = root / "저장소"
            with ProjectService(workspace, auto_run=False, cad_runtime=CadRuntime(Path(CAD_PYTHON))) as service:
                original, original_snapshot = register_fixture(service, fixture())
                preview = service.physical_setup.read("physical.step.preview", {
                    "contract_version": "rfad.api/2.0", "context": {"project_id": original["project_id"]},
                    "input": {"expected_revision": original["revision_id"], "name": source.name,
                              "chunks": [encoded[i:i + 4096] for i in range(0, len(encoded), 4096)]}})
                service.mutate("physical.setup.apply", parameters(service, original, "part", {
                    "name": "대형 표시 시험 기하", "kind": "step", "x": "1500", "y": "5", "z": "530", "yaw": "0",
                    "scenario_id": setup(original)["active_scenario_id"], "include_in_export": True},
                    step_token=preview["preview_token"]))
                saved = load(service, original)
                part = next(item for item in setup(saved)["parts"] if item["kind"] == "step")
                self.assertEqual(base64.b64decode("".join(part["step"]["chunks"])), raw)
                self.assertIsNone(part["material_id"])
                self.assertFalse(part["include_in_em"])
                snapshot = self.complete(service, "snapshot.create", saved, {"expected_revision": saved["revision_id"]})
                evidence = self.export(service, saved, snapshot)
                artifact = next(item for item in evidence["artifacts"] if item["role"] == "display_mesh")
                mesh = json.loads(service.journal._safe_path(artifact["uri"]).read_bytes())
                self.assertEqual(mesh["schema"], "rfad.display-mesh/0.2")
                self.assertEqual(mesh["snapshot"], snapshot)
                triangles = sum(len(body["triangles"]) for body in mesh["bodies"])
                self.assertTrue(100000 < triangles <= 1000000)
                evidence["display_profile"] = {"schema": mesh["schema"], "triangles": triangles,
                                               "bytes": artifact["bytes"], "sha256": artifact["sha256"]}
                self.complete(service, "project.save", saved, {"expected_revision": saved["revision_id"]})
            self.reopen(workspace, saved, original_snapshot, original, evidence)


if __name__ == "__main__":
    unittest.main()
