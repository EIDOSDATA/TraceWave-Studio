"""! @brief 불변 해석 계획과 WSL 작업 수명, 결과 게시를 연결한다."""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import threading
import time
from uuid import UUID, uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.solver import PROFILE, build_analysis_plan, make_prepared_plan, validate_reference_plan
from rfad.domain.errors import ProjectError


CODE_ROOT = Path(__file__).resolve().parents[3]
SOLVER_METHODS = {"solver.plan", "solver.prepare", "job.submit"}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
RUNTIME_PROFILE = "openems-wsl-reference/0.1"
PCB_PROFILE = "rfad.openems.pcb-single-port/0.1"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 128 * 1024 * 1024


def _fields(value, required, optional=()):
    """! @brief 알 수 없는 입력을 실행 옵션으로 전달하지 않는다."""
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ProjectError("E_SCHEMA", "해석 요청 필드가 유효하지 않습니다.")
    return value


def _uuid(value):
    """! @brief 실행 식별자는 정규 UUID로 한정한다."""
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise ProjectError("E_SCHEMA", "정규 UUID가 필요합니다.") from error


def _reference(value, id_key):
    """! @brief 클라이언트는 등록된 ID와 내용 해시로만 입력을 선택한다."""
    _fields(value, {id_key, "content_hash"})
    _uuid(value[id_key])
    digest = value["content_hash"]
    if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ProjectError("E_HASH", "SHA256 참조가 유효하지 않습니다.")


