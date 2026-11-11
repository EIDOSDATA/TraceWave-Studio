"""! @brief 기본 PCB 예산을 보존하고 명시적인 손실 정밀 연구만 유한하게 확장한다."""

from rfad.application.pcb_geometry import fail


def limits(settings):
    """! @brief 연구 profile이 없으면 과거 계획의 격자/시간/스레드 값을 그대로 반환한다."""
    profile = settings.get("compute_profile")
    if profile is None and "compute_profile" not in settings:
        return {"max_grid_points": 1500000, "max_wall_time_seconds": 300, "num_threads": 2}
    if (type(profile) is not dict or set(profile) != {"kind", "num_threads"}
            or profile["kind"] not in {"loss_refinement/0.1", "loss_refinement_deep/0.1"} or type(profile["num_threads"]) is not int
            or not 1 <= profile["num_threads"] <= 8 or "power_balance" not in settings):
        fail("E_RESOURCE", "손실 정밀 연구에는 지원하는 profile과 1~8개 스레드 및 독립 손실 기록을 명시하십시오.", "settings.compute_profile")
    if profile["kind"] == "loss_refinement_deep/0.1":
        return {"max_grid_points": 3000000, "max_wall_time_seconds": 1800, "max_loss_field_bytes": 96 * 1024 * 1024, "num_threads": profile["num_threads"]}
    return {"max_grid_points": 2400000, "max_wall_time_seconds": 900, "num_threads": profile["num_threads"]}
