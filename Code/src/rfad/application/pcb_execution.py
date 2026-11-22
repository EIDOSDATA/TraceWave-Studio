"""! @brief PCB 계산의 사전 추정, 실제 측정과 종료 근거를 같은 범위로 비교한다."""

from bisect import bisect_left, bisect_right
import math
import re

from rfad.domain.errors import ProjectError

SCHEMA = "rfad.pcb-execution-cost/0.1"
NATIVE_SCOPE = "openems_process_wall_and_peak_rss"


def estimate(plan, lines):
    """! @brief 최대 단계의 계산량과 기록 면 크기를 사용한 결정적 초기 추정이다."""
    case = plan["case"]
    resource = plan["resource_estimate"]
    steps = case["settings"]["max_timesteps"]
    work = resource["estimated_grid_points"] * steps
    # @brief 배포 전 원호/IFA WSL2의 4스레드 기록 범위를 바깥으로 반올림한 참조 처리율이다.
    scale = min(case["num_threads"], 4) / 4
    rates = [17_000_000 * scale, 51_000_000 * scale]
    raw_bytes = 64 * 1024 + 8 * steps + 24 * sum(map(len, lines.values()))
    radiation = case.get("radiation_recording")
    if radiation is not None:
        counts = [bisect_right(lines[axis], high) - bisect_left(lines[axis], low)
                  for axis, low, high in zip("xyz", radiation["start_mm"], radiation["stop_mm"])]
        x, y, z = counts
        raw_bytes += 12 * 16 * 1024 + 4 * (x * y + y * z + x * z) * 24 * len(radiation["frequency_hz"])
    if "loss_recording" in case:
        raw_bytes += case["loss_recording"]["estimated_field_bytes"] + 3 * 16 * 1024
    return {"schema": SCHEMA, "time_basis": "reference_throughput_at_max_timesteps",
            "wall_seconds_low": work / rates[1], "wall_seconds_high": work / rates[0],
            "memory_bytes": resource["estimated_memory_bytes"], "raw_output_bytes": raw_bytes,
            "max_timesteps": steps, "num_threads": case["num_threads"],
            "plan_wall_limit_seconds": resource["max_wall_time_seconds"],
            "package_limit_bytes": resource["max_output_bytes"]}


def _time(value):
    """! @brief 유한한 관측 시간만 비교에 사용한다."""
    if type(value) in (int, float) and 0 <= value <= 86400 and math.isfinite(value):
        return value
    return None


def _bytes(value):
    """! @brief 없는 값과 관측한 0바이트를 구분한다."""
    return value if type(value) is int and 0 <= value < 2**53 else None


def validate_measurement(measurement):
    """! @brief 새 native 계측의 범위를 확인하고 과거 실행에서 누락된 필드는 허용한다."""
    if (type(measurement) is not dict or set(measurement) != {"scope", "wall_seconds", "peak_rss_bytes", "raw_output_bytes"}
            or measurement["scope"] != NATIVE_SCOPE or _time(measurement["wall_seconds"]) in (None, 0)
            or _bytes(measurement["peak_rss_bytes"]) in (None, 0) or _bytes(measurement["raw_output_bytes"]) is None):
        raise ProjectError("E_HASH", "PCB native 실행 비용의 측정 범위 또는 수치가 유효하지 않습니다.")


_PROGRESS = re.compile(
    r"Timestep:\s*(\d+)[^\r\n]*?Energy:\s*~\s*([+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*"
    r"\(\s*([+-])\s*(\d+(?:\.\d+)?|inf)\s*dB\)", re.IGNORECASE)


