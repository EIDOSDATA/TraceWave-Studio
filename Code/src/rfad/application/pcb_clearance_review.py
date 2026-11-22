"""! @brief 실제 해석 형상 사이의 간극과 통과 격자 셀을 찾는다."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import combinations
import math

from rfad.domain.boundary_distance import Arc, Segment, boundary_distance
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

    def contains(self, point):
        """! @brief 배럴의 보어를 제외하고 평면 투영이 점을 포함하는지 확인한다."""
        if self.rings:
            center, inner, outer = self.rings
            return inner <= math.dist(point, center) <= outer
        return point_in_loop(point, self.loop)


def _polygon(points, z_range):
    """! @brief 실제 해석 다각형의 경계 선분과 닫힌 Z 범위를 캐시한다."""
    points = tuple(map(tuple, points))
    edges = tuple((Segment(a, b), _bounds((a, b))) for a, b in zip(points, points[1:] + points[:1]) if a != b)
    return _Piece((*_bounds(points), tuple(z_range)), edges, points[:1], loop=points)


def _barrel(primitives):
    """! @brief 실제 모델과 같은 동심 내경 및 외경을 대상으로 간극을 계산한다."""
    outer, bore = primitives
    center = tuple(outer["center_mm"])
    inner, outer_radius = bore["radius_mm"], outer["radius_mm"]
    arcs = tuple(Arc(center, radius) for radius in (outer_radius, inner))
    edges = tuple((arc, tuple((axis - arc.radius, axis + arc.radius) for axis in center)) for arc in arcs)
    return _Piece((*edges[0][1], tuple(outer["z_mm"])), edges,
                  tuple(arc.point(0) for arc in arcs), rings=(center, inner, outer_radius))


def _pieces(row):
    """! @brief 도체 시트, PTH 배럴과 해석에 들어간 설치물 상자만 사용한다."""
    primitives = row["primitives"]
    if row["role"] == "conductor":
        return [_polygon(primitive["points_mm"], primitive["z_mm"]) for primitive in primitives]
    if row["role"] == "via" and primitives:
        return [_barrel(primitives)]
    if row["role"] == "environment":
        result = []
        for primitive in primitives:
            (x0, x1), (y0, y1), z_range = primitive["bounds_mm"]
            result.append(_polygon(((x0, y0), (x1, y0), (x1, y1), (x0, y1)), z_range))
        return result
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
    for row in included:
        pieces = _pieces(row)
        if pieces:
            box = tuple((min(axis[0] for axis in bounds), max(axis[1] for axis in bounds))
                        for bounds in zip(*(piece.bounds for piece in pieces)))
            objects.append((row, pieces, box))

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
            "clearance_total": len(rows), "clearances": visible}
