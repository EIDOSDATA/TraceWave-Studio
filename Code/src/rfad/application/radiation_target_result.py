"""! @brief 스냅샷의 목표를 실제 기록한 방사 각도 표본에서 평가한다."""

from copy import deepcopy
import math

from rfad.application.canonical import canonical_hash
from rfad.domain.errors import ProjectError
from rfad.domain.radiation_polarization import CONVENTION, polarization


def describe(document):
    """! @brief 현재 결과의 원본 개정에 관측 조건이 남은 목표만 열거한다."""
    return [{"id": target["id"], "name": target["name"]} for target in document["targets"] if "observation" in target]


def evaluate(target, radiation, port_id, normalization):
    """! @brief 누락한 각도, 급전 및 편파를 보간하거나 가정하지 않는다."""
    point = target["observation"]
    result = {"target_id": target["id"], "target_revision_id": target["revision_id"], "target_hash": canonical_hash(target),
              "name": target["name"], "observation": deepcopy(point), "source_refs": deepcopy(target["source_refs"]),
              "polarization_convention": CONVENTION["profile"], "physics_validated": False,
              "gain_dbi": None, "value_state": "unrecorded", "status": "not_evaluated"}
    required = ("frequency", "theta_deg", "phi_deg", "polarization")
    if any(point[key] is None for key in required):
        return {**result, "reason": "관측 주파수, 방향 또는 편파가 미정입니다."}
    if (target["port_id"] != port_id or target.get("reference_plane") is None or
            target["reference_plane"] != normalization["reference_plane"] or
            target["reference_impedance"]["value_si"] != normalization["reference_impedance_ohm"]):
        return {**result, "reason": "목표 포트, 기준면 또는 Z0가 해석의 급전 조건과 다르거나 미정입니다."}
    recording = radiation["recording"]
    try:
        frequency = recording["frequency_hz"].index(point["frequency"]["value_si"])
        theta = recording["theta_deg"].index(point["theta_deg"])
        phi = recording["phi_deg"].index(point["phi_deg"])
    except ValueError:
        return {**result, "reason": "요청한 Hz와 theta/phi의 정확한 기록 표본이 없습니다."}
    row = radiation["frequencies"][frequency]
    e_theta, e_phi = row["e_theta"][theta][phi], row["e_phi"][theta][phi]
    power = row["normalized_power"][theta][phi]
    component = point["polarization"]
    fraction = 1.0
    if component != "total" and power > 0.0:
        peak_scale = max(abs(value) for pair in (e_theta, e_phi) for value in pair)
        if peak_scale == 0.0:
            return {**result, "reason": "편파를 계산할 유효한 복소 전계가 없습니다."}
        e_theta, e_phi = ([value / peak_scale for value in pair] for pair in (e_theta, e_phi))
        if component in ("theta", "phi"):
            selected = e_theta if component == "theta" else e_phi
        else:
            selected = polarization(e_theta, e_phi, point["phi_deg"])[component + "_ri"]
        fraction = min(1.0, math.hypot(*selected) / math.hypot(*e_theta, *e_phi))
    db = None
    if fraction > 0.0 and power > 0.0:
        db = row["metrics"]["realized_gain_dbi"] + 10 * math.log10(power) + 20 * math.log10(fraction)
    limit = point["minimum_gain_dbi"]
    status = "recorded" if limit is None else "conditional" if db is not None and db >= limit else "fail"
    return {**result, "gain_dbi": db, "value_state": "finite" if db is not None else "negative_infinity",
            "status": status, "reason": "기록한 단일 방향의 계산값입니다."}


def result_for(resolved, radiation, target_id):
    """! @brief 계산 스냅샷의 목표·급전만 읽으며 현재 설계의 다른 목표로 대체하지 않는다."""
    document = resolved["source_document"]
    target = next((row for row in document["targets"] if row["id"] == target_id and "observation" in row), None)
    if target is None:
        raise ProjectError("E_CONFLICT", "이 계산의 원본 개정에 선택한 방사 관측 목표가 없습니다.")
    original = resolved["normalized"]
    port = original["provenance"]["analysis_plan"]["case"]["port"]
    return evaluate(target, radiation, port["id"], original["normalization"])
