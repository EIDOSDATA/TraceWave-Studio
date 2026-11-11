"""! @brief 봉인된 실제 RO4350B 필드에서 일반/가속 분할의 수치와 비용을 대조한다."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time
from xml.etree import ElementTree
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))

from rfad.application.pcb_mesh import mesh_lines
from rfad.adapters.solvers.openems.pcb_absorption import sheet_partition, read_fields, edge_weights
from rfad.adapters.solvers.openems.pcb_loss_partition import material_partition, sampled_material_partition, partition_work
from rfad.adapters.solvers.openems.pcb_loss_box import box_partition
from rfad.application.radiation_study import require


def verify(path, reference):
    """! @brief 전체 SHA256/바이트 수를 확인하며 원본 파일을 변경하지 않는다."""
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    require(path.stat().st_size == reference["bytes"] and digest == reference["sha256"], "분할 비교의 원본 파일 봉인이 다릅니다.")


def run(report_path, workspace, destination):
    """! @brief 가장 큰 완료 필드를 사용하고 세 주파수의 모든 손실을 독립 경로와 비교한다."""
    import CSXCAD
    import numpy as np

    require(not destination.exists(), "기존 비용 비교 기록을 덮어쓸 수 없습니다.")
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    pointer = (workspace / "current.json").read_bytes()
    completed = [item for item in report["runs"].values() if item["status"] == "completed"]
    entry = max(completed, key=lambda item: item["power_balance"]["recording"]["estimated_field_bytes"])
    normalized_path = workspace / entry["normalized_result"]["uri"]
    verify(normalized_path, entry["normalized_result"])
    normalized = json.loads(normalized_path.read_bytes())
    plan = normalized["provenance"]["analysis_plan"]
    raw = normalized_path.parent / "raw"
    for item in normalized["raw_manifest"]["files"]:
        verify(normalized_path.parent / Path(item["path"]).relative_to("output"), item)
    csx = CSXCAD.ContinuousStructure()
    structure = ElementTree.parse(raw / "pcb.xml").getroot().find("ContinuousStructure")
    with tempfile.TemporaryDirectory(prefix="rfad-box-cost-") as temporary:
        path = Path(temporary) / "geometry.xml"
        ElementTree.ElementTree(structure).write(path, encoding="utf-8", xml_declaration=True)
        require(not csx.ReadFromXML(str(path)), "실제 native 구조를 읽지 못했습니다.")
    case = plan["case"]
    lines = mesh_lines(case)
    recording = case["loss_recording"]
    indices = [list(range(a, b + 1)) for a, b in zip(recording["start_indices"], recording["stop_indices"])]
    sheet, _ = sheet_partition(csx, case, lines, indices)
    require(box_partition(csx, case, lines, indices, sheet) is not None, "선택 사례가 실제 box 가속 경로를 사용하지 않습니다.")
    started = time.perf_counter()
    reference = sampled_material_partition(csx, case, lines, indices, sheet)
    reference_seconds = time.perf_counter() - started
    durations = []
    for _ in range(5):
        started = time.perf_counter()
        accelerated = material_partition(csx, case, lines, indices, sheet)
        durations.append(time.perf_counter() - started)
    np.testing.assert_allclose(reference[0], accelerated[0], rtol=1e-14, atol=0)
    require(len(reference[1]) == len(accelerated[1]) == 1, "단일 box 연구가 아닙니다.")
    for key in ("indices", "fraction"):
        np.testing.assert_array_equal(reference[1][0][key], accelerated[1][0][key])
    weights = [edge_weights(lines, indices, direction) for direction in range(3)]
    observations = []
    for index, frequency in enumerate(recording["frequency_hz"]):
        fields = read_fields(raw, recording, lines, index)
        left, _ = partition_work(*fields, weights, sheet, frequency, normalized["native_statistics"]["timestep_seconds"], case["shapes"], reference)
        right, _ = partition_work(*fields, weights, sheet, frequency, normalized["native_statistics"]["timestep_seconds"], case["shapes"], accelerated)
        differences = [abs(left[key] - right[key]) / max(abs(left[key]), abs(right[key]), 1e-300)
                       for key in ("dielectric_loss_w_s2", "conductor_loss_w_s2", "sheet_loss_w_s2", "via_loss_w_s2")]
        require(max(differences) <= 1e-13 and left["sheet_components"] == right["sheet_components"], "가속 경로가 개별 손실을 바꿨습니다.")
        observations.append({"frequency_hz": frequency, "max_relative_loss_delta": max(differences)})
    require((workspace / "current.json").read_bytes() == pointer and report_path.read_bytes() == report_bytes, "비용 비교 중 원래 보고서/Journal이 바뀌었습니다.")
    evidence = {"schema": "rfad.loss-partition-cost-comparison/0.1", "status": "passed",
                "actual_fast_path_used": True,
                "producer_report_sha256": hashlib.sha256(report_bytes).hexdigest(), "normalized_result": entry["normalized_result"],
                "native_producer_runtime": report["runtime_identity"], "analysis_plan_id": plan["plan_id"],
                "reference_seconds": reference_seconds, "accelerated_seconds": durations,
                "median_speed_ratio_for_material_partition_only": reference_seconds / sorted(durations)[2],
                "coefficient_relative_tolerance": 1e-14, "loss_relative_tolerance": 1e-13, "observations": observations,
                "scope": "same_fields_same_process_material_partition_only_not_total_fdtd_speed",
                "fdtd_executed": False, "original_artifacts_modified": False, "physics_validated": False,
                "calculator_sources": [{"path": path.relative_to(CODE).as_posix(), "sha256": hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()}
                                       for path in (Path(__file__), CODE / "src/rfad/adapters/solvers/openems/pcb_loss_box.py", CODE / "src/rfad/adapters/solvers/openems/pcb_loss_partition.py")]}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.report, args.workspace, args.output)
    print(json.dumps({key: result[key] for key in ("status", "reference_seconds", "accelerated_seconds", "median_speed_ratio_for_material_partition_only")}))
