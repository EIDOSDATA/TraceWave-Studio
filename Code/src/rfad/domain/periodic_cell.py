"""! @brief 이중 주기 셀의 입력을 검증하고 유한 재료 격자를 구성한다."""

import math

from rfad.domain.network_data import fail, finite
from rfad.domain.planar import MAX_REGION_HOLES, MAX_REGION_POINTS, validate_region


MAX_GRID_POINTS = 625
MAX_LAYERS = 12
MAX_REGIONS = 64
MAX_VERTICES = 4096


def _keys(value, required, field):
    """! @brief 지원 형식 밖의 필드를 조용히 버리지 않는다."""
    if type(value) is not dict or set(value) != set(required):
        fail("필수 입력 필드를 확인하십시오.", field)


def _number(value, lower, upper, field):
    """! @brief 단위별 유효 범위를 검사한다."""
    if not lower <= finite(value, field) <= upper:
        fail(f"입력 범위는 {lower}~{upper}입니다.", field)


def _loop(loop, period, field):
    """! @brief 셀 좌표의 단순 닫힌 경로를 검사한다."""
    if type(loop) is not list or not 3 <= len(loop) <= MAX_REGION_POINTS:
        fail("다각형에 3~64개 꼭짓점이 필요합니다.", field)
    for pair in loop:
        if type(pair) is not list or len(pair) != 2:
            fail("평면 좌표는 [x, y]입니다.", field)
        for value, limit in zip(pair, period):
            _number(value, 0, limit, field)


def validate(case):
    """! @brief 직교 단위셀, 수동 재료, 입사 및 두 해상도의 계산 예산을 검사한다."""
    _keys(case, ("period_mm", "epsilon_left", "epsilon_right", "materials", "layers", "frequencies_hz",
                 "theta_deg", "phi_deg", "polarization", "grid", "comparison_grid"), "case")
    period = case["period_mm"]
    if type(period) is not list or len(period) != 2:
        fail("X/Y 주기를 각각 입력하십시오.", "period_mm")
    for value in period:
        _number(value, 1e-3, 1000, "period_mm")
    for key in ("epsilon_left", "epsilon_right"):
        _number(case[key], 0.01, 100, key)
    _number(case["theta_deg"], 0, 89.99, "theta_deg")
    _number(case["phi_deg"], -360, 360, "phi_deg")
    if case["polarization"] not in ("TE", "TM"):
        fail("입사 편파는 TE 또는 TM입니다.", "polarization")
    frequencies = case["frequencies_hz"]
    if type(frequencies) is not list or not 1 <= len(frequencies) <= 31:
        fail("증가하는 주파수를 1~31개 입력하십시오.", "frequencies_hz")
    for frequency in frequencies:
        _number(frequency, 1e6, 1e13, "frequencies_hz")
    if any(b <= a for a, b in zip(frequencies, frequencies[1:])):
        fail("증가하는 주파수를 입력하십시오.", "frequencies_hz")
    for key in ("grid", "comparison_grid"):
        grid = case[key]
        if (type(grid) is not list or len(grid) != 2
                or any(type(n) is not int or n < 1 or n % 2 == 0 for n in grid)
                or math.prod(grid) > MAX_GRID_POINTS):
            fail(f"각 축에 홀수 격자를 사용하고 곱은 {MAX_GRID_POINTS} 이하여야 합니다.", key, "E_RESOURCE")
    if (case["grid"] == case["comparison_grid"]
            or any(a > b for a, b in zip(case["grid"], case["comparison_grid"]))):
        fail("비교 격자는 두 축 모두 같거나 촘촘하며 한 축 이상을 세분해야 합니다.", "comparison_grid")
    materials = case["materials"]
    if type(materials) is not dict or not 1 <= len(materials) <= 32:
        fail("재료를 1~32개 정의하십시오.", "materials")
    for name, material in materials.items():
        if type(name) is not str or not name.strip() or len(name) > 128:
            fail("재료 이름을 확인하십시오.", "materials")
        field = "materials." + name
        _keys(material, ("epsilon_r", "tan_delta", "conductivity_s_per_m"), field)
        _number(material["epsilon_r"], 0.01, 100, field + ".epsilon_r")
        _number(material["tan_delta"], 0, 1, field + ".tan_delta")
        _number(material["conductivity_s_per_m"], 0, 1e9, field + ".conductivity_s_per_m")
    layers = case["layers"]
    if type(layers) is not list or not 1 <= len(layers) <= MAX_LAYERS:
        fail(f"두께 방향 층을 1~{MAX_LAYERS}개 정의하십시오.", "layers")
    vertices = 0
    for index, layer in enumerate(layers):
        field = f"layers.{index}"
        _keys(layer, ("thickness_mm", "background", "regions"), field)
        _number(layer["thickness_mm"], 1e-4, 1000, field + ".thickness_mm")
        if type(layer["background"]) is not str or layer["background"] not in materials:
            fail("정의한 바탕 재료를 지정하십시오.", field + ".background")
        if type(layer["regions"]) is not list or len(layer["regions"]) > MAX_REGIONS:
            fail(f"각 층의 재료 영역은 최대 {MAX_REGIONS}개입니다.", field + ".regions", "E_RESOURCE")
        for index, region in enumerate(layer["regions"]):
            path = f"{field}.regions.{index}"
            _keys(region, ("material", "outer", "holes"), path)
            if type(region["material"]) is not str or region["material"] not in materials:
                fail("정의한 영역 재료를 지정하십시오.", path + ".material")
            if type(region["holes"]) is not list or len(region["holes"]) > MAX_REGION_HOLES:
                fail("내부 구멍은 최대 8개입니다.", path + ".holes")
            for loop in (region["outer"], *region["holes"]):
                _loop(loop, period, path)
                vertices += len(loop)
                if vertices > MAX_VERTICES:
                    fail("전체 재료 영역의 꼭짓점 수 상한을 넘었습니다.", path, "E_RESOURCE")
            validate_region(region["outer"], region["holes"], path)


