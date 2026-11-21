"""! @brief 봉인된 RO4350B 동박 전계와 면 전류를 대칭 slab의 독립 물성식과 대조한다."""

import argparse
import json
import math
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))

from rfad.adapters.solvers.openems.native import file_identity, require
from rfad.adapters.solvers.openems.pcb_absorption import edge_weights, read_fields, sheet_partition
from rfad.application.pcb_mesh import mesh_lines
from rfad.domain.rf_reference import symmetric_sheet_impedance


def verify(path, record):
    """! @brief 연구가 참조한 크기와 해시를 원본에서 읽어 일치 여부를 확인한다."""
    identity = file_identity(path)
    require(all(record[key] == value for key, value in identity.items()), "봉인된 손실 자료가 다릅니다.", "E_HASH")


def sheet_width_fraction(partition):
    """! @brief native sheet 둘레의 반 폭 규칙을 반영할 면적 비율을 얻는다."""
    import numpy as np

    fractions = []
    for tangent in (1, 0):
        across = partition[tangent] >= 0
        previous = np.roll(across, 1, axis=tangent)
        previous.swapaxes(0, tangent)[0] = False
        fractions.append(np.where(across & previous, 1.0, 0.5))
    return np.stack(fractions)


def ade_parameter_table(path):
    """! @brief 같은 버전의 openEMS 소스에서 실제 사용한 ADE 표만 읽는다."""
    fields = ("omega_stop", "g", "r1", "l1", "r2", "l2")
    require(0 < path.stat().st_size <= 32 * 1024, "ADE 표 크기가 유효하지 않습니다.")
    text = path.read_text(encoding="utf-8")
    series = []
    for field in fields:
        row = re.search(r"^double " + field + r"\[\d+\]\s*=\s*\{([^}]+)\}", text, re.M)
        require(row is not None, "ADE 계수의 배열이 누락됐습니다.")
        values = [float(value) for value in row[1].split(",")]
        require(all(math.isfinite(value) and value > 0 for value in values), "ADE 계수가 유효하지 않습니다.")
        series.append(values)
    return list(zip(*series, strict=True))


def ade_impedance(frequency, timestep, sigma, thickness, excitation, table):
    """! @brief 두 직렬 RL 분기와 병렬 컨덕턴스/수치 커패시턴스의 면 임피던스를 구한다."""
    dc_conductance = sigma * thickness
    w0 = 8 / (dc_conductance * thickness * (4e-7 * math.pi))
    omega_max = math.tau * (excitation["center_hz"] + excitation["width_hz"]) / w0
    _, g, r1, l1, r2, l2 = next((row for row in table if row[0] > omega_max), table[-1])
    resistances = (r1 / dc_conductance, r2 / dc_conductance)
    inductances = (l1 / (dc_conductance * w0), l2 / (dc_conductance * w0))
    capacitance = timestep**2 / 4 * (16 / min(inductances) + sum(1 / item for item in inductances))
    omega = 2 * math.tan(math.pi * frequency * timestep) / timestep
    admittance = g * dc_conductance + 1j * omega * capacitance
    admittance += sum(1 / (r + 1j * omega * l) for r, l in zip(resistances, inductances, strict=True))
    return 1 / admittance


