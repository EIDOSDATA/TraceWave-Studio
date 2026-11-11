"""! @brief PCB 준비/종료/정규화 결과와 직접 계산 표본의 계약을 검증한다."""

import math
import re

from rfad.application.pcb_geometry import fail, shape_polygons
from rfad.application.pcb_mesh import mesh_lines

RAW_NAMES = ("port_ut_1", "port_it_1", "openEMS_stats.txt", "openEMS_run_stats.txt", "native.log", "pcb.xml")


def normalization_contract(port, *, radiation=False):
    """! @brief 명시적 lumped 저항과 pulse Fourier 비율의 결과 규약을 반환한다."""
    result = {"schema": "rfad.normalization.pcb-single-port/0.1", "fourier_convention": "exp(-j*2*pi*f*t)",
            "native_fourier_scale": "2*dt*sum(value*exp(-j*2*pi*f*t))", "native_voltage_unit": "V*s", "native_current_unit": "A*s",
            "wave_definition": "voltage_wave_real_lumped_resistance", "reference_impedance_ohm": port["resistance_ohm"],
            "reference_plane": port["reference_plane"], "reference_plane_shift_mm": 0.0,
            "start_terminal": "reference_geometry_id", "stop_terminal": "positive_geometry_id", "polarity": 1,
            "absolute_power_gain_efficiency": "not_evaluated", "vswr_invalid_when_reflection_ge_one": True}

    if radiation:
        result.update(absolute_power_gain_efficiency="absolute_power_not_evaluated_gain_efficiency_from_nf2ff_ratios",
                      radiation_power_unit="W*s^2", radiation_electric_field_unit="V*s/m",
                      radiation_radius_m=1.0, radiation_center_unit="m")
    return result


def read_statistics_values(text, max_timesteps):
    """! @brief 유한 native 통계와 time step 상한 미도달을 검사한다."""
    values = [float(line.split()[0]) for line in text.splitlines() if line.strip()]
    if (len(values) < 6 or not all(math.isfinite(v) for v in values) or values[0] != int(values[0])
            or values[2] != int(values[2]) or not 0 < values[2] < max_timesteps or values[1] <= 0):
        fail("E_SOLVER", "PCB native 통계가 불완전하거나 시간 상한에 도달했습니다.")
    return {"native_cells": int(values[0]), "timestep_seconds": values[1], "iterations": int(values[2]), "raw_values": values}


def check_termination(log, iterations, settings):
    """! @brief 요청한 에너지 종료 목표를 실제 native 로그에서 확인한다."""
    lowered = log.lower()
    if any(token in lowered for token in ("checkabortcond", "aborting simulation", "max. number of timesteps was reached", "fallback to pec")) or "Exact-endcriteria: evaluating the end criteria every " not in log:
        fail("E_SOLVER", "PCB 해석이 정상 에너지 종료 조건을 충족하지 못했습니다.")
    pattern = r"RunFDTD: end-criteria of -([0-9.]+)dB reached after ([0-9]+) timesteps \(-([0-9.]+|inf)dB\)"
    matches = re.findall(pattern, log)
    target = -10 * math.log10(settings["end_criterion"])
    if len(matches) != 1 or int(matches[0][1]) != iterations or not 0 < iterations < settings["max_timesteps"] or abs(float(matches[0][0]) - target) > 0.011 or float(matches[0][2]) + 0.011 < target:
        fail("E_SOLVER", "PCB 종료 에너지 또는 반복 수의 근거가 다릅니다.")
    decay = float(matches[0][2])
    return {"status": "end_criterion_reached", "iterations": iterations, "target_energy_ratio": settings["end_criterion"],
            "reported_decay_db": decay if math.isfinite(decay) else None, "reported_zero_energy": math.isinf(decay),
            "evidence": list(matches[0]), "exact_endcriterion_schedule": True}