def energy_observations(log, termination, limit=96):
    """! @brief 로그에 실제 기록된 진행 표본과 확인된 마지막 표본을 단계 순으로 읽는다."""
    samples = {}
    stop = termination["iterations"]
    for match in _PROGRESS.finditer(log):
        step = int(match[1])
        energy = float(match[2])
        decay = float(match[4])
        if not 0 < step < stop or not math.isfinite(energy) or energy < 0 or math.isnan(decay):
            continue
        samples[step] = {"step": step, "reported_energy": energy,
                         "decay_db": decay * (1 if match[3] == "-" else -1) if math.isfinite(decay) else None,
                         "final": False}
    ordered = [samples[step] for step in sorted(samples)]
    ordered.append({"step": stop, "reported_energy": 0.0 if termination["reported_zero_energy"] else None,
                    "decay_db": termination["reported_decay_db"], "final": True})
    total = len(ordered)
    if total > limit:
        ordered = [ordered[index * (total - 1) // (limit - 1)] for index in range(limit)]
    return {"samples": ordered, "logged_total": total}


def completed(result, files, budget, native_log=""):
    """! @brief 봉인된 계획과 원시 결과에서 실제 계산을 한 번만 읽어 비교 DTO로 제공한다."""
    provenance = result["provenance"]
    execution = result["raw_manifest"]["execution"]
    measured = execution.get("cost", {})
    estimate_before_run = execution.get("cost_estimate")
    if estimate_before_run is None:
        estimate_before_run = estimate(provenance["analysis_plan"], result["mesh_statistics"]["lines_mm"])
    termination = result["termination"]
    return {"estimate": estimate_before_run, "estimate_retrospective": "cost_estimate" not in execution,
            "execution_budget_seconds": _time(budget), "revision_id": provenance["analysis_plan"]["snapshot"]["revision_id"],
            "energy_observations": energy_observations(native_log, termination),
            "recovery_stage": "published",
            "actual": {"wall_seconds": _time(measured.get("wall_seconds", execution.get("elapsed_seconds"))),
                       "time_scope": "native_process" if measured else "legacy_native_log",
                       "peak_rss_bytes": _bytes(measured.get("peak_rss_bytes")),
                       "raw_output_bytes": sum(row["bytes"] for row in result["raw_manifest"]["files"]),
                       "archived_output_bytes": sum(row["artifact"]["bytes"] for row in files),
                       "postprocess_seconds": _time(provenance.get("postprocess_timings", {}).get("total_seconds"))},
            "termination": {"reason": termination["status"], "confirmed": True,
                            "iterations": termination["iterations"], "target_energy_ratio": termination["target_energy_ratio"],
                            "decay_db": termination["reported_decay_db"], "zero_energy": termination["reported_zero_energy"]}}


def stopped(job, state, process, diagnostic):
    """! @brief 취소, 시간 한도와 미수렴을 분리하며 성공 결과에는 영향을 주지 않는다."""
    captured = job["solver"]
    plan = captured.get("analysis_plan")
    if job["kind"] != "em_analysis" or not plan or plan["analysis_profile"] != "rfad.openems.pcb-single-port/0.1":
        return None
    data = diagnostic.details
    measured = data.get("execution_cost", {})
    if measured:
        validate_measurement(measured)
    native = process.get("native") or {}
    confirmed = process.get("termination_confirmed") is True and not process.get("outcome_unknown", False)
    if state in {"cancelled", "interrupted"}:
        reason = state
    elif data.get("criterion") == "native_timestep_limit":
        reason = "timestep_limit"
    else:
        reason = process["state"] if process.get("state") in {"timeout", "output_limit"} else "solver_error"
    lines = (captured.get("preparation") or {}).get("mesh_statistics", {}).get("lines_mm")
    retrospective = lines is None
    if retrospective:
        from rfad.application.pcb_mesh import mesh_lines
        lines = mesh_lines(plan["case"])
    return {"estimate": estimate(plan, lines),
            "estimate_retrospective": retrospective, "execution_budget_seconds": job["input"]["budget"]["timeout_seconds"],
            "recovery_stage": "restart_prepared_plan" if confirmed else "confirm_guest_exit",
            "revision_id": plan["snapshot"]["revision_id"],
            "actual": {"wall_seconds": _time(measured.get("wall_seconds")), "time_scope": "native_process",
                       "peak_rss_bytes": _bytes(measured.get("peak_rss_bytes")),
                       "raw_output_bytes": _bytes(measured.get("raw_output_bytes")), "partial_raw": bool(measured),
                       "worker_wall_seconds": _time(native.get("wall_seconds")) if confirmed else None,
                       "observed_output_peak_bytes": _bytes((native.get("file_monitor") or {}).get("observed_peak_bytes")) if confirmed else None},
            "termination": {"reason": reason, "confirmed": confirmed, "iterations": data.get("iterations"),
                            "target_energy_ratio": plan["case"]["settings"]["end_criterion"], "message": diagnostic.message}}
