"""! @brief 공통 결과 출처에 봉인된 방사 전계와 읽기 전용 3D 투영을 연결한다."""

from copy import deepcopy
import json
import math

from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_radiation import validate_result, summary
from rfad.application.result_sources import resolve, read_solver_artifact, validate_pin
from rfad.application.solver_requests import require_fields, require_uuid
from rfad.domain.errors import ProjectError
from rfad.domain.radiation_polarization import CONVENTION, polarization, projection


def request(params, optional=()):
    """! @brief 조회가 원본 선택과 검토 해시를 항상 명시하게 한다."""
    require_fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    require_fields(params["context"], {"project_id"})
    require_uuid(params["context"]["project_id"])
    data = require_fields(params["input"], {"source", "pin"}, optional)
    validate_pin(data["pin"])
    return data


def load(service, resolved):
    """! @brief 실제 해석 결과와 같은 NF2FF 산출물 및 요약만 읽는다."""
    record, normalized = resolved["solver_record"], resolved["normalized"]
    if record is None or normalized is None:
        raise ProjectError("E_UNSUPPORTED", "이 자료에는 같은 해석에서 기록한 방사 전계가 없습니다.")
    references = [item["artifact"] for item in record["files"] if item["role"] == "radiation_result"]
    if not references:
        raise ProjectError("E_MISSING_ARTIFACT", "이 결과에는 NF2FF 기록이 없습니다. 방사를 기록한 해석 결과를 선택하십시오.")
    if len(references) != 1:
        raise ProjectError("E_HASH", "방사 원본 참조가 중복되었습니다.")
    plan = normalized["provenance"]["analysis_plan"]
    value = json.loads(read_solver_artifact(service, resolved["project"], record, references[0]))
    validate_result(plan, value)
    if normalized.get("radiation_summary") != summary(value) or plan["snapshot"] != resolved["source_snapshot"]:
        raise ProjectError("E_HASH", "방사 원본과 선택한 계산의 출처 또는 요약이 다릅니다.")
    return value, deepcopy(references[0])


def _options(data):
    """! @brief 표시 선택은 유한한 열거형과 실제 기록 페이지로 한정한다."""
    frequency, offset, limit = (data.get(key, default) for key, default in
                                (("frequency_index", 0), ("theta_offset", 0), ("theta_limit", 5)))
    if any(type(x) is not int for x in (frequency, offset, limit)) or not 0 <= frequency < 3 or offset < 0 or not 1 <= limit <= 5:
        raise ProjectError("E_RESOURCE", "주파수와 theta 페이지 범위를 확인하십시오.")
    observable = data.get("observable", "total")
    scale = data.get("display_scale", "linear_amplitude")
    basis = data.get("polarization_basis", "theta_phi")
    floor = data.get("floor_db", -40)
    if (observable not in ("total", "e_theta", "e_phi", "rhcp", "lhcp", "directivity", "gain", "realized_gain")
            or scale not in ("linear_amplitude", "db_amplitude") or basis not in ("theta_phi", "theta_co", "phi_co")
            or type(floor) not in (float, int) or not -120 <= floor <= -10):
        raise ProjectError("E_SCHEMA", "지원하는 방사 관측량, 편파 기저와 표시 범위를 선택하십시오.")
    return frequency, offset, limit, observable, scale, basis, floor


