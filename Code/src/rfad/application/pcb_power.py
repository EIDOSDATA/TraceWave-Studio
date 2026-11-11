"""! @brief 선택적 독립 흡수 적분의 입력, 기록 영역과 전력 수지 계약을 정의한다."""

from bisect import bisect_left, bisect_right
import math

from rfad.application.pcb_geometry import fail


SCHEMA = "rfad.pcb-power-balance/0.1"
NAMES = ("pcb_loss_E.h5", "pcb_loss_J.h5", "pcb_loss_rotH.h5")


def validate_settings(settings):
    """! @brief 방사와 같은 직접 포트 주파수 및 사전에 정한 잔차 기준만 허용한다."""
    if "power_balance" not in settings:
        return
    value = settings["power_balance"]
    if (type(value) is not dict or set(value) != {"max_relative_residual"}
            or type(value["max_relative_residual"]) not in (int, float)
            or not 1e-4 <= value["max_relative_residual"] <= 0.1 or "radiation" not in settings):
        fail("E_SCHEMA", "전체 전력 수지에는 방사 설정과 0.0001~0.1의 명시적 상대 잔차 기준이 필요합니다.", "settings.power_balance")
    band = settings["frequency_hz"]
    for frequency in settings["radiation"]["frequency_hz"]:
        index = (frequency - band["start"]) / (band["stop"] - band["start"]) * (band["count"] - 1)
        if not math.isclose(index, round(index), rel_tol=0, abs_tol=1e-8):
            fail("E_SCHEMA", "전체 전력 수지는 보간하지 않는 직접 포트 주파수가 필요합니다.", "settings.radiation.frequency_hz")


def recording(case, lines):
    """! @brief 물체 주위 한 격자 여유의 무보간 Yee 전기 edge를 기록한다."""
    if "power_balance" not in case["settings"]:
        return None
    bounds = [*case["board"]["bounds_mm"],
              [min(layer["z_min_mm"] for layer in case["layers"]),
               max(layer["z_min_mm"] + layer["thickness_mm"] for layer in case["layers"])]]
    starts, stops = [], []
    for axis, (low, high) in zip("xyz", bounds):
        values = lines[axis]
        first, last = bisect_left(values, low) - 1, bisect_right(values, high)
        if first < 10 or last >= len(values) - 10:
            fail("E_GEOMETRY", "손실 기록 영역과 PML 사이의 공기 여유가 부족합니다.", "settings.power_balance")
        starts.append(first)
        stops.append(last)
    points = math.prod(b - a + 1 for a, b in zip(starts, stops))
    # @brief 세 벡터/복소 float32/세 dump와 주파수, HDF 및 기존 방사 파일의 여유를 선계산한다.
    estimated = points * 3 * 8 * len(case["radiation_recording"]["frequency_hz"]) * 3
    from rfad.application.pcb_compute import limits

    maximum = limits(case["settings"]).get("max_loss_field_bytes", 48 * 1024 * 1024)
    if estimated > maximum:
        fail("E_RESOURCE", f"독립 손실 필드 기록의 {maximum // (1024 * 1024)} MiB 예산을 초과했습니다.", "settings.power_balance")
    result = {"schema": "rfad.pcb-loss-recording/0.1", "start_indices": starts, "stop_indices": stops,
            "start_mm": [lines[axis][i] for axis, i in zip("xyz", starts)],
            "stop_mm": [lines[axis][i] for axis, i in zip("xyz", stops)],
            "primitive_start_mm": [lines[axis][i] + (lines[axis][i + 1] - lines[axis][i]) * 0.25 for axis, i in zip("xyz", starts)],
            "primitive_stop_mm": [lines[axis][i] - (lines[axis][i] - lines[axis][i - 1]) * 0.25 for axis, i in zip("xyz", stops)],
            "frequency_hz": case["radiation_recording"]["frequency_hz"], "dump_mode": 0,
            "dump_types": [10, 12, 13], "estimated_field_bytes": estimated,
            "method": "yee_edge_e_j_and_sheet_e_roth", "volume_conductor_supported": False}
    if case.get("vias"):
        result.update(schema="rfad.pcb-loss-recording/0.2", method="quarter_cell_volume_and_native_sheet_override/0.1", volume_conductor_supported=True)
    return result


def raw_names(plan):
    """! @brief 기존 결과 계약은 유지하고 명시적으로 요청한 경우만 원시 필드를 추가한다."""
    return NAMES if "loss_recording" in plan["case"] else ()


