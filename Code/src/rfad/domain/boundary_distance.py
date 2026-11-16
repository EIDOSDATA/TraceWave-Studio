"""! @brief 선분과 원호 경계의 해석적 최소 거리 및 최근접 위치를 계산한다."""

from dataclasses import dataclass
import math


def add(a, b):
    """! @brief 두 평면 벡터를 더한다."""
    return a[0] + b[0], a[1] + b[1]


def sub(a, b):
    """! @brief 두 평면 벡터의 차이를 구한다."""
    return a[0] - b[0], a[1] - b[1]


def mul(a, scale):
    """! @brief 평면 벡터에 유한 배율을 적용한다."""
    return a[0] * scale, a[1] * scale


def dot(a, b):
    """! @brief 평면 내적을 계산한다."""
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    """! @brief 평면 외적의 부호 있는 스칼라를 계산한다."""
    return a[0] * b[1] - a[1] * b[0]


def norm(a):
    """! @brief overflow를 줄이는 유클리드 길이를 사용한다."""
    return math.hypot(*a)


@dataclass(frozen=True)
class Segment:
    """! @brief 양 끝점을 포함하는 닫힌 선분이다."""
    a: tuple
    b: tuple


@dataclass(frozen=True)
class Arc:
    """! @brief 양의 CCW 전개각 또는 한 바퀴를 가진 원호 경계다."""
    center: tuple
    radius: float
    start: float = 0.0
    sweep: float = math.tau

    def point(self, angle):
        """! @brief 지정한 절대 각도의 점을 계산한다."""
        return add(self.center, (self.radius * math.cos(angle), self.radius * math.sin(angle)))

    def accepts(self, angle):
        """! @brief 전개각 밖의 원 전체를 거리 후보로 사용하지 않는다."""
        return self.sweep >= math.tau or (angle - self.start) % math.tau <= self.sweep


def ends(edge):
    """! @brief 경계의 양 끝점을 반환하며 원도 한 기준점을 제공한다."""
    return (edge.a, edge.b) if isinstance(edge, Segment) else (edge.point(edge.start), edge.point(edge.start + edge.sweep))


def point_distance(point, edge):
    """! @brief 점에서 닫힌 경계까지의 거리와 두 witness를 반환한다."""
    if isinstance(edge, Segment):
        vector = sub(edge.b, edge.a)
        length = dot(vector, vector)
        factor = 0.0 if length == 0 else max(0.0, min(1.0, dot(sub(point, edge.a), vector) / length))
        nearest = add(edge.a, mul(vector, factor))
    else:
        delta = sub(point, edge.center)
        angle = math.atan2(delta[1], delta[0])
        if norm(delta) > 0 and edge.accepts(angle):
            nearest = edge.point(angle)
        else:
            nearest = min(ends(edge), key=lambda candidate: norm(sub(point, candidate)))
    return norm(sub(point, nearest)), point, nearest


def _segments(a, b):
    """! @brief 교차/접촉과 평행 선분을 끝점 거리와 함께 검사한다."""
    u, v, offset = sub(a.b, a.a), sub(b.b, b.a), sub(b.a, a.a)
    denominator = cross(u, v)
    if denominator != 0:
        t, s = cross(offset, v) / denominator, cross(offset, u) / denominator
        if 0 <= t <= 1 and 0 <= s <= 1:
            point = add(a.a, mul(u, t))
            return 0.0, point, point
    candidates = [point_distance(point, b) for point in ends(a)]
    candidates += [(distance, q, p) for distance, p, q in (point_distance(point, a) for point in ends(b))]
    return min(candidates, key=lambda value: value[0])


