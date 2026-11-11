"""! @brief 사용자 PCB의 선택적 NF2FF 입력과 공기 기록 상자 계약을 정의한다."""

from copy import deepcopy
import math

from rfad.application.pcb_geometry import fail


SCHEMA = "rfad.pcb-radiation/0.1"
NAME = "pcb_nf2ff"


def validate_settings(settings):
    """! @brief 방사 계산은 명시한 대역 내 주파수와 유한 각도 격자만 사용한다."""
    value = settings.get("radiation")
    if value is None:
        if "radiation" in settings:
            fail("E_SCHEMA", "방사 설정은 명시적 객체여야 합니다.", "settings.radiation")
        return
    if type(value) is not dict or set(value) != {"frequency_hz", "theta_step_deg", "phi_step_deg"}:
        fail("E_SCHEMA", "방사 주파수와 theta/phi 간격이 필요합니다.", "settings.radiation")
    frequencies = value["frequency_hz"]
    band = settings["frequency_hz"]
    if (type(frequencies) is not list or not 1 <= len(frequencies) <= 3
            or any(type(f) not in (int, float) or not band["start"] <= f <= band["stop"] for f in frequencies)
            or any(a >= b for a, b in zip(frequencies, frequencies[1:]))):
        fail("E_SCHEMA", "방사 주파수는 해석 대역 안의 증가하는 1~3개 수치여야 합니다.", "settings.radiation.frequency_hz")
    for key in ("theta_step_deg", "phi_step_deg"):
        if type(value[key]) is not int or value[key] not in (5, 10, 15, 30):
            fail("E_RESOURCE", "방사 각도 간격은 5/10/15/30 degree를 지원합니다.", "settings.radiation." + key)


def recording(case, lines):
    """! @brief 물리 기판 전체와 PML 사이의 공기 안에 격자 정렬된 폐곡면을 배치한다."""
    if "radiation" not in case["settings"]:
        return None
    z = [v for layer in case["layers"] for v in (layer["z_min_mm"], layer["z_min_mm"] + layer["thickness_mm"])]
    physical = [*case["board"]["bounds_mm"], [min(z), max(z)]]
    low, high = [], []
    for axis, bounds in zip("xyz", physical):
        values = lines[axis]
        if len(values) <= 22 or not values[10] < bounds[0] or not values[-11] > bounds[1]:
            fail("E_GEOMETRY", "NF2FF 폐곡면과 기판 및 PML 사이에 공기 격자가 부족합니다. 공기 여백을 늘리십시오.", "settings.air_padding_mm")
        low.append(values[10])
        high.append(values[-11])
    value = case["settings"]["radiation"]
    return {"schema": "rfad.nf2ff-recording/0.1", "name": NAME, "start_mm": low, "stop_mm": high,
            "center_m": [(a + b) * 0.0005 for a, b in zip(low, high)], "radius_m": 1.0,
            "frequency_hz": deepcopy(value["frequency_hz"]),
            "theta_deg": list(range(0, 181, value["theta_step_deg"])),
            "phi_deg": list(range(0, 360, value["phi_step_deg"])),
            "pml_separation_cells": 2, "surrounding_medium": "vacuum",
            "field_recording": "frequency_domain", "physics_validated": False}


def surface_names(plan):
    """! @brief 모서리 6면의 E/H 원시 파일을 정확히 한 번씩 요구한다."""
    if "radiation_recording" not in plan["case"]:
        return ()
    return tuple(f"{NAME}_{field}_{index}.h5" for field in ("E", "H") for index in range(6))


def raw_names(plan):
    """! @brief 기존 포트 원시 계약을 유지하며 선택한 경우에만 기록 면을 추가한다."""
    from rfad.application.pcb_results import RAW_NAMES

    return (*RAW_NAMES, *surface_names(plan))


