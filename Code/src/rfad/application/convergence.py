"""! @brief 명시적 benchmark 조건으로 불변 PCB 결과의 수치 안정성을 비교한다.

@details 물리 검증이나 실측 일치를 선언하지 않는다. 공진은 표본의 내부 최소점과
양옆 주파수 bracket으로만 평가하며 보간으로 해상도를 꾸미지 않는다.
"""

from copy import deepcopy
import math

from rfad.application.canonical import canonical_hash


PROFILE_KEYS = {"id", "minimum_levels", "max_resonance_relative_shift", "max_s11_complex_delta"}
AXES = ("mesh", "boundary", "termination")


def _require(condition, message):
    """! @brief 비교할 수 없는 입력을 숫자 안정성 합격과 분리한다."""
    if not condition:
        raise ValueError(message)


def _finite(value):
    """! @brief bool과 표현 범위를 넘는 정수도 유한한 측정값으로 수용하지 않는다."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _profile(profile):
    """! @brief 임계값을 보편 기본값으로 채우지 않고 호출자의 명시적 조건을 요구한다."""
    _require(type(profile) is dict and set(profile) == PROFILE_KEYS, "비교 profile의 네 필드를 명시해야 합니다.")
    _require(type(profile["id"]) is str and bool(profile["id"].strip()), "비교 profile 식별자가 필요합니다.")
    _require(type(profile["minimum_levels"]) is int and profile["minimum_levels"] >= 3, "공간 비교에는 최소 세 수준이 필요합니다.")
    for key in ("max_resonance_relative_shift", "max_s11_complex_delta"):
        _require(_finite(profile[key]) and profile[key] > 0, "비교 임계값은 명시적 유한 양수여야 합니다.")
    return deepcopy(profile)


def _vector(value, name):
    """! @brief 주파수와 격자선을 양의 차이가 있는 유한 배열로 검증한다."""
    _require(type(value) is list and len(value) >= 2 and all(_finite(item) for item in value), name + " 배열이 유효하지 않습니다.")
    _require(all(right > left for left, right in zip(value, value[1:])), name + " 배열은 엄격히 증가해야 합니다.")
    return value


def _result(result):
    """! @brief 결과의 표본/원본/실제 격자/시간 종료 근거를 읽고 원본을 바꾸지 않는다."""
    try:
        _require(result["schema"] == "rfad.openems-pcb-result/0.1", "PCB 정규화 결과가 필요합니다.")
        assessment = result["assessment"]
        _require(assessment["status"] == "computed_unvalidated" and assessment["physics_validated"] is False
                 and assessment["converged"] is True and assessment["finite_samples"] is True,
                 "시간 종료가 확인된 computed_unvalidated 결과만 비교합니다.")
        plan = result["provenance"]["analysis_plan"]
        _require(result["analysis_plan_id"] == plan["plan_id"], "결과와 계획 식별자가 다릅니다.")
        _require(plan["snapshot"]["content_hash"] == canonical_hash(plan["source_semantics"]), "원본과 스냅샷 hash가 다릅니다.")
        _require(result["normalization"] == plan["normalization"] and bool(result["normalization"]), "정규화 계약이 계획과 다릅니다.")
        _require(bool(plan["runtime_identity"]) and bool(result["provenance"]["runtime"]), "고정 및 관측 runtime 근거가 필요합니다.")
        rows = result["samples"]
        _require(type(rows) is list and len(rows) >= 3, "주파수 표본이 세 개 이상 필요합니다.")
        frequencies, reflections, impedances = [], [], []
        for row in rows:
            frequency = row["frequency_hz"]
            _require(_finite(frequency) and frequency > 0, "주파수는 유한한 양수여야 합니다.")
            frequencies.append(frequency)
            for key, target in (("s11", reflections), ("impedance_ohm", impedances)):
                value = row[key]
                _require(type(value) is list and len(value) == 2 and all(_finite(number) for number in value), "복소 S11/임피던스 표본이 유효하지 않습니다.")
                converted = complex(*value)
                _require(_finite(abs(converted)), "복소 크기가 표현 범위를 초과했습니다.")
                target.append(converted)
        _vector(frequencies, "주파수")
        settings = plan["case"]["settings"]
        frequency = settings["frequency_hz"]
        _require(type(frequency["count"]) is int and frequency["count"] == len(rows)
                 and frequency["start"] == frequencies[0] and frequency["stop"] == frequencies[-1],
                 "표본 주파수 범위/개수가 계획과 다릅니다.")
        _require(type(settings["max_timesteps"]) is int and settings["max_timesteps"] > 0
                 and _finite(settings["end_criterion"]) and 0 < settings["end_criterion"] < 1
                 and _finite(settings["air_padding_mm"]) and settings["air_padding_mm"] > 0,
                 "시간 종료/경계 설정은 명시적인 유한 범위여야 합니다.")
        mesh = result["mesh_statistics"]
        lines = {axis: _vector(mesh["lines_mm"][axis], "격자 " + axis) for axis in "xyz"}
        counts = [len(lines[axis]) for axis in "xyz"]
        count = math.prod(counts)
        _require(mesh["line_counts"] == counts and type(mesh["native_grid_points"]) is int and mesh["native_grid_points"] == count,
                 "실제 격자선과 격자 개수가 다릅니다.")
        _require(mesh["interval_counts"] == [number - 1 for number in counts]
                 and type(mesh["yee_interval_cells"]) is int and mesh["yee_interval_cells"] == math.prod(number - 1 for number in counts),
                 "실제 격자선과 Yee 구간 수가 다릅니다.")
        _require(mesh["grid_mm"] == settings["grid_mm"] and _finite(settings["grid_mm"]) and settings["grid_mm"] > 0,
                 "격자 간격 설정이 결과와 다릅니다.")
        pml = mesh["pml_cells_per_end"]
        _require(type(pml) is int and pml > 0 and all(n > 2 * pml + 1 for n in counts), "PML 내부 격자 근거가 부족합니다.")
        native = result["native_statistics"]
        termination = result["termination"]
        _require(type(native["native_cells"]) is int and native["native_cells"] == count, "실행한 native 격자 수가 다릅니다.")
        iterations = native["iterations"]
        _require(type(iterations) is int and 0 < iterations < settings["max_timesteps"] and termination["iterations"] == iterations,
                 "시간 상한/실제 종료 단계가 유효하지 않습니다.")
        _require(termination["status"] == "end_criterion_reached" and termination["exact_endcriterion_schedule"] is True
                 and termination["target_energy_ratio"] == settings["end_criterion"], "명시적 에너지 종료 근거가 다릅니다.")
        # @brief 격자별 손실 dump 인덱스/크기는 관측 영역이며 전기적 물리 입력의 차이가 아니다.
        identity = {"snapshot": plan["snapshot"], "source_semantics": plan["source_semantics"],
                    "normalization": result["normalization"], "runtime_identity": plan["runtime_identity"],
                    "observed_runtime": result["provenance"]["runtime"], "analysis_profile": plan["analysis_profile"],
                    "runtime_profile": plan["runtime_profile"], "model_report": plan["model_report"],
                    "physics": {key: value for key, value in plan["case"].items() if key not in {"settings", "stop_criteria", "mesh_policy_report", "loss_recording"}}}
        return {"frequencies": frequencies, "s11": reflections, "impedance": impedances, "identity": identity,
                "plan": plan, "settings": settings, "lines": lines, "native_cells": count, "pml": pml}
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError("비교에 필요한 정규화/계획/격자 근거가 없거나 유효하지 않습니다.") from error


def _resonance(data):
    """! @brief 하나의 엄격한 내부 최소점만 선택하고 양옆 표본을 불확실성 구간으로 보존한다."""
    magnitudes = [abs(value) for value in data["s11"]]
    frequencies = data["frequencies"]
    candidates = [index for index in range(1, len(magnitudes) - 1)
                  if magnitudes[index] < magnitudes[index - 1] and magnitudes[index] < magnitudes[index + 1]]
    minimum = min(magnitudes)
    if len(candidates) != 1 or magnitudes[candidates[0]] != minimum or magnitudes.count(minimum) != 1:
        reason = "multiple_local_minima" if len(candidates) > 1 else "no_unique_interior_global_minimum"
        return {"status": "not_established", "reason": reason, "interior_minimum_count": len(candidates)}
    index = candidates[0]
    return {"status": "bracketed", "frequency_hz": frequencies[index], "sample_index": index,
            "bracket_hz": [frequencies[index - 1], frequencies[index + 1]], "s11_magnitude": minimum}


def compare_samples(left_result, right_result, profile):
    """! @brief 같은 원본/규약/주파수의 복소 결과를 비교하되 의도한 설정 차이는 허용한다."""
    selected = _profile(profile)
    left, right = _result(left_result), _result(right_result)
    _require(left["identity"] == right["identity"], "스냅샷/기하/물성/정규화/소스/runtime가 다른 결과는 비교할 수 없습니다.")
    _require(left["frequencies"] == right["frequencies"], "동일한 주파수 배열에서만 비교할 수 있습니다.")
    s_delta = [abs(a - b) for a, b in zip(left["s11"], right["s11"])]
    z_delta = [abs(a - b) for a, b in zip(left["impedance"], right["impedance"])]
    db_delta = [abs(20 * math.log10(abs(a)) - 20 * math.log10(abs(b))) for a, b in zip(left["s11"], right["s11"]) if abs(a) > 0 and abs(b) > 0]
    _require(all(_finite(number) for number in (*s_delta, *z_delta, *db_delta)), "표본 차이가 유한 범위를 초과했습니다.")
    metrics = {"max_s11_complex_delta": max(s_delta), "max_impedance_complex_delta_ohm": max(z_delta),
               "max_s11_db_delta": max(db_delta) if db_delta else None, "s11_db_undefined_pair_count": len(s_delta) - len(db_delta),
               "worst_s11_frequency_hz": left["frequencies"][s_delta.index(max(s_delta))]}
    a, b = _resonance(left), _resonance(right)
    resonance = {"left": a, "right": b, "status": "not_established", "sampled_relative_shift": None, "bracket_max_relative_shift": None}
    s_passed = metrics["max_s11_complex_delta"] <= selected["max_s11_complex_delta"]
    status = "not_established" if s_passed else "failed"
    if a["status"] == b["status"] == "bracketed":
        low_a, high_a = a["bracket_hz"]
        low_b, high_b = b["bracket_hz"]
        upper = max(abs(low_a / high_b - 1), abs(high_a / low_b - 1))
        _require(_finite(upper), "공진 bracket 비율이 유한 범위를 초과했습니다.")
        resonance.update(sampled_relative_shift=abs(a["frequency_hz"] / b["frequency_hz"] - 1), bracket_max_relative_shift=upper,
                         status="passed" if upper <= selected["max_resonance_relative_shift"] else "not_established")
        if resonance["sampled_relative_shift"] > selected["max_resonance_relative_shift"]:
            resonance["status"] = "failed"
        elif resonance["status"] == "not_established":
            resonance["reason"] = "frequency_resolution_cannot_bound_resonance_shift"
        status = "established" if s_passed and resonance["status"] == "passed" else (
            "failed" if not s_passed or resonance["status"] == "failed" else "not_established")
    return {"status": status, "acceptance_profile": selected, "sample_count": len(s_delta), "metrics": metrics,
            "complex_s11_passed": s_passed, "resonance": resonance, "physics_validated": False,
            "source_assessments": [deepcopy(left_result["assessment"]), deepcopy(right_result["assessment"])]}


def _slice(lines, low, high):
    """! @brief 고정 물리 구간의 실제 격자선을 오차 보정 없이 추출한다."""
    return [value for value in lines if low <= value <= high]


def _pml_grid(left, right):
    """! @brief PML cell 수와 실제 폭을 비교하며 native 생성 후조건의 수치 오차만 허용한다."""
    widths = {}
    for axis in "xyz":
        first, second = left["lines"][axis], right["lines"][axis]
        a = [b - a for a, b in zip(first, first[1:])]
        b = [b - a for a, b in zip(second, second[1:])]
        a = a[:left["pml"]] + a[-left["pml"]:]
        b = b[:right["pml"]] + b[-right["pml"]:]
        widths[axis] = len(a) == len(b) and all(math.isclose(x, y, rel_tol=0, abs_tol=1e-9) for x, y in zip(a, b))
    count_matches = left["pml"] == right["pml"]
    return {"pml_cell_count_matches": count_matches, "pml_cell_width_axes_match": widths,
            "pml_width_absolute_tolerance_mm": 1e-9, "pml_passed": count_matches and all(widths.values())}


def _mesh_boundary_grid(left, right):
    """! @brief 내부 격자 세분화 중 실제 외곽/PML 시작면과 PML cell 폭이 고정됐는지 확인한다."""
    outer, interface = {}, {}
    for axis in "xyz":
        first, second = left["lines"][axis], right["lines"][axis]
        outer[axis] = [first[0], first[-1]] == [second[0], second[-1]]
        interface[axis] = [first[left["pml"]], first[-left["pml"] - 1]] == [second[right["pml"]], second[-right["pml"] - 1]]
    pml = _pml_grid(left, right)
    return {"outer_boundary_axes_match": outer, "pml_interface_axes_match": interface, **pml,
            "passed": all(outer.values()) and all(interface.values()) and pml["pml_passed"]}


def _boundary_grids(left, right):
    """! @brief 보드 내부와 두 계산의 공통 비-PML 구간이 같은 실제 격자인지 확인한다."""
    case = left["plan"]["case"]
    bounds = deepcopy(case["board"]["bounds_mm"])
    bounds.append([min(layer["z_min_mm"] for layer in case["layers"]),
                   max(layer["z_min_mm"] + layer["thickness_mm"] for layer in case["layers"])])
    board, common, domain, interface = {}, {}, {}, {}
    for axis, (low, high) in zip("xyz", bounds):
        first, second = left["lines"][axis], right["lines"][axis]
        domain[axis] = second[0] < first[0] and second[-1] > first[-1]
        interface[axis] = second[right["pml"]] < first[left["pml"]] and second[-right["pml"] - 1] > first[-left["pml"] - 1]
        a, b = _slice(first, low, high), _slice(second, low, high)
        board[axis] = bool(a) and a == b
        low = max(first[left["pml"]], second[right["pml"]])
        high = min(first[-left["pml"] - 1], second[-right["pml"] - 1])
        a, b = _slice(first, low, high), _slice(second, low, high)
        common[axis] = low < high and len(a) >= 2 and a == b
    pml = _pml_grid(left, right)
    return {"board_axes_match": board, "common_non_pml_axes_match": common,
            "domain_axes_expand": domain, "pml_interface_axes_expand": interface, **pml,
            "passed": all(board.values()) and all(common.values()) and all(domain.values()) and all(interface.values()) and pml["pml_passed"]}


def assess_study(cases, profile):
    """! @brief 세 공간 수준과 별도 시간 제어의 최종 쌍을 판정하고 모든 인접 비교를 남긴다."""
    selected = _profile(profile)
    _require(type(cases) is list and bool(cases), "비교 사례 목록이 필요합니다.")
    prepared = []
    labels = set()
    for case in cases:
        _require(type(case) is dict and case.get("axis") in AXES and type(case.get("label")) is str and bool(case["label"]), "사례의 이름/축이 유효하지 않습니다.")
        key = (case["axis"], case["label"])
        _require(key not in labels, "같은 축의 사례 이름이 중복되었습니다.")
        labels.add(key)
        data = _result(case["normalized_result"])
        _require(case["settings"] == data["settings"], "사례 설정이 실제 계획과 다릅니다.")
        _require(type(case.get("artifact")) is dict and bool(case["artifact"]), "불변 결과 artifact 근거가 필요합니다.")
        if prepared:
            _require(data["identity"] == prepared[0][1]["identity"] and data["frequencies"] == prepared[0][1]["frequencies"], "연구 전체의 원본/runtime/주파수가 동일해야 합니다.")
        prepared.append((case, data))
    axes = {}
    for axis in AXES:
        group = [(case, data) for case, data in prepared if case["axis"] == axis]
        minimum = 2 if axis == "termination" else selected["minimum_levels"]
        issues, pairs = [], []
        if len(group) < minimum:
            issues.append("insufficient_levels")
        expected_key = {"mesh": "grid_mm", "boundary": "air_padding_mm", "termination": "end_criterion"}[axis]
        for (left_case, left), (right_case, right) in zip(group, group[1:]):
            changed = {key for key in set(left["settings"]) | set(right["settings"]) if left["settings"].get(key) != right["settings"].get(key)}
            pair = compare_samples(left_case["normalized_result"], right_case["normalized_result"], selected)
            pair.update(left_label=left_case["label"], right_label=right_case["label"], changed_settings=sorted(changed))
            pair_issues = []
            if changed != {expected_key}:
                pair_issues.append("expected_exactly_one_axis_setting")
            else:
                a, b = left["settings"][expected_key], right["settings"][expected_key]
                if not (_finite(a) and _finite(b) and (b > a if axis == "boundary" else 0 < b < a)):
                    pair_issues.append("axis_levels_not_strictly_ordered")
            if axis == "mesh":
                if right["native_cells"] <= left["native_cells"]:
                    pair_issues.append("actual_native_mesh_did_not_increase")
                pair["grid_comparison"] = _mesh_boundary_grid(left, right)
                if not pair["grid_comparison"]["passed"]:
                    pair_issues.append("mesh_changed_boundary_or_pml")
            if axis == "boundary":
                pair["grid_comparison"] = _boundary_grids(left, right)
                if not all(pair["grid_comparison"]["board_axes_match"].values()) or not all(pair["grid_comparison"]["common_non_pml_axes_match"].values()):
                    pair_issues.append("boundary_changed_common_interior_grid")
                if not all(pair["grid_comparison"]["domain_axes_expand"].values()) or not all(pair["grid_comparison"]["pml_interface_axes_expand"].values()):
                    pair_issues.append("actual_boundary_did_not_expand")
                if not pair["grid_comparison"]["pml_passed"]:
                    pair_issues.append("boundary_changed_pml_cells")
            if axis == "termination" and left["lines"] != right["lines"]:
                pair_issues.append("termination_changed_mesh")
            pair["study_issues"] = pair_issues
            issues.extend(pair_issues)
            pairs.append(pair)
        status = "not_established" if issues or not pairs else pairs[-1]["status"]
        axes[axis] = {"status": status, "level_count": len(group), "minimum_levels": minimum,
                      "issues": sorted(set(issues)), "pairs": pairs, "final_pair": deepcopy(pairs[-1]) if pairs else None,
                      "artifacts": [{"label": case["label"], "artifact": deepcopy(case["artifact"])} for case, _ in group]}
    statuses = {item["status"] for item in axes.values()}
    status = "established" if statuses == {"established"} else ("failed" if "failed" in statuses else "not_established")
    groups = {axis: [case for case, _ in prepared if case["axis"] == axis] for axis in AXES}
    anchors = {"status": "not_established", "labels": []}
    study_issues = []
    if all(groups.values()):
        controls = [groups["mesh"][-1], groups["boundary"][-1], groups["termination"][0]]
        anchors["labels"] = [case["label"] for case in controls]
        if all(case["settings"] == controls[0]["settings"] for case in controls[1:]):
            anchors["status"] = "matched"
        else:
            study_issues.append("axis_anchors_do_not_match")
    else:
        study_issues.append("axis_anchor_missing")
    if study_issues:
        status = "not_established"
    return {"schema": "rfad.numerical-stability-study/0.1", "acceptance_profile": selected,
            "numerical_stability": {"status": status, "axes": axes, "anchors": anchors, "issues": study_issues}, "physics_validated": False,
            "source_assessments": [{"label": case["label"], "axis": case["axis"], "assessment": deepcopy(case["normalized_result"]["assessment"])} for case, _ in prepared],
            "limitations": ["Explicit benchmark thresholds; not universal RF acceptance criteria", "Same runtime and source only; no independent solver or measurement validation",
                            "Resonance is a sampled magnitude minimum with a conservative bracket; no interpolated precision", "No target-band matching, NF2FF, gain or efficiency acceptance"]}
