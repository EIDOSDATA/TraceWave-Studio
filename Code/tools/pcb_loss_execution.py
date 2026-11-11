"""! @brief 종료 확인된 실패를 보존하고 독립 손실 사례의 명시적 후속 실행을 지원한다."""

from copy import deepcopy
import time

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_loss_study import assess
from rfad.application.radiation_study import require
from verify_openems_worker import call
from verify_ifa_convergence import execute_phase, save_report
from radiation_convergence.evidence import reference


def blocked_job(service, entry):
    """! @brief 소유 native의 확정 종료/슬롯 반환이 있는 실패만 후속 독립 실행에서 건너뛴다."""
    state = service.journal.read()
    for phase in ("analysis", "prepare"):
        task = entry.get("phases", {}).get(phase, {}).get("task")
        if task is None:
            continue
        job = state["jobs"].get(task["job_id"])
        require(job is not None, "원래 손실 연구 작업이 journal에 없습니다.")
        if job["state"] in {"failed", "cancelled", "interrupted"}:
            event = job["events"][-1]
            require(event.get("termination_confirmed") is True and not event.get("outcome_unknown", False)
                    and not job["solver"].get("resource_reserved"), "실패한 native의 종료/슬롯 반환이 확인되지 않았습니다.")
            return {"job_id": job["job_id"], "run_id": job["run_id"], "state": job["state"], "terminal_event": deepcopy(event)}
    return None


def execute_case(service, report, path, entry, subject):
    """! @brief 같은 요청 키를 재조회하며 실패한 계산의 대체 시도를 만들지 않는다."""
    started = time.monotonic()
    prepared = execute_phase(service, report, path, entry, "prepare", "solver.prepare", {
        "analysis_plan": {name: entry["analysis_plan"][name] for name in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 300}}, subject["context"])
    solved = execute_phase(service, report, path, entry, "analysis", "job.submit", {
        "task_plan": {"kind": "em_analysis", "prepared_plan": {name: prepared["prepared_plan"][name] for name in ("prepared_plan_id", "content_hash")}, "execution_mode": "solve_and_postprocess"},
        "budget": {"timeout_seconds": 300}}, subject["context"])
    opened = call(service, "result.open", {"artifact_id": solved["artifact_id"]}, subject["context"])
    roles = {item["role"]: item for item in opened["files"]}
    entry.update(status="completed", artifact_id=solved["artifact_id"], elapsed_seconds=time.monotonic() - started,
                 **{role: reference(roles[role]) for role in ("normalized_result", "radiation_result", "power_balance_result")})
    save_report(path, report)


def assess_available(study, runs):
    """! @brief 실패한 수준은 미확립으로 남기고 완료한 독립 축만 별도로 판정한다."""
    powers = {key: entry["power_balance"] for key, entry in runs.items() if entry["status"] == "completed"}
    if len(powers) == len(runs):
        return assess(study, powers)
    axes = {}
    for axis in sorted({case["axis"] for case in study["cases"]}):
        cases = [case for case in study["cases"] if case["axis"] == axis]
        missing = [case["label"] for case in cases if canonical_hash(case["settings"]) not in powers]
        if missing:
            axes[axis] = {"status": "not_established", "reason": "native_cases_not_completed", "missing_cases": missing,
                          "minimum_levels_met": False, "comparisons": []}
        else:
            axes[axis] = assess({**study, "cases": cases}, powers)["axes"][axis]
    return {"schema": "rfad.pcb-loss-study-assessment/0.1", "study_hash": canonical_hash(study), "axes": axes,
            "status": "not_established", "individual_loss_stability": "not_established", "full_energy_closure": "not_established",
            "scope": "tested_settings_only_not_continuum_accuracy", "physics_validated": False,
            "fabrication_validated": False, "measurement_validated": False}
