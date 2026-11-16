"""! @brief 후보를 하나씩 구체화하고 기존 단일 solver 슬롯과 외부 회로 계산을 조정한다."""

from copy import deepcopy
import os
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.design_sweep_store import (
    ACTIVE, candidate_source, folder, load_candidate, load_definition, publish_candidate,
    read_json, seal_result,
)
from rfad.application.job_state import TERMINAL
from rfad.domain.errors import ProjectError


def _charge(service, study):
    """! @brief 활성 시간은 중간 단계와 재개 사이에 초기화하지 않고 누적한다."""
    now = service._now()
    if study["active_since"] is not None:
        study["usage"]["wall_seconds"] += max(0.0, now - study["active_since"])
    study["active_since"] = now if study["state"] in ACTIVE else None


def _bucket(candidate):
    """! @brief 재개 가능한 중단 후보는 완료로 세지 않고 대기 개수를 유지한다."""
    value = "planned" if candidate is None else candidate["state"]
    return value if value in {"completed", "failed", "running", "skipped"} else "pending"


def _current(state, study):
    """! @brief 느린 계산 사이에 취소/재개된 세대와 후보를 덮어쓰지 않는다."""
    current = state["sweeps"][study["study_id"]]
    if (current["generation"] != study["generation"] or current["state"] not in ACTIVE
            or current["next_index"] != study["next_index"]
            or current["records"].get(str(study["next_index"])) != study["records"].get(str(study["next_index"]))):
        raise ProjectError("E_CONFLICT", "연구 제어 또는 후보 기록이 변경되었습니다.", details={"stale_sweep": True})
    return current


def _save(service, state, study, previous, candidate):
    """! @brief 후보 참조와 개수를 같은 journal commit에서 바꾼다."""
    study["counts"][_bucket(previous)] -= 1
    study["counts"][_bucket(candidate)] += 1
    publish_candidate(service, state, study, candidate)


def _budget(study, definition, *, disk=0, ram=0, solves=0, retaining=False):
    """! @brief 추정 RAM 예약과 누적 실행/보존 비용을 실제 측정 수용과 구분한다."""
    budget, usage = definition["specification"]["budget"], study["usage"]
    if not retaining and usage["wall_seconds"] >= budget["wall_seconds"]:
        raise ProjectError("E_RESOURCE", "누적 실행 시간 예산을 소진했습니다.")
    if usage["disk_bytes"] + disk > budget["disk_bytes"]:
        raise ProjectError("E_RESOURCE", "원본/계획/작업/결과 보존 디스크 예산을 초과합니다.")
    if ram > budget["ram_bytes"]:
        raise ProjectError("E_RESOURCE", "후보의 초기 RAM 추정치가 예약 예산을 초과합니다. 실제 peak 측정값은 아닙니다.")
    if usage["native_solves"] + solves > budget["max_native_solves"]:
        raise ProjectError("E_RESOURCE", "native 해석 접수 시도 예산을 소진했습니다.")


def _tree_bytes(path):
    """! @brief 소유 작업 폴더의 실제 파일 크기를 세며 외부 링크를 따라가지 않는다."""
    if not path.exists():
        return 0
    total = 0
    for current, directories, files in os.walk(path, followlinks=False):
        from pathlib import Path
        for item in [Path(current), *[Path(current) / name for name in directories + files]]:
            status = item.lstat()
            if item.is_symlink() or getattr(status, "st_file_attributes", 0) & 0x400:
                raise ProjectError("E_HASH", "연구 작업 저장 영역에 링크 또는 Windows 재분석 지점이 있습니다.")
        total += sum((Path(current) / name).stat().st_size for name in files)
    return total


def _job_bytes(service, state, job):
    """! @brief source/capture, staging 복사본과 봉인 결과를 모두 누적 사용량에 포함한다."""
    root = state["projects"][job["context"]["project_id"]]["path"]
    paths = (root + "/solver-inputs/" + job["run_id"], "solver-staging/" + job["run_id"],
             "solver-artifacts/" + job["run_id"])
    return sum(_tree_bytes(service.journal._safe_path(path)) for path in paths)


def _guest_bytes(attempt, job):
    """! @brief guest 사용량이 불명이면 처음 예약한 최대 논리 바이트를 유지한다."""
    process = job.get("solver", {}).get("process_outcome", {})
    guest = process.get("guest_disk_bytes")
    if type(guest) is int and guest >= 0:
        basis = "observed_logical_bytes"
    elif job["state"] == "queued" or process.get("not_started") is True:
        guest, basis = 0, "not_started"
    else:
        guest, basis = attempt.get("guest_reserved_bytes", 0), "conservative_reservation"
    return guest, basis


