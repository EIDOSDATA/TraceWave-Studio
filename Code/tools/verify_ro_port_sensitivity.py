"""! @brief 봉인된 RO4350B 7·8 분할의 포트 스펙트럼과 수용 전력 변화를 대조한다."""

import argparse
import cmath
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

from verify_installed_port_band import Trace
from verify_ro_sheet_impedance import require, verify


@dataclass(frozen=True)
class Run:
    """! @brief 원시 포트와 공통 면적 적분에 필요한 봉인 실행 한 건을 보관한다."""

    raw: Path
    artifacts: dict
    case: dict
    traces: tuple
    coordinates: list
    current_indices: list
    timestep: float
    power: list


def load_run(workspace, entry):
    """! @brief 전압·전류 적분 좌표와 복소 변환에 필요한 시계열의 봉인을 확인한다."""
    seal = entry["normalized_result"]
    path = (workspace / seal["uri"]).resolve()
    require(path.is_relative_to(workspace), "workspace 밖의 해석 결과입니다.", "E_HASH")
    verify(path, seal)
    normalized = json.loads(path.read_bytes())
    plan = normalized["provenance"]["analysis_plan"]
    require(plan["plan_id"] == entry["analysis_plan"]["plan_id"], "봉인 계획 식별자가 다릅니다.", "E_HASH")
    artifacts = {row["role"].removeprefix("raw/"): row for row in normalized["raw_manifest"]["files"]}
    raw = path.parent / "raw"
    traces, coordinates, indices = [], [], []
    for name in ("port_ut_1", "port_it_1"):
        artifact = raw / name
        verify(artifact, artifacts[name])
        payload = artifact.read_bytes()
        headings = re.findall(rb"^% (?:start|stop)-coordinates: \(([^)]+)\) m -> \[([^]]+)\]", payload, re.M)
        require(len(headings) == 2, "native 적분 좌표와 격자 인덱스가 필요합니다.", "E_GEOMETRY")
        coordinates.append([[float(value) for value in endpoint.split(b",")] for endpoint, _ in headings])
        indices.append([[int(value) for value in endpoint.split(b",")] for _, endpoint in headings])
        traces.append(Trace.load(payload))
    return Run(raw, artifacts, plan["case"], tuple(traces), coordinates, indices[1],
               normalized["native_statistics"]["timestep_seconds"], normalized["power_balance"]["frequencies"])


def point(traces, frequency, reference, end=None):
    """! @brief 직접 합산한 전압·전류의 크기와 위상으로 수용 전력을 계산한다."""
    if end is not None:
        traces = [Trace(tuple(term for term in trace.terms if -term[0] / math.tau <= end)) for trace in traces]
    voltage, current = (trace.at(frequency) for trace in traces)
    phase = cmath.phase(voltage / current)
    accepted = 0.5 * abs(voltage) * abs(current) * math.cos(phase)
    forward = voltage + reference * current
    reflected = voltage - reference * current
    incident = abs(forward)**2 / (8 * reference)
    matched = 1 - abs(reflected / forward)**2
    require(accepted > 0 and math.isclose(accepted, incident * matched, rel_tol=1e-12),
            "포트 복소 일률과 입사·반사 파가 일치하지 않습니다.")
    impedance = voltage / current
    return {"voltage_abs_v_s": abs(voltage), "current_abs_a_s": abs(current),
            "phase_deg": math.degrees(phase), "accepted_w_s2": accepted, "incident_w_s2": incident,
            "accepted_fraction": matched, "impedance_ohm": [impedance.real, impedance.imag]}