def validate_preparation(plan, preparation):
    """! @brief 실제 준비 통계/소비/정규화가 계획의 결정적 투영과 같은지 확인한다."""
    if preparation.get("radiation_recording") != plan["case"].get("radiation_recording"):
        fail("E_HASH", "NF2FF 준비 기록이 계획과 다릅니다.")
    lines = mesh_lines(plan["case"])
    mesh = preparation["mesh_statistics"]
    consumption = preparation["consumption_report"]
    counts = [len(lines[axis]) for axis in "xyz"]
    mappings = []
    for shape in plan["case"]["shapes"]:
        polygons = shape_polygons(shape, plan["case"]["settings"]["curve_tolerance_mm"])
        mappings.append({"source_entity_id": shape["id"], "native_property": "conductor_" + shape["id"],
                         "polygon_count": len(polygons), "polygon_point_count": sum(len(poly) for poly in polygons),
                         "curve_tolerance_mm": plan["case"]["settings"]["curve_tolerance_mm"], "sheet_z_mm": shape["sheet_z_mm"],
                         "modeled_thickness_m": shape["thickness_m"], "conductivity_s_per_m": shape["conductivity_s_per_m"]})
    via_mappings = [{"source_entity_id": via["id"], "native_property": "via_" + via["id"], "drill_property": "drill_" + via["id"],
                     "model": via["native_model"], "center_mm": via["center_mm"], "z_range_mm": [via["z_min_mm"], via["z_max_mm"]],
                     "inner_radius_mm": via["inner_radius_mm"], "outer_radius_mm": via["outer_radius_mm"],
                     "conductivity_s_per_m": via["conductivity_s_per_m"], "epsilon_r": via["epsilon_r"], "skin_depth_loss_validated": False,
                     "tool_hole_diameter_mm": via["tool_hole_diameter_mm"], "tool_hole_used_for_native_geometry": False, "native_drill_basis": "finished_hole_diameter"}
                    for via in plan["case"].get("vias", [])]
    connectivity = consumption.get("native_connectivity", {})
    expected_entities = sorted(item["id"] for item in plan["case"]["shapes"] + plan["case"].get("vias", []))
    records = connectivity.get("entities", [])
    if (connectivity.get("schema") != "rfad.pcb-native-connectivity/0.1" or connectivity.get("yee_connectivity_checked") is not True
            or connectivity.get("operator_coefficients_checked") is not False or connectivity.get("physics_validated") is not False
            or connectivity.get("port_terminals_connected") is not True or type(connectivity.get("port_gap_edge_count")) is not int
            or connectivity["port_gap_edge_count"] < 2 or connectivity.get("components") != sorted(plan["case"]["connectivity"]["components"])
            or type(records) is not list or [record.get("entity_id") for record in records] != expected_entities
            or any(type(record.get("conductor_edge_count")) is not int or record["conductor_edge_count"] <= 0 or record.get("component_count") != 1 for record in records)):
        fail("E_HASH", "PCB native 격자 연결/급전 보고가 계획한 도체와 다릅니다.")
    if (mesh.get("lines_mm") != lines or mesh.get("line_counts") != counts or mesh.get("native_grid_points") != math.prod(counts)
            or mesh.get("interval_counts") != [c - 1 for c in counts] or mesh.get("yee_interval_cells") != math.prod(c - 1 for c in counts)
            or mesh.get("fdtd_executed") is not False or mesh.get("native_preprocessing_executed") is not False
            or mesh.get("delta_unit_m") != 0.001 or mesh.get("native_length_unit") != "mm"
            or mesh.get("mesh_policy_report") != plan["case"].get("mesh_policy_report")
            or preparation.get("normalization") != plan["normalization"] or preparation["consumption_report"].get("consumed_case") != plan["case"]
            or consumption.get("project_geometry_consumed") is not True or consumption.get("project_materials_consumed") is not True
            or consumption.get("source_mapping") != mappings or consumption.get("fdtd_executed") is not False or consumption.get("physics_validated") is not False
            or consumption.get("board_native_primitive") != ("cylinder" if plan["case"]["board"]["kind"] == "circle" else "box")
            or consumption.get("approximations") != plan["model_report"]["approximations"]
            or consumption.get("via_source_mapping") != via_mappings
            or consumption.get("analysis_plan_id") != plan["plan_id"] or consumption.get("source") != "user_project"):
        fail("E_HASH", "PCB 준비된 격자/소비 보고 또는 정규화가 계획과 다릅니다.")