def _account_attempt(service, state, study, candidate, job, actual=None):
    """! @brief 동일 시도는 증가한 파일 바이트만 청구하고 삭제로 예산을 환급하지 않는다."""
    attempt = next(item for item in candidate["attempts"] if item["job_id"] == job["job_id"])
    actual = _job_bytes(service, state, job) if actual is None else actual
    charged = attempt.get("disk_accounted_bytes", 0)
    study["usage"]["disk_bytes"] += max(0, actual - charged)
    attempt["disk_accounted_bytes"] = max(actual, charged)
    guest, basis = _guest_bytes(attempt, job)
    old_guest = attempt.get("guest_disk_accounted_bytes", 0)
    delta = max(0, guest - old_guest)
    study["usage"]["disk_bytes"] += delta
    study["usage"]["guest_disk_bytes"] = study["usage"].get("guest_disk_bytes", 0) + delta
    attempt.update(guest_disk_accounted_bytes=max(guest, old_guest), guest_usage_basis=basis if guest >= old_guest else "conservative_retained")


def _initial(source):
    """! @brief 원문/값/순번만 후보 기록에 두고 원본 프로젝트 본문은 반복 저장하지 않는다."""
    return {"ordinal": source["ordinal"], "indices": source["indices"], "values": source["values"],
            "evaluation_key": source["evaluation_key"], "validation_status": source["status"],
            "state": "planned", "phase": "materialize", "outcome": "not_evaluated",
            "diagnostics": source["diagnostics"], "attempts": [], "results": {},
            "convergence_state": "not_established", "physics_validated": False}


def _reject(service, study, definition, previous, candidate, error=None):
    """! @brief 기하/지원 범위 실패 후보를 순번과 원인 그대로 남기고 다음 후보로 진행한다."""
    if error is not None:
        candidate["diagnostics"].append(error.diagnostic())
        candidate["validation_status"] = "unsupported" if error.code in {"E_UNSUPPORTED", "E_VERSION"} else "invalid"
    unsupported = candidate["validation_status"] == "unsupported"
    geometry_error = any(item.get("code") == "E_GEOMETRY" for item in candidate["diagnostics"])
    candidate.update(state="skipped" if unsupported else "failed", phase="done",
                     outcome="unsupported" if unsupported else "invalid_geometry" if geometry_error else "invalid_input")
    def reject(state):
        """! @brief 취소가 먼저 확정한 경우 새 후보를 진행하지 않는다."""
        current = _current(state, study)
        _charge(service, current)
        if current["state"] != "cancel_requested":
            _budget(current, definition, disk=len(canonical_bytes({**candidate, "study_id": study["study_id"]})))
            _save(service, state, current, previous, candidate)
            current["next_index"] += 1
    service.journal.transaction(reject)


def _assess(source, definition, dataset, metrics=None):
    """! @brief 명시 대응이 없는 목표는 미평가로 보존하고 실제 표본만 평가한다."""
    from rfad.application.network_candidates import resolved_target
    from rfad.domain.network_assessment import evaluate_target

    spec, document = definition["specification"], source["document"]
    contexts = {item["target_id"]: item["context"] for item in spec["target_contexts"]}
    results = []
    for identity in spec["target_ids"]:
        target = next(item for item in document["targets"] if item["id"] == identity)
        context = contexts.get(identity)
        if context is None or context["target_port_id"] != target["port_id"]:
            result = {"target_id": identity, "target_revision_id": target["revision_id"],
                      "status": "not_evaluated", "criteria": [], "continuous_band_verified": False,
                      "physics_validated": False, "reason": "목표와 자료의 명시 포트/기준면 대응이 없습니다."}
        else:
            try:
                result = evaluate_target(resolved_target(document, target), dataset, context, metrics=metrics)
            except ProjectError as error:
                result = {"target_id": identity, "target_revision_id": target["revision_id"],
                          "status": "not_evaluated", "criteria": [], "continuous_band_verified": False,
                          "physics_validated": False, "diagnostic": error.diagnostic()}
        result["evidence"] = {"target_original": deepcopy(target), "project_revision": document["revision_id"],
                              "context": deepcopy(context), "dataset_hash": canonical_hash(dataset)}
        results.append(result)
    return {"schema": "rfad.sweep-assessments/0.1", "assessments": results,
            "continuous_band_verified": False, "physics_validated": False}


