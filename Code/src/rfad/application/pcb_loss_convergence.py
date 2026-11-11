"""! @brief 에너지 수지와 구분하여 개별 독립 손실의 설정별 안정성을 비교한다."""

import math

from rfad.application.pcb_geometry import fail


def initial_profile():
    """! @brief 실측 정확도가 아닌 사전 채택용 개별 손실 수치 예산을 반환한다."""
    return {"id": "independent-loss-initial/0.1", "minimum_levels": 3,
            "max_relative_delta": 0.02, "absolute_fraction_floor": 1e-5}


def validate_profile(profile):
    """! @brief 영에 가까운 손실의 명시적 절대 바닥과 상대 예산을 함께 고정한다."""
    if (type(profile) is not dict or set(profile) != {"id", "minimum_levels", "max_relative_delta", "absolute_fraction_floor"}
            or type(profile["id"]) is not str or not 1 <= len(profile["id"]) <= 120
            or type(profile["minimum_levels"]) is not int or not 3 <= profile["minimum_levels"] <= 6
            or any(type(profile[key]) not in (int, float) or not math.isfinite(profile[key]) for key in ("max_relative_delta", "absolute_fraction_floor"))
            or not 1e-4 <= profile["max_relative_delta"] <= 0.1 or not 1e-8 <= profile["absolute_fraction_floor"] <= 1e-3):
        fail("E_SCHEMA", "독립 손실 비교에는 최소 3수준과 유한한 상대/수용 전력 비율 예산이 필요합니다.")


def _fractions(result):
    """! @brief 동일 여기 크기에 의존하지 않는 수용 전력 정규화와 원본별 성분을 읽는다."""
    rows = []
    for row in result["frequencies"]:
        frequency = row["frequency_hz"]
        if (type(frequency) not in (int, float) or not math.isfinite(frequency) or frequency <= 0
                or rows and frequency <= rows[-1][0]):
            fail("E_HASH", "손실 비교의 직접 주파수는 양의 유한 증가 배열이어야 합니다.")
        accepted = row["accepted_power_w_s2"]
        if type(accepted) not in (int, float) or not math.isfinite(accepted) or accepted <= 0:
            fail("E_HASH", "손실 비교에는 양의 수용 전력이 필요합니다.")
        values = {key: row[key] / accepted for key in ("dielectric_loss_w_s2", "conductor_loss_w_s2")}
        for key in ("sheet_loss_w_s2", "via_loss_w_s2"):
            if key in row:
                values[key] = row[key] / accepted
        for key in ("sheet_components", "dielectric_components", "via_components"):
            for item in row.get(key, []):
                name = key + ":" + item["entity_id"]
                if name in values:
                    fail("E_HASH", "손실 비교에 원본 식별자가 중복됐습니다.")
                values[name] = item["loss_w_s2"] / accepted
        if any(not math.isfinite(value) for value in values.values()):
            fail("E_HASH", "손실 비교 성분은 유한해야 합니다.")
        rows.append((frequency, values))
    return rows


def compare_losses(left, right, profile):
    """! @brief 모든 직접 주파수와 원본별 성분을 비교하며 작은 음수도 합격으로 자르지 않는다."""
    validate_profile(profile)
    first, second = _fractions(left), _fractions(right)
    if (not first or len(first) != len(second) or any(a[0] != b[0] or a[1].keys() != b[1].keys() for a, b in zip(first, second))):
        fail("E_HASH", "손실 비교의 주파수 또는 재료/도체 분할이 다릅니다.")
    rows = []
    for (frequency, a), (_, b) in zip(first, second):
        for name in a:
            delta, scale = abs(a[name] - b[name]), max(abs(a[name]), abs(b[name]))
            tolerance = max(profile["absolute_fraction_floor"], profile["max_relative_delta"] * scale)
            rows.append({"frequency_hz": frequency, "component": name, "left_fraction": a[name], "right_fraction": b[name],
                         "absolute_fraction_delta": delta, "relative_delta": delta / scale if scale else 0.0,
                         "allowed_fraction_delta": tolerance, "status": "passed" if min(a[name], b[name]) >= 0 and delta <= tolerance else "not_established"})
    return {"status": "passed" if all(row["status"] == "passed" for row in rows) else "not_established", "components": rows}


def assess_losses(results, profile):
    """! @brief 최소 수준을 확인하고 마지막 인접 쌍을 판정하며 이전 실패를 보존한다."""
    validate_profile(profile)
    comparisons = [compare_losses(a, b, profile) for a, b in zip(results, results[1:])]
    enough = len(results) >= profile["minimum_levels"]
    return {"schema": "rfad.independent-loss-stability/0.1", "profile": profile,
            "minimum_levels_met": enough, "comparisons": comparisons,
            "status": comparisons[-1]["status"] if comparisons and enough else "not_established",
            "scope": "tested_settings_only_not_continuum_accuracy", "physics_validated": False,
            "fabrication_validated": False, "measurement_validated": False}
