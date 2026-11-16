"""! @brief 고정 합성 RF 참조를 표준 봉인 worker의 준비/해석/후처리로 실행한다.

@details 사용자 PCB나 미정 sheet/급전 모델을 대신 실행하지 않는다. 과거 독립
worker의 PEC 다이폴 생성은 이 모듈로 모으고 source/runtime 수명은 공통 경로를 쓴다.
"""

from copy import deepcopy
import json
import math
import shutil
import subprocess
import time

from rfad.application.canonical import canonical_hash
from rfad.application.rf_reference_contract import (PROFILE, RESULT_SCHEMA, RADIATION_SCHEMA, REFERENCE_SCOPE,
        raw_names, validate_plan, validate_preparation, validate_result, validate_radiation, radiation_summary)
from rfad.application.pcb_results import read_statistics_values, check_termination
from .native import (EXECUTABLE, MAX_FILE_BYTES, require, file_identity, write_json, descriptor,
                     _check_preparation, _mapped_files, _validate_mapped)


def prepare(stage, plan, runtime):
    """! @brief 고정 PEC 다이폴과 실제 CSXCAD 격자/XML만 준비하고 FDTD는 실행하지 않는다."""
    import CSXCAD
    import openEMS
    from .pcb_radiation import create_box

    validate_plan(plan)
    case = plan["case"]
    output = stage / "output/prepared"
    output.mkdir()
    csx = CSXCAD.ContinuousStructure()
    solver = openEMS.openEMS(NrTS=case["settings"]["max_timesteps"], EndCriteria=case["settings"]["end_criterion"])
    solver.SetCSX(csx)
    solver.SetGaussExcite(case["excitation"]["center_hz"], case["excitation"]["width_hz"])
    solver.SetBoundaryCond(case["boundary_conditions"])
    grid = csx.GetGrid()
    grid.SetDeltaUnit(case["delta_unit_m"])
    for axis, values in case["mesh"]["lines_mm"].items():
        grid.AddLine(axis, values)
    geometry = case["geometry"]
    metal = csx.AddMetal("reference_PEC")
    for cylinder in geometry["cylinders"]:
        metal.AddCylinder(start=cylinder["start_mm"], stop=cylinder["stop_mm"],
                          radius=geometry["radius_mm"], priority=geometry["priority"])
    port = case["port"]
    solver.AddLumpedPort(port["number"], port["resistance_ohm"], port["start_mm"], port["stop_mm"],
                        port["axis"], excite=port["excite"], priority=port["priority"])
    create_box(csx, case["radiation_recording"])
    xml = output / "reference.xml"
    solver.Write2XML(str(xml))
    observed = {axis: [float(value) for value in grid.GetLines(axis)] for axis in "xyz"}
    require(observed == case["mesh"]["lines_mm"], "고정 참조의 실제 native 격자가 계획과 다릅니다.", "E_HASH")
    counts = [len(observed[axis]) for axis in "xyz"]
    mesh = {"schema": "rfad.openems-reference-mesh/0.1", "grid_mm": case["mesh"]["interior_grid_mm"],
            "native_length_unit": "mm", "delta_unit_m": 0.001, "lines_mm": observed, "line_counts": counts,
            "interval_counts": [value - 1 for value in counts], "native_grid_points": math.prod(counts),
            "yee_interval_cells": math.prod(value - 1 for value in counts), "pml_cells_per_end": 8,
            "native_preprocessing_executed": False, "fdtd_executed": False}
    consumption = {"schema": "rfad.openems-reference-consumption/0.1", "analysis_plan_id": plan["plan_id"],
                   "source": "explicit_reference_case", "consumed_case": case,
                   "project_geometry_consumed": False, "project_materials_consumed": False,
                   "reference_scope": deepcopy(REFERENCE_SCOPE), "fdtd_executed": False, "physics_validated": False}
    files = [descriptor(stage, xml, "native_input")]
    for name, role, value in (("mesh.json", "mesh_statistics", mesh), ("consumption.json", "consumption_report", consumption),
                             ("normalization.json", "normalization", plan["normalization"]),
                             ("runtime.json", "runtime_provenance", runtime),
                             ("radiation_recording.json", "radiation_recording", case["radiation_recording"])):
        write_json(output / name, value)
        files.append(descriptor(stage, output / name, role))
    preparation = {"schema": "rfad.preparation-artifact/0.1", "analysis_plan_id": plan["plan_id"],
                   "analysis_plan_hash": canonical_hash(plan), "profile": PROFILE, "files": files,
                   "mesh_statistics": mesh, "normalization": plan["normalization"], "consumption_report": consumption,
                   "runtime_identity": runtime, "radiation_recording": case["radiation_recording"]}
    validate_preparation(plan, preparation)
    write_json(output / "preparation.json", preparation)
    return preparation, files + [descriptor(stage, output / "preparation.json", "preparation_artifact")]