def _completed(service, study, definition, previous, candidate, source, dataset, diagnostics, *, metrics=None, job=None, extra_payloads=None):
    """! @brief 계산 결과와 목표 원문을 봉인한 뒤 취소 경합 없이 완료 후보를 게시한다."""
    assessment = _assess(source, definition, dataset, metrics)
    payloads = {"dataset": canonical_bytes(dataset), "assessment": canonical_bytes(assessment),
                "diagnostics": canonical_bytes({"schema": "rfad.sweep-diagnostics/0.1", "items": diagnostics})}
    if metrics is not None:
        payloads["metrics"] = canonical_bytes(metrics)
    payloads.update(extra_payloads or {})
    size = sum(len(value) for value in payloads.values())
    actual = None if job is None else _job_bytes(service, service.journal.read(), job)
    extra = 0 if job is None else (max(0, actual - candidate["attempts"][-1].get("disk_accounted_bytes", 0))
        + max(0, _guest_bytes(candidate["attempts"][-1], job)[0] - candidate["attempts"][-1].get("guest_disk_accounted_bytes", 0)))
    _budget(study, definition, disk=size + extra + len(canonical_bytes(candidate)) + 4096, retaining=True)
    candidate["results"] = {**candidate["results"], **seal_result(service, study, candidate["ordinal"], payloads)}
    candidate.update(state="completed", phase="done", outcome="evaluated" if any(
        row["status"] != "not_evaluated" for row in assessment["assessments"]) else "not_evaluated")
    def publish(state):
        """! @brief 별도 network 자료 목록에 자동 등록하지 않고 연구 결과로만 남긴다."""
        current = _current(state, study)
        _charge(service, current)
        if job is not None:
            _account_attempt(service, state, current, candidate, job, actual)
        _budget(current, definition, disk=size + len(canonical_bytes(candidate)) + 4096, retaining=True)
        current["usage"]["disk_bytes"] += size
        if current["state"] == "cancel_requested":
            candidate.update(state="cancelled", phase="results_ready")
        _save(service, state, current, previous, candidate)
        current["current_job_id"] = None
        if current["state"] != "cancel_requested":
            current["next_index"] += 1
            current["physical_cache"][candidate["evaluation_key"]] = candidate["ordinal"]
        current["message"] = "후보 계산과 표본 평가를 보존했습니다. 수렴/제작/실측 수용은 별개입니다."
        if current["usage"]["wall_seconds"] >= definition["specification"]["budget"]["wall_seconds"]:
            current.update(state="blocked", active_since=None, stop_reason="누적 실행 시간 예산 초과",
                           message="완료된 계산 근거를 보존했으나 누적 시간 예산을 초과해 연구를 중단했습니다.")
    service.journal.transaction(publish)


