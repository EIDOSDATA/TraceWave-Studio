"""! @brief 열린 선·원호의 접선 필렛을 해석형 교점으로 구한다."""

from itertools import product
import math

from rfad.domain.curve_boolean import TOLERANCE_MM, _cross, _intersections, _point
from rfad.domain.errors import ProjectError
from rfad.domain.precision_transform import fail


def _span(edge):
    """! @brief 선 또는 전개한 호의 길이를 mm로 구한다."""
    if edge["kind"] == "line":
        return math.dist(edge["start"], edge["end"])
    return edge["radius"] * abs(math.radians(edge["sweep_deg"]))


def _tangent(edge, t, span):
    """! @brief 매개변수가 증가하는 방향의 단위 접선을 반환한다."""
    if edge["kind"] == "line":
        return tuple((b - a) / span for a, b in zip(edge["start"], edge["end"]))
    radial = tuple(value - center for value, center in zip(_point(edge, t), edge["center"]))
    sign = 1 if edge["sweep_deg"] > 0 else -1
    return (-sign * radial[1] / edge["radius"], sign * radial[0] / edge["radius"])


def _offsets(edge, radius, span):
    """! @brief 원래의 매개 구간을 유지한 양쪽 중심 후보 궤적을 구성한다."""
    if edge["kind"] == "arc":
        return [{**edge, "radius": edge["radius"] + direction * radius} for direction in (-1, 1)]
    tx, ty = _tangent(edge, 0, span)
    return [{"kind": "line",
             **{key: [edge[key][0] - direction * radius * ty, edge[key][1] + direction * radius * tx]
                for key in ("start", "end")}}
            for direction in (-1, 1)]


def _candidate(edges, starts, spans, offsets, parameters, radius):
    """! @brief 양 접점의 진행 방향과 맞는 단일 원호만 선택한다."""
    lengths = [abs(parameter - endpoint) * span for parameter, endpoint, span in zip(parameters, starts, spans)]
    if any(not TOLERANCE_MM < length < span - TOLERANCE_MM for length, span in zip(lengths, spans)):
        return None
    a, b = (_point(edge, parameter) for edge, parameter in zip(offsets, parameters))
    center = [(x + y) / 2 for x, y in zip(a, b)]
    if max(map(abs, center)) > 1e6:
        return None
    points = [_point(edge, parameter) for edge, parameter in zip(edges, parameters)]
    radial = [[value - origin for value, origin in zip(point, center)] for point in points]
    if any(abs(math.hypot(*vector) - radius) > max(TOLERANCE_MM, radius * 1e-10) for vector in radial):
        return None
    first, second = (_tangent(edge, parameter, span) for edge, parameter, span in zip(edges, parameters, spans))
    arrival = [component * (1 if starts[0] else -1) for component in first]
    departure = [component * (-1 if starts[1] else 1) for component in second]
    sign = 1 if _cross(radial[0], arrival) > 0 else -1
    if (_cross(radial[0], arrival) * sign < radius * (1 - 1e-9)
            or _cross(radial[1], departure) * sign < radius * (1 - 1e-9)):
        return None
    start, stop = [math.degrees(math.atan2(vector[1], vector[0])) for vector in radial]
    sweep = ((stop - start) * sign) % 360
    if not 1e-8 < sweep < 180:
        return None
    return (sum(lengths), center, start, sign * sweep, parameters)


def curved_fillet(edges, radius):
    """! @brief 열린 두 중심선의 공통 끝점에서 유일한 최소 절삭 필렛을 찾는다."""
    spans = [_span(edge) for edge in edges]
    if any(span <= TOLERANCE_MM for span in spans):
        fail("길이가 있는 도체 두 개가 필요합니다.", "selection_ids")
    if any(edge["kind"] == "arc" and (abs(edge["sweep_deg"]) >= 360 - 1e-9
                                         or edge["radius"] - radius <= TOLERANCE_MM) for edge in edges):
        fail("원래 원호보다 작은 필렛 반경과 열린 원호를 지정하십시오.", "radius_mm")
    matches = [(a, b) for a, b in product((0, 1), repeat=2)
               if math.dist(_point(edges[0], a), _point(edges[1], b)) <= TOLERANCE_MM]
    if len(matches) != 1:
        fail("두 도체가 만나는 공통 끝점 한 개가 필요합니다.", "selection_ids")
    ends = matches[0]
    candidates = []
    for offsets in product(*(_offsets(edge, radius, span) for edge, span in zip(edges, spans))):
        try:
            intersections = _intersections(*offsets)
        except ProjectError as error:
            if error.code != "E_UNSUPPORTED":
                raise
            # @brief 일치하거나 접한 중심 궤적은 독립된 중심을 확정할 수 없다.
            continue
        for parameters in intersections:
            candidate = _candidate(edges, ends, spans, offsets, parameters, radius)
            if candidate is not None and all(math.dist(candidate[1], other[1]) > TOLERANCE_MM for other in candidates):
                candidates.append(candidate)
    candidates.sort(key=lambda item: item[0])
    if not candidates or (len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) <= TOLERANCE_MM):
        fail("이 반경으로 유일한 접선 필렛을 찾을 수 없습니다.", "radius_mm")
    _, center, start, sweep, parameters = candidates[0]
    return ends, parameters, center, start, sweep
