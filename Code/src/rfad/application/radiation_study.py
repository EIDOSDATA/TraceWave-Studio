"""! @brief 방사 수렴 연구의 명시적 판정 기준과 독립 변화 행렬을 검증한다."""

from copy import deepcopy
import math
import re

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import validate_settings


AXES = ("mesh", "box", "angle")
LIMITS = ("max_pattern_delta", "max_radiated_relative_delta", "max_directivity_delta_db",
          "max_gain_delta_db", "max_efficiency_delta", "max_s11_complex_delta",
          "max_sphere_relative_error", "max_passivity_excess", "max_port_balance_relative_error")


def require(condition, message):
    """! @brief 비교 불가능한 입력을 수치 불합격과 별도의 오류로 차단한다."""
    if not condition:
        raise ValueError(message)


def finite(value):
    """! @brief bool 및 표현 범위를 넘는 정수를 유한 값으로 수용하지 않는다."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_profile(profile):
    """! @brief 계산 뒤 임계값을 낮추지 않도록 명시적 유한 판정 기준을 요구한다."""
    require(type(profile) is dict and set(profile) == {"id", "minimum_levels", *LIMITS}, "방사 연구 판정 profile의 필드가 다릅니다.")
    require(type(profile["id"]) is str and bool(profile["id"].strip()), "판정 profile 식별자가 필요합니다.")
    require(type(profile["minimum_levels"]) is int and 3 <= profile["minimum_levels"] <= 6, "각 수렴 축에는 최소 3수준이 필요합니다.")
    for key in LIMITS:
        require(finite(profile[key]) and 0 < profile[key] <= (3 if key.endswith("_db") else 0.25), "유한 양수인 초기 비교 한계가 필요합니다: " + key)
    return deepcopy(profile)


def changed_settings(settings, axis, overrides):
    """! @brief 격자/기록 거리/각도 한 축만 변경하고 숨은 기본값을 만들지 않는다."""
    allowed = {"mesh": {"grid_mm"}, "box": {"box_clearance_mm"}, "angle": {"theta_step_deg", "phi_step_deg"}}
    require(axis in AXES and type(overrides) is dict and set(overrides) == allowed[axis], "해당 연구 축의 설정만 바꿀 수 있습니다.")
    result = deepcopy(settings)
    target = result if axis == "mesh" else result["radiation"]
    target.update(deepcopy(overrides))
    validate_settings(result)
    return result


def validate_study(study):
    """! @brief 공유 기준 계산으로 연결된 세 축의 유한한 실행 행렬을 확장한다."""
    keys = {"schema", "id", "description", "fixture", "acceptance_profile", "base_settings", "cases"}
    require(type(study) is dict and set(study) == keys and study["schema"] == "rfad.pcb-radiation-study/0.1", "방사 연구 형식 또는 필드가 다릅니다.")
    for key in ("id", "description", "fixture"):
        require(type(study[key]) is str and bool(study[key].strip()), "명시적 연구 식별자/설명/fixture가 필요합니다.")
    profile = validate_profile(study["acceptance_profile"])
    base = study["base_settings"]
    validate_settings(base)
    require("radiation" in base and "box_clearance_mm" in base["radiation"], "독립 연구에는 명시적 기록 상자 거리가 필요합니다.")
    band = base["frequency_hz"]
    port_frequencies = [band["start"] + (band["stop"] - band["start"]) * i / (band["count"] - 1) for i in range(band["count"])]
    require(all(any(math.isclose(frequency, port, rel_tol=0, abs_tol=1e-5) for port in port_frequencies) for frequency in base["radiation"]["frequency_hz"]),
            "전력 수지 주파수는 직접 포트 표본에 있어야 합니다. 보간하지 않습니다.")
    require(type(study["cases"]) is list and 9 <= len(study["cases"]) <= 18, "세 축 각 3수준 이상의 사례가 필요합니다.")
    result, labels = [], set()
    for case in study["cases"]:
        require(type(case) is dict and set(case) == {"label", "axis", "overrides"}, "연구 사례의 필드가 다릅니다.")
        label, axis = case["label"], case["axis"]
        require(type(label) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", label) is not None and label not in labels, "고유한 ASCII 사례 이름이 필요합니다.")
        labels.add(label)
        settings = changed_settings(base, axis, case["overrides"])
        result.append({"label": label, "axis": axis, "settings": settings, "settings_hash": canonical_hash(settings)})
    for axis in AXES:
        rows = [row for row in result if row["axis"] == axis]
        require(len(rows) >= profile["minimum_levels"], "각 방사 연구 축의 수준이 부족합니다.")
        require(rows[-1]["settings"] == base, "모든 축의 최종 사례가 같은 기준 계산이어야 합니다.")
        for first, second in zip(rows, rows[1:]):
            a, b = first["settings"], second["settings"]
            if axis == "mesh":
                ordered = b["grid_mm"] < a["grid_mm"]
            elif axis == "box":
                ordered = b["radiation"]["box_clearance_mm"] > a["radiation"]["box_clearance_mm"]
            else:
                a, b = a["radiation"], b["radiation"]
                ordered = all(b[key] < a[key] and a[key] % b[key] == 0 for key in ("theta_step_deg", "phi_step_deg"))
            require(ordered, "격자/각도는 세분화하고 기록 거리는 늘려야 하며 각도 표본은 중첩되어야 합니다.")
    return result