def _segment_arc(segment, arc):
    """! @brief 원 교점과 접선 법선의 극값 중 실제 원호 범위에 속한 후보만 비교한다."""
    candidates = [point_distance(point, arc) for point in ends(segment)]
    candidates += [(distance, q, p) for distance, p, q in (point_distance(point, segment) for point in ends(arc))]
    vector, delta = sub(segment.b, segment.a), sub(arc.center, segment.a)
    aa = dot(vector, vector)
    if aa > 0:
        middle = dot(delta, vector) / aa
        perpendicular = norm(sub(delta, mul(vector, middle)))
        if perpendicular <= arc.radius:
            half = math.sqrt((arc.radius - perpendicular) * (arc.radius + perpendicular) / aa)
            for t in (middle - half, middle + half):
                if 0 <= t <= 1:
                    point = add(segment.a, mul(vector, t))
                    angle = math.atan2(point[1] - arc.center[1], point[0] - arc.center[0])
                    if arc.accepts(angle):
                        candidates.append((0.0, point, point))
        normal = (-vector[1] / math.sqrt(aa), vector[0] / math.sqrt(aa))
        for sign in (-1, 1):
            radial = mul(normal, sign)
            angle = math.atan2(radial[1], radial[0])
            if arc.accepts(angle):
                point = add(arc.center, mul(radial, arc.radius))
                distance, p, q = point_distance(point, segment)
                candidates.append((distance, q, p))
    return min(candidates, key=lambda value: value[0])


def _arcs(a, b):
    """! @brief 원 교점/공통 법선/동심 원호의 각도 중첩을 해석적으로 검사한다."""
    candidates = [point_distance(point, b) for point in ends(a)]
    candidates += [(distance, q, p) for distance, p, q in (point_distance(point, a) for point in ends(b))]
    delta = sub(b.center, a.center)
    distance = norm(delta)
    if distance == 0:
        for angle in (a.start, a.start + a.sweep, b.start, b.start + b.sweep):
            if a.accepts(angle) and b.accepts(angle):
                candidates.append((abs(a.radius - b.radius), a.point(angle), b.point(angle)))
    else:
        direction = mul(delta, 1 / distance)
        for sign_a in (-1, 1):
            for sign_b in (-1, 1):
                angle_a = math.atan2(direction[1] * sign_a, direction[0] * sign_a)
                angle_b = math.atan2(direction[1] * sign_b, direction[0] * sign_b)
                if a.accepts(angle_a) and b.accepts(angle_b):
                    p, q = a.point(angle_a), b.point(angle_b)
                    candidates.append((norm(sub(p, q)), p, q))
        if abs(a.radius - b.radius) <= distance <= a.radius + b.radius:
            along = (distance ** 2 + (a.radius - b.radius) * (a.radius + b.radius)) / (2 * distance)
            height = math.sqrt(max(0.0, (a.radius - along) * (a.radius + along)))
            midpoint = add(a.center, mul(direction, along))
            for sign in (-1, 1):
                point = add(midpoint, (-direction[1] * height * sign, direction[0] * height * sign))
                angles = [math.atan2(point[1] - edge.center[1], point[0] - edge.center[0]) for edge in (a, b)]
                if a.accepts(angles[0]) and b.accepts(angles[1]):
                    candidates.append((0.0, point, point))
    return min(candidates, key=lambda value: value[0])


def boundary_distance(a, b):
    """! @brief 형식 조합에 맞는 계산을 선택하고 원본 방향의 witness 순서를 보존한다."""
    if isinstance(a, Segment) and isinstance(b, Segment):
        return _segments(a, b)
    if isinstance(a, Arc) and isinstance(b, Arc):
        return _arcs(a, b)
    if isinstance(a, Segment):
        return _segment_arc(a, b)
    distance, p, q = _segment_arc(b, a)
    return distance, q, p


def extreme_points(edge, center=None):
    """! @brief AABB 또는 기준 중심의 최대 반경을 결정하는 유한 후보를 반환한다."""
    points = list(ends(edge))
    if isinstance(edge, Arc):
        angles = [0, math.pi / 2, math.pi, 3 * math.pi / 2]
        if center is not None:
            angles.append(math.atan2(edge.center[1] - center[1], edge.center[0] - center[0]))
        points.extend(edge.point(angle) for angle in angles if edge.accepts(angle))
    return points