def compare(workspace, entry, table):
    """! @brief 같은 Yee 면과 포트 입력에서 native 일과 독립 물성식의 흡수를 계산한다."""
    import CSXCAD
    import numpy as np

    sealed = entry["normalized_result"]
    source = (workspace / sealed["uri"]).resolve()
    require(source.is_relative_to(workspace), "workspace 밖의 해석 결과입니다.", "E_HASH")
    verify(source, sealed)
    normalized = json.loads(source.read_bytes())
    plan = normalized["provenance"]["analysis_plan"]
    require(plan["plan_id"] == entry["analysis_plan"]["plan_id"], "손실 연구가 선택한 해석 계획과 다릅니다.", "E_HASH")
    case = plan["case"]
    recording = case["loss_recording"]
    raw = source.parent / "raw"
    records = {row["role"]: row for row in normalized["raw_manifest"]["files"]}
    for name in ("pcb.xml", "pcb_loss_E.h5", "pcb_loss_J.h5", "pcb_loss_rotH.h5"):
        verify(raw / name, records["raw/" + name])

    # @brief 격자와 공간 배정은 생산 결과와 같게 두고 물성식만 교체하여 대조한다.
    lines = mesh_lines(case)
    indices = [list(range(a, b + 1)) for a, b in zip(recording["start_indices"], recording["stop_indices"], strict=True)]
    csx = CSXCAD.ContinuousStructure()
    structure = ElementTree.parse(raw / "pcb.xml").getroot().find("ContinuousStructure")
    require(structure is not None, "보존한 native 기하를 읽을 수 없습니다.", "E_GEOMETRY")
    with TemporaryDirectory(prefix="rfad-ro-sheet-") as folder:
        xml = Path(folder) / "geometry.xml"
        ElementTree.ElementTree(structure).write(xml, encoding="utf-8", xml_declaration=True)
        require(not csx.ReadFromXML(str(xml)), "보존한 native 기하를 읽을 수 없습니다.", "E_GEOMETRY")
    partition, _ = sheet_partition(csx, case, lines, indices)
    width_fraction = sheet_width_fraction(partition)
    z = np.asarray(lines["z"]) * 1e-3
    zi = np.asarray(indices[2])
    normal_width = (z[zi + 1] - z[zi - 1]) * 0.5
    area = np.stack([edge_weights(lines, indices, d) / normal_width for d in (0, 1)])
    timestep = normalized["native_statistics"]["timestep_seconds"]
    rows = []
    for sample, frequency in enumerate(recording["frequency_hz"]):
        e, _, total_current = read_fields(raw, recording, lines, sample)
        angle = math.pi * frequency * timestep
        sheet_current = total_current[:2] * normal_width * np.exp(-1j * angle) / math.cos(angle)
        accepted = normalized["power_balance"]["frequencies"][sample]
        components = {row["entity_id"]: row["loss_w_s2"] for row in accepted["sheet_components"]}
        for index, shape in enumerate(case["shapes"]):
            mask = partition[:2] == index
            sigma, thickness = shape["conductivity_s_per_m"], shape["thickness_m"]
            impedance = symmetric_sheet_impedance(frequency, sigma, thickness, 4e-7 * math.pi)
            if not mask.any():
                require(components[shape["id"]] == 0, "활성 edge 없는 도체에 손실이 기록됐습니다.")
                continue
            field, current, measure = e[:2][mask], sheet_current[mask], area[mask]
            fraction = width_fraction[mask]
            metal_area = measure * fraction
            local_current = current / fraction
            field_square = np.abs(field)**2
            current_square = np.abs(local_current)**2
            field_norm = float(np.sum(field_square * metal_area))
            current_norm = float(np.sum(current_square * metal_area))
            native = float(np.sum(0.5 * (field * np.conj(current)).real * measure))
            electric_loss = 0.5 * (1 / impedance).real * field_square * measure
            current_loss = 0.5 * impedance.real * np.abs(current)**2 * measure
            fitted_impedance = None
            fit_residual = None
            if field_norm > 0 and current_norm > 0:
                fit = np.sum(field * np.conj(local_current) * metal_area) / current_norm
                fitted_impedance = [float(fit.real), float(fit.imag)]
                fit_residual = math.sqrt(float(np.sum(np.abs(field - fit * local_current)**2 * metal_area)) / field_norm)
            original = components[shape["id"]]
            require(math.isclose(native, original, rel_tol=1e-10, abs_tol=1e-300), "재조립한 native 면 일과 보존 결과가 다릅니다.")
            row = {"frequency_hz": frequency, "id": shape["id"], "role": shape["role"], "edges": int(mask.sum()),
                   "half_width_edges": int(np.count_nonzero(fraction == 0.5)), "native_loss_w_s2": native,
                   "slab_e_loss_w_s2": float(np.sum(electric_loss)), "slab_k_loss_w_s2": float(np.sum(current_loss)),
                   "slab_e_with_edge_width_w_s2": float(np.sum(electric_loss * fraction)),
                   "slab_k_with_edge_width_w_s2": float(np.sum(current_loss / fraction)),
                   "slab_impedance_ohm": [impedance.real, impedance.imag],
                   "fitted_raw_impedance_ohm": fitted_impedance, "relative_field_fit_residual": fit_residual,
                   "accepted_power_w_s2": accepted["accepted_power_w_s2"]}
            if table is not None:
                model = ade_impedance(frequency, timestep, sigma, thickness, case["excitation"], table)
                row["native_ade_impedance_ohm"] = [model.real, model.imag]
            rows.append(row)
    return {"subdivisions": entry["settings"]["feature_subdivisions"], "normalized_sha256": sealed["sha256"],
            "raw_sha256": {name: records["raw/" + name]["sha256"] for name in (
                "pcb.xml", "pcb_loss_E.h5", "pcb_loss_J.h5", "pcb_loss_rotH.h5")}, "components": rows}


def main():
    """! @brief 명시한 손실 연구의 실제 N7/N8 원문만 읽고 별도 JSON을 출력한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--ade-parameters", type=Path, help="같은 native 개정의 cond_sheet_parameter.h")
    args = parser.parse_args()
    report = json.loads(args.report.read_bytes())
    require(report.get("schema") == "rfad.pcb-loss-equivalent-input-study/0.1" and report.get("status") == "completed",
            "완료된 RO4350B 국부 손실 연구가 필요합니다.")
    selected = sorted((row for row in report["runs"].values() if row["settings"]["feature_subdivisions"] in (7, 8)),
                      key=lambda row: row["settings"]["feature_subdivisions"])
    require([row["settings"]["feature_subdivisions"] for row in selected] == [7, 8], "N7과 N8의 원문이 필요합니다.")
    table = None if args.ade_parameters is None else ade_parameter_table(args.ade_parameters)
    result = {"schema": "rfad.ro-sheet-impedance-audit/0.1", "fdtd_executed": False, "physics_validated": False,
              "ade_source": None if table is None else file_identity(args.ade_parameters),
              "runs": [compare(args.workspace.resolve(), row, table) for row in selected]}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
