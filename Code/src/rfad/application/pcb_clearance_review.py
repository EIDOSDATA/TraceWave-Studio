"""! @brief 실제 해석 형상 사이의 간극과 통과 격자 셀을 찾는다."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from itertools import combinations
import math

from rfad.domain.boundary_distance import Arc, Segment, boundary_distance, point_distance
from rfad.domain.planar import point_in_loop


EDGE_PAIR_LIMIT = 300_000
DISPLAY_LIMIT = 40


def _bounds(points):
    """! @brief 투영 점의 축별 닫힌 경계를 구한다."""
    return tuple((min(axis), max(axis)) for axis in zip(*points))


def _box_gap(a, b):
    """! @brief 두 경계 상자의 간극은 실제 형상 간극의 하한이다."""
    return math.hypot(*(max(lo_a - hi_b, lo_b - hi_a, 0.0)
                        for (lo_a, hi_a), (lo_b, hi_b) in zip(a, b)))


@dataclass(frozen=True)
class _Piece:
    """! @brief 평면 경계와 Z 범위의 곱으로 실제 해석 프리미티브를 표현한다."""
    bounds: tuple
    edges: tuple
    witnesses: tuple
    loop: tuple = ()
    rings: tuple = ()
    capsule: tuple = ()
    openings: tuple = ()

    def contains(self, point, *, include_boundary=True):
        """! @brief 절삭의 내부를 뺀 실제 닫힌 평면 단면에서 포함 여부를 구한다."""
        if self.rings:
            center, inner, outer = self.rings
            distance = math.dist(point, center)
            inside = inner <= distance <= outer if include_boundary else distance < outer and (not inner or distance > inner)
        elif self.capsule:
            centerline, radius = self.capsule
            distance = point_distance(point, centerline)[0]
            inside = distance <= radius if include_boundary else distance < radius
        else:
            inside = point_in_loop(point, self.loop, include_boundary=include_boundary)
        return inside and not any(opening.contains(point, include_boundary=False) for opening in self.openings)


def _polygon(points, z_range):
    """! @brief 실제 해석 다각형의 경계 선분과 닫힌 Z 범위를 캐시한다."""
    points = tuple(map(tuple, points))
    edges = tuple((Segment(a, b), _bounds((a, b))) for a, b in zip(points, points[1:] + points[:1]) if a != b)
    return _Piece((*_bounds(points), tuple(z_range)), edges, points[:1], loop=points)


def _round_piece(outer, inner=0):
    """! @brief 실제 원통 또는 배럴의 닫힌 투영과 Z 경계를 만든다."""
    center = tuple(outer["center_mm"])
    outer_radius = outer["radius_mm"]
    arcs = [Arc(center, outer_radius)]
    if inner:
        arcs.append(Arc(center, inner))
    edges = tuple((arc, tuple((axis - arc.radius, axis + arc.radius) for axis in center)) for arc in arcs)
    return _Piece((*edges[0][1], tuple(outer["z_mm"])), edges,
                  tuple(arc.point(0) for arc in arcs), rings=(center, inner, outer_radius))


def _height(primitive):
    """! @brief 투영 primitive들의 저장 형식에서 공통 Z 범위를 읽는다."""
    return primitive["bounds_mm"][2] if primitive["kind"] == "box" else primitive["z_mm"]


def _solid_piece(primitive):
    """! @brief 선형 다각형, 사각 타일 또는 원통을 실제 소비 경계로 바꾼다."""
    if primitive["kind"] == "box":
        (x0, x1), (y0, y1), z_range = primitive["bounds_mm"]
        return _polygon(((x0, y0), (x1, y0), (x1, y1), (x0, y1)), z_range)
    if primitive["kind"] == "circle":
        return _round_piece(primitive)
    return _polygon(primitive["points_mm"], primitive["z_mm"])


def _mechanical_opening(primitives):
    """! @brief 검증한 관통 절삭의 원형, 다각형 또는 슬롯의 바깥 경계만 구성한다."""
    if len(primitives) == 1:
        return _solid_piece(primitives[0])
    # @brief 모델 검토의 슬롯은 직사각형 가운데와 동일 반경의 두 끝 원통이다.
    middle, first, last = primitives
    a, b = tuple(first["center_mm"]), tuple(last["center_mm"])
    radius, height = first["radius_mm"], first["z_mm"]
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    start = Arc(a, radius, angle + math.pi / 2, math.pi)
    stop = Arc(b, radius, angle - math.pi / 2, math.pi)
    one, two, three, four = map(tuple, middle["points_mm"])
    arcs = [(edge, tuple((v - radius, v + radius) for v in edge.center)) for edge in (start, stop)]
    sides = [(Segment(s, e), _bounds((s, e))) for s, e in ((one, four), (two, three))]
    bounds = tuple((min(x, y) - radius, max(x, y) + radius) for x, y in zip(a, b))
    return _Piece((*bounds, tuple(height)), (*arcs, *sides), (one, two, three, four),
                  capsule=(Segment(a, b), radius))


def _pieces(row, mechanical, bore_heights):
    """! @brief 닫힌 관통 절삭은 체적 경계에 포함하고 부분 절삭 및 겹친 보어는 제외한다."""
    primitives = row["primitives"]
    role = row["role"]
    if role == "via" and primitives:
        outer, bore = primitives
        return [_round_piece(outer, bore["radius_mm"])]
    if role in {"surface", "dielectric"}:
        if any(primitive.get("opening") for primitive in primitives):
            return []
        pieces = [_solid_piece(primitive) for primitive in primitives]
        actual = []
        for piece in pieces:
            low, high = piece.bounds[2]
            if any(max(low, a) < min(high, b) for a, b in bore_heights):
                return []
            openings = [cut for cut in mechanical
                        if max(low, cut.bounds[2][0]) < min(high, cut.bounds[2][1])
                        and _box_gap(piece.bounds[:2], cut.bounds[:2]) == 0]
            if openings:
                # @brief 이 절삭은 계획의 기판 유전체를 관통하며, 부분 높이나 다른 재료를 재구성하지 않는다.
                if role != "dielectric" or any(cut.bounds[2][0] > low or cut.bounds[2][1] < high for cut in openings):
                    return []
                piece = replace(piece, openings=tuple(openings),
                                edges=piece.edges + tuple(edge for cut in openings for edge in cut.edges),
                                witnesses=piece.witnesses + tuple(point for cut in openings for point in cut.witnesses))
            actual.append(piece)
        return actual
    if role in {"conductor", "environment"}:
        return [_solid_piece(primitive) for primitive in primitives]
    return []


def _closest_heights(a, b):
    """! @brief 공통 높이 또는 서로 마주 보는 두 Z 끝을 선택한다."""
    if a[1] < b[0]:
        return a[1], b[0]
    if b[1] < a[0]:
        return a[0], b[1]
    return (max(a[0], b[0]),) * 2


def _projected_gap(a, b, radius, budget):
    """! @brief 다각형 및 원의 각 경계 교차, 포함 또는 최근접점으로 투영 간극을 구한다."""
    if _box_gap(a.bounds[:2], b.bounds[:2]) == 0:
        for piece, other in ((a, b), (b, a)):
            for point in piece.witnesses:
                if other.contains(point):
                    return (0.0, point, point), budget
    best = None
    for edge_a, box_a in a.edges:
        if _box_gap(box_a, b.bounds[:2]) > radius:
            continue
        for edge_b, box_b in b.edges:
            if budget == 0:
                return None, -1
            budget -= 1
            if _box_gap(box_a, box_b) > radius:
                continue
            distance, start, stop = boundary_distance(edge_a, edge_b)
            if distance <= 1e-12:
                return (0.0, start, start), budget
            if distance <= radius and (best is None or distance < best[0]):
                best = distance, start, stop
                radius = distance
    return best, budget


def _nearest(pieces_a, pieces_b, radius, budget):
    """! @brief 프리미티브별 정확한 3D 간극의 최솟값과 양 끝점을 결정한다."""
    best = None
    for a in pieces_a:
        for b in pieces_b:
            if _box_gap(a.bounds, b.bounds) > radius:
                continue
            za, zb = _closest_heights(a.bounds[2], b.bounds[2])
            dz = abs(za - zb)
            limit = math.sqrt(max(0, (radius - dz) * (radius + dz)))
            projected, budget = _projected_gap(a, b, limit, budget)
            if budget < 0:
                return None, budget
            if projected is None:
                continue
            horizontal, start, stop = projected
            distance = math.hypot(horizontal, dz)
            if best is None or distance < best[0]:
                best = distance, (*start, za), (*stop, zb)
                radius = distance
            if distance <= 1e-12:
                return best, budget
    return best, budget


def _crossed_cells(a, b, lines):
    """! @brief 간극 선분과 길이가 겹치는 셀 인덱스를 축과 진행 순서대로 반환한다."""
    axes = [lines[axis] for axis in "xyz"[:len(a)]]
    events = [0.0, 1.0]
    for start, stop, axis in zip(a, b, axes):
        if start != stop:
            low, high = sorted((start, stop))
            events.extend((value - start) / (stop - start)
                          for value in axis[bisect_right(axis, low):bisect_left(axis, high)])
    events.sort()
    cells = []
    for left, right in zip(events, events[1:]):
        if right - left <= 1e-12:
            continue
        mid = (left + right) / 2
        indices = [min(len(axis) - 2, bisect_right(axis, start + (stop - start) * mid) - 1)
                   for start, stop, axis in zip(a, b, axes)]
        if not cells or cells[-1] != indices:
            cells.append(indices)
    return cells


def planar_clearances(included, lines, grid_mm):
    """! @brief 실제 해석 형상의 기본 셀 폭 2배 이내의 간극을 표시한다."""
    radius = 2 * grid_mm
    objects = []
    omitted = 0
    mechanical = [_mechanical_opening(row["primitives"]) for row in included if row["role"] == "void"]
    bore_heights = [_height(primitive) for row in included if row["role"] == "via"
                    for primitive in row["primitives"] if primitive.get("opening")]
    for row in included:
        pieces = _pieces(row, mechanical, bore_heights)
        if pieces:
            box = tuple((min(axis[0] for axis in bounds), max(axis[1] for axis in bounds))
                        for bounds in zip(*(piece.bounds for piece in pieces)))
            objects.append((row, pieces, box))
        elif row["role"] in {"surface", "dielectric"}:
            omitted += 1

    candidates = []
    for left, right in combinations(objects, 2):
        lower = _box_gap(left[2], right[2])
        if lower <= radius:
            candidates.append((lower, left, right))
    candidates.sort(key=lambda row: (row[0], row[1][2][2][0], row[1][0]["id"], row[2][0]["id"]))
    budget = EDGE_PAIR_LIMIT
    rows = []
    evaluated = 0
    for _, (a, pieces_a, _), (b, pieces_b, _) in candidates:
        nearest, budget = _nearest(pieces_a, pieces_b, radius, budget)
        if budget < 0:
            break
        evaluated += 1
        if nearest is not None:
            distance, start, stop = nearest
            if distance <= 1e-12 or distance > radius:
                continue
            row = {"object_ids": [a["id"], b["id"]], "object_names": [a["name"], b["name"]],
                   "object_roles": [a["role"], b["role"]], "distance_mm": distance,
                   "z_mm": start[2], "points_mm": [start[:2], stop[:2]]}
            if start[2] != stop[2]:
                row["other_z_mm"] = stop[2]
            rows.append(row)
    rows.sort(key=lambda row: (row["distance_mm"], row["z_mm"], row["object_ids"]))
    visible = rows[:DISPLAY_LIMIT]
    for row in visible:
        a, b = row["points_mm"]
        if "other_z_mm" in row:
            row["cells_xyz"] = _crossed_cells((*a, row["z_mm"]), (*b, row["other_z_mm"]), lines)
        else:
            row["cells_xy"] = _crossed_cells(a, b, lines)
    return {"search_radius_mm": radius, "pair_total": len(candidates), "pair_evaluated": evaluated,
            "clearance_total": len(rows), "clearances": visible, "volume_omitted_count": omitted}
