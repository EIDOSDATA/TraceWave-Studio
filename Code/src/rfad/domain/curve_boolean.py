"""! @brief 닫힌 선/원호 경계의 차집합을 해석형 조각으로 계산한다.

@details 원호를 polygon으로 근사하지 않는다. 겹치는 동일 경계와 접점 분기 등
수치적으로 유일하게 연결할 수 없는 경우에는 조용한 치유 대신 명시 차단한다.
"""

from copy import deepcopy
import math

from rfad.domain.errors import ProjectError

TOLERANCE_MM = 1e-8
MAX_PAIRS = 1000000
MAX_EDGES = 4096


def _fail(message, code="E_GEOMETRY"):
    """! @brief 불확실한 Boolean 결과를 출력 성공으로 넘기지 않는다."""
    raise ProjectError(code, message, details={"field_path": "drawing.mechanical_boolean"})


def _point(edge, parameter):
    """! @brief 원래 유한 선/원호의 매개 좌표를 계산한다."""
    if edge["kind"] == "line":
        return [a + parameter * (b - a) for a, b in zip(edge["start"], edge["end"])]
    angle = math.radians(math.remainder(edge["start_deg"], 360.0) + parameter * edge["sweep_deg"])
    return [edge["center"][0] + edge["radius"] * math.cos(angle),
            edge["center"][1] + edge["radius"] * math.sin(angle)]


def _parameter(edge, point):
    """! @brief 무한 직선/원 교점을 원래 유한 경계에 한정한다."""
    if edge["kind"] == "line":
        a, b = edge["start"], edge["end"]
        delta = [b[i] - a[i] for i in range(2)]
        length2 = sum(value * value for value in delta)
        if length2 <= TOLERANCE_MM ** 2:
            _fail("길이가 없는 도면 경계는 절삭할 수 없습니다.")
        value = sum((point[i] - a[i]) * delta[i] for i in range(2)) / length2
        span = math.sqrt(length2)
    else:
        angle = math.degrees(math.atan2(point[1] - edge["center"][1], point[0] - edge["center"][0]))
        sign = 1 if edge["sweep_deg"] > 0 else -1
        delta = ((angle - math.remainder(edge["start_deg"], 360.0)) * sign) % 360
        if 360 - delta <= math.degrees(TOLERANCE_MM / edge["radius"]):
            delta = 0
        value = delta / abs(edge["sweep_deg"])
        span = edge["radius"] * math.radians(abs(edge["sweep_deg"]))
    epsilon = TOLERANCE_MM / span
    if -epsilon <= value <= 1 + epsilon:
        return min(1.0, max(0.0, value))
    return None


def _cross(a, b):
    """! @brief 평면 외적의 부호를 원래 좌표에서 계산한다."""
    return a[0] * b[1] - a[1] * b[0]


def _intersections(first, second):
    """! @brief 직선/원 및 원/원의 교점을 구하고 유한 경계에서만 반환한다."""
    if first["kind"] == second["kind"] == "line":
        a, b, c, d = first["start"], first["end"], second["start"], second["end"]
        u, v, w = ([b[i] - a[i] for i in range(2)], [d[i] - c[i] for i in range(2)], [c[i] - a[i] for i in range(2)])
        determinant = _cross(u, v)
        epsilon = 32 * math.ulp(max(abs(u[0] * v[1]), abs(u[1] * v[0]), 1.0))
        if abs(determinant) <= epsilon:
            if abs(_cross(w, u)) <= TOLERANCE_MM * math.hypot(*u):
                candidates = [_parameter(first, p) for p in (c, d)] + [_parameter(second, p) for p in (a, b)]
                if any(value is not None for value in candidates):
                    _fail("동일 직선에 겹치거나 접한 절삭 경계는 현재 도면 profile 밖입니다.", "E_UNSUPPORTED")
            return []
        parameter = _cross(w, v) / determinant
        points = [[a[i] + parameter * u[i] for i in range(2)]]
    elif first["kind"] == "line" or second["kind"] == "line":
        straight, circle = (first, second) if first["kind"] == "line" else (second, first)
        a, b, c = straight["start"], straight["end"], circle["center"]
        u, v = [b[i] - a[i] for i in range(2)], [a[i] - c[i] for i in range(2)]
        qa = sum(value * value for value in u)
        if qa <= TOLERANCE_MM ** 2:
            _fail("길이가 없는 절삭 경계입니다.")
        closest = -sum(u[i] * v[i] for i in range(2)) / qa
        distance2 = sum((v[i] + closest * u[i]) ** 2 for i in range(2))
        height2 = circle["radius"] ** 2 - distance2
        epsilon = 64 * math.ulp(max(circle["radius"] ** 2, distance2))
        if height2 < -epsilon:
            return []
        root = math.sqrt(max(0.0, height2) / qa)
        points = [[a[i] + t * u[i] for i in range(2)] for t in (closest - root, closest + root)]
    else:
        a, b, r, s = first["center"], second["center"], first["radius"], second["radius"]
        distance = math.dist(a, b)
        if distance <= TOLERANCE_MM:
            if abs(r - s) <= TOLERANCE_MM:
                _fail("일치하는 원호 절삭 경계는 현재 도면 profile 밖입니다.", "E_UNSUPPORTED")
            return []
        if distance > r + s + TOLERANCE_MM or distance < abs(r - s) - TOLERANCE_MM:
            return []
        along = ((r - s) * (r + s) + distance * distance) / (2 * distance)
        height2 = r * r - along * along
        epsilon = 64 * math.ulp(max(r * r, along * along, 1.0))
        if height2 < -epsilon:
            return []
        height = math.sqrt(max(0.0, height2))
        u = [(b[i] - a[i]) / distance for i in range(2)]
        points = [[a[0] + along * u[0] - sign * height * u[1], a[1] + along * u[1] + sign * height * u[0]] for sign in (-1, 1)]
    result = []
    for point in points:
        a, b = _parameter(first, point), _parameter(second, point)
        if a is not None and b is not None:
            result.append((a, b))
    if len(result) == 2 and math.dist(_point(first, result[0][0]), _point(first, result[1][0])) <= TOLERANCE_MM:
        _fail("접하는 선/원호 절삭은 유일한 재료 경계를 만들지 않습니다.", "E_UNSUPPORTED")
    return result


