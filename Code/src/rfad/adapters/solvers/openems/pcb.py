"""! @brief 사용자 PCB의 유전체/유한 전도 sheet/단일 포트를 실제 openEMS에 연결한다."""

import json
import math
from pathlib import Path
import shutil
import subprocess
import time

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import (
    PROFILE, RAW_NAMES, check_termination, mesh_lines, read_statistics_values,
    shape_polygons, validate_pcb_plan, validate_preparation, validate_result,
)
from .native import (
    EXECUTABLE, MAX_FILE_BYTES, _check_preparation, _mapped_files, _validate_mapped,
    descriptor, file_identity, require, write_json,
)
from .pcb_mesh import audit_native_mesh
from .pcb_ports import spectra
from rfad.application.pcb_radiation import raw_names


def prepare(stage, plan, runtime):
    """! @brief 원/직사각 기판과 명시적 도체를 준비하되 FDTD는 실행하지 않는다."""
    import numpy as np
    import CSXCAD
    import openEMS

    validate_pcb_plan(plan)
    case = plan["case"]
    settings = case["settings"]
    output = stage / "output/prepared"
    output.mkdir()
    csx = CSXCAD.ContinuousStructure()
    solver = openEMS.openEMS(NrTS=settings["max_timesteps"], EndCriteria=settings["end_criterion"])
    solver.SetCSX(csx)
    solver.SetGaussExcite(case["excitation"]["center_hz"], case["excitation"]["width_hz"])
    solver.SetBoundaryCond(case["boundary_conditions"])
    grid = csx.GetGrid()
    grid.SetDeltaUnit(case["delta_unit_m"])
    lines = mesh_lines(case)
    for axis in "xyz":
        grid.AddLine(axis, lines[axis])
    board = case["board"]
    for layer in case["layers"]:
        if layer["role"] != "dielectric":
            continue
        prop = csx.AddMaterial("dielectric_" + layer["id"], epsilon=layer["epsilon_r"], kappa=layer["kappa_s_per_m"])
        low, high = layer["z_min_mm"], layer["z_min_mm"] + layer["thickness_mm"]
        if board["kind"] == "circle":
            cx, cy = board["center_mm"]
            prop.AddCylinder(start=[cx, cy, low], stop=[cx, cy, high], radius=board["radius_mm"], priority=1)
        else:
            prop.AddBox(start=[0, 0, low], stop=[*board["dimensions_mm"], high], priority=1)
    mappings = []
    for shape in case["shapes"]:
        prop = csx.AddConductingSheet("conductor_" + shape["id"], conductivity=shape["conductivity_s_per_m"], thickness=shape["thickness_m"])
        polygons = shape_polygons(shape, settings["curve_tolerance_mm"])
        for polygon in polygons:
            prop.AddPolygon(np.asarray(polygon, dtype=float).T, norm_dir=2, elevation=shape["sheet_z_mm"], priority=5)
        mappings.append({"source_entity_id": shape["id"], "native_property": "conductor_" + shape["id"],
                         "polygon_count": len(polygons), "polygon_point_count": sum(len(poly) for poly in polygons),
                         "curve_tolerance_mm": settings["curve_tolerance_mm"], "sheet_z_mm": shape["sheet_z_mm"],
                         "modeled_thickness_m": shape["thickness_m"], "conductivity_s_per_m": shape["conductivity_s_per_m"]})
    via_mappings = []
    for via in case.get("vias", []):
        start, stop = [*via["center_mm"], via["z_min_mm"]], [*via["center_mm"], via["z_max_mm"]]
        # @brief 3D shell을 sheet 속성에 붙이면 native가 PEC로 바꾸므로 유한 kappa 체적을 사용한다.
        prop = csx.AddMaterial("via_" + via["id"], epsilon=via["epsilon_r"], kappa=via["conductivity_s_per_m"])
        prop.AddCylindricalShell(start=start, stop=stop, radius=(via["inner_radius_mm"] + via["outer_radius_mm"]) / 2,
                                 shell_width=via["plating_thickness_mm"], priority=6)
        bore = csx.AddMaterial("drill_" + via["id"], epsilon=1.0, kappa=0.0)
        bore.AddCylinder(start=start, stop=stop, radius=via["inner_radius_mm"], priority=30)
        via_mappings.append({"source_entity_id": via["id"], "native_property": "via_" + via["id"], "drill_property": "drill_" + via["id"],
                             "model": via["native_model"], "center_mm": via["center_mm"], "z_range_mm": [via["z_min_mm"], via["z_max_mm"]],
                             "inner_radius_mm": via["inner_radius_mm"], "outer_radius_mm": via["outer_radius_mm"],
                             "conductivity_s_per_m": via["conductivity_s_per_m"], "epsilon_r": via["epsilon_r"], "skin_depth_loss_validated": False,
                             "tool_hole_diameter_mm": via["tool_hole_diameter_mm"], "tool_hole_used_for_native_geometry": False,
                             "native_drill_basis": "finished_hole_diameter"})
    connectivity = audit_native_mesh(csx, case, lines)
    port = case["port"]
    solver.AddLumpedPort(1, port["resistance_ohm"], port["start_mm"], port["stop_mm"], port["axis"], excite=1, priority=10)
    if "radiation_recording" in case:
        from .pcb_radiation import create_box

        create_box(csx, case["radiation_recording"])
    if "loss_recording" in case:
        from .pcb_absorption import create_dumps

        create_dumps(csx, case["loss_recording"])
    xml = output / "pcb.xml"
    solver.Write2XML(str(xml))
    observed = {axis: [float(value) for value in grid.GetLines(axis)] for axis in "xyz"}
    require(observed == lines, "native 준비 격자가 계획과 다릅니다.", "E_HASH")
    counts = [len(lines[axis]) for axis in "xyz"]
    mesh = {"schema": "rfad.openems-pcb-mesh/0.1", "grid_mm": settings["grid_mm"], "native_length_unit": "mm", "delta_unit_m": 0.001,
            "lines_mm": observed, "line_counts": counts, "interval_counts": [c - 1 for c in counts],
            "native_grid_points": math.prod(counts), "yee_interval_cells": math.prod(c - 1 for c in counts),
            "pml_cells_per_end": 8, "native_preprocessing_executed": False, "fdtd_executed": False}
    if "mesh_policy_report" in case:
        mesh["mesh_policy_report"] = case["mesh_policy_report"]
    consumption = {"schema": "rfad.openems-pcb-consumption/0.1", "analysis_plan_id": plan["plan_id"], "source": "user_project",
                   "consumed_case": case, "project_geometry_consumed": True, "project_materials_consumed": True,
                   "source_mapping": mappings, "board_native_primitive": "cylinder" if board["kind"] == "circle" else "box",
                   "via_source_mapping": via_mappings, "native_connectivity": connectivity,
                   "approximations": plan["model_report"]["approximations"], "fdtd_executed": False, "physics_validated": False}
    normalization = plan["normalization"]
    files = [descriptor(stage, xml, "native_input")]
    for name, role, data in (("mesh.json", "mesh_statistics", mesh), ("consumption.json", "consumption_report", consumption),
                             ("normalization.json", "normalization", normalization), ("runtime.json", "runtime_provenance", runtime)):
        write_json(output / name, data)
        files.append(descriptor(stage, output / name, role))
    preparation = {"schema": "rfad.preparation-artifact/0.1", "analysis_plan_id": plan["plan_id"], "analysis_plan_hash": canonical_hash(plan),
                   "profile": PROFILE, "files": files, "mesh_statistics": mesh, "normalization": normalization,
                   "consumption_report": consumption, "runtime_identity": runtime}
    if "radiation_recording" in case:
        preparation["radiation_recording"] = case["radiation_recording"]
        write_json(output / "radiation_recording.json", case["radiation_recording"])
        files.append(descriptor(stage, output / "radiation_recording.json", "radiation_recording"))
    validate_preparation(plan, preparation)
    write_json(output / "preparation.json", preparation)
    return preparation, files + [descriptor(stage, output / "preparation.json", "preparation_artifact")]