class SolverRuntime:
    """! @brief API와 분리된 고정 WSL 설치 및 worker 바이트를 캡처한다."""

    def __init__(self, transport=None, *, audit=None, manifest=None):
        """! @brief native 모듈을 호스트에 import하지 않고 설치 명세만 읽는다."""
        if transport is None:
            from rfad.application.wsl_process import WslRuntime

            transport = WslRuntime()
        self.transport = transport
        audit_data = json.loads((audit or CODE_ROOT / ".local/wsl/native-audit.json").read_bytes())
        manifest_data = json.loads((manifest or CODE_ROOT / "runtime_profiles/python-openems-linux-x64.json").read_bytes())
        if audit_data.get("status") != "passed" or audit_data.get("qt_found") is not False or manifest_data.get("qt_allowed") is not False:
            raise ProjectError("E_VERSION", "검증된 Qt 없는 openEMS 설치 명세가 필요합니다.")
        self.manifest_bytes = canonical_bytes({"schema": "rfad.openems-worker-runtime/0.1", "python_manifest": manifest_data, "native_audit": audit_data})
        files = [CODE_ROOT / "tools/openems_worker.py", *sorted((CODE_ROOT / "src/rfad").rglob("*.py"))]
        self.sources = {p.relative_to(CODE_ROOT).as_posix(): p.read_text(encoding="utf-8") for p in files}
        self.source_bytes = canonical_bytes(self.sources)
        if len(self.source_bytes) > 4 * 1024 * 1024 or len(files) > 192:
            raise ProjectError("E_RESOURCE", "해석 worker 소스 묶음이 상한을 초과했습니다.")
        self.identity = {"runtime_profile": RUNTIME_PROFILE, "manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest(),
                         "code_files": [{"path": path, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": len(text.encode("utf-8"))} for path, text in self.sources.items()],
                         "transport": transport.identity()}


class SolverCoordinator:
    """! @brief 편집 및 CAD와 독립된 단일 WSL 해석 슬롯을 관리한다."""

    def __init__(self, service, runtime=None):
        """! @brief 장시간 실행을 journal 잠금 밖에서 처리할 상태를 만든다."""
        self.service, self.runtime = service, runtime
        self.wake, self.stop, self.cancel = threading.Event(), threading.Event(), threading.Event()
        self.thread, self.error = None, None
        self._run_lock = threading.Lock()

    def start(self):
        """! @brief 구성된 서비스에만 WSL 조정 스레드를 시작한다."""
        if self.runtime is not None:
            self.thread = threading.Thread(target=self._loop, name="rfad-openems-coordinator", daemon=False)
            self.thread.start()
            self.wake.set()

    def close(self):
        """! @brief 소유 실행에 취소를 요청하고 상태 처리를 기다린다."""
        self.stop.set()
        self.cancel.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join()
            self.thread = None

    @staticmethod
    def validate_input(method, context, data):
        """! @brief 초기 도파관 profile과 명시적 준비 계획만 허용한다."""
        _fields(context, {"project_id"})
        _uuid(context["project_id"])
        if method == "solver.plan":
            _fields(data, {"snapshot", "analysis_profile", "runtime_profile"}, {"grid_mm", "settings"})
            _reference(data["snapshot"], "snapshot_id")
            if data["analysis_profile"] not in (PROFILE, PCB_PROFILE) or data["runtime_profile"] != RUNTIME_PROFILE:
                raise ProjectError("E_UNSUPPORTED", "지원하는 해석 profile을 지정하십시오.")
            if data["analysis_profile"] == PROFILE:
                if "settings" in data or type(data.get("grid_mm")) not in (int, float) or data["grid_mm"] not in (1.0, 0.75):
                    raise ProjectError("E_UNSUPPORTED", "참조 격자는 1.0 또는 0.75 mm입니다.")
            elif "grid_mm" in data or type(data.get("settings")) is not dict:
                raise ProjectError("E_SCHEMA", "사용자 PCB 해석에는 명시적인 settings가 필요합니다.")
        else:
            _fields(data, {"analysis_plan", "budget"} if method == "solver.prepare" else {"task_plan", "budget"})
            _fields(data["budget"], {"timeout_seconds"})
            timeout = data["budget"]["timeout_seconds"]
            if type(timeout) not in (float, int) or not math.isfinite(timeout) or not 0 < timeout <= 300:
                raise ProjectError("E_RESOURCE", "실행 제한은 0초 초과 300초 이하여야 합니다.")
            if method == "solver.prepare":
                _reference(data["analysis_plan"], "plan_id")
            else:
                task = _fields(data["task_plan"], {"kind", "prepared_plan", "execution_mode"}, {"raw_result_id"})
                _reference(task["prepared_plan"], "prepared_plan_id")
                if task["kind"] != "em_analysis" or task["execution_mode"] not in {"solve_and_postprocess", "postprocess_only"}:
                    raise ProjectError("E_UNSUPPORTED", "지원하는 em_analysis 실행 모드를 지정하십시오.")
                if task["execution_mode"] == "postprocess_only":
                    _uuid(task.get("raw_result_id"))
                elif "raw_result_id" in task:
                    raise ProjectError("E_SCHEMA", "원시 결과는 후처리 전용 작업에서만 지정합니다.")

    def _record(self, state, collection, ref, id_key, project_id):
        """! @brief 다른 프로젝트 또는 변조한 계획 참조의 사용을 막는다."""
        record = state[collection].get(ref[id_key])
        if record is None or record["project_id"] != project_id or record["reference"]["content_hash"] != ref["content_hash"]:
            raise ProjectError("E_HASH", "등록된 해석 계획과 프로젝트 또는 해시가 다릅니다.")
        document = json.loads(self.service.journal.read_artifact(record["reference"]["artifact"]))
        if canonical_hash(document) != ref["content_hash"]:
            raise ProjectError("E_HASH", "해석 계획 내용이 변경되었습니다.")
        return record, document

    def admit(self, state, method, context, data):
        """! @brief 불변 계획과 원시 입력 참조를 캡처하고 슬롯을 예약한다."""
        if self.runtime is None:
            raise ProjectError("E_UNSUPPORTED", "서비스 실행 시 --openems-wsl 설정이 필요합니다.")
        if self.error is not None or any(j.get("solver", {}).get("resource_reserved") for j in state["jobs"].values()):
            raise ProjectError("E_RESOURCE", "해석 슬롯이 사용 중이거나 이전 실행 종료 확인이 필요합니다.")
        if len(state["jobs"]) >= 512:
            raise ProjectError("E_RESOURCE", "작업 보존 상한에 도달했습니다.")
        project = self.service._project(state, context)
        project_id = context["project_id"]
        job_id, run_id, nonce = str(uuid4()), str(uuid4()), uuid4().hex
        captured = {"nonce": nonce, "runtime": deepcopy(self.runtime.identity), "resource_reserved": True}
        if method == "solver.plan":
            snapshot = state["snapshots"].get(data["snapshot"]["snapshot_id"])
            if snapshot is None or snapshot["project_id"] != project_id or snapshot["content_hash"] != data["snapshot"]["content_hash"]:
                raise ProjectError("E_HASH", "등록된 불변 스냅샷이 필요합니다.")
            document = self.service._load({"current": snapshot["artifact"]})
            if data["analysis_profile"] == PCB_PROFILE:
                from rfad.application.pcb_solver import build_pcb_plan

                captured["plan"] = build_pcb_plan(document, snapshot, self.runtime.identity, data["settings"])
            else:
                captured["plan"] = build_analysis_plan(document, snapshot, self.runtime.identity, data["grid_mm"])
            kind = "data_processing"
        elif method == "solver.prepare":
            record, plan = self._record(state, "analysis_plans", data["analysis_plan"], "plan_id", project_id)
            captured.update(analysis_plan=plan, analysis_plan_ref=record["reference"])
            kind = "em_prepare"
        else:
            task = data["task_plan"]
            record, prepared = self._record(state, "prepared_plans", task["prepared_plan"], "prepared_plan_id", project_id)
            plan_record = state["analysis_plans"][record["analysis_plan_id"]]
            _, plan = self._record(state, "analysis_plans", {k: plan_record["reference"][k] for k in ("plan_id", "content_hash")}, "plan_id", project_id)
            preparation = json.loads(self.service.journal.read_artifact(record["preparation_artifact"]))
            captured.update(analysis_plan=plan, analysis_plan_ref=plan_record["reference"], prepared_plan=prepared,
                            preparation=preparation, preparation_files=record["files"])
            if task["execution_mode"] == "postprocess_only":
                raw = state["solver_results"].get(task["raw_result_id"])
                if raw is None or raw["prepared_plan_id"] != prepared["prepared_plan_id"] or raw["project_id"] != project_id:
                    raise ProjectError("E_MISSING_ARTIFACT", "동일한 PreparedPlan의 봉인된 원시 결과가 필요합니다.")
                captured["raw_files"] = deepcopy(raw["raw_files"])
            kind = "em_analysis"
        plan = captured.get("analysis_plan", captured.get("plan"))
        if plan["analysis_profile"] == PCB_PROFILE:
            from rfad.application.pcb_solver import validate_pcb_plan

            validate_pcb_plan(plan)
        else:
            validate_reference_plan(plan)
        if plan["runtime_identity"] != self.runtime.identity:
            raise ProjectError("E_VERSION", "계획을 작성한 런타임과 현재 실행 설정이 다릅니다.")
        base = project["path"] + "/solver-inputs/" + run_id
        captured["manifest"] = self.service.journal.put_immutable(base + "/runtime.json", self.runtime.manifest_bytes)
        captured["source"] = self.service.journal.put_immutable(base + "/source.json", self.runtime.source_bytes)
        job = {"job_id": job_id, "run_id": run_id, "kind": kind, "operation_method": method,
               "context": deepcopy(context), "input": deepcopy(data), "solver": captured, "events": []}
        self.service._event(job, "queued")
        state["jobs"][job_id] = job
        return {"job_id": job_id, "state": "queued", "events_cursor": 1}

    def cancel_job(self, job, reason):
        """! @brief 실행 중 작업은 실제 guest 종료 확인 전까지 예약을 유지한다."""
        if job["state"] == "queued":
            self.service._event(job, "cancel_requested", reason=reason)
            job["solver"]["resource_reserved"] = False
            self.service._event(job, "cancelled", termination_confirmed=True)
        elif job["state"] in {"preparing", "running", "postprocessing"}:
            self.service._event(job, "cancel_requested", reason=reason)
            self.cancel.set()

    def run_next(self):
        """! @brief 하나의 접수 작업을 journal 잠금 밖에서 실행한다."""
        if self.runtime is None or not self._run_lock.acquire(blocking=False):
            return False
        try:
            return self._run_one()
        finally:
            self._run_lock.release()

    def _run_one(self):
        """! @brief 실행 및 취소 경쟁에서 먼저 확정한 terminal 상태를 보존한다."""
        self.cancel.clear()
        if not any("solver" in j and j["state"] == "queued" for j in self.service.journal.read()["jobs"].values()):
            return False
        def begin(state):
            for job in state["jobs"].values():
                if "solver" in job and job["state"] == "queued":
                    phase = "preparing" if job["kind"] == "em_prepare" else "running"
                    if job["input"].get("task_plan", {}).get("execution_mode") == "postprocess_only":
                        phase = "postprocessing"
                    self.service._event(job, phase)
                    return deepcopy(job)
            return None
        job = self.service.journal.transaction(begin)
        if job is None:
            return False
        process = {"state": "failed", "termination_confirmed": True, "outcome_unknown": False}
        try:
            if job["operation_method"] == "solver.plan":
                self._publish_plan(job)
                return True
            stage, request = self._stage(job)
            process = {"state": "failed", "termination_confirmed": False, "outcome_unknown": True}
            process = self.runtime.transport.execute(stage, run_id=job["run_id"], nonce=job["solver"]["nonce"], cancel=self.cancel,
                                                     timeout_seconds=job["input"]["budget"]["timeout_seconds"], on_state=lambda value: self._progress(job, value))
            if process.get("state") == "failed" and process.get("termination_confirmed") and (stage / "output/result.json").is_file():
                failed = self._read_result(stage, request).get("error", {})
                raise ProjectError(failed.get("code", "E_SOLVER"), str(failed.get("message_ko", "openEMS worker 실행 실패"))[:2048])
            if process.get("state") != "completed" or not process.get("termination_confirmed") or process.get("outcome_unknown", False):
                self._finish(job, process)
                return True
            package = self._read_result(stage, request)
            if "error" in package:
                error = package["error"]
                raise ProjectError(error.get("code", "E_SOLVER"), str(error.get("message_ko", error.get("message", "openEMS 작업 실패")))[:2048])
            files = self._seal(job, stage, package)
            self._publish_result(job, package, files, process)
        except Exception as error:
            if isinstance(error, ProjectError) and error.details.get("not_started") is True and error.details.get("termination_confirmed") is True:
                process = {"state": "failed", "termination_confirmed": True, "outcome_unknown": False}
            diagnostic = error if isinstance(error, ProjectError) else ProjectError("E_DISK" if isinstance(error, OSError) else "E_SOLVER", str(error)[:2048])
            self._finish(job, process, diagnostic)
        return True

    def _publish_plan(self, job):
        """! @brief 계획 본문은 불변 파일로 저장하고 작은 참조만 게시한다."""
        plan = job["solver"]["plan"]
        artifact = self.service.journal.put_immutable("solver-artifacts/" + job["run_id"] + "/analysis-plan.json", canonical_bytes(plan))
        ref = {"plan_id": plan["plan_id"], "content_hash": canonical_hash(plan), "artifact": artifact}
        def publish(state):
            active = state["jobs"][job["job_id"]]
            if active["solver"]["nonce"] != job["solver"]["nonce"]:
                raise ProjectError("E_CONFLICT", "계획 게시 소유권이 변경되었습니다.")
            if active["state"] in TERMINAL:
                return
            active["solver"]["resource_reserved"] = False
            if active["state"] == "cancel_requested":
                self.service._event(active, "cancelled", termination_confirmed=True)
                return
            state["analysis_plans"][plan["plan_id"]] = {"project_id": job["context"]["project_id"], "reference": ref}
            active["artifacts"] = [{"role": "analysis_plan", **artifact}]
            self.service._event(active, "completed", operation_result={"analysis_plan": ref, "profile": plan["analysis_profile"],
                "model_report": plan.get("model_report", {}), "resource_estimate": plan.get("resource_estimate", {})})
        self.service.journal.transaction(publish)

    def _stage(self, job):
        """! @brief journal에서 읽은 바이트만 새로운 작업 디렉터리로 복제한다."""
        captured = job["solver"]
        if captured["runtime"] != self.runtime.identity:
            raise ProjectError("E_VERSION", "재시작 후 런타임이 변경되어 자동 실행할 수 없습니다.")
        stage = self.service.journal._safe_path("solver-staging/" + job["run_id"])
        stage.mkdir(parents=True, exist_ok=False)
        sources = json.loads(self.service.journal.read_artifact(captured["source"]))
        expected = {f["path"]: f for f in captured["runtime"]["code_files"]}
        if sources.keys() != expected.keys():
            raise ProjectError("E_HASH", "worker 소스 목록이 변경되었습니다.")
        for relative, text in sources.items():
            parts = PurePosixPath(relative).parts
            if ".." in parts or PurePosixPath(relative).is_absolute() or "\\" in relative or ":" in relative or not relative.endswith(".py"):
                raise ProjectError("E_HASH", "worker 소스 경로가 유효하지 않습니다.")
            raw = text.encode("utf-8")
            if hashlib.sha256(raw).hexdigest() != expected[relative]["sha256"] or len(raw) != expected[relative]["bytes"]:
                raise ProjectError("E_HASH", "worker 소스 해시가 변경되었습니다.")
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (stage / "runtime.json").write_bytes(self.service.journal.read_artifact(captured["manifest"]))
        phase = "prepare" if job["kind"] == "em_prepare" else "analysis"
        if job["input"].get("task_plan", {}).get("execution_mode") == "postprocess_only":
            phase = "postprocess_only"
        request = {"schema": "rfad.openems-worker/0.1", "phase": phase, "run_id": job["run_id"], "nonce": captured["nonce"],
                   "analysis_plan": captured["analysis_plan"], "runtime": captured["runtime"], "input_files": []}
        if "prepared_plan" in captured:
            request.update(prepared_plan=captured["prepared_plan"], preparation=captured["preparation"])
        for item in captured.get("preparation_files", []) + captured.get("raw_files", []):
            relative = "input/" + item["path"].removeprefix("output/")
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.service.journal.read_artifact(item["artifact"]))
            request["input_files"].append({"path": relative, "role": item["role"], "sha256": item["sha256"], "bytes": item["bytes"]})
        (stage / "request.json").write_bytes(canonical_bytes(request))
        return stage, request

    def _progress(self, job, value):
        """! @brief 제한된 phase와 소유 정보만 저장하고 계산 출력은 로그 파일로 둔다."""
        phase = value.get("phase")
        def update(state):
            active = state["jobs"][job["job_id"]]
            if active["solver"]["nonce"] != job["solver"]["nonce"]:
                raise ProjectError("E_CONFLICT", "해석 실행 소유권이 변경되었습니다.")
            if active["state"] == "cancel_requested" or self.stop.is_set():
                self.cancel.set()
            if phase == "postprocessing" and active["state"] == "running":
                self.service._event(active, "postprocessing")
        current = self.service.journal.read()["jobs"][job["job_id"]]
        if phase == "postprocessing" and current["state"] == "running":
            self.service.journal.transaction(update)
        elif current["state"] == "cancel_requested" or self.stop.is_set():
            self.cancel.set()

    @staticmethod
    def _read_result(stage, request):
        """! @brief 종료된 worker의 작은 결과 봉투를 현재 요청과 대조한다."""
        path = stage / "output/result.json"
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise ProjectError("E_RESOURCE", "해석 결과 메타데이터가 유효하지 않습니다.")
        result = json.loads(path.read_bytes())
        for key, expected in (("schema", "rfad.openems-worker-result/0.1"), ("phase", request["phase"]), ("run_id", request["run_id"]), ("nonce", request["nonce"]), ("analysis_plan_id", request["analysis_plan"]["plan_id"])):
            if result.get(key) != expected:
                raise ProjectError("E_HASH", "해석 결과의 입력 또는 실행 식별이 다릅니다.")
        return result

    def _seal(self, job, stage, package):
        """! @brief 닫힌 파일을 크기와 해시로 검증하고 불변 저장소로 봉인한다."""
        files = package.get("files")
        if type(files) is not list or not 1 <= len(files) <= 64:
            raise ProjectError("E_HASH", "해석 결과 파일 목록이 유효하지 않습니다.")
        sealed, seen, roles, total = [], set(), set(), 0
        for item in files:
            _fields(item, {"path", "role", "sha256", "bytes", "media_type"})
            if type(item["role"]) is not str or item["role"] in roles or type(item["media_type"]) is not str:
                raise ProjectError("E_HASH", "결과 역할이 중복되었거나 유효하지 않습니다.")
            roles.add(item["role"])
            path = item["path"]
            parts = PurePosixPath(path).parts if type(path) is str else ()
            if len(parts) < 2 or parts[0] != "output" or any(p in {".", ".."} for p in parts) or "\\" in path or ":" in path or path in seen or PurePosixPath(path).as_posix() != path:
                raise ProjectError("E_HASH", "해석 결과 경로가 유효하지 않습니다.")
            if type(item["bytes"]) is not int or not 0 < item["bytes"] <= MAX_FILE_BYTES:
                raise ProjectError("E_RESOURCE", "해석 결과 파일 크기가 상한을 초과했습니다.")
            total += item["bytes"]
            if total > MAX_PACKAGE_BYTES:
                raise ProjectError("E_RESOURCE", "해석 결과 묶음이 상한을 초과했습니다.")
            seen.add(path)
            artifact = self.service.journal.seal_file("solver-artifacts/" + job["run_id"] + "/" + path.removeprefix("output/"), stage / path,
                                                      expected_sha256=item["sha256"], expected_bytes=item["bytes"], limit=MAX_FILE_BYTES)
            sealed.append({**item, "artifact": artifact})
        return sealed

    def _publish_result(self, job, package, files, process):
        """! @brief 준비 계획 또는 결과 manifest를 마지막 journal commit으로 게시한다."""
        captured = job["solver"]
        project_id = job["context"]["project_id"]
        prepared_ref, prepared_record, result_record = None, None, None
        if job["kind"] == "em_prepare":
            prep = next((f for f in files if f["role"] == "preparation_artifact"), None)
            if prep is None:
                raise ProjectError("E_HASH", "준비 산출물 manifest가 없습니다.")
            preparation = json.loads(self.service.journal.read_artifact(prep["artifact"]))
            if preparation != package.get("preparation") or preparation.get("analysis_plan_id") != captured["analysis_plan"]["plan_id"] or preparation.get("analysis_plan_hash") != captured["analysis_plan_ref"]["content_hash"]:
                raise ProjectError("E_HASH", "준비 산출물이 해석 계획과 다릅니다.")
            self._check_prepared(captured, preparation, files)
            prepared = make_prepared_plan(captured["analysis_plan_ref"], captured["analysis_plan"]["snapshot"], prep["artifact"], captured["runtime"])
            artifact = self.service.journal.put_immutable("solver-artifacts/" + job["run_id"] + "/prepared-plan.json", canonical_bytes(prepared))
            prepared_ref = {"prepared_plan_id": prepared["prepared_plan_id"], "content_hash": canonical_hash(prepared), "artifact": artifact}
            prepared_record = {"project_id": project_id, "reference": prepared_ref, "analysis_plan_id": captured["analysis_plan"]["plan_id"],
                               "preparation_artifact": prep["artifact"], "files": files}
            operation = {"prepared_plan": prepared_ref, "preparation_artifact": prep["artifact"], "mesh_statistics": preparation["mesh_statistics"]}
        else:
            normalized = next((f for f in files if f["role"] == "normalized_result"), None)
            if normalized is None:
                raise ProjectError("E_HASH", "정규화된 결과가 없습니다.")
            result = json.loads(self.service.journal.read_artifact(normalized["artifact"]))
            if result != package.get("result") or result.get("analysis_plan_id") != captured["analysis_plan"]["plan_id"] or result.get("prepared_plan_id") != captured["prepared_plan"]["prepared_plan_id"]:
                raise ProjectError("E_HASH", "결과가 봉인된 해석 계획과 다릅니다.")
            self._check_result(job, result, files)
            result_id = str(uuid4())
            result_record = {"artifact_id": result_id, "project_id": project_id, "prepared_plan_id": captured["prepared_plan"]["prepared_plan_id"],
                             "analysis_plan_id": captured["analysis_plan"]["plan_id"], "normalized": normalized["artifact"], "files": files,
                             "snapshot": deepcopy(captured["analysis_plan"]["snapshot"]),
                             "raw_files": [f for f in files if f["role"].startswith("raw/") or f["role"] == "raw_manifest"],
                             "metadata": {"schema": "rfad.openems-result-view/0.1", "profile": captured["analysis_plan"]["analysis_profile"], "assessment": result.get("assessment", {}),
                                          "normalization": result.get("normalization", {}), "sample_count": len(result.get("samples", [])),
                                          "physics_scope": "user_pcb_single_port_computed_unvalidated" if captured["analysis_plan"]["analysis_profile"] == PCB_PROFILE else "rectangular_waveguide_reference_only",
                                          "physics_validation_state": "not_validated" if captured["analysis_plan"]["analysis_profile"] == PCB_PROFILE else "reference_case_only"}}
            if not result_record["raw_files"] and job["input"]["task_plan"]["execution_mode"] == "postprocess_only":
                result_record["raw_files"] = captured["raw_files"]
            operation = {"artifact_id": result_id, "normalized_result": normalized["artifact"], "assessment": result.get("assessment", {}),
                         "snapshot": deepcopy(captured["analysis_plan"]["snapshot"]), "profile": captured["analysis_plan"]["analysis_profile"]}
        def publish(state):
            active = state["jobs"][job["job_id"]]
            if active["solver"]["nonce"] != captured["nonce"]:
                raise ProjectError("E_CONFLICT", "해석 결과 게시 소유권이 변경되었습니다.")
            if active["state"] in TERMINAL:
                return
            active["solver"]["resource_reserved"] = False
            active["solver"]["termination_confirmed"] = True
            if active["state"] == "cancel_requested" or self.cancel.is_set():
                self.service._event(active, "cancelled", termination_confirmed=True)
                return
            if prepared_record is not None:
                state["prepared_plans"][prepared_ref["prepared_plan_id"]] = prepared_record
            else:
                if active["state"] == "running":
                    self.service._event(active, "postprocessing")
                state["solver_results"][result_record["artifact_id"]] = result_record
            active["artifacts"] = [{"role": f["role"], **f["artifact"]} for f in files]
            self.service._event(active, "completed", termination_confirmed=True, operation_result=operation)
        self.service.journal.transaction(publish)

    def _check_prepared(self, captured, preparation, files):
        """! @brief 준비 완료 선언 전에 소비 내역과 필수 native 파일의 연결을 검사한다."""
        roles = {f["role"]: f for f in files}
        required = {"native_input", "mesh_statistics", "consumption_report", "normalization", "runtime_provenance", "preparation_artifact"}
        if roles.keys() != required or preparation.get("schema") != "rfad.preparation-artifact/0.1" or preparation.get("profile") != captured["analysis_plan"]["analysis_profile"]:
            raise ProjectError("E_HASH", "준비 산출물의 필수 역할 또는 profile이 다릅니다.")
        descriptions = [{k: v for k, v in f.items() if k != "artifact"} for f in files if f["role"] != "preparation_artifact"]
        if preparation.get("files") != descriptions:
            raise ProjectError("E_HASH", "준비 manifest와 실제 파일 목록이 다릅니다.")
        for role, key in (("mesh_statistics", "mesh_statistics"), ("consumption_report", "consumption_report"), ("normalization", "normalization"), ("runtime_provenance", "runtime_identity")):
            if json.loads(self.service.journal.read_artifact(roles[role]["artifact"])) != preparation.get(key):
                raise ProjectError("E_HASH", "준비 manifest와 소비 보고 내용이 다릅니다.")
        plan, mesh, consumption = captured["analysis_plan"], preparation["mesh_statistics"], preparation["consumption_report"]
        observed = preparation["runtime_identity"]
        if (observed.get("manifest_sha256") != captured["runtime"]["manifest_sha256"] or observed.get("code_files") != captured["runtime"]["code_files"]
                or observed.get("qt_found") is not False):
            raise ProjectError("E_HASH", "실제 준비 런타임이 고정한 식별과 다릅니다.")
        if plan["analysis_profile"] == PCB_PROFILE:
            from rfad.application.pcb_solver import validate_preparation

            validate_preparation(plan, preparation)
            return
        if (preparation["normalization"] != plan["normalization"] or mesh.get("fdtd_executed") is not False
                or mesh.get("native_preprocessing_executed") is not False or mesh.get("grid_mm") != plan["case"]["mesh"]["grid_mm"]
                or mesh.get("delta_unit_m") != 0.001 or mesh.get("native_length_unit") != "mm"
                or consumption.get("consumed_case") != plan["case"] or consumption.get("fdtd_executed") is not False
                or consumption.get("analysis_plan_id") != plan["plan_id"]):
            raise ProjectError("E_HASH", "준비된 물리 조건 또는 단위가 계획과 다릅니다.")
        lines = mesh.get("lines_mm", {})
        counts = []
        for axis, extent in zip(("x", "y", "z"), plan["case"]["dimensions_mm"]):
            values = lines.get(axis, [])
            if (not values or values[0] != 0 or values[-1] != extent
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                    or any(not 0 < b - a <= mesh["grid_mm"] + 1e-12 for a, b in zip(values, values[1:]))):
                raise ProjectError("E_HASH", "실제 준비 격자가 계획 크기 또는 간격과 다릅니다.")
            counts.append(len(values))
        if (mesh.get("line_counts") != counts or mesh.get("native_grid_points") != math.prod(counts)
                or mesh.get("interval_counts") != [n - 1 for n in counts]
                or mesh.get("yee_interval_cells") != math.prod(n - 1 for n in counts)
                or not set(plan["case"]["mesh"]["critical_z_mm"]) <= set(lines["z"])):
            raise ProjectError("E_HASH", "준비 격자 통계 또는 포트 측정면이 다릅니다.")
        observed = preparation["runtime_identity"]
        if (observed.get("manifest_sha256") != captured["runtime"]["manifest_sha256"] or observed.get("code_files") != captured["runtime"]["code_files"]
                or observed.get("qt_found") is not False):
            raise ProjectError("E_HASH", "실제 준비 런타임이 고정한 식별과 다릅니다.")

    def _check_result(self, job, result, files):
        """! @brief 완료된 raw manifest와 후처리 수치를 계획 및 실행 소유권에 결합한다."""
        from rfad.adapters.solvers.openems.reference import assess_samples, check_termination

        captured = job["solver"]
        pcb = captured["analysis_plan"]["analysis_profile"] == PCB_PROFILE
        roles = {f["role"]: f for f in files}
        if pcb:
            from rfad.application.pcb_solver import RAW_NAMES, read_statistics_values, check_termination as check_pcb_termination, validate_result

            raw_names = RAW_NAMES
        else:
            raw_names = ("port_ut_1", "port_it_1", "port_ut_2", "port_it_2", "openEMS_stats.txt", "openEMS_run_stats.txt", "native.log", "waveguide.xml")
        raw_roles = {"raw/" + name for name in raw_names}
        if roles.keys() != raw_roles | {"raw_manifest", "normalized_result", "provenance"}:
            raise ProjectError("E_MISSING_ARTIFACT", "해석 결과의 필수 원시 파일이 없습니다.")
        manifest = json.loads(self.service.journal.read_artifact(roles["raw_manifest"]["artifact"]))
        provenance = json.loads(self.service.journal.read_artifact(roles["provenance"]["artifact"]))
        if result.get("schema") != ("rfad.openems-pcb-result/0.1" if pcb else "rfad.openems-result/0.1") or provenance.get("schema") != "rfad.openems-provenance/0.1":
            raise ProjectError("E_VERSION", "지원하지 않는 해석 결과 스키마입니다.")
        if (manifest != result.get("raw_manifest") or manifest.get("schema") != "rfad.openems-raw/0.1" or manifest.get("complete") is not True
                or manifest.get("analysis_plan_hash") != canonical_hash(captured["analysis_plan"])
                or manifest.get("prepared_plan_hash") != canonical_hash(captured["prepared_plan"])
                or manifest.get("analysis_plan_id") != captured["analysis_plan"]["plan_id"]
                or manifest.get("prepared_plan_id") != captured["prepared_plan"]["prepared_plan_id"]):
            raise ProjectError("E_HASH", "완료된 원시 결과의 봉인 또는 계획 식별이 다릅니다.")
        descriptions = [{k: v for k, v in f.items() if k != "artifact"} for f in files if f["role"] in raw_roles]
        if manifest.get("files") != descriptions:
            raise ProjectError("E_HASH", "원시 manifest와 실제 결과 파일 목록이 다릅니다.")
        native_input = next(f for f in captured["preparation"]["files"] if f["role"] == "native_input")
        execution = manifest.get("execution", {})
        if roles["raw/pcb.xml" if pcb else "raw/waveguide.xml"]["sha256"] != native_input["sha256"] or execution.get("native_input_sha256") != native_input["sha256"] or execution.get("exit_code") != 0:
            raise ProjectError("E_HASH", "실제 해석 입력 또는 종료 코드가 준비 계획과 다릅니다.")
        statistics_text = self.service.journal.read_artifact(roles["raw/openEMS_stats.txt"]["artifact"]).decode("utf-8")
        values = [float(line.split()[0]) for line in statistics_text.splitlines() if line.strip()]
        maximum_steps = captured["analysis_plan"]["case"]["settings"]["max_timesteps"] if pcb else 20000
        if (len(values) < 6 or not all(math.isfinite(v) for v in values) or values[0] != int(values[0])
                or values[2] != int(values[2]) or not 0 < values[2] < maximum_steps or values[1] <= 0
                or values[0] != captured["preparation"]["mesh_statistics"]["native_grid_points"]):
            raise ProjectError("E_SOLVER", "실제 native 통계가 격자 또는 종료 조건과 다릅니다.")
        statistics = {"native_cells": int(values[0]), "timestep_seconds": values[1], "iterations": int(values[2]), "raw_values": values}
        native_log = self.service.journal.read_artifact(roles["raw/native.log"]["artifact"]).decode("utf-8")
        if pcb:
            statistics = read_statistics_values(statistics_text, maximum_steps)
            termination = check_pcb_termination(native_log, int(values[2]), captured["analysis_plan"]["case"]["settings"])
        else:
            termination = check_termination(native_log, int(values[2]))
        if (statistics != execution.get("statistics") or statistics != result.get("native_statistics")
                or termination != execution.get("termination") or termination != result.get("termination")):
            raise ProjectError("E_HASH", "원시 종료 로그/통계와 정규화 결과의 종료 근거가 다릅니다.")
        if (provenance != result.get("provenance") or provenance.get("run_id") != job["run_id"] or provenance.get("nonce") != captured["nonce"]
                or provenance.get("analysis_plan") != captured["analysis_plan"] or provenance.get("prepared_plan") != captured["prepared_plan"]
                or provenance.get("preparation") != captured["preparation"] or provenance.get("raw_manifest") != manifest
                or result.get("normalization") != captured["analysis_plan"]["normalization"]
                or result.get("mesh_statistics") != captured["preparation"]["mesh_statistics"]):
            raise ProjectError("E_HASH", "정규화 결과의 출처 또는 단위가 계획과 다릅니다.")
        observed = provenance.get("runtime", {})
        if observed.get("manifest_sha256") != captured["runtime"]["manifest_sha256"] or observed.get("code_files") != captured["runtime"]["code_files"] or observed.get("qt_found") is not False:
            raise ProjectError("E_HASH", "결과 런타임 출처가 현재 실행과 다릅니다.")
        samples = result.get("samples", [])
        expected = captured["analysis_plan"]["case"]["frequency_hz"]
        if (type(samples) is not list or len(samples) != expected["count"] or any(
                type(row) is not dict or type(row.get("frequency_hz")) not in (int, float)
                or not math.isfinite(row["frequency_hz"])
                or abs(row["frequency_hz"] - (expected["start"] + index * (expected["stop"] - expected["start"]) / (expected["count"] - 1))) > 1e-5
                for index, row in enumerate(samples))):
            raise ProjectError("E_HASH", "결과 주파수 축이 계획과 다릅니다.")
        if pcb:
            validate_result(captured["analysis_plan"], result, captured["prepared_plan"])
            return
        assessment = assess_samples(samples)
        observed_assessment = result.get("assessment", {})
        observed_metrics = observed_assessment.get("metrics", {})
        metrics_match = observed_metrics.keys() == assessment["metrics"].keys() and all(
            type(observed_metrics[name]) in (int, float) and math.isfinite(observed_metrics[name])
            and math.isclose(value, observed_metrics[name], rel_tol=1e-12, abs_tol=1e-14)
            for name, value in assessment["metrics"].items())
        if not assessment["passed"] or observed_assessment.get("passed") is not True or not metrics_match or result.get("termination", {}).get("status") != "end_criterion_reached":
            raise ProjectError("E_SOLVER", "참조 정확도 또는 정상 종료 기준을 충족하지 못했습니다.")

    def _finish(self, job, process, error=None):
        """! @brief guest 종료를 증명하지 못하면 interrupted와 예약을 남긴다."""
        confirmed = process.get("termination_confirmed") is True and not process.get("outcome_unknown", False)
        def finish(state):
            active = state["jobs"][job["job_id"]]
            if active["solver"]["nonce"] != job["solver"]["nonce"]:
                raise ProjectError("E_CONFLICT", "해석 종료 처리의 소유권이 변경되었습니다.")
            if active["state"] in TERMINAL:
                return
            active["solver"]["resource_reserved"] = not confirmed
            active["solver"]["termination_confirmed"] = confirmed
            active["solver"]["process_outcome"] = {k: process.get(k) for k in ("state", "termination_confirmed", "outcome_unknown")}
            terminal = "interrupted" if not confirmed else ("cancelled" if active["state"] == "cancel_requested" or process.get("state") == "cancelled" else "failed")
            diagnostic = error or ProjectError("E_RESOURCE" if process.get("state") in {"timeout", "output_limit"} else "E_SOLVER", "해석 작업을 완료하지 못했습니다.")
            self.service._event(active, terminal, termination_confirmed=confirmed, outcome_unknown=not confirmed, error=diagnostic.diagnostic())
        self.service.journal.transaction(finish)

    def reconcile(self, job_id):
        """! @brief 이전 실행을 재시작하지 않고 동일 nonce의 guest 종료만 확인한다."""
        job = self.service.journal.read()["jobs"].get(job_id)
        if self.runtime is None or job is None or not job.get("solver", {}).get("resource_reserved") or job["state"] != "interrupted":
            raise ProjectError("E_CONFLICT", "종료 확인이 필요한 이전 해석 실행이 아닙니다.")
        if job["solver"]["runtime"]["transport"] != self.runtime.identity["transport"]:
            raise ProjectError("E_VERSION", "이전 실행의 WSL 소유 설정이 필요합니다.")
        status = self.runtime.transport.cancel(job["run_id"], job["solver"]["nonce"])
        deadline = time.monotonic() + 20
        while status.get("termination_confirmed") is not True and status.get("state") not in TERMINAL | {"timeout", "output_limit"} and time.monotonic() < deadline:
            time.sleep(0.25)
            status = self.runtime.transport.inspect(job["run_id"], job["solver"]["nonce"])
        if status.get("termination_confirmed") is True and not status.get("outcome_unknown", False):
            def release(state):
                active = state["jobs"][job_id]
                active["solver"]["resource_reserved"] = False
                active["solver"]["termination_confirmed"] = True
                active["solver"]["reconciled_at"] = self.service._now()
            self.service.journal.transaction(release)
        return {"job_id": job_id, "state": "interrupted", "termination_confirmed": status.get("termination_confirmed") is True and not status.get("outcome_unknown", False)}

    def result_open(self, params):
        """! @brief 결과 조회는 계산을 시작하지 않고 작은 메타데이터와 파일 참조만 반환한다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        _fields(params["context"], {"project_id"})
        data = _fields(params["input"], {"artifact_id"}, {"selection"})
        _uuid(data["artifact_id"])
        if data.get("selection", "all") not in {"all", "normalized", "raw"}:
            raise ProjectError("E_UNSUPPORTED", "결과 선택은 all/normalized/raw를 지원합니다.")
        state = self.service.journal.read()
        self.service._project(state, params["context"])
        result = state["solver_results"].get(data["artifact_id"])
        if result is None or result["project_id"] != params["context"]["project_id"]:
            raise ProjectError("E_MISSING_ARTIFACT", "프로젝트의 봉인된 결과를 찾을 수 없습니다.")
        files = result["files"] if data.get("selection", "all") == "all" else (result["raw_files"] if data["selection"] == "raw" else [f for f in result["files"] if f["role"] == "normalized_result"])
        return {"artifact_id": result["artifact_id"], "prepared_plan_id": result["prepared_plan_id"], "metadata": deepcopy(result["metadata"]),
                "files": [{"role": f["role"], "media_type": f["media_type"], **deepcopy(f["artifact"])} for f in files]}

    def latest(self, params):
        """! @brief 프로젝트의 마지막 완료 해석만 조회하고 새 계산을 시작하지 않는다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        _fields(params["input"], set())
        state = self.service.journal.read()
        self.service._project(state, params["context"])
        candidates = [job for job in state["jobs"].values() if "solver" in job and job["kind"] == "em_analysis"
                      and job["state"] == "completed" and job["context"] == params["context"]]
        if not candidates:
            return {"profile": "rfad.solver-view/0.1", "job_id": None, "result": None}
        job = max(candidates, key=lambda item: (item["events"][-1]["timestamp"], item["job_id"]))
        return {"profile": "rfad.solver-view/0.1", "job_id": job["job_id"], "result": deepcopy(job["events"][-1]["operation_result"])}

    def samples(self, params):
        """! @brief 봉인된 작은 1-port 결과를 제한된 표시 DTO로 투영한다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        data = _fields(params["input"], {"artifact_id"})
        _uuid(data["artifact_id"])
        state = self.service.journal.read()
        self.service._project(state, params["context"])
        record = state["solver_results"].get(data["artifact_id"])
        if record is None or record["project_id"] != params["context"]["project_id"]:
            raise ProjectError("E_MISSING_ARTIFACT", "프로젝트의 완료 해석 결과가 없습니다.")
        result = json.loads(self.service.journal.read_artifact(record["normalized"]))
        source = result.get("samples")
        if type(source) is not list or not 1 <= len(source) <= 201:
            raise ProjectError("E_RESOURCE", "현재 그래프는 최대 201개 주파수 표본을 지원합니다.")
        samples = []
        previous = 0.0
        for row in source:
            if type(row) is not dict:
                raise ProjectError("E_HASH", "봉인된 표본은 객체여야 합니다.")
            frequency = row.get("frequency_hz")
            pairs = [row.get(key) for key in ("s11", "impedance_ohm")]
            if (type(frequency) not in (int, float) or not math.isfinite(frequency) or frequency <= previous
                    or any(type(pair) is not list or len(pair) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in pair) for pair in pairs)):
                raise ProjectError("E_HASH", "봉인된 표본의 주파수 또는 복소 값이 유효하지 않습니다.")
            magnitude = math.hypot(*pairs[0])
            if not math.isfinite(magnitude):
                raise ProjectError("E_HASH", "S11 크기를 유한 값으로 표시할 수 없습니다.")
            vswr = (1 + magnitude) / (1 - magnitude) if magnitude < 1 else None
            if vswr is not None and not math.isfinite(vswr):
                vswr = None
            samples.append({"frequency_hz": frequency, "s11_db": 20 * math.log10(magnitude) if magnitude > 0 else None,
                "vswr": vswr, "impedance_real_ohm": pairs[1][0], "impedance_imag_ohm": pairs[1][1]})
            previous = frequency
        snapshot = result.get("provenance", {}).get("analysis_plan", {}).get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("project_id") != params["context"]["project_id"]:
            raise ProjectError("E_HASH", "표시 결과의 원본 스냅샷을 확인할 수 없습니다.")
        dto = {"profile": "rfad.solver-chart/0.1", "artifact_id": record["artifact_id"], "snapshot": snapshot,
               "metadata": deepcopy(record["metadata"]), "samples": samples}
        if len(canonical_bytes(dto)) > 60 * 1024:
            raise ProjectError("E_RESOURCE", "해석 그래프 DTO가 전송 상한을 초과했습니다.")
        return dto

    def _loop(self):
        """! @brief 새로운 접수에서만 깨어나며 조정기 실패는 숨기지 않는다."""
        while not self.stop.is_set():
            self.wake.wait()
            self.wake.clear()
            try:
                while not self.stop.is_set() and self.run_next():
                    pass
            except Exception as error:
                self.error = error
                return
