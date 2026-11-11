"""! @brief 해석 작업의 접수, 실행, 취소와 원자 게시 수명을 조정한다."""

from copy import deepcopy
import json
import threading
import time
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.job_state import TERMINAL
from rfad.application.solver import build_analysis_plan, make_prepared_plan, validate_reference_plan
from rfad.application.solver_requests import PCB_PROFILE, SOLVER_METHODS, validate_solver_input
from rfad.application.solver_runtime import SolverRuntime, stage_solver_job
from rfad.application.solver_artifacts import read_solver_result, seal_solver_outputs, check_prepared_outputs, check_solver_result
from rfad.application.solver_queries import open_solver_result, latest_solver_result, solver_samples
from rfad.application.radiation_queries import radiation_chart
from rfad.domain.errors import ProjectError


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
            if self.thread.ident is not None:
                self.thread.join()
            self.thread = None

    @staticmethod
    def validate_input(method, context, data):
        """! @brief 해석 입력 계약의 검증을 명령 모듈에 위임한다."""
        validate_solver_input(method, context, data)

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
        if method != "solver.plan" and data["budget"]["timeout_seconds"] > plan["resource_estimate"]["max_wall_time_seconds"]:
            raise ProjectError("E_RESOURCE", "요청한 실행 시간이 해당 불변 계획의 예산을 초과했습니다.")
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
            stage, request = stage_solver_job(self.service.journal, self.runtime, job)
            process = {"state": "failed", "termination_confirmed": False, "outcome_unknown": True}
            process = self.runtime.transport.execute(stage, run_id=job["run_id"], nonce=job["solver"]["nonce"], cancel=self.cancel,
                                                     timeout_seconds=job["input"]["budget"]["timeout_seconds"], on_state=lambda value: self._progress(job, value))
            if process.get("state") == "failed" and process.get("termination_confirmed") and (stage / "output/result.json").is_file():
                failed = read_solver_result(stage, request).get("error", {})
                raise ProjectError(failed.get("code", "E_SOLVER"), str(failed.get("message_ko", "openEMS worker 실행 실패"))[:2048])
            if process.get("state") != "completed" or not process.get("termination_confirmed") or process.get("outcome_unknown", False):
                self._finish(job, process)
                return True
            package = read_solver_result(stage, request)
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


    def _seal(self, job, stage, package):
        """! @brief 종료된 worker 파일을 불변 저장소로 봉인한다."""
        return seal_solver_outputs(self.service.journal, job, stage, package)

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
            check_prepared_outputs(self.service.journal, captured, preparation, files)
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
            if "radiation_summary" in result:
                result_record["metadata"]["radiation_summary"] = deepcopy(result["radiation_summary"])
                operation["radiation_summary"] = deepcopy(result["radiation_summary"])
        def publish(state):
            active = state["jobs"][job["job_id"]]
            if active["solver"]["nonce"] != captured["nonce"]:
                raise ProjectError("E_CONFLICT", "해석 결과 게시 소유권이 변경되었습니다.")
            if active["state"] in TERMINAL:
                return
            active["solver"]["resource_reserved"] = False
            active["solver"]["termination_confirmed"] = True
            if active["state"] == "cancel_requested":
                self.service._event(active, "cancelled", termination_confirmed=True)
                return
            if self.stop.is_set() or self.cancel.is_set():
                self.service._event(active, "interrupted", termination_confirmed=True, outcome_unknown=False,
                                    reason="서비스 종료 또는 명시적 사용자 요청 외의 중단으로 결과를 게시하지 않았습니다.")
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


    def _check_result(self, job, result, files):
        """! @brief 게시 전 결과 검증 경계를 유지하고 전용 검증 모듈에 위임한다."""
        check_solver_result(self.service.journal, job, result, files)

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
            if not confirmed:
                terminal = "interrupted"
            elif active["state"] == "cancel_requested":
                terminal = "cancelled"
            elif self.stop.is_set() or self.cancel.is_set() or process.get("state") == "cancelled":
                terminal = "interrupted"
            else:
                terminal = "failed"
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
        """! @brief 완료 결과의 파일 참조를 계산 없이 조회한다."""
        return open_solver_result(self.service, params)

    def latest(self, params):
        """! @brief 현재 프로젝트의 마지막 완료 결과를 조회한다."""
        return latest_solver_result(self.service, params)

    def samples(self, params):
        """! @brief 봉인 표본을 제한된 화면 DTO로 투영한다."""
        return solver_samples(self.service, params)

    def radiation(self, params):
        """! @brief 계산을 시작하지 않고 봉인된 방사 페이지를 조회한다."""
        return radiation_chart(self.service, params)

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
