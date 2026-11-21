"""! @brief PCB 기본 예산과 명시적 수치 연구의 자원 상한을 반환한다."""

from rfad.application.pcb_geometry import fail


def limits(settings):
    """! @brief 연구 profile이 없으면 과거 계획의 격자/시간/스레드 값을 그대로 반환한다."""
    profile = settings.get("compute_profile")
    if profile is None and "compute_profile" not in settings:
        return {"max_grid_points": 1500000, "max_wall_time_seconds": 300, "num_threads": 2}
    if (type(profile) is not dict or set(profile) != {"kind", "num_threads"}
            or type(profile["kind"]) is not str or type(profile["num_threads"]) is not int
            or not 1 <= profile["num_threads"] <= 8):
        fail("E_RESOURCE", "지원하는 계산 profile과 1~8개 스레드를 명시하십시오.", "settings.compute_profile")
    kind = profile["kind"]
    if kind == "tuning_refinement/0.1":
        return {"max_grid_points": 1500000, "max_wall_time_seconds": 900, "num_threads": profile["num_threads"]}
    if kind not in {"loss_refinement/0.1", "loss_refinement_deep/0.1"} or "power_balance" not in settings:
        fail("E_RESOURCE", "손실 정밀 연구에는 지원하는 profile과 독립 손실 기록을 명시하십시오.", "settings.compute_profile")
    if kind == "loss_refinement_deep/0.1":
        return {"max_grid_points": 3000000, "max_wall_time_seconds": 1800, "max_loss_field_bytes": 96 * 1024 * 1024, "num_threads": profile["num_threads"]}
    return {"max_grid_points": 2400000, "max_wall_time_seconds": 900, "num_threads": profile["num_threads"]}
