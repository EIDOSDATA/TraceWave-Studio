"""! @brief 순수 서비스와 별도 CAD Python 프로세스 사이의 실제 STEP 발행을 검증한다."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application.cad import PROFILE
from rfad.application.cad_jobs import CadRuntime
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from test_cad_projection import cad_fixture


CAD_PYTHON = os.environ.get("RFAD_CAD_PYTHON", "")
CODE_ROOT = Path(__file__).resolve().parents[1]


def request(service, project_id, data):
    """! @brief 현재 epoch와 독립 request key로 mutation envelope를 구성한다."""
    return {"contract_version": "rfad.api/2.0", "context": {"project_id": project_id}, "input": data,
            "request_key": str(uuid4()), "request_key_epoch": service.policy()["request_key_epoch"]}


def status(service, job_id):
    """! @brief 일반 작업 조회 계약으로 현재 상태와 artifact를 읽는다."""
    return service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": job_id}})


def register_fixture(service, document=None):
    """! @brief 시험 전용 문서를 journal에 등록하고 제품 API로 스냅샷을 봉인한다."""
    document = deepcopy(cad_fixture() if document is None else document)
    path = "projects/CAD 한글 교환 검증"

    def register(state):
        """! @brief 기존 내용 없는 시험 저장소의 최초 개정을 등록한다."""
        reference = service._store_document(path, document)
        state["projects"][document["project_id"]] = {
            "path": path, "current": reference, "saved": deepcopy(reference),
            "revisions": {document["revision_id"]: reference},
            "history": {"undo": [], "redo": [], "head_revision": document["revision_id"]},
        }
        state["paths"][path] = document["project_id"]

    service.journal.transaction(register)
    task = service.mutate("snapshot.create", request(service, document["project_id"], {
        "expected_revision": document["revision_id"], "description": "기하 교환 fixture, RF 검증 IFA 아님",
    }))
    service.run_next()
    result = status(service, task["job_id"])
    if result["state"] != "completed":
        raise AssertionError(result)
    return document, result["events"][-1]["operation_result"]


def cad_request(service, document, snapshot, method="export.build"):
    """! @brief 직접 경로 대신 등록된 스냅샷 ID/hash로 CAD 출력을 접수한다."""
    data = {"snapshot": {"snapshot_id": snapshot["snapshot_id"], "content_hash": snapshot["content_hash"]}, "profile": PROFILE}
    data["format" if method == "export.build" else "projection_kind"] = "step" if method == "export.build" else "brep"
    return request(service, document["project_id"], data)


@unittest.skipUnless(sys.platform == "win32" and CAD_PYTHON, "RFAD_CAD_PYTHON으로 고정 Windows CAD 환경을 지정해야 합니다.")
class CadWorkerProcessTests(unittest.TestCase):
    """! @brief native worker의 실제 파일 발행과 고정 snapshot 연결을 확인한다."""

    def test_service_to_native_export_snapshot_hashes_reopen_and_restart(self):
        """! @brief 접수 후 편집해도 이전 스냅샷에서 생성하고 재시작 뒤 결과를 유지한다."""
        with TemporaryDirectory(prefix="TraceWave worker 한글 ") as directory:
            workspace = Path(directory)
            runtime = CadRuntime(Path(CAD_PYTHON))
            with ProjectService(workspace, cad_runtime=runtime, auto_run=False) as service:
                document, snapshot = register_fixture(service)
                params = cad_request(service, document, snapshot)
                task = service.mutate("export.build", params)
                self.assertEqual(task, service.mutate("export.build", params))
                self.assertEqual(task["state"], "queued")
                self.assertFalse(service.run_next())
                changed = service.mutate("project.apply_command", request(service, document["project_id"], {
                    "expected_revision": document["revision_id"], "command_id": str(uuid4()),
                    "type": "metadata.set", "payload": {"name": "CAD 접수 후 편집한 프로젝트", "description": "스냅샷은 고정됨"},
                }))
                self.assertTrue(service.cad.run_next())
                completed = status(service, task["job_id"])
                self.assertEqual(completed["state"], "completed", completed)
                self.assertEqual([event["state"] for event in completed["events"]], ["queued", "running", "completed"])
                result = completed["events"][-1]["operation_result"]
                self.assertEqual(result["snapshot"], snapshot)
                self.assertNotEqual(snapshot["revision_id"], changed["new_revision"])
                self.assertEqual(result["status"], "generated_unverified")
                self.assertFalse(result["physics_verified"])
                self.assertFalse(result["manufacturing_verified"])
                self.assertFalse(result["kernel_independent"])
                self.assertEqual(len(completed["artifacts"]), 6)
                artifacts = {item["role"]: item for item in completed["artifacts"]}
                for item in completed["artifacts"]:
                    raw = (workspace / item["uri"]).read_bytes()
                    self.assertEqual(len(raw), item["bytes"])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
                sidecar = json.loads(service.journal.read_artifact(artifacts["sidecar"]))
                manifest = json.loads(service.journal.read_artifact(artifacts["manifest"]))
                self.assertEqual(sidecar["source_semantics"], document)
                self.assertEqual(sidecar["snapshot"], snapshot)
                self.assertEqual(sidecar["projection_sha256"], manifest["input_sha256"])
                self.assertEqual(sidecar["run_id"], manifest["run_id"])
                mesh = json.loads(service.journal.read_artifact(artifacts["display_mesh"]))
                self.assertEqual(mesh["snapshot"], snapshot)
                self.assertEqual(mesh["run_id"], manifest["run_id"])
                self.assertEqual(mesh["purpose"], "display_only")
                self.assertEqual({body["id"] for body in mesh["bodies"]}, {body["id"] for body in sidecar["body_map"]})
                self.assertFalse(service.journal.read()["jobs"][task["job_id"]]["cad"]["resource_reserved"])
                self.assertEqual(service._load(service.journal.read()["projects"][document["project_id"]])["revision_id"], changed["new_revision"])
                self.assertEqual(service.journal.read_artifact(snapshot["artifact"]), canonical_bytes(document))
                self.assertEqual(task, service.mutate("export.build", params))
                self.assertFalse(service.cad.run_next())
                step_path = workspace / artifacts["step"]["uri"]
                brep_path = workspace / artifacts["brep"]["uri"]
                program = (
                    "import json,sys;from pathlib import Path;"
                    "sys.path.insert(0,sys.argv[1]);"
                    "from rfad.adapters.cad.native import read_step;import cadquery as cq;"
                    "shape=cq.Shape.importBrep(sys.argv[3]);"
                    "print(json.dumps({'step':read_step(Path(sys.argv[2])),'brep_valid':shape.isValid(),'brep_solids':len(shape.Solids())}))"
                )
                readback = subprocess.run([CAD_PYTHON, "-I", "-X", "utf8", "-c", program,
                                           str(CODE_ROOT / "src"), str(step_path), str(brep_path)],
                                          capture_output=True, timeout=60, check=False)
                self.assertEqual(readback.returncode, 0, readback.stderr.decode("utf-8", errors="replace"))
                checked = json.loads(readback.stdout)
                self.assertTrue(checked["brep_valid"])
                self.assertEqual(checked["brep_solids"], result["solid_count"])
                self.assertEqual(set(checked["step"]), {body["name"] for body in sidecar["body_map"]})
            with ProjectService(workspace, cad_runtime=CadRuntime(Path(CAD_PYTHON)), auto_run=False) as reopened:
                self.assertEqual(status(reopened, task["job_id"]), completed)
                self.assertFalse(reopened.cad.run_next())
                for item in completed["artifacts"]:
                    self.assertEqual(hashlib.sha256((workspace / item["uri"]).read_bytes()).hexdigest(), item["sha256"])
        if importlib_missing_cad():
            self.assertFalse(any(name == "cadquery" or name.startswith("OCP") for name in sys.modules))

    def test_geometry_build_produces_brep_and_failed_native_does_not_publish(self):
        """! @brief B-rep 접수와 실제 native 중첩 실패의 미게시 경계를 확인한다."""
        for overlapping in (False, True):
            with self.subTest(overlapping=overlapping), TemporaryDirectory(prefix="rfad CAD 결과 ") as directory:
                with ProjectService(Path(directory), cad_runtime=CadRuntime(Path(CAD_PYTHON)), auto_run=False) as service:
                    document = cad_fixture()
                    if overlapping:
                        # @brief 서로 다른 net을 같은 위치에 놓아 native 접촉 검사를 실제 실행한다.
                        document["geometry"][1]["start"] = deepcopy(document["geometry"][0]["start"])
                        document["geometry"][1]["end"] = deepcopy(document["geometry"][0]["end"])
                    document, snapshot = register_fixture(service, document)
                    task = service.mutate("geometry.build", cad_request(service, document, snapshot, "geometry.build"))
                    self.assertTrue(service.cad.run_next())
                    result = status(service, task["job_id"])
                    if overlapping:
                        self.assertEqual(result["state"], "failed", result)
                        self.assertEqual(result["artifacts"], [])
                        self.assertEqual(result["events"][-1]["error"]["code"], "E_CONNECTIVITY")
                    else:
                        self.assertEqual(result["state"], "completed", result)
                        self.assertIn("brep", {item["role"] for item in result["artifacts"]})
                    self.assertFalse(service.journal.read()["jobs"][task["job_id"]]["cad"]["resource_reserved"])


def importlib_missing_cad():
    """! @brief 서비스 가상환경에서만 native import 분리 단언을 적용한다."""
    import importlib.util

    return importlib.util.find_spec("cadquery") is None


if __name__ == "__main__":
    unittest.main()