def _inside(np, loop, x, y):
    """! @brief 반개구간 교차 규칙으로 경계에 놓인 격자 표본을 일관되게 분류한다."""
    inside = np.zeros(np.broadcast_shapes(x.shape, y.shape), dtype=bool)
    for (xa, ya), (xb, yb) in zip(loop, loop[1:] + loop[:1]):
        if ya != yb:
            inside ^= ((ya > y) != (yb > y)) & (x < xa + (xb - xa) * (y - ya) / (yb - ya))
    return inside


def raster(np, case, layer, grid, offsets):
    """! @brief 전계 성분별 표본에 바탕, 도체 및 손실 재료를 배정한다."""
    positions = [(np.arange(n) + offset) * period / n
                 for n, offset, period in zip(grid, offsets, case["period_mm"])]
    x, y = positions[0][:, None], positions[1][None, :]
    names = list(case["materials"])
    labels = np.full(grid, -1, dtype=int)
    for region in layer["regions"]:
        mask = _inside(np, region["outer"], x, y)
        for hole in region["holes"]:
            void = _inside(np, hole, x, y)
            if not void.any():
                fail("격자에서 사라지는 내부 구멍이 있습니다. 격자를 세분하십시오.", "grid", "E_GEOMETRY")
            mask &= ~void
        if not mask.any():
            fail("격자에서 사라지는 재료 영역이 있습니다. 격자를 세분하십시오.", "grid", "E_GEOMETRY")
        label = names.index(region["material"])
        if np.any(mask & (labels >= 0) & (labels != label)):
            fail("한 층에서 서로 다른 재료 영역이 겹칩니다.", "layers", "E_GEOMETRY")
        labels[mask] = label
    labels[labels < 0] = names.index(layer["background"])
    return labels.reshape(-1)