def face_flux(current, dual, box, recording):
    """! @brief dual 면의 겹치는 넓이에 현재 밀도를 곱하고 y의 이웃 평면을 보간한다."""
    import numpy as np

    widths = []
    for axis in (0, 2):
        lower, upper = box[axis]
        first, last = recording["start_indices"][axis], recording["stop_indices"][axis]
        border = dual[axis]
        require(0 < first and border[first - 1] <= lower < upper <= border[last],
                "공통 적분 면적을 저장 필드가 덮지 않습니다.", "E_GEOMETRY")
        widths.append(np.maximum(0.0, np.minimum(border[first:last + 1], upper)
                                 - np.maximum(border[first - 1:last], lower)) * 1e-3)
    first, last = recording["start_indices"][1], recording["stop_indices"][1]
    planes = dual[1][first:last + 1]
    y = box[1, 0]
    require(planes[0] <= y <= planes[-1], "공통 적분면의 y 범위가 맞지 않습니다.", "E_GEOMETRY")
    below = min(np.searchsorted(planes, y, side="right") - 1, len(planes) - 2)
    share = (y - planes[below]) / (planes[below + 1] - planes[below])
    field = (1 - share) * current[:, below, :] + share * current[:, below + 1, :]
    return complex(np.sum(field * widths[0][:, None] * widths[1][None, :]))


def match_current_aperture(runs):
    """! @brief 같은 dual 적분면으로 전류를 재구성하기 전에 native 폐곡선과 대조한다."""
    import numpy as np
    from rfad.adapters.solvers.openems.pcb_absorption import read_fields
    from rfad.application.pcb_mesh import mesh_lines
    from rfad.application.pcb_power import NAMES

    grids = []
    for run in runs:
        start, stop = run.current_indices
        require(run.case["port"]["axis"] in ("y", 1) and start[1] == stop[1],
                "y 방향 급전의 단일 dual 면만 비교할 수 있습니다.", "E_GEOMETRY")
        for name in NAMES:
            verify(run.raw / name, run.artifacts[name])
        lines = mesh_lines(run.case)
        dual = [0.5 * (np.asarray(lines[k][:-1]) + np.asarray(lines[k][1:])) for k in "xyz"]
        box = np.array([[axis[i], axis[j]] for axis, i, j in zip(dual, start, stop, strict=True)])
        grids.append((lines, dual, box))

    # @brief 가운데 y에 두 폐곡선의 전체 x-z 범위를 포함해 여기 edge를 부분 절단하지 않는다.
    contours = np.stack([box for _, _, box in grids])
    envelope = np.mean(contours, axis=0)
    envelope[[0, 2], 0] = np.min(contours[:, [0, 2], 0], axis=0)
    envelope[[0, 2], 1] = np.max(contours[:, [0, 2], 1], axis=0)
    values = []
    for run, (lines, dual, box) in zip(runs, grids, strict=True):
        recording = run.case["loss_recording"]
        points = []
        for index, frequency in enumerate(recording["frequency_hz"]):
            _, _, curl = read_fields(run.raw, recording, lines, index)
            alignment = cmath.exp(-1j * math.pi * frequency * run.timestep)
            native_i = run.traces[1].at(frequency)
            restored = face_flux(curl[1], dual, box, recording) * alignment
            common = face_flux(curl[1], dual, envelope, recording) * alignment
            complex_error = abs(restored / native_i - 1)
            require(complex_error < 5e-4, "원래 면에서 복원한 복소 전류가 native 포트와 다릅니다.")
            voltage = run.traces[0].at(frequency)
            points.append({"frequency_hz": frequency, "native_contour_complex_current_error": complex_error,
                           "relative_aperture_current_change": abs(common / restored - 1),
                           "reconstructed_contour_accepted_w_s2": 0.5 * (voltage * restored.conjugate()).real,
                           "common_aperture_accepted_w_s2": 0.5 * (voltage * common.conjugate()).real})
        values.append(points)

    return {"native_dual_boxes_mm": contours.tolist(), "common_dual_box_mm": envelope.tolist(),
            "rotH_sha256": [run.artifacts[NAMES[2]]["sha256"] for run in runs],
            "native_contour_current_error_limit": 5e-4, "N7": values[0], "N8": values[1]}


