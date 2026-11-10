"""! @brief 단위에 독립적인 단순 다각형과 구멍의 검증 및 면적 보존 분할을 제공한다."""

import math

from rfad.domain.errors import ProjectError


MAX_REGION_POINTS = 64
MAX_REGION_HOLES = 8


def _fail(message, field):
    """! @brief 원본 다각형의 위치와 함께 기하 오류를 반환한다."""
    raise ProjectError("E_GEOMETRY", message, details={"field_path": field})


def _tolerance(points):
    """! @brief 절대 단위를 고정하지 않고 크기와 좌표의 표현 정밀도로 공차를 정한다."""
    span = max(max(p[i] for p in points) - min(p[i] for p in points) for i in (0, 1))
    return max(span * 1e-12, max(math.ulp(v) for p in points for v in p) * 8), span


def signed_area(loop):
    """! @brief 첫 점을 원점으로 옮긴 외적으로 큰 좌표의 면적 상쇄를 줄인다."""
    x, y = loop[0]
    return math.fsum((a[0] - x) * (b[1] - y) - (a[1] - y) * (b[0] - x)
                     for a, b in zip(loop, loop[1:] + loop[:1])) / 2


def _cross(a, b, c):
    """! @brief 두 방향의 부호 있는 외적을 구한다."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(p, a, b, tolerance):
    """! @brief 선분 경계의 수치 공차 안에 점이 있는지 검사한다."""
    length = math.dist(a, b)
    return (abs(_cross(a, b, p)) <= tolerance * length
            and all(min(a[i], b[i]) - tolerance <= p[i] <= max(a[i], b[i]) + tolerance for i in (0, 1)))


def _intersect(a, b, c, d, tolerance):
    """! @brief 끝점 접촉과 겹친 선분을 포함하는 경계 교차를 검사한다."""
    if any(max(a[i], b[i]) + tolerance < min(c[i], d[i]) or max(c[i], d[i]) + tolerance < min(a[i], b[i]) for i in (0, 1)):
        return False
    values = (_cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b))
    if ((values[0] < 0 < values[1] or values[1] < 0 < values[0])
            and (values[2] < 0 < values[3] or values[3] < 0 < values[2])):
        return True
    return any(_on_segment(p, start, stop, tolerance) for p, start, stop in ((a, c, d), (b, c, d), (c, a, b), (d, a, b)))


def point_in_loop(point, loop, *, include_boundary=True):
    """! @brief 유효한 단순 loop의 내부를 홀수 교차 규칙으로 검사한다."""
    tolerance, _ = _tolerance(loop)
    if any(_on_segment(point, a, b, tolerance) for a, b in zip(loop, loop[1:] + loop[:1])):
        return include_boundary
    inside = False
    for a, b in zip(loop, loop[1:] + loop[:1]):
        if (a[1] > point[1]) != (b[1] > point[1]):
            if point[0] < a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                inside = not inside
    return inside


def validate_region(outer, holes, field="geometry"):
    """! @brief 반복 닫힘점 없는 outer/holes를 검증하며 입력 winding과 좌표는 보존한다.

    @param outer 유한 숫자 2개로 구성된 점의 목록. SI/mm 등 동일 단위만 사용한다.
    @param holes outer와 엄격히 분리된 내부 loop 목록.
    @return 정상 입력에서는 None이며 오류 시 ProjectError를 발생시킨다.
    """
    if type(outer) is not list or type(holes) is not list or len(holes) > MAX_REGION_HOLES:
        _fail("다각형 외곽과 최대 8개의 구멍 목록이 필요합니다.", field)
    loops = [outer, *holes]
    if any(type(loop) is not list or len(loop) < 3 for loop in loops) or sum(map(len, loops)) > MAX_REGION_POINTS:
        _fail("각 loop는 3점 이상이고 외곽과 구멍의 합계는 최대 64점입니다.", field)
    points = [point for loop in loops for point in loop]
    if any(type(point) is not list or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in point) for point in points):
        _fail("다각형 좌표는 유한 숫자 2개여야 합니다.", field)
    tolerance, span = _tolerance(points)
    if span <= tolerance:
        _fail("다각형의 크기를 표현할 수 없습니다.", field)
    edges = []
    for index, loop in enumerate(loops):
        loop_field = field + (".outer" if index == 0 else f".holes[{index - 1}]")
        boundary = list(zip(loop, loop[1:] + loop[:1]))
        if any(math.dist(a, b) <= tolerance for a, b in boundary) or abs(signed_area(loop)) <= tolerance * span:
            _fail("다각형의 반복점, 0 길이 변 또는 퇴화 면적은 허용하지 않습니다.", loop_field)
        for i, (a, b) in enumerate(boundary):
            c = loop[(i + 2) % len(loop)]
            if abs(_cross(a, b, c)) <= tolerance * max(math.dist(a, b), math.dist(b, c)):
                if (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) <= 0:
                    _fail("인접한 다각형 변이 되돌아가 겹칩니다.", loop_field)
            for j in range(i + 1, len(boundary)):
                if j == i + 1 or (i == 0 and j == len(boundary) - 1):
                    continue
                if _intersect(a, b, *boundary[j], tolerance):
                    _fail("다각형 경계가 자기 교차하거나 접합니다.", loop_field)
        edges.append(boundary)
    for index, hole in enumerate(holes, start=1):
        if not point_in_loop(hole[0], outer, include_boundary=False):
            _fail("구멍은 외곽의 엄격한 내부에 있어야 합니다.", field + f".holes[{index - 1}]")
        for other in range(index):
            if any(_intersect(a, b, c, d, tolerance) for a, b in edges[index] for c, d in edges[other]):
                _fail("구멍 경계가 외곽 또는 다른 구멍과 접하거나 교차합니다.", field)
            if other and (point_in_loop(hole[0], loops[other]) or point_in_loop(loops[other][0], hole)):
                _fail("구멍의 중첩이나 내부 중첩 구멍은 허용하지 않습니다.", field)


def decompose_region(outer, holes):
    """! @brief 모든 꼭짓점 높이에서 면을 분할해 구멍 없는 볼록 삼각형/사각형으로 반환한다.

    @details 경계의 모든 교차를 사용하므로 일정 간격 표본화가 아니다. 원본 winding을
    변경하지 않으며 반환한 조각은 반시계 방향이다. 합계 면적도 다시 검사한다.
    """
    validate_region(outer, holes)
    loops = [outer, *holes]
    points = [p for loop in loops for p in loop]
    tolerance, span = _tolerance(points)
    levels = sorted({p[1] for p in points})
    edges = [(a, b) for loop in loops for a, b in zip(loop, loop[1:] + loop[:1]) if a[1] != b[1]]
    polygons = []
    def x_at(edge, y):
        """! @brief 해당 높이에서 한 경계 선분의 x 좌표를 계산한다."""
        a, b = edge
        return a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
    for low, high in zip(levels, levels[1:]):
        middle = low + (high - low) / 2
        active = [edge for edge in edges if min(edge[0][1], edge[1][1]) < middle < max(edge[0][1], edge[1][1])]
        active.sort(key=lambda edge: x_at(edge, middle))
        if len(active) % 2:
            _fail("다각형 면 분할의 경계 교차 수가 홀수입니다.", "geometry")
        for left, right in zip(active[::2], active[1::2]):
            raw = [[x_at(left, low), low], [x_at(right, low), low], [x_at(right, high), high], [x_at(left, high), high]]
            polygon = []
            for point in raw:
                if not polygon or math.dist(point, polygon[-1]) > tolerance:
                    polygon.append(point)
            if len(polygon) > 1 and math.dist(polygon[0], polygon[-1]) <= tolerance:
                polygon.pop()
            if len(polygon) >= 3 and signed_area(polygon) > 0:
                polygons.append(polygon)
    expected = abs(signed_area(outer)) - math.fsum(abs(signed_area(hole)) for hole in holes)
    observed = math.fsum(signed_area(polygon) for polygon in polygons)
    if not polygons or abs(expected - observed) > max(tolerance * span * 8, expected * 1e-10):
        _fail("구멍을 포함한 다각형 분할의 면적이 원본과 다릅니다.", "geometry")
    return polygons
