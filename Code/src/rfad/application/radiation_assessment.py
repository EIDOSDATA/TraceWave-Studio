"""! @brief 방사 연구의 세 축과 최종 전력 예산을 별도 수치 판정으로 게시한다."""

from copy import deepcopy

from rfad.application.radiation_study import AXES, require, validate_profile
from rfad.application.radiation_comparison import case_data, compare_cases, power_audit


def assess_study(cases, profile):
    """! @brief 최소 세 수준의 마지막 인접 쌍을 사용하고 모든 중간 실패를 보존한다."""
    selected = validate_profile(profile)
    require(type(cases) is list and 9 <= len(cases) <= 18, "방사 연구에는 세 축의 유한한 사례 목록이 필요합니다.")
    labels, grouped, powers = set(), {axis: [] for axis in AXES}, []
    for case in cases:
        require(type(case) is dict and case.get("axis") in AXES and type(case.get("label")) is str and bool(case["label"]), "방사 사례의 축/식별자가 다릅니다.")
        require(case["label"] not in labels, "방사 사례 식별자가 중복되었습니다.")
        labels.add(case["label"])
        case_data(case)
        grouped[case["axis"]].append(case)
        powers.append({"label": case["label"], "axis": case["axis"], **power_audit(case["normalized_result"], case["radiation_result"], selected)})
    axes, anchors = {}, []
    for axis in AXES:
        rows = grouped[axis]
        require(len(rows) >= selected["minimum_levels"], "방사 수렴 축의 수준이 부족합니다.")
        comparisons = [compare_cases(a, b, selected) for a, b in zip(rows, rows[1:])]
        anchors.append(rows[-1])
        axes[axis] = {"status": "established" if comparisons[-1]["status"] == "passed" else "not_established",
                      "level_count": len(rows), "comparisons": comparisons,
                      "decision_rule": "last_adjacent_pair_after_minimum_levels", "finest_case": rows[-1]["label"]}
    require(all(case["settings"] == anchors[0]["settings"] for case in anchors), "세 축의 최종 설정이 같은 기준 계산으로 연결되어야 합니다.")
    finest_power = next(row for row in powers if row["label"] == anchors[0]["label"])
    established = all(value["status"] == "established" for value in axes.values()) and finest_power["status"] == "passed"
    return {"schema": "rfad.pcb-radiation-convergence/0.1", "acceptance_profile": selected,
            "numerical_stability": {"status": "established" if established else "not_established", "axes": axes},
            "power_balance": {"status": finest_power["status"], "reference_case": anchors[0]["label"], "cases": powers,
                              "full_energy_closure": "not_evaluated", "independent_absorption_integral": "not_evaluated"},
            "source_settings": [{"label": row["label"], "axis": row["axis"], "settings": deepcopy(row["settings"])} for row in cases],
            "power_unit": "W*s^2", "absolute_power_w": None, "physics_validated": False,
            "measurement_validated": False, "fabrication_validated": False}