def radiation(service, params):
    """! @brief 원본 전계, 편파와 투영을 크기 제한 페이지로 반환하며 계산을 실행하지 않는다."""
    data = request(params, {"frequency_index", "theta_offset", "theta_limit", "observable", "display_scale",
                            "floor_db", "polarization_basis"})
    frequency, offset, limit, observable, scale, basis, floor = _options(data)
    resolved = resolve(service, params["context"], data["source"], data["pin"])
    value, reference = load(service, resolved)
    recording = value["recording"]
    count = len(recording["theta_deg"])
    if frequency >= len(value["frequencies"]) or offset >= count:
        raise ProjectError("E_RESOURCE", "기록하지 않은 주파수 또는 각도입니다.")
    row = value["frequencies"][frequency]
    peak = max(math.hypot(*t, *p) for ts, ps in zip(row["e_theta"], row["e_phi"]) for t, p in zip(ts, ps))
    metric = observable if observable in ("directivity", "gain", "realized_gain") else None
    peak_quantity = row["metrics"][metric + "_linear"] if metric is not None else None
    peak_db = row["metrics"][metric + "_dbi"] if metric is not None else None
    result = {"profile": "rfad.result-radiation/0.1", "source": deepcopy(resolved["source"]), "pin": deepcopy(resolved["pin"]),
              "artifact_id": resolved["solver_result_id"], "snapshot": deepcopy(resolved["source_snapshot"]),
              "source_refs": [reference], "frequency_hz": deepcopy(recording["frequency_hz"]),
              "frequency_index": frequency, "theta_offset": offset, "theta_count": count, "returned_count": 0,
              "next_offset": offset, "theta_deg": [], "phi_deg": deepcopy(recording["phi_deg"]),
              "metrics": deepcopy(row["metrics"]), "radius_m": recording["radius_m"], "center_m": deepcopy(recording["center_m"]),
              "power_unit": value["power_unit"], "electric_field_unit": value["electric_field_unit"],
              "absolute_power_w": None, "physics_validated": False, "status": "computed_unvalidated",
              "states": deepcopy(resolved["states"]), "observable": observable, "display_scale": scale, "floor_db": floor,
              "normalization_basis": "sampled_total_field_peak", "normalization_peak_v_s_per_m": peak,
              "coordinate_unit": "dimensionless_display", "color_range": [floor, 0] if scale == "db_amplitude" else [0, 1],
              "color_unit": "dB" if scale == "db_amplitude" else "1", "directional_metric": metric,
              "polarization_basis": basis, "co_component": {"theta_co": "e_theta", "phi_co": "e_phi"}.get(basis),
              "cross_component": {"theta_co": "e_phi", "phi_co": "e_theta"}.get(basis),
              "polarization_convention": deepcopy(CONVENTION), "e_theta": [], "e_phi": [], "normalized_power": [],
              "directivity": [], "polarization": [], "projection": [],
              "interpolation": "none", "mesh_interpolation": "display_only"}
    if metric is not None:
        result["color_range"] = [peak_db + floor, peak_db] if scale == "db_amplitude" else [0, peak_quantity]
        result["color_unit"] = "dBi" if scale == "db_amplitude" else "1"
    arrays = ("theta_deg", "e_theta", "e_phi", "normalized_power", "directivity", "polarization", "projection")
    for index in range(offset, min(offset + limit, count)):
        result["theta_deg"].append(recording["theta_deg"][index])
        for key in ("e_theta", "e_phi", "normalized_power", "directivity"):
            result[key].append(deepcopy(row[key][index]))
        polar, projected = [], []
        for column, phi in enumerate(recording["phi_deg"]):
            theta_value, phi_value = row["e_theta"][index][column], row["e_phi"][index][column]
            details = polarization(theta_value, phi_value, phi)
            polar.append(details)
            amplitudes = {"total": math.hypot(*theta_value, *phi_value), "e_theta": math.hypot(*theta_value),
                          "e_phi": math.hypot(*phi_value), "rhcp": math.hypot(*details["rhcp_ri"]),
                          "lhcp": math.hypot(*details["lhcp_ri"])}
            amplitude = amplitudes["total" if metric is not None else observable] / peak
            point = projection(amplitude, recording["theta_deg"][index], phi, scale, floor)
            if metric is not None:
                quantity = row["normalized_power"][index][column] * peak_quantity
                quantity_db = 10 * math.log10(quantity) if quantity > 0 else None
                point.update(quantity_linear=quantity, quantity_db=quantity_db,
                             quantity_db_state="finite" if quantity_db is not None else "negative_infinity")
                point["color"] = (max(peak_db + floor, quantity_db) if quantity_db is not None else peak_db + floor) if scale == "db_amplitude" else quantity
            projected.append(point)
        result["polarization"].append(polar)
        result["projection"].append(projected)
        result.update(returned_count=index - offset + 1, next_offset=index + 1 if index + 1 < count else None)
        if len(canonical_bytes(result)) > 128 * 1024:
            for key in arrays:
                result[key].pop()
            if index == offset:
                raise ProjectError("E_RESOURCE", "한 각도 행이 방사 표시 전송 상한을 초과했습니다.")
            result.update(returned_count=index - offset, next_offset=index)
            break
    return result
