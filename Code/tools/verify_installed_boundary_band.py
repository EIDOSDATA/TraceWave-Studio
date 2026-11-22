"""! @brief 봉인된 설치 후보의 격자 및 외부 여백 대조를 고정 회로로 판정한다."""
import argparse
import json
from pathlib import Path

import numpy as np

from verify_installed_port_uncertainty import LIMIT_DB, START, STEPS, STOP, payload, relative_bound
from verify_installed_retuning import circuit, frequency_projection


def band(model, case):
    """! @brief 각 표본에 가장 가까운 주파수 구간의 반사계수 상한을 구한다."""
    frequencies = np.linspace(START, STOP, STEPS + 1)
    voltage, current = case["traces"]
    v = frequency_projection(voltage, frequencies)
    i = frequency_projection(current, frequencies)
    forward_error = model.bound(voltage, current)
    reflection, incidence = model.waves(frequencies, v, i)
    if np.any(abs(incidence) <= forward_error):
        raise ValueError("대역 내 입사 파의 하한이 양수가 아닙니다.")
    gamma = reflection / incidence
    radius = forward_error * (1 + abs(gamma)) / (abs(incidence) - forward_error)
    measured = int(np.argmax(abs(gamma)))
    upper = int(np.argmax(abs(gamma) + radius))
    limit_db = float(20 * np.log10(abs(gamma[upper]) + radius[upper]))
    return list(zip(gamma, radius, strict=True)), {
        "sample_peak_hz": float(frequencies[measured]),
        "sample_peak_db": float(20 * np.log10(abs(gamma[measured]))),
        "upper_bound_center_hz": float(frequencies[upper]),
        "continuous_upper_db": limit_db,
        "within_goal": limit_db <= LIMIT_DB,
    }


def compare(first, second, expected_setting):
    """! @brief 고정 물리 입력과 달라져야 할 설정 한 항목을 확인한다."""
    first_settings = first["evidence"]["settings"]
    second_settings = second["evidence"]["settings"]
    differences = {key for key in first_settings.keys() | second_settings.keys()
                   if first_settings.get(key) != second_settings.get(key)}
    if first["physical"] != second["physical"] or differences != {expected_setting}:
        raise ValueError(f"물리 조건 또는 단일 변경 조건이 다릅니다. {expected_setting}: {sorted(differences)}")


def inspect(record, original, refinement, near_folder):
    """! @brief 기존 격자 쌍과 새 여백 쌍의 실제 결과를 대조한다."""
    retuned = record["candidate"]["retuned"]
    archived = retuned["runs"]
    route = (retuned["shunt_capacitance_pf"], retuned["series_kind"], retuned["series_value_pf_or_nh"])
    reference = payload(original, archived["fine"]["run_id"])
    far = payload(original, archived["boundary"]["run_id"])
    finer_row = record["refinement"]["grid_mm"]
    finer = payload(refinement, finer_row["evidence"]["run_id"])
    for value, expected in ((reference, archived["fine"]), (far, archived["boundary"]),
                            (finer, finer_row["evidence"])):
        if value["evidence"] != expected:
            raise ValueError("재사용한 실행 봉인이 기록과 다릅니다.")
    near_report = json.loads((near_folder / "report.json").read_bytes())
    near_row = near_report["axes"]["graded_reference"]
    if near_report["baseline"] != reference["evidence"] or not near_report["source_unchanged"]:
        raise ValueError("새 경계 실행이 기준 사본을 보존했는지 확인할 수 없습니다.")
    if near_row["status"] != "completed":
        raise ValueError("새 경계 실행의 봉인 결과가 아직 없습니다.")
    near = payload(near_folder / "workspace", near_row["evidence"]["run_id"])
    if near["evidence"] != near_row["evidence"] or near["physical"] != reference["physical"]:
        raise ValueError("새 경계 실행과 봉인 또는 물리 입력이 다릅니다.")
    compare(reference, finer, "grid_mm")
    compare(near, far, "air_padding_mm")
    model = circuit(route)
    result = {}
    curves = {}
    for key, case in (("grid_reference", reference), ("grid_finer", finer),
                      ("boundary_near", near), ("boundary_far", far)):
        curves[key], metrics = band(model, case)
        result[key] = {**case["evidence"], **metrics}
    return {
        "circuit": {"shunt_pf": route[0], "series_kind": route[1], "series_pf_or_nh": route[2]},
        "cases": result,
        "near_run_statistics": near_row["native_statistics"],
        "complex_difference_upper": {
            "grid_mm": relative_bound(curves["grid_reference"], curves["grid_finer"]),
            "air_padding_mm": relative_bound(curves["boundary_near"], curves["boundary_far"]),
        },
        "all_observed_conditions_within_goal": all(item["within_goal"] for item in result.values()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accepted_record", type=Path)
    parser.add_argument("original_workspace", type=Path)
    parser.add_argument("--arc-refinement", type=Path, required=True)
    parser.add_argument("--ifa-refinement", type=Path, required=True)
    parser.add_argument("--arc-near", type=Path, required=True)
    parser.add_argument("--ifa-near", type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.accepted_record.read_bytes())
    cases = {
        kind: inspect(evidence["candidates"][kind], args.original_workspace, refinement, near)
        for kind, refinement, near in (("arc", args.arc_refinement, args.arc_near),
                                       ("ifa", args.ifa_refinement, args.ifa_near))
    }
    print(json.dumps({"schema": "rfad.installed-boundary-band/0.1", "limit_db": LIMIT_DB,
                      "frequency_hz": [START, STOP], "frequencies_per_case": STEPS + 1,
                      "cases": cases}, ensure_ascii=False, allow_nan=False, indent=2))
