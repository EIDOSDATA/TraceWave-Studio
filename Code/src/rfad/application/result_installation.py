"""! @brief 동일 기판과 급전의 설치 비교용 효율과 방사 단면을 읽는다."""

import math

from rfad.application.result_radiation import load
from rfad.application.pcb_surfaces import surface_label
from rfad.domain.errors import ProjectError
from rfad.domain.network_assessment import reflection_metrics
from rfad.domain.radiation_polarization import CONVENTION


def _part_label(part):
    """! @brief 같은 부품 이름을 유지한 경우에도 해석의 접지 상태를 알려 준다."""
    state = {"isolated": " (비접촉)", "grounded": " (접지 연결)"}.get(part.get("electrical_connection"), "")
    return part["name"] + state


def _reflection(dataset, frequency):
    """! @brief 방사 주파수에 복소 원본이 있을 때만 S11과 VSWR을 계산한다."""
    result = {"status": "not_recorded", "z0_ohm": None, "s11_ri": None, "s11_db": None, "vswr": None}
    grid = dataset["frequency_hz"]
    if frequency not in grid:
        return result
    index = grid.index(frequency)
    result["z0_ohm"] = None if dataset["z0_ohm"] is None else dataset["z0_ohm"][index][0]
    if dataset["valid_mask"][index][0][0]:
        pair = dataset["values_ri"][index][0][0]
        result.update(status="recorded", s11_ri=pair, **reflection_metrics(complex(*pair)))
    return result


def _fields_at(source, case, frequency):
    """! @brief 같은 주파수에서 원시 파일을 보존한 기록 성분을 식별한다."""
    if frequency not in case.get("loss_recording", {}).get("frequency_hz", []):
        return []
    roles = {row["role"] for row in source["solver_record"].get("raw_files", [])}
    return [field for field in ("E", "J", "rotH") if f"raw/pcb_loss_{field}.h5" in roles]


def compare(service, left, right):
    """! @brief 실제 공통 표본의 효율과 실현 이득을 같은 조건에서 비교한다."""
    pair = (left, right)
    plans = [item["normalized"]["provenance"]["analysis_plan"] if item["normalized"] is not None else {}
             for item in pair]
    cases = [plan.get("case", {}) for plan in plans]
    if not any("environment" in case or "surface_layers" in case for case in cases):
        return None
    surfaces = [row for case in cases for row in case.get("surface_layers", [])]
    empty_surface = "마스크 없음" if any(row["kind"] == "solder_mask" for row in surfaces) else "표면층 없음"
    names = [" / ".join(filter(None, (case.get("environment", {}).get("name", ""),
                                      (surface_label(case) or empty_surface) if surfaces else ""))) or "기판 단독"
             for case in cases]
    if names[0] == names[1]:
        names = [name + " / " + ("기준 결과" if index == 0 else "비교 결과") + " / " +
                 ", ".join(_part_label(part) for part in case.get("environment", {}).get("parts", []))
                 for index, (name, case) in enumerate(zip(names, cases))]
    identity = ("board", "layers", "shapes", "vias", "mechanical_voids",
                "port", "settings", "frequency_hz", "excitation", "boundary_conditions")
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
    if any(recording[key] != other[key] for key in ("frequency_hz", "theta_deg", "phi_deg", "radius_m", "center_m", "surrounding_medium")):
        return {"reason": "같은 주파수, 방사 중심, 반경과 각도에서 기록한 결과를 선택하십시오."}
    if first["power_unit"] != second["power_unit"] or first["electric_field_unit"] != second["electric_field_unit"]:
        return {"reason": "방사 전력 또는 전계의 원래 정규화 단위가 다릅니다."}
    phi = [angle for angle in (0, 90) if angle in recording["phi_deg"]]
    columns = [recording["phi_deg"].index(angle) for angle in phi]
    observables = ("directivity", "gain", "realized_gain")
    frequencies = []
    for a, b in zip(first["frequencies"], second["frequencies"]):
        rows = []
        for item, source, case in zip((a, b), pair, cases):
            metric = item["metrics"]
            peaks = {kind: metric[kind + "_dbi"] for kind in observables}
            cuts = {kind: [[None if ring[column] <= 0 or peak is None else peak + 10 * math.log10(ring[column])
                            for ring in item["normalized_power"]] for column in columns] for kind, peak in peaks.items()}
            rows.append({"radiation_efficiency": metric["radiation_efficiency"],
                         "total_efficiency": metric["radiated_power_w_s2"] / metric["incident_power_w_s2"],
                         "power_balance_status": metric["power_balance_status"], "realized_gain_cuts_dbi": cuts["realized_gain"],
                         "cuts_dbi": cuts, "peaks_dbi": peaks,
                         "power": {kind: metric[kind + "_power_w_s2"] for kind in ("radiated", "accepted", "incident")},
                         "reflection": _reflection(source["dataset"], item["frequency_hz"]),
                         "field_recordings": _fields_at(source, case, item["frequency_hz"]),
                         "termination": source["numerical_details"]["status"]})
        frequencies.append({"frequency_hz": a["frequency_hz"], "results": rows})
    return {"names": names, "theta_deg": recording["theta_deg"], "phi_deg": phi, "frequencies": frequencies,
            "center_m": recording["center_m"], "radius_m": recording["radius_m"], "power_unit": first["power_unit"],
            "reference_plane": left["dataset"]["reference_planes"][0],
            "polarization_basis": "theta_phi", "polarization_convention": CONVENTION, "physics_validated": False}