def _number(value):
    """! @brief 방사 결과에서 bool이나 비유한 수치를 수용하지 않는다."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_result(plan, value):
    """! @brief 주파수/각도/복소 필드와 전력 비율을 검증하며 물리 합격으로 승격하지 않는다."""
    from rfad.application.radiation import spectral_power_metrics

    expected = plan["case"].get("radiation_recording")
    if expected is None or type(value) is not dict or value.get("schema") != SCHEMA:
        fail("E_VERSION", "요청한 PCB 방사 결과가 아닙니다.")
    if (value.get("analysis_plan_id") != plan["plan_id"] or value.get("recording") != expected
            or value.get("physics_validated") is not False or value.get("absolute_power_w") is not None
            or value.get("power_unit") != "W*s^2" or value.get("electric_field_unit") != "V*s/m"):
        fail("E_HASH", "방사 결과의 계획, 정규화 또는 기록 상자가 다릅니다.")
    rows = value.get("frequencies")
    if type(rows) is not list or len(rows) != len(expected["frequency_hz"]):
        fail("E_HASH", "방사 결과 주파수 개수가 다릅니다.")
    nt, np = len(expected["theta_deg"]), len(expected["phi_deg"])
    for frequency, row in zip(expected["frequency_hz"], rows):
        if type(row) is not dict or row.get("frequency_hz") != frequency:
            fail("E_HASH", "방사 결과 주파수가 다릅니다.")
        metrics = row.get("metrics", {})
        try:
            checked = spectral_power_metrics(metrics["radiated_power_w_s2"], metrics["accepted_power_w_s2"],
                                              metrics["incident_power_w_s2"], metrics["directivity_linear"])
        except (ValueError, KeyError, TypeError):
            fail("E_SOLVER", "방사 전력 비율을 확인할 수 없습니다.")
        if (metrics.keys() != checked.keys() or any(
                not (_number(metrics[key]) and math.isclose(metrics[key], expected_value, rel_tol=1e-10, abs_tol=0))
                if type(expected_value) in (int, float) else metrics[key] != expected_value
                for key, expected_value in checked.items())):
            fail("E_HASH", "지향성/이득/효율이 기록한 전력 비율과 다릅니다.")
        fields = {key: row.get(key) for key in ("e_theta", "e_phi", "normalized_power", "directivity")}
        for key, matrix in fields.items():
            if type(matrix) is not list or len(matrix) != nt or any(type(line) is not list or len(line) != np for line in matrix):
                fail("E_HASH", "방사 각도 격자의 크기가 다릅니다.")
            for line in matrix:
                for cell in line:
                    if key.startswith("e_"):
                        if type(cell) is not list or len(cell) != 2 or not all(_number(x) for x in cell):
                            fail("E_SOLVER", "방사 복소 필드가 유효하지 않습니다.")
                    elif not _number(cell) or cell < 0:
                        fail("E_SOLVER", "방사 전력 패턴이 유효하지 않습니다.")
        power = [[sum(x * x for key in ("e_theta", "e_phi") for x in fields[key][i][j])
                  for j in range(np)] for i in range(nt)]
        peak = max(max(line) for line in power)
        if not _number(peak) or peak <= 0:
            fail("E_SOLVER", "방사 필드를 정규화할 수 없습니다.")
        for i in range(nt):
            for j in range(np):
                normalized = power[i][j] / peak
                if (not math.isclose(fields["normalized_power"][i][j], normalized, rel_tol=1e-10, abs_tol=1e-12)
                        or not math.isclose(fields["directivity"][i][j], normalized * metrics["directivity_linear"], rel_tol=1e-10, abs_tol=1e-12)):
                    fail("E_HASH", "복소 필드와 전력 패턴이 다릅니다.")


def summary(value):
    """! @brief 큰 복소 필드 배열을 일반 결과 DTO에 중복하지 않는다."""
    return {"profile": SCHEMA, "frequency_hz": deepcopy(value["recording"]["frequency_hz"]),
            "metrics": [{"frequency_hz": row["frequency_hz"], **deepcopy(row["metrics"])} for row in value["frequencies"]],
            "power_unit": "W*s^2", "absolute_power_w": None, "physics_validated": False}