def _materialize(service, study, definition, previous):
    """! @brief 필요한 후보 하나의 원본과 계획만 만들고 동일 물리 입력은 검증 후 재사용한다."""
    source = candidate_source(service, study, study["next_index"])
    candidate = _initial(source) if previous is None else deepcopy(previous)
    if candidate["phase"] == "results_ready":
        dataset = read_json(service, candidate["results"]["dataset"])
        metrics = read_json(service, candidate["results"]["metrics"]) if "metrics" in candidate["results"] else None
        diagnostics = read_json(service, candidate["results"]["diagnostics"])["items"]
        _completed(service, study, definition, previous, candidate, source, dataset,
                   [*diagnostics, {"code": "I_RETAINED", "native_reexecuted": False}], metrics=metrics)
        return
    if source["status"] != "valid":
        _reject(service, study, definition, previous, candidate)
        return
    cached_index = study["physical_cache"].get(source["evaluation_key"])
    if cached_index is not None:
        cached = load_candidate(service, study, cached_index)
        if cached["state"] != "completed" or cached["evaluation_key"] != source["evaluation_key"]:
            raise ProjectError("E_HASH", "재사용할 후보의 완료 상태 또는 물리 입력이 다릅니다.")
        dataset = read_json(service, cached["results"]["dataset"])
        metrics = read_json(service, cached["results"]["metrics"]) if "metrics" in cached["results"] else None
        diagnostics = read_json(service, cached["results"]["diagnostics"])["items"]
        candidate["results"] = deepcopy(cached["results"])
        candidate["cached_from_ordinal"] = cached_index
        candidate["convergence_state"] = cached["convergence_state"]
        _completed(service, study, definition, previous, candidate, source, dataset,
                   [*diagnostics, {"code": "I_REUSED", "source_ordinal": cached_index, "original_candidate_preserved": True}], metrics=metrics)
        return
    if study["type"] == "circuit_sweep":
        from rfad.domain.network_circuit import apply_circuit
        original = read_json(service, definition["network"]["dataset"])
        _budget(study, definition, ram=4 * len(canonical_bytes(original)) + 32 * 1024**2)
        try:
            derived = apply_circuit(original, source["circuit"])
        except ProjectError as error:
            if error.code in {"E_CONFLICT", "E_UNSUPPORTED", "E_GEOMETRY", "E_SCHEMA"}:
                _reject(service, study, definition, previous, candidate, error)
                return
            raise
        _completed(service, study, definition, previous, candidate, source, derived["dataset"], derived["diagnostics"])
        return
    from rfad.application.pcb_solver import build_pcb_plan
    document = source["document"]
    raw = canonical_bytes(document)
    snapshot = {**deepcopy(definition["snapshot"]), "snapshot_id": str(uuid4()),
                "revision_id": document["revision_id"], "content_hash": canonical_hash(document),
                "description": "스윕 후보 " + str(candidate["ordinal"] + 1), "sealed_at": service._now()}
    # @brief 계획 생성 전 예상 참조로 순수 검증하고, 실제 바이트는 자원 검사 후 봉인한다.
    import hashlib
    path = folder(service, study) + "/sources/" + snapshot["snapshot_id"] + ".json"
    snapshot["artifact"] = {"uri": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    try:
        plan = build_pcb_plan(document, snapshot, definition["runtime_identity"], source["settings"])
    except ProjectError as error:
        _reject(service, study, definition, previous, candidate, error)
        return
    encoded = canonical_bytes(plan)
    _budget(study, definition, disk=len(raw) + len(encoded) + 8192,
            ram=plan["resource_estimate"]["estimated_memory_bytes"])
    snapshot["artifact"] = service.journal.put_immutable(path, raw)
    reference = service.journal.put_immutable(folder(service, study) + "/plans/" + plan["plan_id"] + ".json", encoded)
    candidate.update(phase="prepare", snapshot=snapshot,
        analysis_plan={"plan_id": plan["plan_id"], "content_hash": canonical_hash(plan), "artifact": reference},
        resource_estimate=plan["resource_estimate"])
    def publish(state):
        """! @brief 생성 중 취소되면 새 해석을 접수하지 않는다."""
        current = _current(state, study)
        _charge(service, current)
        _budget(current, definition, disk=len(raw) + len(encoded) + len(canonical_bytes(candidate)) + 4096)
        current["usage"]["disk_bytes"] += len(raw) + len(encoded)
        state["analysis_plans"][plan["plan_id"]] = {"project_id": study["project_id"], "reference": candidate["analysis_plan"]}
        _save(service, state, current, previous, candidate)
    service.journal.transaction(publish)


def _admit(service, study, definition, candidate):
    """! @brief 시간/RAM/디스크/해석 횟수를 예약한 경우에만 기존 solver에 한 단계를 접수한다."""
    phase, estimate = candidate["phase"], candidate["resource_estimate"]
    runtime = service.solver.runtime
    if runtime is None or runtime.identity != definition["runtime_identity"]:
        raise ProjectError("E_VERSION", "고정한 해석 runtime이 없거나 변경되었습니다.")
    guest_reservation = (estimate["max_output_bytes"] + len(runtime.source_bytes)
                         + len(runtime.manifest_bytes) + candidate["analysis_plan"]["artifact"]["bytes"] + 1024**2)
    prepared_inputs = 0
    if phase == "solve":
        prepared = service.journal.read()["prepared_plans"][candidate["prepared_plan"]["prepared_plan_id"]]
        prepared_inputs = sum(item["artifact"]["bytes"] for item in prepared["files"])
        guest_reservation += prepared_inputs
    reservation = (2 * estimate["max_output_bytes"] + 2 * len(runtime.source_bytes)
                   + 2 * len(runtime.manifest_bytes) + 2 * candidate["analysis_plan"]["artifact"]["bytes"] + 1024**2
                   + guest_reservation + prepared_inputs)
    def admit(state):
        """! @brief 기존 연구와 새 스윕이 같은 예약 슬롯을 공유하도록 원자 접수한다."""
        current = _current(state, study)
        _charge(service, current)
        if current["state"] == "cancel_requested":
            return
        if any(job.get("solver", {}).get("resource_reserved") for job in state["jobs"].values()):
            return
        _budget(current, definition, disk=reservation, ram=estimate["estimated_memory_bytes"], solves=int(phase == "solve"))
        remaining = definition["specification"]["budget"]["wall_seconds"] - current["usage"]["wall_seconds"]
        timeout = min(remaining, estimate["max_wall_time_seconds"])
        if phase == "prepare":
            method, data = "solver.prepare", {"analysis_plan": {key: candidate["analysis_plan"][key] for key in ("plan_id", "content_hash")}}
        else:
            method, data = "job.submit", {"task_plan": {"kind": "em_analysis", "execution_mode": "solve_and_postprocess",
                "prepared_plan": {key: candidate["prepared_plan"][key] for key in ("prepared_plan_id", "content_hash")}}}
        data["budget"] = {"timeout_seconds": timeout}
        task = service.solver.admit(state, method, {"project_id": study["project_id"]}, data, compact=True)
        output = deepcopy(candidate)
        output.update(state="running")
        output["attempts"].append({"phase": phase, "job_id": task["job_id"], "disk_accounted_bytes": 0,
                                   "guest_reserved_bytes": guest_reservation, "guest_disk_accounted_bytes": 0})
        if len(output["attempts"]) > 256:
            raise ProjectError("E_RESOURCE", "후보별 실행 시도 보존 상한에 도달했습니다.")
        current["usage"]["native_solves"] += int(phase == "solve")
        _account_attempt(service, state, current, output, state["jobs"][task["job_id"]])
        _save(service, state, current, candidate, output)
        current.update(current_job_id=task["job_id"], state="running", message="후보의 " + phase + " 단계를 실행 중입니다.")
    service.journal.transaction(admit)
    service.solver.wake.set()


def _collect(service, study, definition, candidate, job):
    """! @brief 완료 단계와 중단 시도를 보존하며 재개에서만 미완료 단계를 다시 허용한다."""
    output = deepcopy(candidate)
    if job["state"] == "completed" and candidate["phase"] == "solve":
        from rfad.application.network_solver_import import solver_dataset, radiation_metrics
        result = job["events"][-1]["operation_result"]
        source = candidate_source(service, study, candidate["ordinal"])
        state = service.journal.read()
        dataset, raw = solver_dataset(service, state, source["document"], result["artifact_id"])
        output["solver_result_id"] = result["artifact_id"]
        output["convergence_state"] = "solver_end_criterion_only"
        record = state["solver_results"][result["artifact_id"]]
        project = state["projects"][study["project_id"]]
        # @brief 임시 읽기 전용 참조로 공통 방사 투영을 재사용하고 원문은 아래 결과와 함께 봉인한다.
        proxy_project = {**project, "path": record["normalized"]["uri"].rsplit("/", 1)[0]}
        metrics = radiation_metrics(service, proxy_project, {"kind": "solver", "raw": record["normalized"]}, dataset)
        output["solver_normalized"] = record["normalized"]
        _completed(service, study, definition, candidate, output, source, dataset, [], metrics=metrics, job=job,
                   extra_payloads={"solver_original": raw})
        return
    actual = _job_bytes(service, service.journal.read(), job)
    def collect(state):
        """! @brief guest 종료 미확인 상태에서는 예약과 현재 작업을 그대로 유지한다."""
        current = _current(state, study)
        _charge(service, current)
        _account_attempt(service, state, current, output, job, actual)
        if job["state"] == "completed":
            output.update(state="planned", phase="solve", prepared_plan=job["events"][-1]["operation_result"]["prepared_plan"])
            current["current_job_id"] = None
        elif current["state"] == "resuming" and not job["solver"].get("resource_reserved"):
            output["state"] = "planned"
            current.update(current_job_id=None, state="running")
        else:
            output.update(state="cancelled" if current["state"] == "cancel_requested" else "failed", outcome="solver_failed")
            diagnostic = job["events"][-1].get("error", {"code": "E_SOLVER", "state": job["state"]})
            output["diagnostics"].append(diagnostic)
            if diagnostic.get("details", {}).get("convergence_state") == "not_converged":
                output.update(outcome="nonconverged", convergence_state="not_converged")
            current.update(state="blocked" if current.get("stop_reason") else "cancelled" if current["state"] == "cancel_requested" else job["state"],
                           active_since=None, message="실행 시도를 보존했습니다. 실제 종료와 원본 검증 후 명시적으로 재개하십시오.")
        _save(service, state, current, candidate, output)
    service.journal.transaction(collect)


def _stop(service, study, error):
    """! @brief 자원/출처 오류 뒤 새 후보를 만들지 않고 실행 중 guest의 종료를 요청한다."""
    def stop(state):
        """! @brief 세대가 바뀐 연구에는 이전 계산 오류를 게시하지 않는다."""
        current = state["sweeps"][study["study_id"]]
        if current["generation"] != study["generation"] or current["state"] not in ACTIVE:
            return
        _charge(service, current)
        current.update(stop_reason=str(error)[:2048], message=str(error)[:2048])
        job = state["jobs"].get(current["current_job_id"])
        if job is not None and job["state"] not in TERMINAL:
            service.solver.cancel_job(job, "연구 자원 또는 원본 검증 실패")
            current["state"] = "cancel_requested"
        else:
            current.update(state="blocked", active_since=None)
    service.journal.transaction(stop)


def run_next(service, stop_event):
    """! @brief 공유 StudyCoordinator 잠금 아래에서 후보의 한 단계만 처리한다."""
    if stop_event.is_set():
        return False
    state = service.journal.read()
    study = next((item for item in state.get("sweeps", {}).values() if item["state"] in ACTIVE), None)
    if study is None:
        return False
    try:
        definition = load_definition(service, study)
        job = state["jobs"].get(study["current_job_id"])
        if job is not None and study["state"] == "resuming" and job["solver"].get("resource_reserved"):
            service.solver.reconcile(job["job_id"])
            job = service.journal.read()["jobs"][job["job_id"]]
            if job["solver"].get("resource_reserved"):
                raise ProjectError("E_CONFLICT", "이전 guest 종료가 확인되지 않아 새 계산을 시작할 수 없습니다.")
        if job is not None and job["state"] not in TERMINAL:
            elapsed = 0 if study["active_since"] is None else max(0, service._now() - study["active_since"])
            if study["usage"]["wall_seconds"] + elapsed >= definition["specification"]["budget"]["wall_seconds"]:
                _stop(service, study, ProjectError("E_RESOURCE", "실행 시간 예산을 소진하여 현재 guest의 종료를 요청했습니다."))
            return False
        if job is None and study["state"] != "cancel_requested" and study["type"] != "circuit_sweep" and any(
                item.get("solver", {}).get("resource_reserved") for item in state["jobs"].values()):
            elapsed = 0 if study["active_since"] is None else max(0, service._now() - study["active_since"])
            if study["usage"]["wall_seconds"] + elapsed >= definition["specification"]["budget"]["wall_seconds"]:
                _stop(service, study, ProjectError("E_RESOURCE", "해석 슬롯 대기 중 누적 시간 예산을 소진했습니다."))
            return False
        if study["next_index"] >= study["counts"]["total"] or (study["state"] == "cancel_requested" and job is None):
            def finish(current_state):
                """! @brief 완료/취소를 물리 검증 수용으로 승격하지 않는다."""
                current = _current(current_state, study)
                _charge(service, current)
                current.update(state="blocked" if current.get("stop_reason") else "cancelled" if current["state"] == "cancel_requested" else "completed",
                               active_since=None, message="완료 결과와 미평가/실패 근거를 보존했습니다. 제작/측정 검증은 미확립입니다.")
            service.journal.transaction(finish)
            return True
        candidate = load_candidate(service, study, study["next_index"])
        if job is not None:
            _collect(service, study, definition, candidate, job)
        else:
            _charge(service, study)
            _budget(study, definition)
            if study["state"] == "resuming":
                def resume(current_state):
                    current = _current(current_state, study)
                    current["state"] = "running"
                service.journal.transaction(resume)
                study["state"] = "running"
            if candidate is None or candidate["phase"] in {"materialize", "circuit", "results_ready"}:
                _materialize(service, study, definition, candidate)
            else:
                _admit(service, study, definition, candidate)
        return True
    except ProjectError as error:
        if error.details.get("stale_sweep") is not True:
            _stop(service, study, error)
        return False
    except Exception as error:
        _stop(service, study, ProjectError("E_RESOURCE" if isinstance(error, OSError) else "E_SCHEMA", str(error)[:2048]))
        return False