def validate_result(plan, result, prepared_plan=None):
    """! @brief 유한 복소 결과와 계산 상태를 검사하되 물리 검증 합격을 만들지 않는다."""
    if result.get("schema") != "rfad.openems-pcb-result/0.1" or result.get("analysis_plan_id") != plan["plan_id"] or result.get("normalization") != plan["normalization"]:
        fail("E_HASH", "PCB 정규화 결과의 계획 또는 단위가 다릅니다.")
    if prepared_plan is not None and result.get("prepared_plan_id") != prepared_plan["prepared_plan_id"]:
        fail("E_HASH", "PCB 결과의 준비 계획이 다릅니다.")
    frequency = plan["case"]["frequency_hz"]
    samples = result.get("samples", [])
    if len(samples) != frequency["count"]:
        fail("E_SOLVER", "PCB 결과 주파수 표본 수가 다릅니다.")
    for index, row in enumerate(samples):
        target = frequency["start"] + (frequency["stop"] - frequency["start"]) * index / (frequency["count"] - 1)
        if (type(row) is not dict or type(row.get("frequency_hz")) not in (int, float)
                or not frequency["start"] <= row["frequency_hz"] <= frequency["stop"] or abs(row["frequency_hz"] - target) > 1e-5):
            fail("E_HASH", "PCB 결과 주파수 축이 계획과 다릅니다.")
        for key in ("s11", "impedance_ohm"):
            pair = row.get(key)
            if type(pair) is not list or len(pair) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in pair):
                fail("E_SOLVER", "PCB 복소 결과는 유한한 실수 쌍이어야 합니다.")
        magnitude = math.hypot(*row["s11"])
        if not math.isfinite(magnitude):
            fail("E_SOLVER", "PCB 반사 계수의 크기가 유한 범위를 벗어났습니다.")
        expected_vswr = (1 + magnitude) / (1 - magnitude) if magnitude < 1 else None
        expected_db = 20 * math.log10(magnitude) if magnitude > 0 else None
        if row.get("vswr_status") != ("defined" if expected_vswr is not None else "undefined_reflection_ge_one"):
            fail("E_HASH", "PCB VSWR의 정의 상태가 반사 계수와 다릅니다.")
        for key, expected in (("vswr", expected_vswr), ("s11_db", expected_db)):
            actual = row.get(key)
            if expected is None:
                if actual is not None:
                    fail("E_HASH", "정의되지 않은 VSWR/dB를 유한한 합격값으로 대체할 수 없습니다.")
            elif type(actual) not in (int, float) or not math.isclose(expected, actual, rel_tol=1e-10, abs_tol=1e-12):
                fail("E_HASH", "복소 결과와 표시용 VSWR/dB가 다릅니다.")
    validate_radiation_summary(plan, result)
    if ("loss_recording" in plan["case"]) != ("power_balance" in result):
        fail("E_HASH", "독립 손실을 요청한 계획과 전력 수지 결과의 존재가 다릅니다.")
    expected_assessment = {"status": "computed_unvalidated", "physics_validated": False, "converged": True, "finite_samples": True}
    if result.get("assessment") != expected_assessment or result.get("termination", {}).get("status") != "end_criterion_reached":
        fail("E_SOLVER", "PCB 계산 완료와 물리 검증 합격을 구분해야 합니다.")


def validate_radiation_summary(plan, result):
    """! @brief 방사 요청과 결과 요약의 존재/주파수/단위가 대응하는지 확인한다."""
    recording = plan["case"].get("radiation_recording")
    summary = result.get("radiation_summary")
    if recording is None:
        if summary is not None:
            fail("E_HASH", "방사를 요청하지 않은 결과에 방사 요약이 있습니다.")
        return
    if (type(summary) is not dict or summary.get("frequency_hz") != recording["frequency_hz"]
            or summary.get("physics_validated") is not False or summary.get("absolute_power_w") is not None
            or summary.get("power_unit") != "W*s^2"):
        fail("E_HASH", "방사 결과 요약이 요청한 대역/정규화와 다릅니다.")
