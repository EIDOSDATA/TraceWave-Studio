"""! @brief 실제 격리 프로세스로 CAD 접수, 취소, 게시와 복구 경계를 검증한다."""

from copy import deepcopy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.cad import PROFILE
from rfad.application.cad_jobs import CadRuntime
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from test_cad_projection import cad_fixture


_FAKE_WORKER = '''"""! @brief CAD 커널 대신 프로세스/파일 계약만 실행하는 시험 전용 worker다."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

MODE = __MODE__
request = json.loads(sys.stdin.buffer.readline())
projection = json.loads(Path("input.json").read_bytes())
Path("started.json").write_text(json.dumps({"pid": os.getpid(), "snapshot": projection["snapshot"], "run_id": request["run_id"]}), encoding="utf-8")
if MODE == "sleep":
    time.sleep(30)
if MODE == "crash":
    os._exit(7)
if MODE == "flood":
    sys.stderr.buffer.write(b"x" * (2 * 1024 * 1024))
    sys.stderr.buffer.flush()
    time.sleep(30)
if MODE == "missing_result":
    raise SystemExit(0)
output = Path("output")
output.mkdir()
schema = "AUTOMOTIVE_DESIGN" if MODE == "wrong_step_schema" else "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF"
output.joinpath("model.step").write_text("ISO-10303-21;\\nHEADER;FILE_SCHEMA(('" + schema + "'));ENDSEC;\\nSI_UNIT(.MILLI.,.METRE.);\\nEND-ISO-10303-21;\\n", encoding="ascii")
output.joinpath("model.brep").write_bytes(b"fake B-rep: coordinator contract only\\n")
validation = {"status": "passed_same_kernel", "kernel_independent": False, "reader": "fake test reader", "bodies": []}
output.joinpath("validation.json").write_text(json.dumps(validation), encoding="utf-8")
body = {"id": projection["layers"][0]["id"], "layer_id": projection["layers"][0]["id"], "role": "dielectric",
        "source_entity_ids": [projection["board"]["id"], projection["layers"][0]["id"]]}
mesh = {"schema": "rfad.display-mesh/0.1", "snapshot": projection["snapshot"], "run_id": request["run_id"],
        "unit": "mm", "purpose": "display_only", "linear_deflection_mm": 0.05, "angular_deflection_rad": 0.15,
        "bodies": [{**body, "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "triangles": [[0, 1, 2]]}]}
if MODE == "wrong_mesh_snapshot":
    mesh["snapshot"] = {"snapshot_id": "wrong snapshot"}
if MODE == "wrong_mesh_run":
    mesh["run_id"] = "wrong run"
if MODE == "wrong_mesh_mapping":
    mesh["bodies"][0]["source_entity_ids"] = []
if MODE == "wrong_mesh_index":
    mesh["bodies"][0]["triangles"] = [[0, 1, 3]]
output.joinpath("mesh.json").write_text(json.dumps(mesh), encoding="utf-8")

def file_record(name, role, media_type):
    """! @brief 시험 파일의 실제 크기와 SHA256을 기록한다."""
    raw = output.joinpath(name).read_bytes()
    return {"path": name, "role": role, "media_type": media_type, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

files = [file_record("model.step", "step", "model/step"),
         file_record("model.brep", "brep", "application/vnd.opencascade.brep"),
         file_record("mesh.json", "display_mesh", "application/json"),
         file_record("validation.json", "validation", "application/json")]
if MODE == "wrong_mesh_hash":
    files[2]["sha256"] = "0" * 64
if MODE == "bad_hash":
    files[0]["sha256"] = "0" * 64
if MODE == "byte_limit":
    files[0]["bytes"] = 64 * 1024 * 1024 + 1
sidecar = {"schema": "rfad.step-sidecar/0.1", "status": "generated_unverified", "profile": projection["profile"],
           "snapshot": projection["snapshot"], "project_id": projection["project_id"], "revision_id": projection["revision_id"],
           "run_id": request["run_id"], "projection_sha256": request["input_sha256"], "unit": "mm", "step_schema": schema,
           "source_semantics": projection["source_semantics"], "files": list(files), "verification": validation,
           "body_map": [{**body, "name": "fake_test_body"}]}
if MODE == "wrong_sidecar":
    sidecar["projection_sha256"] = "0" * 64
if MODE == "wrong_source_semantics":
    sidecar["source_semantics"]["metadata"]["name"] = "unrelated source"
output.joinpath("sidecar.json").write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")
files.append(file_record("sidecar.json", "sidecar", "application/json"))
package = {"schema": "rfad.cad-package/0.1", "status": "generated_unverified", "profile": projection["profile"],
           "source_snapshot": projection["snapshot"], "step_schema": schema, "body_count": 1, "solid_count": 1, "files": files}
result = {"schema": "rfad.cad-worker-result/0.1", "run_id": request["run_id"], "nonce": request["nonce"],
          "input_sha256": request["input_sha256"], "package": package}
if MODE == "wrong_nonce":
    result["nonce"] = "unrelated nonce"
if MODE == "wrong_input_hash":
    result["input_sha256"] = "0" * 64
if MODE == "wrong_result_schema":
    result["schema"] = "wrong/0.1"
if MODE == "wrong_result_snapshot":
    package["source_snapshot"] = {"snapshot_id": "wrong snapshot"}
if MODE == "wrong_body_count":
    package["body_count"] = 2
if MODE == "missing_file":
    output.joinpath("model.brep").unlink()
if MODE == "unsafe_filename":
    files[0]["path"] = "../model.step"
Path("result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
'''