def statistics_and_termination(raw, plan):
    """! @brief 실제 통계와 로그에서 요청한 시간/에너지 종료 조건을 확인한다."""
    settings = plan["case"]["settings"]
    stats = read_statistics_values((raw / "openEMS_stats.txt").read_text(encoding="utf-8"), settings["max_timesteps"])
    termination = check_termination((raw / "native.log").read_text(encoding="utf-8"), stats["iterations"], settings)
    return stats, termination


def solve(stage, request, inputs, runtime):
    """! @brief 준비 XML의 실제 바이트를 고정 CLI로 실행하고 원시 결과를 봉인한다."""
    prep = _check_preparation(request, inputs)
    validate_preparation(request["analysis_plan"], prep)
    raw = stage / "output/raw"
    raw.mkdir()
    shutil.copyfile(inputs["native_input"], raw / "pcb.xml")
    require(file_identity(inputs["native_input"]) == file_identity(raw / "pcb.xml"), "준비 XML 복사본의 해시가 다릅니다.", "E_HASH")
    command = [str(EXECUTABLE), "pcb.xml", "--engine=multithreaded", "--numThreads=2", "--dump-statistics", "--exact-endcriteria"]
    started, mapped = time.monotonic(), set()
    with (raw / "native.log").open("xb") as stream:
        child = subprocess.Popen(command, cwd=raw, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
        try:
            while child.poll() is None:
                mapped.update(_mapped_files(child.pid))
                require((raw / "native.log").stat().st_size <= MAX_FILE_BYTES, "native 로그 상한을 초과했습니다.", "E_RESOURCE")
                time.sleep(0.02)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
    require(child.returncode == 0, "PCB native solver가 정상 종료하지 않았습니다.")
    require(file_identity(inputs["native_input"]) == file_identity(raw / "pcb.xml"), "실행 중 준비 XML이 변경되었습니다.", "E_HASH")
    actual = _validate_mapped(sorted(mapped), {f["path"]: {key: f[key] for key in ("bytes", "sha256")} for f in runtime["native_files"]})
    require(any("libopenEMS" in f["path"] for f in actual), "실제 native 로딩을 확인하지 못했습니다.", "E_VERSION")
    stats, termination = statistics_and_termination(raw, request["analysis_plan"])
    require(stats["native_cells"] == prep["mesh_statistics"]["native_grid_points"], "실제 native cell 수가 준비 격자와 다릅니다.")
    files = [descriptor(stage, raw / name, "raw/" + name) for name in raw_names(request["analysis_plan"])]
    execution = {"command": command, "elapsed_seconds": time.monotonic() - started, "exit_code": child.returncode, "loaded_native_files": actual,
                 "statistics": stats, "termination": termination, "native_input_sha256": file_identity(raw / "pcb.xml")["sha256"]}
    manifest = {"schema": "rfad.openems-raw/0.1", "complete": True, "analysis_plan_id": request["analysis_plan"]["plan_id"],
                "analysis_plan_hash": canonical_hash(request["analysis_plan"]), "prepared_plan_id": request["prepared_plan"]["prepared_plan_id"],
                "prepared_plan_hash": canonical_hash(request["prepared_plan"]), "files": files, "execution": execution}
    write_json(stage / "output/raw_manifest.json", manifest)
    return manifest, files + [descriptor(stage, stage / "output/raw_manifest.json", "raw_manifest")]


def normalize_probes(raw, plan):
    """! @brief 실제 단일 lumped 전압/전류에서 복소 S11/Z와 표시값을 계산한다."""
    import numpy as np

    frequency = plan["case"]["frequency_hz"]
    frequencies = np.linspace(frequency["start"], frequency["stop"], frequency["count"])
    voltage, current = spectra(raw, frequencies)
    incident = 0.5 * (voltage + plan["case"]["port"]["resistance_ohm"] * current)
    require(np.max(np.abs(incident)) > 1e-18 and np.all(np.abs(incident) > np.max(np.abs(incident)) * 1e-4)
            and np.all(np.abs(current) > 1e-24), "포트 여기 또는 전류가 너무 작아 정규화할 수 없습니다.")
    reflection, impedance = (voltage - incident) / incident, voltage / current
    require(np.all(np.isfinite(reflection)) and np.all(np.isfinite(impedance)), "PCB 포트 결과가 유한하지 않습니다.")
    result = []
    for f, s11, z in zip(frequencies, reflection, impedance):
        magnitude = float(abs(s11))
        result.append({"frequency_hz": float(f), "s11": [float(s11.real), float(s11.imag)], "impedance_ohm": [float(z.real), float(z.imag)],
                       "vswr": (1 + magnitude) / (1 - magnitude) if magnitude < 1 else None,
                       "s11_db": 20 * math.log10(magnitude) if magnitude > 0 else None,
                       "vswr_status": "defined" if magnitude < 1 else "undefined_reflection_ge_one"})
    return result


def postprocess(stage, request, inputs, runtime, manifest=None):
    """! @brief 봉인된 원시 데이터만 후처리하며 solver를 재실행하지 않는다."""
    prep = _check_preparation(request, inputs)
    validate_preparation(request["analysis_plan"], prep)
    files = []
    names = raw_names(request["analysis_plan"])
    raw = stage / "output/raw"
    if manifest is None:
        require("raw_manifest" in inputs, "후처리할 원시 manifest가 없습니다.", "E_MISSING_ARTIFACT")
        manifest = json.loads(inputs["raw_manifest"].read_bytes())
        require(manifest.get("complete") is True and manifest.get("schema") == "rfad.openems-raw/0.1", "원시 결과가 완료 상태가 아닙니다.", "E_MISSING_ARTIFACT")
        require(manifest["analysis_plan_hash"] == canonical_hash(request["analysis_plan"]) and manifest["prepared_plan_hash"] == canonical_hash(request["prepared_plan"]), "원시 결과의 계획 해시가 다릅니다.", "E_HASH")
        records = manifest.get("files", [])
        require(len(records) == len(names) and {f["role"] for f in records} == {"raw/" + name for name in names}, "원시 결과의 필수 파일이 누락 또는 중복되었습니다.", "E_MISSING_ARTIFACT")
        raw.mkdir()
        for record in records:
            role = record["role"]
            require(record["path"] == "output/" + role and role in inputs, "원시 결과 파일 경로가 다릅니다.", "E_HASH")
            identity = file_identity(inputs[role])
            require(all(identity[key] == record[key] for key in identity), "원시 결과의 바이트 봉인이 다릅니다.", "E_HASH")
            shutil.copyfile(inputs[role], raw / role.split("/")[1])
        files = [descriptor(stage, raw / name, "raw/" + name) for name in names]
        write_json(stage / "output/raw_manifest.json", manifest)
        files.append(descriptor(stage, stage / "output/raw_manifest.json", "raw_manifest"))
    require(file_identity(raw / "pcb.xml") == file_identity(inputs["native_input"]), "원시 해석의 XML이 준비 입력과 다릅니다.", "E_HASH")
    stats, termination = statistics_and_termination(raw, request["analysis_plan"])
    require(stats == manifest["execution"]["statistics"] and termination == manifest["execution"]["termination"], "원시 통계 또는 종료 보고가 다릅니다.", "E_HASH")
    samples = normalize_probes(raw, request["analysis_plan"])
    provenance = {"schema": "rfad.openems-provenance/0.1", "run_id": request["run_id"], "nonce": request["nonce"], "execution_mode": request["phase"],
                  "analysis_plan": request["analysis_plan"], "prepared_plan": request["prepared_plan"], "preparation": prep, "runtime": runtime, "raw_manifest": manifest}
    result = {"schema": "rfad.openems-pcb-result/0.1", "analysis_plan_id": request["analysis_plan"]["plan_id"], "prepared_plan_id": request["prepared_plan"]["prepared_plan_id"],
              "samples": samples, "assessment": {"status": "computed_unvalidated", "physics_validated": False, "converged": True, "finite_samples": True},
              "termination": termination, "native_statistics": stats, "mesh_statistics": prep["mesh_statistics"], "normalization": prep["normalization"],
              "provenance": provenance, "raw_manifest": manifest}
    if "radiation_recording" in request["analysis_plan"]["case"]:
        from .pcb_radiation import postprocess as postprocess_radiation

        result["radiation_summary"], radiation_files = postprocess_radiation(stage, request["analysis_plan"], raw)
        files.extend(radiation_files)
    if "loss_recording" in request["analysis_plan"]["case"]:
        from .pcb_absorption import postprocess as postprocess_absorption

        radiation = json.loads((stage / "output/radiation.json").read_bytes())
        result["power_balance"], loss_file = postprocess_absorption(stage, request["analysis_plan"], raw, radiation, result["native_statistics"])
        files.append(loss_file)
    validate_result(request["analysis_plan"], result, request["prepared_plan"])
    write_json(stage / "output/normalized.json", result)
    write_json(stage / "output/provenance.json", provenance)
    files += [descriptor(stage, stage / "output/normalized.json", "normalized_result"), descriptor(stage, stage / "output/provenance.json", "provenance")]
    return result, files