def statistics_and_termination(raw, plan):
    """! @brief 에너지 종료 근거를 확인하고 시간 상한 도달을 수렴으로 바꾸지 않는다."""
    settings = plan["case"]["settings"]
    statistics = read_statistics_values((raw / "openEMS_stats.txt").read_text(encoding="utf-8"), settings["max_timesteps"])
    termination = check_termination((raw / "native.log").read_text(encoding="utf-8"), statistics["iterations"], settings)
    return statistics, termination


def solve(stage, request, inputs, runtime):
    """! @brief 준비된 동일 XML 바이트를 실행하고 실제 로딩/종료/필수 raw를 봉인한다."""
    preparation = _check_preparation(request, inputs)
    plan = request["analysis_plan"]
    validate_preparation(plan, preparation)
    raw = stage / "output/raw"
    raw.mkdir()
    shutil.copyfile(inputs["native_input"], raw / "reference.xml")
    require(file_identity(inputs["native_input"]) == file_identity(raw / "reference.xml"), "참조 XML 복사 봉인이 다릅니다.", "E_HASH")
    threads = plan["case"]["num_threads"]
    command = [str(EXECUTABLE), "reference.xml", "--engine=multithreaded", "--numThreads=" + str(threads),
               "--dump-statistics", "--exact-endcriteria"]
    started, mapped = time.monotonic(), set()
    with (raw / "native.log").open("xb") as stream:
        child = subprocess.Popen(command, cwd=raw, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
        try:
            while child.poll() is None:
                mapped.update(_mapped_files(child.pid))
                require((raw / "native.log").stat().st_size <= MAX_FILE_BYTES, "참조 native 로그 상한을 초과했습니다.", "E_RESOURCE")
                time.sleep(0.1)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
    require(child.returncode == 0, "고정 참조 native solver가 정상 종료하지 않았습니다.")
    require(file_identity(inputs["native_input"]) == file_identity(raw / "reference.xml"), "실행 중 참조 XML이 변경되었습니다.", "E_HASH")
    actual = _validate_mapped(sorted(mapped), {item["path"]: {key: item[key] for key in ("bytes", "sha256")}
                                             for item in runtime["native_files"]})
    require(any("libopenEMS" in item["path"] for item in actual), "참조 CLI의 실제 native 로딩을 확인하지 못했습니다.", "E_VERSION")
    statistics, termination = statistics_and_termination(raw, plan)
    require("openEMS - fixed number of threads: " + str(threads) + "\n" in (raw / "native.log").read_text(encoding="utf-8"),
            "참조 native 스레드 수의 실제 로그가 다릅니다.", "E_HASH")
    require(statistics["native_cells"] == preparation["mesh_statistics"]["native_grid_points"], "실제 참조 격자 통계가 준비와 다릅니다.")
    files = [descriptor(stage, raw / name, "raw/" + name) for name in raw_names(plan)]
    execution = {"command": command, "elapsed_seconds": time.monotonic() - started, "exit_code": child.returncode,
                 "loaded_native_files": actual, "statistics": statistics, "termination": termination,
                 "native_input_sha256": file_identity(raw / "reference.xml")["sha256"]}
    manifest = {"schema": "rfad.openems-raw/0.1", "complete": True, "analysis_plan_id": plan["plan_id"],
                "analysis_plan_hash": canonical_hash(plan), "prepared_plan_id": request["prepared_plan"]["prepared_plan_id"],
                "prepared_plan_hash": canonical_hash(request["prepared_plan"]), "files": files, "execution": execution}
    write_json(stage / "output/raw_manifest.json", manifest)
    return manifest, files + [descriptor(stage, stage / "output/raw_manifest.json", "raw_manifest")]


def _restore_raw(stage, request, inputs):
    """! @brief 다른 계획/중복/누락 파일을 거절한 뒤 원시 사본만 후처리 공간에 복원한다."""
    require("raw_manifest" in inputs, "참조 후처리에 완료 원시 manifest가 필요합니다.", "E_MISSING_ARTIFACT")
    manifest = json.loads(inputs["raw_manifest"].read_bytes())
    require(type(manifest) is dict and manifest.get("complete") is True and manifest.get("schema") == "rfad.openems-raw/0.1",
            "참조 원시 manifest가 완료 상태가 아닙니다.", "E_MISSING_ARTIFACT")
    require(manifest.get("analysis_plan_hash") == canonical_hash(request["analysis_plan"])
            and manifest.get("prepared_plan_hash") == canonical_hash(request["prepared_plan"]), "참조 원시 결과의 계획 봉인이 다릅니다.", "E_HASH")
    names = raw_names(request["analysis_plan"])
    records = manifest.get("files")
    require(type(records) is list and len(records) == len(names)
            and all(type(item) is dict and type(item.get("role")) is str for item in records)
            and {item["role"] for item in records} == {"raw/" + name for name in names},
            "참조 원시 필수 파일이 중복되었거나 누락되었습니다.", "E_MISSING_ARTIFACT")
    raw = stage / "output/raw"
    raw.mkdir()
    for item in records:
        role = item["role"]
        require(item.get("path") == "output/" + role and role in inputs, "참조 원시 경로와 역할이 다릅니다.", "E_HASH")
        identity = file_identity(inputs[role])
        require(all(identity[key] == item.get(key) for key in identity), "참조 원시 바이트 봉인이 다릅니다.", "E_HASH")
        shutil.copyfile(inputs[role], raw / role.split("/")[1])
    files = [descriptor(stage, raw / name, "raw/" + name) for name in names]
    write_json(stage / "output/raw_manifest.json", manifest)
    return manifest, files + [descriptor(stage, stage / "output/raw_manifest.json", "raw_manifest")]


def postprocess(stage, request, inputs, runtime, manifest=None):
    """! @brief 봉인된 참조 raw를 공통 산술로 재처리하고 새 FDTD는 실행하지 않는다."""
    from .pcb import normalize_probes
    from .pcb_radiation import postprocess as postprocess_radiation

    plan = request["analysis_plan"]
    preparation = _check_preparation(request, inputs)
    validate_preparation(plan, preparation)
    files = []
    if manifest is None:
        manifest, files = _restore_raw(stage, request, inputs)
    raw = stage / "output/raw"
    require(file_identity(raw / "reference.xml") == file_identity(inputs["native_input"]), "참조 raw XML과 준비 입력이 다릅니다.", "E_HASH")
    statistics, termination = statistics_and_termination(raw, plan)
    require(statistics == manifest["execution"]["statistics"] and termination == manifest["execution"]["termination"],
            "참조 실행 보고와 실제 종료/통계가 다릅니다.", "E_HASH")
    samples = normalize_probes(raw, plan)
    radiation, radiation_files = postprocess_radiation(stage, plan, raw, schema=RADIATION_SCHEMA,
                                                      validator=validate_radiation, summarize=radiation_summary)
    files.extend(radiation_files)
    provenance = {"schema": "rfad.openems-provenance/0.1", "run_id": request["run_id"], "nonce": request["nonce"],
                  "execution_mode": request["phase"], "analysis_plan": plan, "prepared_plan": request["prepared_plan"],
                  "preparation": preparation, "runtime": runtime, "raw_manifest": manifest}
    result = {"schema": RESULT_SCHEMA, "analysis_plan_id": plan["plan_id"], "prepared_plan_id": request["prepared_plan"]["prepared_plan_id"],
              "samples": samples, "assessment": {"status": "computed_unvalidated", "physics_validated": False,
                                                   "converged": True, "finite_samples": True},
              "termination": termination, "native_statistics": statistics, "mesh_statistics": preparation["mesh_statistics"],
              "normalization": preparation["normalization"], "provenance": provenance, "raw_manifest": manifest,
              "reference_scope": deepcopy(REFERENCE_SCOPE), "radiation_summary": radiation}
    validate_result(plan, result, request["prepared_plan"])
    write_json(stage / "output/normalized.json", result)
    write_json(stage / "output/provenance.json", provenance)
    files.extend([descriptor(stage, stage / "output/normalized.json", "normalized_result"),
                  descriptor(stage, stage / "output/provenance.json", "provenance")])
    return result, files
