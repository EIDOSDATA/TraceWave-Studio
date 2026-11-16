"""! @brief 실제 Sii를 명시한 정합 종단 조건의 Smith 표시 수치로 투영한다."""

from copy import deepcopy
import math

from rfad.application.result_sources import fail


def _pair(value):
    """! @brief 유한 복소 결과만 반환하고 overflow를 0이나 pole로 바꾸지 않는다."""
    if math.isfinite(value.real) and math.isfinite(value.imag):
        return [float(value.real), float(value.imag)], "finite"
    return None, "nonfinite"


def _positive_real(value):
    """! @brief 복소/미정 기준 임피던스를 단순 실수 Smith 기준으로 대체하지 않는다."""
    return type(value) is list and len(value) == 2 and value[0] > 0 and value[1] == 0


def project(dataset, *, port=0, chart="impedance", offset=0, limit=201):
    """! @brief 표시 계산만 수행하며 원본 S와 주파수/출처/단위를 수정하지 않는다."""
    if dataset["parameter_kind"] != "S":
        fail("Smith 표시는 S 대각 채널을 사용합니다. S/Z/Y 변환을 명시적으로 검토하십시오.", "E_UNSUPPORTED")
    count = len(dataset["port_ids"])
    if type(port) is not int or not 0 <= port < count or chart not in ("impedance", "admittance"):
        fail("Smith 포트 또는 표시 종류가 유효하지 않습니다.")
    total = len(dataset["frequency_hz"])
    if type(offset) is not int or not 0 <= offset < total or type(limit) is not int or not 1 <= limit <= 201:
        fail("Smith 표본은 유효한 시작 순번과 1~201개 크기로 조회하십시오.", "E_RESOURCE")
    reasons = []
    if dataset["wave_definition"] == "unknown":
        reasons.append("wave_definition_unknown")
    if dataset["phasor_convention"] == "unknown":
        reasons.append("phasor_convention_unknown")
    if any(value != "single_ended" for value in dataset["port_modes"]):
        reasons.append("port_mode_unsupported")
    if any(value != "into_dut" for value in dataset["current_orientation"]):
        reasons.append("current_orientation_unknown")
    points = []
    for index in range(offset, min(offset + limit, total)):
        pair = deepcopy(dataset["values_ri"][index][port][port])
        valid = dataset["valid_mask"][index][port][port]
        point_reasons = list(reasons)
        references = None if dataset["z0_ohm"] is None else dataset["z0_ohm"][index]
        if references is None or any(not _positive_real(value) for value in references):
            point_reasons.append("real_positive_z0_required")
        if not valid:
            point_reasons.append("masked_sample")
        z0 = None if references is None else deepcopy(references[port])
        point = {"index": index, "frequency_hz": dataset["frequency_hz"][index], "gamma_ri": pair,
                 "z0_ohm": z0, "normalized_impedance_ri": None, "normalized_admittance_ri": None,
                 "input_impedance_ohm_ri": None, "input_admittance_siemens_ri": None,
                 "impedance_state": "unavailable", "admittance_state": "unavailable",
                 "normalized_impedance_state": "unavailable", "normalized_admittance_state": "unavailable",
                 "passivity_region": "unknown", "status": dataset["sample_status"][index][port][port],
                 "origin": dataset["sample_origin"][index], "smith_valid": not point_reasons,
                 "projection_status": "unavailable" if point_reasons else "valid", "reasons": point_reasons}
        if not point_reasons:
            gamma = complex(*pair)
            magnitude = math.hypot(*pair)
            point["passivity_region"] = "active_region" if magnitude > 1 else "unit_circle" if magnitude == 1 else "inside_unit_circle"
            if gamma == 1:
                point.update(normalized_impedance_state="infinite", impedance_state="infinite")
            else:
                normalized = (1 + gamma) / (1 - gamma)
                point["normalized_impedance_ri"], point["normalized_impedance_state"] = _pair(normalized)
                point["input_impedance_ohm_ri"], point["impedance_state"] = _pair(normalized * z0[0])
            if gamma == -1:
                point.update(normalized_admittance_state="infinite", admittance_state="infinite")
            else:
                normalized = (1 - gamma) / (1 + gamma)
                point["normalized_admittance_ri"], point["normalized_admittance_state"] = _pair(normalized)
                point["input_admittance_siemens_ri"], point["admittance_state"] = _pair(normalized / z0[0])
            if any(point[key] == "nonfinite" for key in ("normalized_impedance_state", "normalized_admittance_state", "impedance_state", "admittance_state")):
                point["projection_status"] = "nonfinite_projection"
                point["reasons"].append("nonfinite_projection")
        points.append(point)
    return {"chart": chart, "channel": {"row": port, "column": port}, "points": points,
            "termination": "other_ports_matched_to_their_recorded_z0", "impedance_meaning": "driving_point_input_not_z_matrix_diagonal",
            "offset": offset, "total": total, "next_offset": offset + len(points) if offset + len(points) < total else None,
            "physics_validated": False}
