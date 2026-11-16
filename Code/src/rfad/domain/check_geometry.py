"""! @brief 원본 수량에서 곡선 tessellation 없는 평면 DRC 경계를 해석한다."""

from dataclasses import dataclass
from functools import cached_property
import math

from rfad.domain.boundary_distance import Arc, Segment, add, sub, norm, point_distance, boundary_distance, extreme_points
from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.units import QuantityError


MAX_COORDINATE_MM = 1e6
MIN_FEATURE_MM = 1e-6


def scalar(document, value, dimension="length", unit="mm"):
    """! @brief 미정이나 지원 수치 범위를 0으로 바꾸지 않는다."""
    quantity = resolve_scalar(document, value, dimension)
    if quantity.value_si is None:
        raise ProjectError("E_CHECK_UNKNOWN", "검사에 필요한 치수가 미정입니다.")
    try:
        number = quantity.as_unit(unit)
    except QuantityError as error:
        raise ProjectError("E_CHECK_RANGE", "검사 단위에서 표현할 수 없는 치수입니다.") from error
    if not math.isfinite(number) or abs(number) > MAX_COORDINATE_MM:
        raise ProjectError("E_CHECK_RANGE", "기본 DRC의 수치 범위를 벗어납니다.")
    return number


def _inside_loop(point, loop):
    """! @brief 접합 허용오차 없이 ray crossing과 정확한 선분 경계를 검사한다."""
    inside = False
    for a, b in zip(loop, loop[1:] + loop[:1]):
        if point_distance(point, Segment(a, b))[0] == 0:
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            crossing = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if point[0] < crossing:
                inside = not inside
    return inside


@dataclass
class Footprint:
    """! @brief 검사용 파생 경계이며 저장 원본이나 형상을 수정하지 않는다."""
    source: dict
    edges: list
    contains: object
    width: float | None

    @cached_property
    def bounds(self):
        """! @brief 해석적 극값으로 broad-phase AABB를 계산한다."""
        points = [point for edge in self.edges for point in extreme_points(edge)]
        return (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))

    @cached_property
    def guard(self):
        """! @brief 형상 수치 조건의 경계 판정에 쓰는 float64 보호 구간이다."""
        return max(1e-12, 64 * math.ulp(max(1.0, *map(abs, self.bounds))))