def compare(workspace, entries):
    """! @brief 수용 전력의 로그 차이를 크기·상대 위상과 동일 시간창 영향으로 분해한다."""
    first, second = runs = tuple(load_run(workspace, entry) for entry in entries)
    require(first.case["port"] == second.case["port"], "두 격자의 원래 급전 계약이 다릅니다.", "E_GEOMETRY")
    common_end = min(-trace.terms[-1][0] / math.tau for run in runs for trace in run.traces)
    reference = first.case["port"]["resistance_ohm"]
    radiators = [next(shape["id"] for shape in run.case["shapes"] if shape["role"] == "radiator") for run in runs]
    result = []
    for a, b in zip(first.power, second.power, strict=True):
        frequency = a["frequency_hz"]
        require(frequency == b["frequency_hz"], "손실 표본의 주파수가 다릅니다.")
        old, new = (point(run.traces, frequency, reference) for run in runs)
        for values, original in ((old, a), (new, b)):
            for kind in ("accepted", "incident"):
                require(math.isclose(values[kind + "_w_s2"], original[kind + "_power_w_s2"], rel_tol=1e-10),
                        "독립 포트 변환과 저장 파 전력이 다릅니다.")
        elapsed = [point(run.traces, frequency, reference, common_end) for run in runs]
        terms = {key: 100 * math.log(new[key] / old[key]) for key in ("voltage_abs_v_s", "current_abs_a_s")}
        terms["phase_cosine"] = 100 * math.log(math.cos(math.radians(new["phase_deg"])) /
                                              math.cos(math.radians(old["phase_deg"])))
        losses = [next(row["loss_w_s2"] for row in snapshot["sheet_components"] if row["entity_id"] == radiator)
                  for radiator, snapshot in zip(radiators, (a, b), strict=True)]
        incident_ratio = new["incident_w_s2"] / old["incident_w_s2"]
        result.append({"frequency_hz": frequency, "incident_ratio": incident_ratio,
                       "accepted_fraction_ratio": new["accepted_fraction"] / old["accepted_fraction"],
                       "incident_normalized_radiator_loss_ratio": (losses[1] / losses[0]) / incident_ratio, "N7": old, "N8": new, "log_accepted_terms_pct": terms,
                       "accepted_ratio_full": new["accepted_w_s2"] / old["accepted_w_s2"],
                       "accepted_ratio_common_end": elapsed[1]["accepted_w_s2"] / elapsed[0]["accepted_w_s2"],
                       "radiator_loss_ratio": losses[1] / losses[0]})
    return runs, {"schema": "rfad.ro-port-sensitivity/0.1", "physics_validated": False, "common_end_seconds": common_end,
                  "primary_port_coords_m_N7": first.coordinates, "primary_port_coords_m_N8": second.coordinates,
                  "port_sha256_N7": [first.artifacts[name]["sha256"] for name in ("port_ut_1", "port_it_1")],
                  "port_sha256_N8": [second.artifacts[name]["sha256"] for name in ("port_ut_1", "port_it_1")],
                  "frequencies": result}


def main():
    """! @brief 기존 연구의 동일 7·8 분할에서 원문을 재계산하고 진단 결과만 출력한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--common-aperture", action="store_true", help="NumPy/HDF5로 공통 물리 전류 적분면을 비교합니다.")
    args = parser.parse_args()
    report = json.loads(args.report.read_bytes())
    require(report.get("schema") == "rfad.pcb-loss-equivalent-input-study/0.1" and report.get("status") == "completed",
            "완료된 RO4350B 국부 손실 연구가 필요합니다.")
    selected = {row["settings"]["feature_subdivisions"]: row for row in report["runs"].values()}
    runs, result = compare(args.workspace.resolve(), [selected[7], selected[8]])
    if args.common_aperture:
        result["current_aperture"] = match_current_aperture(runs)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
