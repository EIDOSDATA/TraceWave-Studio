"""! @brief 유한 검증 예산 안에서 기존 solver 작업을 한 단계씩 명시 접수한다."""

from rfad.application.rf_reference_contract import PROFILE as REFERENCE_PROFILE
from rfad.application.rf_validation_records import PHASES, fail, load_json, phase_status
from rfad.application.solver_requests import validate_solver_input


def _reference(value, key):
    """! @brief 등록된 계획의 식별자와 해시만 기존 solver 접수에 넘긴다."""
    return {key: value[key], "content_hash": value["content_hash"]}


def _completed(phases, phase):
    """! @brief 미확인/실패 작업을 자동 재시도하거나 다음 단계로 넘기지 않는다."""
    if phase not in phases or phases[phase]["state"] != "completed" or phases[phase]["resource_reserved"]:
        fail("선행 단계의 성공과 실행 종료를 먼저 확인해야 합니다.", "E_CONFLICT")
    return phases[phase]["operation_result"]


def advance(service, state, record, data):
    """! @brief 같은 영속 예산과 고정 runtime으로 단계당 최대 한 번만 실행한다."""
    plan = load_json(service, record["definition"])
    if record["cancelled"]:
        fail("취소한 캠페인은 자동 재개하지 않습니다.", "E_CONFLICT")
    runtime = service.solver.runtime
    if runtime is None or plan["runtime_identity"] != runtime.identity:
        fail("검토 시 고정한 실행 환경이 없거나 바뀌었습니다.", "E_VERSION")
    case = next((item for item in plan["cases"] if item["case_id"] == data["case_id"]), None)
    if case is None:
        fail("고정 캠페인에 없는 사례입니다.")
    if case["blocked_reason"] is not None:
        fail("실행 전에 차단된 사례입니다: " + case["blocked_reason"], "E_UNSUPPORTED")
    phase = data["phase"]
    phases = phase_status(state, record, case["case_id"])
    if phase in phases:
        fail("이미 접수한 검증 단계를 다시 실행할 수 없습니다.", "E_CONFLICT")
    position = PHASES.index(phase)
    if position:
        _completed(phases, PHASES[position - 1])
    if phase == "solve":
        # @brief 동일 군의 모든 수준이 실제 준비 검증을 마친 뒤에만 첫 FDTD를 허용한다.
        for other in plan["cases"]:
            if other["group"] == case["group"] and other["blocked_reason"] is None:
                _completed(phase_status(state, record, other["case_id"]), "prepare")
    now = service._now()
    started = now if record["started_at"] is None else record["started_at"]
    timeout = 0 if phase == "plan" else case["analysis_seconds"] if phase == "solve" else 120
    reservation = 0 if phase == "plan" else timeout + 60
    if now - started + reservation > plan["budget"]["wall_seconds"]:
        fail("중단 시간을 포함한 캠페인 벽시계 예산이 부족합니다.", "E_RESOURCE")
    increments = {"native_solves": int(phase == "solve"), "worker_calls": int(phase != "plan"),
                  "analysis_seconds": timeout if phase == "solve" else 0,
                  "worker_reserved_seconds": reservation,
                  "disk_bytes": (8 if phase == "plan" else 672) * 1024**2}
    # @brief native 단계는 host/guest 입력 2개와 출력/봉인 3개 각 128 MiB 및 소스/명세 32 MiB를 예약한다.
    # @brief host 계획도 소스/manifest 캡처 8 MiB를 예약하며 실패와 재개 후에도 예약을 환급하지 않는다.
    for key, increment in increments.items():
        if record["usage"][key] + increment > plan["budget"][key]:
            fail("누적 검증 예산이 부족합니다: " + key, "E_RESOURCE")
    context = {"project_id": record["project_id"]}
    if phase == "plan":
        method = "solver.plan"
        request = {"snapshot": _reference(record["snapshot"], "snapshot_id"),
                   "analysis_profile": REFERENCE_PROFILE, "runtime_profile": runtime.identity["runtime_profile"],
                   "settings": case["settings"]}
    elif phase == "prepare":
        method = "solver.prepare"
        request = {"analysis_plan": _reference(_completed(phases, "plan")["analysis_plan"], "plan_id"),
                   "budget": {"timeout_seconds": timeout}}
    else:
        method = "job.submit"
        task = {"kind": "em_analysis",
                "prepared_plan": _reference(_completed(phases, "prepare")["prepared_plan"], "prepared_plan_id"),
                "execution_mode": "solve_and_postprocess" if phase == "solve" else "postprocess_only"}
        if phase == "postprocess":
            task["raw_result_id"] = _completed(phases, "solve")["artifact_id"]
        request = {"task_plan": task, "budget": {"timeout_seconds": timeout}}
    validate_solver_input(method, context, request)
    submitted = service.solver.admit(state, method, context, request, compact=phase != "plan")
    record["jobs"].setdefault(case["case_id"], {})[phase] = submitted["job_id"]
    record["started_at"] = started
    for key, increment in increments.items():
        record["usage"][key] += increment
    return {"validation_id": record["validation_id"], "case_id": case["case_id"], "phase": phase, **submitted}