def footprint(document, row):
    """! @brief round cap 선/원호, 원/사각 패드, 구멍 polygon과 비아 annulus를 해석한다."""
    length = lambda raw: scalar(document, raw)
    point = lambda raw: tuple(length(value) for value in raw)
    kind = row["kind"]
    edges, width = [], None
    if kind == "line_path":
        a, b, width = point(row["start"]), point(row["end"]), length(row["width"])
        delta = sub(b, a)
        distance = norm(delta)
        if distance < MIN_FEATURE_MM or width < MIN_FEATURE_MM:
            raise ProjectError("E_CHECK_RANGE", "선의 길이/폭이 기본 DRC 범위보다 작습니다.")
        theta, half = math.atan2(delta[1], delta[0]), width / 2
        normal = (-delta[1] * half / distance, delta[0] * half / distance)
        edges = [Segment(add(a, normal), add(b, normal)), Segment(sub(a, normal), sub(b, normal)),
                 Arc(a, half, theta + math.pi / 2, math.pi), Arc(b, half, theta - math.pi / 2, math.pi)]
        contains = lambda p: point_distance(p, Segment(a, b))[0] <= half
    elif kind == "arc_path":
        center, radius, width = point(row["center"]), length(row["radius"]), length(row["width"])
        theta = scalar(document, row["start_angle"], "angle", "rad")
        sweep = scalar(document, row["sweep_angle"], "angle", "rad")
        half = width / 2
        if min(width, radius - half) < MIN_FEATURE_MM or abs(sweep) > math.tau or abs(sweep) < 1e-12:
            raise ProjectError("E_CHECK_UNSUPPORTED", "단순 annular 원호의 기본 DRC 범위를 벗어납니다.")
        start, stop = theta, theta + sweep
        base = Arc(center, radius, min(start, stop), abs(sweep))
        edges = [Arc(center, radius + half, base.start, base.sweep), Arc(center, radius - half, base.start, base.sweep)]
        first, last = base.point(start), base.point(stop)
        closed = abs(sweep) == math.tau
        if not closed:
            if abs(sweep) > math.pi and norm(sub(first, last)) <= width:
                raise ProjectError("E_CHECK_UNSUPPORTED", "원호 끝 cap 자기 중첩은 기본 DRC에서 미평가입니다.")
            edges += [Arc(first, half, start + (math.pi if sweep > 0 else 0), math.pi),
                      Arc(last, half, stop + (0 if sweep > 0 else math.pi), math.pi)]
        contains = lambda p: (abs(norm(sub(p, center)) - radius) <= half and base.accepts(math.atan2(p[1] - center[1], p[0] - center[0]))) or (not closed and min(norm(sub(p, first)), norm(sub(p, last))) <= half)
    elif kind == "via" or (kind == "pad" and row["pad_shape"] == "circle"):
        center = point(row["center"])
        if kind == "via":
            inner, plating = length(row["finished_hole_diameter"]) / 2, length(row["plating_thickness"])
            outer = inner + plating
            if min(inner, plating) < MIN_FEATURE_MM:
                raise ProjectError("E_CHECK_RANGE", "비아 치수가 기본 DRC 범위보다 작습니다.")
            edges = [Arc(center, outer), Arc(center, inner)]
            contains = lambda p: inner <= norm(sub(p, center)) <= outer
        else:
            width = length(row["size"][0])
            if width < MIN_FEATURE_MM:
                raise ProjectError("E_CHECK_RANGE", "패드 치수가 기본 DRC 범위보다 작습니다.")
            edges = [Arc(center, width / 2)]
            contains = lambda p: norm(sub(p, center)) <= width / 2
    else:
        if kind == "pad":
            cx, cy = point(row["center"])
            sx, sy = (length(raw) for raw in row["size"])
            angle = scalar(document, row["rotation"], "angle", "rad")
            width = min(sx, sy)
            if width < MIN_FEATURE_MM:
                raise ProjectError("E_CHECK_RANGE", "패드 치수가 기본 DRC 범위보다 작습니다.")
            loop = [(cx + x * math.cos(angle) - y * math.sin(angle), cy + x * math.sin(angle) + y * math.cos(angle))
                    for x, y in ((-sx/2,-sy/2),(sx/2,-sy/2),(sx/2,sy/2),(-sx/2,sy/2))]
            loops = [loop]
        else:
            loops = [[point(raw) for raw in loop] for loop in [row["outer"], *row["holes"]]]
            loop = loops[0]
            if len(loops) == 1 and len(loop) == 4 and all(a[0] == b[0] or a[1] == b[1] for a, b in zip(loop, loop[1:] + loop[:1])):
                width = min(max(p[axis] for p in loop) - min(p[axis] for p in loop) for axis in (0, 1))
        edges = [Segment(a, b) for loop in loops for a, b in zip(loop, loop[1:] + loop[:1])]
        contains = lambda p: _inside_loop(p, loops[0]) and not any(_inside_loop(p, loop) for loop in loops[1:])
    result = Footprint(row, edges, contains, width)
    if max(map(abs, result.bounds)) > MAX_COORDINATE_MM:
        raise ProjectError("E_CHECK_RANGE", "기본 DRC의 실제 경계 좌표 범위를 벗어납니다.")
    return result


def separation(a, b, budget):
    """! @brief 구멍/곡선의 경계 거리와 포함 관계를 함께 확인한다."""
    budget[0] -= len(a.edges) * len(b.edges)
    if budget[0] < 0:
        raise ProjectError("E_RESOURCE", "기본 DRC 경계쌍 계산 예산을 초과했습니다.")
    nearest = min((boundary_distance(x, y) for x in a.edges for y in b.edges), key=lambda row: row[0])
    for shape, other in ((a, b), (b, a)):
        for edge in shape.edges:
            probe = extreme_points(edge)[0]
            if other.contains(probe):
                return 0.0, probe, probe
    return nearest


def board_clearance(document, shape):
    """! @brief 기판 외부에는 음수 여유를 반환하며 전체 원호의 극값을 검사한다."""
    board = document["board"]
    if board is None:
        raise ProjectError("E_CHECK_UNKNOWN", "기판 외곽이 미정입니다.")
    outline = board["outline"]
    points = [point for edge in shape.edges for point in extreme_points(edge)]
    if outline["kind"] == "rectangle":
        width, height = scalar(document, outline["width"]), scalar(document, outline["height"])
        candidates = ((min(x, y, width - x, height - y), [x, y]) for x, y in points)
        return min(candidates, key=lambda row: row[0])
    center = tuple(scalar(document, value) for value in outline["center"])
    radius = scalar(document, outline["radius"])
    points = [point for edge in shape.edges for point in extreme_points(edge, center)]
    farthest = max(points, key=lambda point: norm(sub(point, center)))
    return radius - norm(sub(farthest, center)), list(farthest)