def _piece(edge, start, end, reverse=False):
    """! @brief 원래 원의 중심과 반지름을 유지하며 경계 일부만 자른다."""
    if reverse:
        start, end = end, start
    if edge["kind"] == "line":
        return {"kind": "line", "start": _point(edge, start), "end": _point(edge, end)}
    return {"kind": "arc", "center": list(edge["center"]), "radius": edge["radius"],
            "start_deg": math.remainder(edge["start_deg"], 360.0) + start * edge["sweep_deg"], "sweep_deg": (end - start) * edge["sweep_deg"]}


def difference(subject, cutter, inside):
    """! @brief even-odd 내부 판정과 교점 분할로 원본 minus 절삭의 닫힌 경계를 반환한다."""
    if not cutter:
        return deepcopy(subject)
    first, second = [edge for loop in subject for edge in loop], [edge for loop in cutter for edge in loop]
    if not first or not second:
        return deepcopy(subject)
    if len(first) * len(second) > MAX_PAIRS or len(first) + len(second) > MAX_EDGES:
        _fail("해석형 도면 절삭의 교점 계산 상한을 초과했습니다.", "E_RESOURCE")
    edges = first + second
    splits = [[0.0, 1.0] for _ in edges]
    for i, a in enumerate(first):
        for j, b in enumerate(second):
            for aa, bb in _intersections(a, b):
                splits[i].append(aa)
                splits[len(first) + j].append(bb)
    boundaries = []
    for edge, values in zip(edges, splits):
        span = (math.dist(edge["start"], edge["end"]) if edge["kind"] == "line"
                else edge["radius"] * math.radians(abs(edge["sweep_deg"])))
        values = sorted(values)
        unique = [values[0]]
        for value in values[1:]:
            if (value - unique[-1]) * span > TOLERANCE_MM:
                unique.append(value)
        for start, end in zip(unique, unique[1:]):
            middle = (start + end) / 2
            point = _point(edge, middle)
            if edge["kind"] == "line":
                tangent = [edge["end"][i] - edge["start"][i] for i in range(2)]
            else:
                sign = 1 if edge["sweep_deg"] > 0 else -1
                tangent = [-(point[1] - edge["center"][1]) * sign, (point[0] - edge["center"][0]) * sign]
            length = math.hypot(*tangent)
            if length <= TOLERANCE_MM:
                _fail("퇴화한 도면 경계를 치유하지 않습니다.")
            delta = max(2e-7, 64 * max(math.ulp(value) for value in point))
            normal = [-tangent[1] / length * delta, tangent[0] / length * delta]
            left, right = ([point[i] + normal[i] for i in range(2)], [point[i] - normal[i] for i in range(2)])
            left_inside = inside(left, subject) and not inside(left, cutter)
            right_inside = inside(right, subject) and not inside(right, cutter)
            if left_inside != right_inside:
                boundaries.append(_piece(edge, start, end, reverse=not left_inside))
    if len(boundaries) > MAX_EDGES:
        _fail("절삭 후 도면 경계 수 상한을 초과했습니다.", "E_RESOURCE")
    starts = {}
    for index, edge in enumerate(boundaries):
        key = tuple(math.floor(value / TOLERANCE_MM) for value in _point(edge, 0))
        starts.setdefault(key, []).append(index)
    follows, incoming = {}, [0] * len(boundaries)
    for index, edge in enumerate(boundaries):
        end = _point(edge, 1)
        x, y = [math.floor(value / TOLERANCE_MM) for value in end]
        candidates = [candidate for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                      for candidate in starts.get((x + dx, y + dy), [])
                      if math.dist(_point(boundaries[candidate], 0), end) <= TOLERANCE_MM]
        if len(candidates) != 1:
            _fail("절삭 경계의 연결이 유일하지 않습니다. 접촉/퇴화 형상을 명시적으로 수정하십시오.", "E_UNSUPPORTED")
        follows[index] = candidates[0]
        incoming[candidates[0]] += 1
    if any(count != 1 for count in incoming):
        _fail("절삭 경계에 분기 또는 끊김이 있습니다.", "E_UNSUPPORTED")
    loops = []
    remaining = set(range(len(boundaries)))
    while remaining:
        current = origin = min(remaining)
        remaining.remove(current)
        loop = [boundaries[current]]
        while follows[current] != origin:
            current = follows[current]
            if current not in remaining:
                _fail("절삭 경계가 이전 연결 성분으로 되돌아갑니다.")
            remaining.remove(current)
            loop.append(boundaries[current])
        loops.append(loop)
    return loops