def balance_rows(recording, radiation, losses, threshold):
    """! @brief 독립 필드 적분을 수용 전력과 비교하며 부호 있는 잔차를 보존한다."""
    rows = []
    for field, loss in zip(radiation["frequencies"], losses):
        metrics = field["metrics"]
        incident, accepted, radiated = [metrics[key] for key in
                                        ("incident_power_w_s2", "accepted_power_w_s2", "radiated_power_w_s2")]
        dielectric, conductor = loss["dielectric_loss_w_s2"], loss["conductor_loss_w_s2"]
        values = (incident, accepted, radiated, dielectric, conductor)
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in values) or accepted <= 0:
            fail("E_SOLVER", "독립 전력 수지의 전력은 유한하고 수용 전력은 양수여야 합니다.")
        residual = accepted - radiated - dielectric - conductor
        fraction = residual / accepted
        components = [*loss["sheet_components"], *loss.get("via_components", []), *loss.get("dielectric_components", [])]
        passed = abs(fraction) <= threshold and dielectric >= 0 and conductor >= 0 and all(item["loss_w_s2"] >= 0 for item in components)
        rows.append({"frequency_hz": field["frequency_hz"], "incident_power_w_s2": incident,
                     "reflected_power_w_s2": incident - accepted, "accepted_power_w_s2": accepted,
                     "radiated_power_w_s2": radiated, **loss,
                     "independent_absorption_power_w_s2": dielectric + conductor,
                     "inferred_loss_w_s2": accepted - radiated, "residual_w_s2": residual,
                     "relative_residual": fraction, "status": "within_initial_numerical_budget" if passed else "requires_review"})
    if len(losses) != len(recording["frequency_hz"]) or len(rows) != len(recording["frequency_hz"]):
        fail("E_HASH", "손실과 방사의 직접 주파수 표본 수가 다릅니다.")
    return rows


def validate_result(plan, result, radiation):
    """! @brief 별도 손실 산출물의 식별, 분할 합계와 기준별 상태를 재계산한다."""
    recording = plan["case"].get("loss_recording")
    if (recording is None or type(result) is not dict or result.get("schema") != SCHEMA
            or result.get("analysis_plan_id") != plan["plan_id"] or result.get("recording") != recording
            or result.get("power_unit") != "W*s^2" or result.get("absolute_power_w") is not None
            or any(result.get(key) is not False for key in ("physics_validated", "fabrication_validated", "measurement_validated"))):
        fail("E_HASH", "독립 손실 결과의 계획/기록/정규화가 다릅니다.")
    threshold = plan["case"]["settings"]["power_balance"]["max_relative_residual"]
    rows = result.get("frequencies", [])
    losses = []
    for row in rows:
        components = row.get("sheet_components", [])
        if (type(components) is not list or any(type(item.get("loss_w_s2")) not in (int, float)
                                               or not math.isfinite(item["loss_w_s2"]) for item in components)
                or {item.get("entity_id") for item in components} != {shape["id"] for shape in plan["case"]["shapes"]}
                or len(components) != len(plan["case"]["shapes"])
                or not math.isclose(math.fsum(item["loss_w_s2"] for item in components), row.get("sheet_loss_w_s2", row.get("conductor_loss_w_s2", math.nan)), rel_tol=1e-10, abs_tol=0)):
            fail("E_HASH", "도체별 독립 손실 분할의 합계/원본 식별자가 다릅니다.")
        keys = ["dielectric_loss_w_s2", "conductor_loss_w_s2", "sheet_components"]
        if "via_components" in row or plan["case"].get("vias"):
            from rfad.application.pcb_loss_components import validate_components

            validate_components(plan, row)
            keys += ["sheet_loss_w_s2", "via_loss_w_s2", "via_components", "dielectric_components"]
        losses.append({key: row[key] for key in keys})
    expected = balance_rows(recording, radiation, losses, threshold)
    if any("via_components" in row for row in rows) or plan["case"].get("vias"):
        from rfad.application.pcb_loss_components import validate_audit

        validate_audit(plan, result)
    if rows != expected or result.get("max_relative_residual") != threshold or result.get("full_energy_closure") != (
            "within_initial_numerical_budget" if all(row["status"] == "within_initial_numerical_budget" for row in expected) else "requires_review"):
        fail("E_HASH", "독립 손실의 합계/잔차 또는 초기 수치 판정이 다릅니다.")
