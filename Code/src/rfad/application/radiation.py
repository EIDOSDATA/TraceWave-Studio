"""! @brief 방사 전력, 지향성, 이득과 정합을 서로 다른 지표로 보존한다."""

import math


def _positive(value):
    """! @brief 큰 정수와 bool도 유한 전력값으로 잘못 수용하지 않는다."""
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def power_metrics(radiated_w, accepted_w, incident_w, directivity):
    """! @brief 실제 양의 전력으로 효율과 이득을 구하고 수치 오차를 임의 보정하지 않는다."""
    values = (radiated_w, accepted_w, incident_w, directivity)
    if not all(_positive(value) for value in values):
        raise ValueError("방사 지표에는 명시적 유한 양수가 필요합니다.")
    efficiency = radiated_w / accepted_w
    gain = directivity * efficiency
    realized = directivity * radiated_w / incident_w
    if not all(_positive(value) for value in (efficiency, gain, realized)):
        raise ValueError("방사 전력 비율이 표현 범위를 벗어났습니다.")
    return {"radiated_power_w": radiated_w, "accepted_power_w": accepted_w, "incident_power_w": incident_w,
            "radiation_efficiency": efficiency, "directivity_linear": directivity,
            "directivity_dbi": 10 * math.log10(directivity), "gain_linear": gain,
            "gain_dbi": 10 * math.log10(gain), "realized_gain_linear": realized,
            "realized_gain_dbi": 10 * math.log10(realized),
            "power_balance_status": "requires_review" if radiated_w > accepted_w or accepted_w > incident_w else "nonnegative_loss",
            "physics_validated": False}
