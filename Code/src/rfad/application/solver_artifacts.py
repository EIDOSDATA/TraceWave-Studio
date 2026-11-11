"""! @brief 해석 산출물의 봉인과 물리/출처 계약 검증을 담당한다."""

import json
import math
from pathlib import PurePosixPath

from rfad.application.canonical import canonical_hash
from rfad.application.solver_requests import PCB_PROFILE, require_fields
from rfad.domain.errors import ProjectError

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 128 * 1024 * 1024


def read_solver_result(stage, request):
    """! @brief 종료된 worker의 작은 결과 봉투를 현재 요청과 대조한다."""
    path = stage / "output/result.json"
    if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
        raise ProjectError("E_RESOURCE", "해석 결과 메타데이터가 유효하지 않습니다.")
    result = json.loads(path.read_bytes())
    for key, expected in (("schema", "rfad.openems-worker-result/0.1"), ("phase", request["phase"]), ("run_id", request["run_id"]), ("nonce", request["nonce"]), ("analysis_plan_id", request["analysis_plan"]["plan_id"])):
        if result.get(key) != expected:
            raise ProjectError("E_HASH", "해석 결과의 입력 또는 실행 식별이 다릅니다.")
    return result


def seal_solver_outputs(journal, job, stage, package):
    """! @brief 닫힌 파일을 크기와 해시로 검증하고 불변 저장소로 봉인한다."""
    files = package.get("files")
    if type(files) is not list or not 1 <= len(files) <= 64:
        raise ProjectError("E_HASH", "해석 결과 파일 목록이 유효하지 않습니다.")
    sealed, seen, roles, total = [], set(), set(), 0
    for item in files:
        require_fields(item, {"path", "role", "sha256", "bytes", "media_type"})
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
        artifact = journal.seal_file("solver-artifacts/" + job["run_id"] + "/" + path.removeprefix("output/"), stage / path,
                                                  expected_sha256=item["sha256"], expected_bytes=item["bytes"], limit=MAX_FILE_BYTES)
        sealed.append({**item, "artifact": artifact})
    return sealed


def check_prepared_outputs(journal, captured, preparation, files):
    """! @brief 준비 완료 선언 전에 소비 내역과 필수 native 파일의 연결을 검사한다."""
    roles = {f["role"]: f for f in files}
    required = {"native_input", "mesh_statistics", "consumption_report", "normalization", "runtime_provenance", "preparation_artifact"}
    radiation = "radiation_recording" in captured["analysis_plan"]["case"]
    if radiation:
        required.add("radiation_recording")
    if roles.keys() != required or preparation.get("schema") != "rfad.preparation-artifact/0.1" or preparation.get("profile") != captured["analysis_plan"]["analysis_profile"]:
        raise ProjectError("E_HASH", "준비 산출물의 필수 역할 또는 profile이 다릅니다.")
    descriptions = [{k: v for k, v in f.items() if k != "artifact"} for f in files if f["role"] != "preparation_artifact"]
    if preparation.get("files") != descriptions:
        raise ProjectError("E_HASH", "준비 manifest와 실제 파일 목록이 다릅니다.")
    if radiation and json.loads(journal.read_artifact(roles["radiation_recording"]["artifact"])) != preparation.get("radiation_recording"):
        raise ProjectError("E_HASH", "NF2FF 기록 상자가 준비 manifest와 다릅니다.")
    for role, key in (("mesh_statistics", "mesh_statistics"), ("consumption_report", "consumption_report"), ("normalization", "normalization"), ("runtime_provenance", "runtime_identity")):
        if json.loads(journal.read_artifact(roles[role]["artifact"])) != preparation.get(key):
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


def check_solver_result(journal, job, result, files):
    """! @brief 완료된 raw manifest와 후처리 수치를 계획 및 실행 소유권에 결합한다."""
    from rfad.adapters.solvers.openems.reference import assess_samples, check_termination

    captured = job["solver"]
    pcb = captured["analysis_plan"]["analysis_profile"] == PCB_PROFILE
    roles = {f["role"]: f for f in files}
    if pcb:
        from rfad.application.pcb_solver import read_statistics_values, check_termination as check_pcb_termination, validate_result
        from rfad.application.pcb_radiation import raw_names as pcb_raw_names

        raw_names = pcb_raw_names(captured["analysis_plan"])
    else:
        raw_names = ("port_ut_1", "port_it_1", "port_ut_2", "port_it_2", "openEMS_stats.txt", "openEMS_run_stats.txt", "native.log", "waveguide.xml")
    raw_roles = {"raw/" + name for name in raw_names}
    radiation = pcb and "radiation_recording" in captured["analysis_plan"]["case"]
    radiation_roles = {"radiation_result", "radiation_native"} if radiation else set()
    loss_recording = pcb and "loss_recording" in captured["analysis_plan"]["case"]
    if loss_recording:
        radiation_roles.add("power_balance_result")
    if roles.keys() != raw_roles | {"raw_manifest", "normalized_result", "provenance"} | radiation_roles:
        raise ProjectError("E_MISSING_ARTIFACT", "해석 결과의 필수 원시 파일이 없습니다.")
    manifest = json.loads(journal.read_artifact(roles["raw_manifest"]["artifact"]))
    provenance = json.loads(journal.read_artifact(roles["provenance"]["artifact"]))
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
    statistics_text = journal.read_artifact(roles["raw/openEMS_stats.txt"]["artifact"]).decode("utf-8")
    values = [float(line.split()[0]) for line in statistics_text.splitlines() if line.strip()]
    maximum_steps = captured["analysis_plan"]["case"]["settings"]["max_timesteps"] if pcb else 20000
    if (len(values) < 6 or not all(math.isfinite(v) for v in values) or values[0] != int(values[0])
            or values[2] != int(values[2]) or not 0 < values[2] < maximum_steps or values[1] <= 0
            or values[0] != captured["preparation"]["mesh_statistics"]["native_grid_points"]):
        raise ProjectError("E_SOLVER", "실제 native 통계가 격자 또는 종료 조건과 다릅니다.")
    statistics = {"native_cells": int(values[0]), "timestep_seconds": values[1], "iterations": int(values[2]), "raw_values": values}
    native_log = journal.read_artifact(roles["raw/native.log"]["artifact"]).decode("utf-8")
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
        if radiation:
            from rfad.application.pcb_radiation import validate_result as validate_radiation, summary

            field = json.loads(journal.read_artifact(roles["radiation_result"]["artifact"]))
            validate_radiation(captured["analysis_plan"], field)
            if result["radiation_summary"] != summary(field):
                raise ProjectError("E_HASH", "방사 요약과 봉인 필드 산출물이 다릅니다.")
            if loss_recording:
                from rfad.application.pcb_power import validate_result as validate_power

                balance = json.loads(journal.read_artifact(roles["power_balance_result"]["artifact"]))
                validate_power(captured["analysis_plan"], balance, field)
                if result.get("power_balance") != balance:
                    raise ProjectError("E_HASH", "독립 전력 수지와 별도 봉인 산출물이 다릅니다.")
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
