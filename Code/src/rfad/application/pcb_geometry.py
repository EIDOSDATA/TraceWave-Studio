"""! @brief 사용자 PCB 수량을 mm 기하와 제한된 도체 polygon으로 투영한다."""

import math

from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.planar import decompose_region

MAX_POLYGON_POINTS = 8192


def fail(code, message, field=""):
    """! @brief 원본 입력 위치를 포함한 구조화된 거절 사유를 만든다."""
    raise ProjectError(code, message, details={"field_path": field})


def scalar(document, value, dimension, field, *, positive=False, nonnegative=False):
    """! @brief 미정값을 대체하지 않고 유한 SI 수량만 소비한다."""
    quantity = resolve_scalar(document, value, dimension, field)
    number = quantity.value_si
    if number is None:
        fail("E_MATERIAL_UNKNOWN" if dimension in ("conductivity", "dimensionless") else "E_GEOMETRY", "해석 필수 입력이 미정입니다.", field)
    if not math.isfinite(number) or (positive and number <= 0) or (nonnegative and number < 0):
        fail("E_SCHEMA", "해석 입력의 수치 범위가 유효하지 않습니다.", field)
    return number


def length(document, value, field, *, positive=False):
    """! @brief mm 출력 범위를 검사하고 원본 Quantity는 변경하지 않는다."""
    result = scalar(document, value, "length", field, positive=positive) * 1000.0
    if abs(result) > 1000 or (positive and result < 1e-4):
        fail("E_GEOMETRY", "PCB 해석의 좌표 또는 최소 치수 범위를 벗어났습니다.", field)
    # @brief 0두께 sheet와 격자선을 동일한 mm 표현 정밀도로 맞추고 원본 Quantity는 보존한다.
    return round(result, 12)


def point(document, values, field):
    """! @brief 원본 좌표를 mm로 평가한다."""
    return [length(document, value, field + f"[{i}]") for i, value in enumerate(values)]


def _angles(start, sweep, radius, tolerance):
    """! @brief 원의 chord sagitta가 지정 오차 이내가 되는 각도 표본을 만든다."""
    angle = 2 * math.acos(max(-1.0, min(1.0, 1 - tolerance / radius)))
    count = max(1, math.ceil(abs(sweep) / min(angle, math.pi / 8)))
    if math.isclose(abs(sweep), math.pi, abs_tol=1e-12) and count % 2:
        count += 1
    if count > MAX_POLYGON_POINTS:
        fail("E_RESOURCE", "곡선의 native polygon 분할 수가 상한을 넘습니다.", "settings.curve_tolerance_mm")
    return [start + sweep * i / count for i in range(count + 1)]


def shape_polygons(shape, tolerance):
    """! @brief 원형 끝단을 포함한 선/원호를 오차가 제한된 polygon으로 투영한다."""
    if shape["kind"] == "planar_region":
        return decompose_region(shape["outer_mm"], shape["holes_mm"])
    if shape["kind"] == "pad":
        cx, cy = shape["center_mm"]
        if shape["pad_shape"] == "circle":
            radius = shape["size_mm"][0] / 2
            angles = _angles(0, 2 * math.pi, radius, tolerance)
            return [[[cx + radius * math.cos(t), cy + radius * math.sin(t)] for t in angles[:-1]]]
        half_x, half_y = (size / 2 for size in shape["size_mm"])
        angle = math.radians(shape["rotation_deg"])
        return [[[cx + x * math.cos(angle) - y * math.sin(angle), cy + x * math.sin(angle) + y * math.cos(angle)]
                 for x, y in ((-half_x, -half_y), (half_x, -half_y), (half_x, half_y), (-half_x, half_y))]]
    width = shape["width_mm"]
    half = width / 2
    if shape["kind"] == "line_path":
        a, b = shape["start_mm"], shape["end_mm"]
        direction = math.atan2(b[1] - a[1], b[0] - a[0])
        result = [[b[0] + half * math.cos(t), b[1] + half * math.sin(t)] for t in _angles(direction - math.pi / 2, math.pi, half, tolerance)]
        result += [[a[0] + half * math.cos(t), a[1] + half * math.sin(t)] for t in _angles(direction + math.pi / 2, math.pi, half, tolerance)]
        return [result]
    cx, cy = shape["center_mm"]
    radius, start, sweep = shape["radius_mm"], math.radians(shape["start_angle_deg"]), math.radians(shape["sweep_angle_deg"])
    inner, outer = radius - half, radius + half
    def arc(r, a, d):
        return [[cx + r * math.cos(t), cy + r * math.sin(t)] for t in _angles(a, d, r, tolerance)]
    if abs(sweep) >= 2 * math.pi - 1e-12:
        sign = 1 if sweep > 0 else -1
        return [arc(outer, start + index * sign * math.pi / 2, sign * math.pi / 2) + arc(inner, start + (index + 1) * sign * math.pi / 2, -sign * math.pi / 2) for index in range(4)]
    sign = 1 if sweep > 0 else -1
    end = start + sweep
    ex, ey = cx + radius * math.cos(end), cy + radius * math.sin(end)
    sx, sy = cx + radius * math.cos(start), cy + radius * math.sin(start)
    return [arc(outer, start, sweep)
            + [[ex + half * math.cos(t), ey + half * math.sin(t)] for t in _angles(end, sign * math.pi, half, tolerance)][1:]
            + arc(inner, end, -sweep)[1:]
            + [[sx + half * math.cos(t), sy + half * math.sin(t)] for t in _angles(start + sign * math.pi, sign * math.pi, half, tolerance)][1:]]


