"""! @brief 손실 연구의 격자/임계 구간/종료/곡선 단일 변화 축을 검사한다."""

from copy import deepcopy
import math

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_geometry import fail, shape_polygons
from rfad.application.pcb_loss_convergence import assess_losses, validate_profile
from rfad.application.pcb_mesh import mesh_lines


AXIS_FIELDS = {"mesh": "grid_mm", "local_mesh": "feature_subdivisions", "termination": "end_criterion", "curve": "curve_tolerance_mm"}


def validate_study(study):
    """! @brief native 실행 전에 축별 세 수준 이상과 명시적 손실 기준을 요구한다."""
    if type(study) is not dict or study.get("schema") != "rfad.pcb-loss-study/0.1":
        fail("E_SCHEMA", "독립 손실 정밀도 연구 manifest가 필요합니다.")
    validate_profile(study.get("acceptance_profile"))
    cases = study.get("cases")
    if type(cases) is not list or not 3 <= len(cases) <= 24:
        fail("E_RESOURCE", "손실 연구는 3~24개 비교 행을 지원합니다.")
    labels = set()
    for case in cases:
        if (type(case) is not dict or set(case) != {"label", "axis", "settings"}
                or type(case["label"]) is not str or not 1 <= len(case["label"]) <= 64
                or case["label"] in labels or case["axis"] not in AXIS_FIELDS):
            fail("E_SCHEMA", "손실 연구의 사례 식별/변화 축이 다릅니다.")
        from rfad.application.pcb_solver import validate_settings

        validate_settings(case["settings"])
        if "power_balance" not in case["settings"]:
            fail("E_SCHEMA", "독립 손실 기록 없이 손실 정밀도를 판정할 수 없습니다.")
        labels.add(case["label"])
    for axis in {case["axis"] for case in cases}:
        rows = [case for case in cases if case["axis"] == axis]
        if not study["acceptance_profile"]["minimum_levels"] <= len(rows) <= 6:
            fail("E_SCHEMA", "각 손실 변화 축에는 최소 수준 이상의 순서 있는 사례가 필요합니다.")
        for a, b in zip(rows, rows[1:]):
            changed_pair(a["settings"], b["settings"], axis)


def changed_pair(first, second, axis):
    """! @brief 여러 조건을 함께 바꾼 결과를 개별 축의 수렴으로 해석하지 않는다."""
    key = AXIS_FIELDS[axis]
    a, b = deepcopy(first), deepcopy(second)
    x, y = a.pop(key, 1 if axis == "local_mesh" else None), b.pop(key, 1 if axis == "local_mesh" else None)
    if a != b or x is None or y is None or (y <= x if axis == "local_mesh" else y >= x):
        fail("E_SCHEMA", "손실 연구는 해당 수치 조건 하나만 엄격히 세분화해야 합니다.")


def plan_guard(left, right, axis):
    """! @brief 동일 원본/설치와 PML/기록 면을 확인하고 실제 세분화 근거를 남긴다."""
    a, b = left["case"], right["case"]
    changed_pair(a["settings"], b["settings"], axis)
    if (left["snapshot"] != right["snapshot"] or left["source_semantics"] != right["source_semantics"]
            or left["runtime_identity"] != right["runtime_identity"] or left["normalization"] != right["normalization"]):
        fail("E_HASH", "손실 연구의 원본/재료/급전/정규화/설치가 다릅니다.")
    x, y = mesh_lines(a), mesh_lines(b)
    fixed = all([x[key][0], x[key][8], x[key][-9], x[key][-1]] == [y[key][0], y[key][8], y[key][-9], y[key][-1]] for key in "xyz")
    first, second = a["radiation_recording"], b["radiation_recording"]
    if not fixed or any(first[key] != second[key] for key in ("start_mm", "stop_mm", "center_m", "frequency_hz", "theta_deg", "phi_deg")):
        fail("E_GEOMETRY", "손실 연구는 실제 외곽/PML/방사 기록 면과 각도를 고정해야 합니다.")
    counts = [math.prod(map(len, lines.values())) for lines in (x, y)]
    if axis in {"mesh", "local_mesh"} and counts[1] <= counts[0]:
        fail("E_GEOMETRY", "손실 연구의 실제 격자점이 증가하지 않았습니다.")
    if axis in {"termination", "curve"} and x != y:
        fail("E_GEOMETRY", "종료/곡선 독립 비교는 실제 Yee 격자를 고정해야 합니다.")
    if axis == "curve" and canonical_hash([shape_polygons(shape, a["settings"]["curve_tolerance_mm"]) for shape in a["shapes"]]) == canonical_hash([shape_polygons(shape, b["settings"]["curve_tolerance_mm"]) for shape in b["shapes"]]):
        fail("E_GEOMETRY", "곡선 연구의 실제 native polygon이 세분화되지 않았습니다.")
    return {"same_snapshot_source_runtime": True, "fixed_pml_and_radiation_planes": True,
            "single_setting_changed": True, "actual_grid_points": counts, "passed": True}


def assess(study, powers):
    """! @brief 각 변화 축을 별도 판정하고 개별 성분의 실패와 실물 미검증을 보존한다."""
    axes = {}
    for axis in sorted({case["axis"] for case in study["cases"]}):
        cases = [case for case in study["cases"] if case["axis"] == axis]
        axes[axis] = assess_losses([powers[canonical_hash(case["settings"])] for case in cases], study["acceptance_profile"])
    stable = all(value["status"] == "passed" for value in axes.values())
    closed = all(value["full_energy_closure"] == "within_initial_numerical_budget" for value in powers.values())
    return {"schema": "rfad.pcb-loss-study-assessment/0.1", "study_hash": canonical_hash(study), "axes": axes,
            "individual_loss_stability": "passed" if stable else "not_established",
            "full_energy_closure": "within_initial_numerical_budget" if closed else "requires_review",
            "status": "passed" if stable and closed else "not_established",
            "scope": "tested_settings_only_not_continuum_accuracy", "physics_validated": False,
            "fabrication_validated": False, "measurement_validated": False}
