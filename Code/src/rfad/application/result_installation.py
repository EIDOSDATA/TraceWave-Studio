"""! @brief 동일 기판과 급전의 설치 비교용 효율과 방사 단면을 읽는다."""

import math

from rfad.application.result_radiation import load
from rfad.domain.errors import ProjectError


def compare(service, left, right):
    """! @brief 실제 공통 표본의 효율과 실현 이득을 같은 조건에서 비교한다."""
    pair = (left, right)
    plans = [item["normalized"]["provenance"]["analysis_plan"] if item["normalized"] is not None else {}
             for item in pair]
    cases = [plan.get("case", {}) for plan in plans]
    if not any("environment" in case for case in cases):
        return None
    names = [case.get("environment", {}).get("name", "기판 단독") for case in cases]
    identity = ("board", "layers", "shapes", "vias", "port", "settings", "frequency_hz", "excitation", "boundary_conditions")
    if (any(plan.get("analysis_profile") != "rfad.openems.pcb-single-port/0.1" for plan in plans)
            or any(cases[0].get(key) != cases[1].get(key) for key in identity)):
        return {"reason": "같은 PCB, 급전과 해석 조건의 두 결과를 선택하십시오."}
    fixed_material_ids = {item["material_id"] for key in ("layers", "shapes", "vias") for item in cases[0][key]}
    material_sets = [{item["id"]: item for item in case["materials"] if item["id"] in fixed_material_ids}
                     for case in cases]
    if material_sets[0] != material_sets[1]:
        return {"reason": "기판의 계산 물성이 다른 결과입니다."}
    if not all("radiation_recording" in case for case in cases):
        return {"reason": "두 해석 모두에서 방사 기록을 지정하십시오."}
    try:
        first, second = [load(service, item)[0] for item in pair]
    except ProjectError as error:
        if error.code != "E_MISSING_ARTIFACT":
            raise
        return {"reason": "선택한 결과의 방사 기록을 다시 열 수 없습니다."}
    recording = first["recording"]
    other = second["recording"]
    if any(recording[key] != other[key] for key in ("frequency_hz", "theta_deg", "phi_deg", "radius_m")):
        return {"reason": "같은 주파수와 각도에서 기록한 방사 결과를 선택하십시오."}
    frequencies = []
    for a, b in zip(first["frequencies"], second["frequencies"]):
        rows = []
        for item in (a, b):
            metric = item["metrics"]
            peak = metric["realized_gain_dbi"]
            cuts = [[None if ring[column] <= 0 or peak is None else peak + 10 * math.log10(ring[column])
                     for ring in item["normalized_power"]] for column in (0, recording["phi_deg"].index(90))]
            rows.append({"radiation_efficiency": metric["radiation_efficiency"],
                         "total_efficiency": metric["radiated_power_w_s2"] / metric["incident_power_w_s2"],
                         "power_balance_status": metric["power_balance_status"], "realized_gain_cuts_dbi": cuts})
        frequencies.append({"frequency_hz": a["frequency_hz"], "results": rows})
    return {"names": names, "theta_deg": recording["theta_deg"], "phi_deg": [0, 90], "frequencies": frequencies,
            "physics_validated": False}
