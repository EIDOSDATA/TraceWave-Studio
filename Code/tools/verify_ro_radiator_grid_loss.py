"""! @brief 같은 시간의 원본 N8과 보완 격자에서 방사 도체의 원시 Joule 일을 대조한다."""
import argparse
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

import CSXCAD
import h5py
import numpy as np

from rfad.adapters.solvers.openems.pcb_absorption import edge_weights, integrate_fields, read_fields, sheet_partition
from rfad.application.pcb_power import NAMES
from verify_installed_port_band import Trace
from verify_ro_grid_ablation import COMPLEMENT, FREQUENCIES, PORT_NAMES, grid_tokens, sealed, sha, source


def raw_recording(raw, lines, frequencies):
    """! @brief 원시 기록 좌표를 XML의 연속 내부 격자 구간으로 검증한다."""
    indices = []
    with h5py.File(raw / NAMES[0], "r") as stream:
        for axis in "xyz":
            found = np.asarray(stream["Mesh"][axis])
            if found.ndim != 1 or len(found) < 3:
                raise ValueError("손실 기록에 세 점 이상의 좌표축이 필요합니다.")
            grid = np.asarray(lines[axis]) * 0.001
            firsts = np.flatnonzero(np.isclose(grid, found[0], rtol=0, atol=1e-12))
            if len(firsts) != 1:
                raise ValueError("기록 면의 처음 좌표가 실제 XML 격자에 없습니다.")
            first = int(firsts[0])
            last = first + len(found) - 1
            if first < 1 or last >= len(grid) - 1 or not np.allclose(found, grid[first:last + 1], rtol=0, atol=1e-12):
                raise ValueError("손실 기록이 연속된 내부 원시 격자에 있지 않습니다.")
            indices.append(list(range(first, last + 1)))
    return {"start_indices": [v[0] for v in indices], "stop_indices": [v[-1] for v in indices],
            "frequency_hz": frequencies}, indices


def sheet_work(raw, case, numerical_dt):
    """! @brief native 형상에서 점유를 확인하고 원시 E·rotH의 방사 도체 일을 다시 적분한다."""
    root = ET.parse(raw / "pcb.xml").getroot()
    lines = {axis.lower(): list(map(float, grid_tokens(root, axis)[1])) for axis in "XYZ"}
    recording, indices = raw_recording(raw, lines, FREQUENCIES)
    csx = CSXCAD.ContinuousStructure()
    with TemporaryDirectory(prefix="rfad-ro-field-") as folder:
        model = Path(folder) / "geometry.xml"
        ET.ElementTree(root.find("ContinuousStructure")).write(model, encoding="utf-8", xml_declaration=True)
        if csx.ReadFromXML(str(model)):
            raise ValueError("손실 적분용 native 기하를 읽지 못했습니다.")
    partition, counts = sheet_partition(csx, case, lines, indices)
    weights = [edge_weights(lines, indices, direction) for direction in range(3)]
    radiator, = (shape["id"] for shape in case["shapes"] if shape["role"] == "radiator")
    traces = tuple(Trace.load((raw / name).read_bytes()) for name in PORT_NAMES)
    samples = []
    for index, frequency in enumerate(FREQUENCIES):
        fields = read_fields(raw, recording, lines, index)
        results = integrate_fields(*fields, weights, partition, frequency, numerical_dt, case["shapes"])
        loss, = (row["loss_w_s2"] for row in results["sheet_components"] if row["entity_id"] == radiator)
        voltage, current = (trace.at(frequency) for trace in traces)
        accepted = 0.5 * (voltage * current.conjugate()).real
        incident = abs(voltage + 50 * current)**2 / 400
        if min(loss, accepted, incident) <= 0 or not all(map(math.isfinite, (loss, accepted, incident))):
            raise ValueError("양수인 손실과 포트 전력이 필요합니다.")
        samples.append({"frequency_hz": frequency, "radiator_loss_w_s2": loss, "accepted_w_s2": accepted,
                        "incident_w_s2": incident, "radiator_loss_per_accepted": loss / accepted,
                        "radiator_loss_per_incident": loss / incident})
    return {"samples": samples, "sheet_edge_counts": counts,
            "raw_sha256": {name: sha(raw / name) for name in ("pcb.xml", *PORT_NAMES, *NAMES)}}


def compare(sealed_report, workspace, complement_path):
    """! @brief 봉인 원본을 같은 적분으로 재현하고 보완 실행의 손실 차이를 분석한다."""
    report = json.loads(sealed_report.read_bytes())
    entry, = (item for item in report["runs"].values() if item["settings"]["feature_subdivisions"] == 8)
    originals, normalized = source(workspace.resolve(), entry)
    raw = originals["pcb.xml"].parent
    records = {item["role"]: item for item in normalized["raw_manifest"]["files"]}
    for name in NAMES:
        sealed(raw / name, records["raw/" + name])
    case = normalized["provenance"]["analysis_plan"]["case"]
    stats = normalized["native_statistics"]
    original = sheet_work(raw, case, stats["timestep_seconds"])
    original["normalized_sha256"] = entry["normalized_result"]["sha256"]
    radiator, = (shape["id"] for shape in case["shapes"] if shape["role"] == "radiator")
    for actual, expected in zip(original["samples"], normalized["power_balance"]["frequencies"], strict=True):
        published, = (row["loss_w_s2"] for row in expected["sheet_components"] if row["entity_id"] == radiator)
        if (actual["frequency_hz"] != expected["frequency_hz"]
                or not math.isclose(actual["radiator_loss_w_s2"], published, rel_tol=1e-6)
                or not math.isclose(actual["accepted_w_s2"], expected["accepted_power_w_s2"], rel_tol=1e-6)):
            raise ValueError("보존 N8의 방사 도체 또는 포트 전력을 같은 원시 기록에서 재현하지 못했습니다.")
    result = {"schema": "rfad.ro-radiator-field-comparison/0.1", "physics_validated": False,
              "scope": "same-duration_native_radiator_sheet_diagnostic", "original_n8": original}
    if complement_path is not None:
        record = json.loads(complement_path.read_bytes())
        new, = (row for row in record["runs"] if row["name"] == COMPLEMENT and row["status"] == "completed")
        raw = complement_path.parent / COMPLEMENT
        if (new["stats"]["iterations"] != stats["iterations"]
                or not math.isclose(new["stats"]["timestep_s"], stats["timestep_seconds"], rel_tol=1e-12)
                or sha(raw / "pcb.xml") != new["input_xml_sha256"]
                or any(sha(raw / name) != new["raw_sha256"][name] for name in (*PORT_NAMES, *NAMES))):
            raise ValueError("보완 격자 원시 봉인, 시간 간격 또는 반복 수가 다릅니다.")
        comparison = sheet_work(raw, case, stats["timestep_seconds"])
        rows = []
        for old, actual in zip(original["samples"], comparison["samples"], strict=True):
            row = {"frequency_hz": old["frequency_hz"]}
            for metric in ("radiator_loss_w_s2", "accepted_w_s2", "radiator_loss_per_accepted", "radiator_loss_per_incident"):
                row[metric + "_relative_change"] = actual[metric] / old[metric] - 1
            rows.append(row)
        result.update(complement=comparison, complement_over_n8=rows)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sealed_report", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--complement", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.sealed_report, args.workspace, args.complement), allow_nan=False))