def distance_to_shape(position, shape):
    """! @brief 원형 끝단을 포함한 analytic 중심선까지의 거리를 반환한다."""
    if shape["kind"] == "line_path":
        a, b = shape["start_mm"], shape["end_mm"]
        delta = [b[i] - a[i] for i in range(2)]
        t = max(0, min(1, sum((position[i] - a[i]) * delta[i] for i in range(2)) / sum(v * v for v in delta)))
        return math.dist(position, [a[i] + t * delta[i] for i in range(2)])
    center, radius = shape["center_mm"], shape["radius_mm"]
    start, sweep = math.radians(shape["start_angle_deg"]), math.radians(shape["sweep_angle_deg"])
    angle = math.atan2(position[1] - center[1], position[0] - center[0])
    delta = ((angle - start) * (1 if sweep > 0 else -1)) % (2 * math.pi)
    if delta <= abs(sweep) + 1e-12:
        return abs(math.dist(position, center) - radius)
    return min(math.dist(position, [center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)]) for a in (start, start + sweep))


def _bounds(shape):
    """! @brief analytic 도체 중심선의 축 극값과 round cap 외곽을 구한다."""
    if shape["kind"] == "planar_region":
        return [[min(p[i] for p in shape["outer_mm"]), max(p[i] for p in shape["outer_mm"])] for i in range(2)]
    if shape["kind"] == "pad":
        if shape["pad_shape"] == "circle":
            radius = shape["size_mm"][0] / 2
            return [[c - radius, c + radius] for c in shape["center_mm"]]
        points = shape_polygons(shape, 0.01)[0]
        return [[min(p[i] for p in points), max(p[i] for p in points)] for i in range(2)]
    half = shape["width_mm"] / 2
    if shape["kind"] == "line_path":
        points = [shape["start_mm"], shape["end_mm"]]
    else:
        start, sweep = math.radians(shape["start_angle_deg"]), math.radians(shape["sweep_angle_deg"])
        angles = [start, start + sweep]
        for a in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
            if ((a - start) * (1 if sweep > 0 else -1)) % (2 * math.pi) <= abs(sweep) + 1e-12:
                angles.append(a)
        points = [[shape["center_mm"][0] + shape["radius_mm"] * math.cos(a), shape["center_mm"][1] + shape["radius_mm"] * math.sin(a)] for a in angles]
    return [[min(p[i] for p in points) - half, max(p[i] for p in points) + half] for i in range(2)]


def _inside_board(board, shape):
    """! @brief polygon 표본 대신 analytic 중심선 극값으로 원/직사각 외곽을 검사한다."""
    if board["kind"] == "rectangle":
        bounds = _bounds(shape)
        return all(bounds[i][0] >= -1e-9 and bounds[i][1] <= board["dimensions_mm"][i] + 1e-9 for i in range(2))
    center = board["center_mm"]
    if shape["kind"] in ("planar_region", "pad"):
        if shape["kind"] == "pad" and shape["pad_shape"] == "circle":
            return math.dist(center, shape["center_mm"]) + shape["size_mm"][0] / 2 <= board["radius_mm"] + 1e-9
        points = shape["outer_mm"] if shape["kind"] == "planar_region" else shape_polygons(shape, 0.01)[0]
        return all(math.dist(center, p) <= board["radius_mm"] + 1e-9 for p in points)
    if shape["kind"] == "line_path":
        maximum = max(math.dist(center, p) for p in (shape["start_mm"], shape["end_mm"]))
    else:
        sc = shape["center_mm"]
        start, sweep = math.radians(shape["start_angle_deg"]), math.radians(shape["sweep_angle_deg"])
        angles = [start, start + sweep]
        far = math.atan2(sc[1] - center[1], sc[0] - center[0])
        if ((far - start) * (1 if sweep > 0 else -1)) % (2 * math.pi) <= abs(sweep) + 1e-12:
            angles.append(far)
        maximum = max(math.dist(center, [sc[0] + shape["radius_mm"] * math.cos(a), sc[1] + shape["radius_mm"] * math.sin(a)]) for a in angles)
    return maximum + shape["width_mm"] / 2 <= board["radius_mm"] + 1e-9