def _alive(pid: int) -> bool:
    """! @brief 시험이 시작한 PID의 실행 여부만 조회하고 신호를 보내지 않는다."""
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        return text.rsplit(")", 1)[1].split()[0] not in {"Z", "X"}
    except FileNotFoundError:
        return False


class CadJobTests(unittest.TestCase):
    """! @brief 실제 journal/명령과 실제 자식 프로세스의 경계를 함께 시험한다."""

    def setUp(self):
        """! @brief 한글/공백 경로에 public 명령으로 작은 기계 형상을 저장한다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="rfad CAD 작업 ")
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "프로젝트 저장소"
        self.entry = self.root / "fake CAD worker.py"
        self.runners = []
        self.runner_errors = []
        self.runtime = self.runtime_for("success")
        self.service = ProjectService(self.workspace, auto_run=False, cad_runtime=self.runtime)
        task = self.service.mutate("project.open", self.request({"path": "projects/CAD 보드", "open_mode": "create", "name": "CAD 작업 시험"}, {}))
        self.service.run_next()
        created = self.status(task)["events"][-1]["operation_result"]
        self.project = created["project_id"]
        self.revision = created["revision_id"]
        fixture = cad_fixture()
        frame = created["document"]["frames"]["board"]["id"]
        fixture["board"]["frame_id"] = frame
        self.command("board.set", {"board": fixture["board"]})
        for collection, kind in (("materials", "material"), ("stackup", "layer"), ("nets", "net"), ("geometry", "geometry"), ("ports", "port")):
            for entity in fixture[collection]:
                if "frame_id" in entity:
                    entity["frame_id"] = frame
                self.command(kind + ".set", {kind: entity})
        self.snapshot = self.complete("snapshot.create", {"expected_revision": self.revision})

    def tearDown(self):
        """! @brief 시험이 시작한 native 실행을 회수한 뒤 저장소를 닫는다."""
        self.service.cad.cancel.set()
        for runner in self.runners:
            runner.join(timeout=8.0)
        self.service.close()
        self.temporary.cleanup()

    def runtime_for(self, mode: str, timeout: float = 10.0) -> CadRuntime:
        """! @brief 실행 내용이 고정된 시험 전용 진입점과 실제 Python을 결합한다."""
        self.entry.write_text(_FAKE_WORKER.replace("__MODE__", repr(mode)), encoding="utf-8")
        return CadRuntime(Path(sys.executable), entry=self.entry, timeout_seconds=timeout)

    def set_mode(self, mode: str, timeout: float = 10.0) -> None:
        """! @brief 접수 전 호스트 실행 설정만 새로 구성한다."""
        self.runtime = self.runtime_for(mode, timeout)
        self.service.cad.runtime = self.runtime

    def request(self, data: dict, context: dict | None = None) -> dict:
        """! @brief 유효한 영속 epoch와 새 request key로 명령을 작성한다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project} if context is None else context,
                "input": data, "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def status(self, task: dict) -> dict:
        """! @brief 공개 상태 조회에서 artifact 참조와 단조 이벤트를 읽는다."""
        return self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})

    def complete(self, method: str, data: dict) -> dict:
        """! @brief 짧은 자료 처리 작업의 실제 완료 결과를 기다린다."""
        task = self.service.mutate(method, self.request(data))
        self.service.run_next()
        status = self.wait_for(lambda: self.status(task) if self.status(task)["state"] in {"completed", "failed"} else None)
        self.assertEqual(status["state"], "completed", status)
        return status["events"][-1]["operation_result"]

    def command(self, kind: str, payload: dict) -> dict:
        """! @brief GUI와 같은 영속 명령 경계에서 fixture/후속 편집을 적용한다."""
        result = self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": kind, "payload": payload}))
        self.revision = result["new_revision"]
        return result

    def build_input(self, method: str = "export.build") -> dict:
        """! @brief 현재 revision 대신 봉인된 스냅샷 ID/hash를 지정한다."""
        return {"snapshot": {key: self.snapshot[key] for key in ("snapshot_id", "content_hash")}, "profile": PROFILE,
                "projection_kind" if method == "geometry.build" else "format": "brep" if method == "geometry.build" else "step"}

    def admit(self, method: str = "export.build") -> dict:
        """! @brief 실제 CAD 접수와 자원 예약을 수행한다."""
        return self.service.mutate(method, self.request(self.build_input(method)))

    def job(self, task: dict) -> dict:
        """! @brief 시험에서만 실행 nonce와 자원 예약의 영속 상태를 읽는다."""
        return self.service.journal.read()["jobs"][task["job_id"]]

    def stage(self, task: dict) -> Path:
        """! @brief 이 시험 작업의 실행 전용 staging 경로만 구한다."""
        return self.workspace / "cad-staging" / self.job(task)["run_id"]

    def wait_for(self, predicate, timeout: float = 8.0):
        """! @brief 실패 시 제한 시간 안에 끝나는 상태 대기 도우미다."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(0.01)
        self.fail("CAD test condition timed out")

    def start_run(self, task: dict) -> threading.Thread:
        """! @brief 서비스 API와 격리 실행을 동시에 사용하도록 native 실행을 시작한다."""
        def run():
            """! @brief 비동기 시험 예외를 본 시험의 검증 대상으로 보존한다."""
            try:
                self.service.cad.run_next()
            except BaseException as error:
                self.runner_errors.append(error)
        runner = threading.Thread(target=run)
        self.runners.append(runner)
        runner.start()
        self.wait_for(lambda: (self.stage(task) / "started.json").is_file())
        return runner

    def assert_not_published(self, task: dict, state: str = "failed") -> dict:
        """! @brief 완료/공개 artifact와 자원 반환을 실패 상태와 함께 확인한다."""
        status = self.status(task)
        self.assertEqual(status["state"], state, status)
        self.assertEqual(status["artifacts"], [])
        self.assertFalse(any(event["state"] == "completed" for event in status["events"]))
        return status

    def test_snapshot_output_remains_bound_while_current_revision_changes(self):
        """! @brief 실행 중/후 편집이 이미 봉인한 입력과 결과의 의미를 바꾸지 않는다."""
        task = self.admit("geometry.build")
        frozen = self.service.journal.read_artifact(self.snapshot["artifact"])
        self.command("metadata.describe", {"description": "CAD 접수 뒤 편집"})
        current = self.service._load(self.service.journal.read()["projects"][self.project])
        self.assertTrue(self.service.cad.run_next())
        status = self.status(task)
        self.assertEqual(status["state"], "completed", status)
        result = status["events"][-1]["operation_result"]
        self.assertEqual(result["snapshot"], self.snapshot)
        self.assertNotEqual(result["snapshot"]["revision_id"], self.revision)
        self.assertEqual(self.service._load(self.service.journal.read()["projects"][self.project]), current)
        self.assertEqual(self.service.journal.read_artifact(self.snapshot["artifact"]), frozen)
        self.assertEqual({item["role"] for item in result["artifacts"]}, {"step", "brep", "sidecar", "validation", "display_mesh", "manifest"})
        self.assertFalse(result["physics_verified"])
        self.assertFalse(result["manufacturing_verified"])
        self.assertFalse(result["kernel_independent"])
        self.assertFalse(self.job(task)["cad"]["resource_reserved"])
        for artifact in result["artifacts"]:
            raw = self.service.journal.read_artifact(artifact)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact["sha256"])

    def test_receipt_replay_reuses_job_before_and_after_restart(self):
        """! @brief 접수 응답 재전송이 native 실행을 중복 생성하지 않는다."""
        request = self.request(self.build_input())
        task = self.service.mutate("export.build", request)
        self.assertEqual(self.service.mutate("export.build", request), task)
        self.assertTrue(self.service.cad.run_next())
        before = self.service.journal.read()
        self.assertEqual(self.service.mutate("export.build", request), task)
        self.assertFalse(self.service.cad.run_next())
        self.assertEqual(self.service.journal.read(), before)
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False, cad_runtime=self.runtime)
        self.assertEqual(self.service.mutate("export.build", request), task)
        self.assertEqual(self.status(task)["state"], "completed")
        self.assertFalse(self.service.cad.run_next())

    def test_preview_and_capability_queries_do_not_mutate_workspace(self):
        """! @brief 내부 조회는 불변이고 공개 미리보기는 원본 변경 없는 비동기 작업이다."""
        self.service.cad.runtime = None
        before = self.service.journal.read()
        params = {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": self.build_input()}
        preview = self.service.cad.preview(params)
        self.assertEqual(preview["status"], "preview_only")
        self.assertEqual(preview["shape_count"], 2)
        self.assertFalse(preview["runtime_configured"])
        capabilities = handle_frame(json.dumps({"jsonrpc": "2.0", "id": "capabilities", "method": "capabilities.get", "params": {
            "contract_version": "rfad.api/2.0", "context": {}, "input": {},
        }}).encode(), self.service)["result"]
        self.assertFalse(capabilities["cad_profile"]["runtime_configured"])
        self.assertEqual(capabilities["cad_profile"]["source"], "immutable_snapshot")
        for method in ("geometry.build", "export.preview", "export.build"):
            self.assertEqual(capabilities["methods"][method]["extension_profile"], PROFILE)
        self.assertEqual(self.service.journal.read(), before)
        request = self.request(self.build_input())
        response = handle_frame(json.dumps({"jsonrpc": "2.0", "id": "preview", "method": "export.preview", "params": request}).encode(), self.service)
        task = response["result"]
        self.assertEqual(task["state"], "queued")
        self.assertTrue(self.service.run_next())
        status = self.status(task)
        self.assertEqual(status["state"], "completed", status)
        self.assertEqual(status["events"][-1]["operation_result"], preview)
        self.assertEqual(self.service._load(self.service.journal.read()["projects"][self.project])["revision_id"], self.revision)
        before = self.service.journal.read()
        with self.assertRaises(ProjectError) as caught:
            self.admit()
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
        self.assertEqual(self.service.journal.read(), before)

    def test_invalid_snapshot_or_unapproved_fields_leave_no_receipt(self):
        """! @brief hash/소유 프로젝트 불일치와 임의 실행 설정을 접수하지 않는다."""
        before = self.service.journal.read()
        for key, value in (("content_hash", "f" * 64), ("snapshot_id", str(uuid4()))):
            with self.subTest(key=key):
                data = self.build_input()
                data["snapshot"][key] = value
                with self.assertRaises(ProjectError) as caught:
                    self.service.mutate("export.build", self.request(data))
                self.assertEqual(caught.exception.code, "E_HASH")
        data = self.build_input()
        data["python"] = str(self.entry)
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("export.build", self.request(data))
        self.assertEqual(caught.exception.code, "E_SCHEMA")
        self.assertEqual(self.service.journal.read(), before)

    def test_tampered_snapshot_artifact_is_rejected_before_queueing(self):
        """! @brief 저장 파일을 바꾼 snapshot은 원본 content hash만으로 신뢰하지 않는다."""
        before = self.service.journal.read()
        path = self.workspace / self.snapshot["artifact"]["uri"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ProjectError) as caught:
            self.admit()
        self.assertEqual(caught.exception.code, "E_HASH")
        self.assertEqual(self.service.journal.read(), before)

    def test_queued_cancel_returns_slot_without_starting_process(self):
        """! @brief 시작 전 취소는 종료가 필요한 프로세스를 만들지 않는다."""
        task = self.admit()
        response = self.service.mutate("job.cancel", self.request({"job_id": task["job_id"]}, {}))
        self.assertEqual(response["state"], "cancelled")
        self.assert_not_published(task, "cancelled")
        self.assertFalse(self.job(task)["cad"]["resource_reserved"])
        self.assertFalse(self.service.cad.run_next())
        self.assertFalse(self.stage(task).exists())
        self.assertEqual(self.admit()["state"], "queued")

    def test_running_cancel_finishes_only_after_owned_process_exit(self):
        """! @brief 실제 실행 취소는 process 종료 확인 뒤 terminal과 자원 반환을 기록한다."""
        self.set_mode("sleep")
        task = self.admit()
        runner = self.start_run(task)
        pid = json.loads((self.stage(task) / "started.json").read_text())["pid"]
        self.assertTrue(_alive(pid))
        response = self.service.mutate("job.cancel", self.request({"job_id": task["job_id"], "reason": "사용자 취소 시험"}, {}))
        self.assertIn(response["state"], {"cancel_requested", "cancelled"})
        runner.join(timeout=8.0)
        self.assertFalse(runner.is_alive())
        self.assertEqual(self.runner_errors, [])
        status = self.assert_not_published(task, "cancelled")
        self.assertEqual([event["state"] for event in status["events"]][-2:], ["cancel_requested", "cancelled"])
        self.assertFalse(_alive(pid))
        self.assertFalse(self.job(task)["cad"]["resource_reserved"])

    def test_edit_status_and_save_respond_during_native_execution(self):
        """! @brief 긴 CAD 계산이 journal 잠금이나 자료 처리 worker를 점유하지 않는다."""
        self.set_mode("sleep")
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=True, cad_runtime=self.runtime)
        task = self.admit()
        self.wait_for(lambda: (self.stage(task) / "started.json").is_file())
        started = time.monotonic()
        self.assertEqual(self.status(task)["state"], "running")
        self.command("metadata.describe", {"description": "native 실행 중 저장"})
        saved = self.complete("project.save", {"expected_revision": self.revision})
        self.assertEqual(saved["saved_revision"], self.revision)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual(self.status(task)["state"], "running")
        with self.assertRaises(ProjectError) as caught:
            self.admit()
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        self.service.mutate("job.cancel", self.request({"job_id": task["job_id"]}, {}))
        self.wait_for(lambda: self.status(task)["state"] == "cancelled")

    def test_timeout_and_output_flood_reap_worker_without_artifact_refs(self):
        """! @brief 시간/로그 제한이 종료 확인과 실패 상태로 이어지는지 검증한다."""
        for mode, timeout in (("sleep", 0.4), ("flood", 5.0)):
            with self.subTest(mode=mode):
                self.set_mode(mode, timeout)
                task = self.admit()
                self.assertTrue(self.service.cad.run_next())
                status = self.assert_not_published(task)
                self.assertEqual(status["events"][-1]["error"]["code"], "E_RESOURCE")
                process = json.loads((self.stage(task) / "process.json").read_bytes())
                self.assertIn(process["termination"], {"timeout", "output_limit"})
                self.assertFalse(_alive(process["pid"]))
                self.assertFalse(self.job(task)["cad"]["resource_reserved"])

    def test_crash_and_invalid_native_outputs_never_publish(self):
        """! @brief 오류 파일/nonce/profile/sidecar 혼동을 정상 출력으로 게시하지 않는다."""
        modes = ("crash", "missing_result", "wrong_nonce", "wrong_input_hash", "wrong_result_schema",
                 "missing_file", "bad_hash", "wrong_sidecar", "wrong_source_semantics", "wrong_step_schema",
                 "wrong_result_snapshot", "wrong_body_count", "unsafe_filename", "byte_limit",
                 "wrong_mesh_snapshot", "wrong_mesh_run", "wrong_mesh_mapping", "wrong_mesh_index", "wrong_mesh_hash")
        for mode in modes:
            with self.subTest(mode=mode):
                self.set_mode(mode)
                task = self.admit()
                self.assertTrue(self.service.cad.run_next())
                status = self.assert_not_published(task)
                self.assertTrue((self.stage(task) / "started.json").is_file())
                if mode in {"crash", "missing_result", "missing_file"}:
                    expected = {"E_DISK", "E_GEOMETRY"}
                elif mode == "byte_limit":
                    expected = {"E_RESOURCE"}
                else:
                    expected = {"E_HASH"}
                self.assertIn(status["events"][-1]["error"]["code"], expected)
                self.assertFalse(self.job(task)["cad"]["resource_reserved"])

    def test_runtime_change_after_acceptance_is_not_executed(self):
        """! @brief 접수 뒤 진입점 변경을 새 worker 실행 전에 차단한다."""
        task = self.admit()
        self.entry.write_text(self.entry.read_text(encoding="utf-8") + "\n# 시험용 변경\n", encoding="utf-8")
        self.assertTrue(self.service.cad.run_next())
        status = self.assert_not_published(task)
        self.assertEqual(status["events"][-1]["error"]["code"], "E_VERSION")
        self.assertFalse(self.stage(task).exists())

    def test_staged_input_hash_tampering_is_not_executed(self):
        """! @brief 접수한 입력 파일의 바이트가 바뀌면 native 시작과 결과 게시를 막는다."""
        task = self.admit()
        path = self.workspace / self.job(task)["cad"]["input"]["uri"]
        path.write_bytes(path.read_bytes() + b" ")
        self.assertTrue(self.service.cad.run_next())
        status = self.assert_not_published(task)
        self.assertEqual(status["events"][-1]["error"]["code"], "E_HASH")
        self.assertFalse((self.stage(task) / "started.json").exists())

    def test_recovery_keeps_unknown_native_reservation_and_blocks_reexecution(self):
        """! @brief 재시작 시 native 종료 불명 상태를 자원 반환이나 자동 재실행으로 바꾸지 않는다."""
        for state_name in ("running", "cancel_requested"):
            with self.subTest(state=state_name):
                task = self.admit()
                def simulate_crash(state):
                    """! @brief 실제 자식 없이 복구할 영속 상태만 시험 목적으로 만든다."""
                    self.service._event(state["jobs"][task["job_id"]], state_name)
                self.service.journal.transaction(simulate_crash)
                self.service.close()
                self.service = ProjectService(self.workspace, auto_run=False, cad_runtime=self.runtime)
                status = self.assert_not_published(task, "interrupted")
                self.assertTrue(status["events"][-1]["outcome_unknown"])
                self.assertTrue(self.job(task)["cad"]["resource_reserved"])
                self.assertFalse(self.service.cad.run_next())
                with self.assertRaises(ProjectError) as caught:
                    self.admit()
                self.assertEqual(caught.exception.code, "E_RESOURCE")
                def release_fixture(state):
                    """! @brief 다음 독립 subtest를 위해 가상 복구 예약만 해제한다."""
                    state["jobs"][task["job_id"]]["cad"]["resource_reserved"] = False
                self.service.journal.transaction(release_fixture)

    def test_seal_failure_preserves_previous_published_package(self):
        """! @brief 디스크 봉인 실패가 마지막 정상 패키지를 덮어쓰지 않는다."""
        first = self.admit()
        self.service.cad.run_next()
        previous = self.status(first)
        self.assertEqual(previous["state"], "completed", previous)
        expected = {item["uri"]: self.service.journal.read_artifact(item) for item in previous["artifacts"]}
        failed = self.admit()
        with patch.object(self.service.journal, "seal_file", side_effect=ProjectError("E_DISK", "시험용 디스크 부족")):
            self.service.cad.run_next()
        status = self.assert_not_published(failed)
        self.assertEqual(status["events"][-1]["error"]["code"], "E_DISK")
        self.assertEqual(self.status(first), previous)
        for reference in previous["artifacts"]:
            self.assertEqual(self.service.journal.read_artifact(reference), expected[reference["uri"]])

    def test_publication_failure_keeps_closed_files_unpublished(self):
        """! @brief 파일 봉인 후 journal 게시 실패는 성공 event/artifact를 남기지 않는다."""
        task = self.admit()
        seal = self.service.cad._seal
        def seal_then_fail_once(*args):
            """! @brief 완료 게시 직전의 한 번짜리 저장 실패를 주입한다."""
            result = seal(*args)
            def fail(stage):
                """! @brief current pointer를 바꾸기 전 실패하고 후속 실패 기록은 허용한다."""
                if stage == "before_publish":
                    self.service.journal.fault_hook = None
                    raise OSError("simulated publication disk failure")
            self.service.journal.fault_hook = fail
            return result
        with patch.object(self.service.cad, "_seal", side_effect=seal_then_fail_once):
            self.service.cad.run_next()
        status = self.assert_not_published(task)
        self.assertEqual(status["events"][-1]["error"]["code"], "E_DISK")
        self.assertFalse(self.job(task)["cad"]["resource_reserved"])

    def test_cancel_wins_after_files_close_before_publication(self):
        """! @brief 완료 파일이 존재해도 게시 전 취소한 결과를 성공으로 승격하지 않는다."""
        task = self.admit()
        seal = self.service.cad._seal
        def seal_then_cancel(*args):
            """! @brief 닫힌 파일 검증과 완료 transaction 사이에 취소를 접수한다."""
            result = seal(*args)
            self.service.mutate("job.cancel", self.request({"job_id": task["job_id"]}, {}))
            return result
        with patch.object(self.service.cad, "_seal", side_effect=seal_then_cancel):
            self.service.cad.run_next()
        self.assert_not_published(task, "cancelled")
        self.assertFalse(self.job(task)["cad"]["resource_reserved"])

    def test_error_after_commit_preserves_the_published_success(self):
        """! @brief 완료 pointer 게시 뒤 응답 오류가 이미 확정한 결과를 실패로 되돌리지 않는다."""
        task = self.admit()
        seal = self.service.cad._seal
        def seal_then_fault_once(*args):
            """! @brief 완료 상태가 게시된 직후의 한 번짜리 응답 실패를 주입한다."""
            result = seal(*args)
            def fail(stage):
                """! @brief 이미 게시한 commit 뒤 오류만 발생시키고 다음 조회는 허용한다."""
                if stage == "after_publish":
                    self.service.journal.fault_hook = None
                    raise OSError("simulated post-commit response failure")
            self.service.journal.fault_hook = fail
            return result
        with patch.object(self.service.cad, "_seal", side_effect=seal_then_fault_once):
            self.assertTrue(self.service.cad.run_next())
        status = self.status(task)
        self.assertEqual(status["state"], "completed", status)
        self.assertEqual(len(status["artifacts"]), 6)
        self.assertEqual(sum(event["state"] == "completed" for event in status["events"]), 1)
        self.assertFalse(any(event["state"] == "failed" for event in status["events"]))
        self.assertFalse(self.service.cad.run_next())

    def test_late_nonce_result_cannot_publish_or_release_another_reservation(self):
        """! @brief 소유권이 바뀐 작업에 과거 실행 결과를 게시하지 않는다."""
        task = self.admit()
        seal = self.service.cad._seal
        def seal_then_replace_nonce(*args):
            """! @brief 늦은 결과가 가진 nonce와 다른 영속 소유권을 만든다."""
            result = seal(*args)
            def replace(state):
                """! @brief 시험 대상 작업의 소유권만 변경한다."""
                state["jobs"][task["job_id"]]["cad"]["nonce"] = str(uuid4())
            self.service.journal.transaction(replace)
            return result
        with patch.object(self.service.cad, "_seal", side_effect=seal_then_replace_nonce):
            self.service.cad.run_next()
        self.assert_not_published(task, "running")
        self.assertTrue(self.job(task)["cad"]["resource_reserved"])


if __name__ == "__main__":
    unittest.main()
