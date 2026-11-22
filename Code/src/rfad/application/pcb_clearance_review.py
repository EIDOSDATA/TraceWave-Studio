"""! @brief 실제 해석 도체 다각형의 XY 간극과 격자 셀을 찾는다."""

from bisect import bisect_left, bisect_right
from itertools import combinations
import math

from rfad.domain.boundary_distance import Segment, boundary_distance
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


def _piece(primitive):
    """! @brief 해석기에 들어가는 다각형의 경계 선분을 캐시한다."""
    points = tuple(map(tuple, primitive["points_mm"]))
    edges = [(Segment(a, b), _bounds((a, b))) for a, b in zip(points, points[1:] + points[:1]) if a != b]
    return points, _bounds(points), edges


def _nearest(pieces_a, pieces_b, radius, budget):
    """! @brief 투영이 접하거나 겹칠 때의 공통점도 반환한다."""
    best = None
    for points_a, bounds_a, edges_a in pieces_a:
        for points_b, bounds_b, edges_b in pieces_b:
            lower = _box_gap(bounds_a, bounds_b)
            if lower > (best[0] if best is not None else radius):
                continue
            if lower == 0:
                for point, loop in ((points_a[0], points_b), (points_b[0], points_a)):
                    if point_in_loop(point, loop):
                        return (0.0, point, point), budget
            for edge_a, box_a in edges_a:
                if _box_gap(box_a, bounds_b) > (best[0] if best is not None else radius):
                    continue
                for edge_b, box_b in edges_b:
                    if budget == 0:
                        return None, -1
                    budget -= 1
                    if _box_gap(box_a, box_b) > (best[0] if best is not None else radius):
                        continue
                    distance, a, b = boundary_distance(edge_a, edge_b)
                    if distance <= 1e-12:
                        return (0.0, a, a), budget
                    if distance <= radius and (best is None or distance < best[0]):
                        best = distance, a, b
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
    """! @brief 실제 평면 도체의 3D 간극 중 기본 셀 폭 2배 이내의 간극을 표시한다."""
    radius = 2 * grid_mm
    conductors = []
    for conductor in included:
        if conductor["role"] != "conductor":
            continue
        primitives = conductor["primitives"]
        if not primitives:
            continue
        height = primitives[0]["z_mm"][0]
        pieces = [_piece(primitive) for primitive in primitives]
        overall = _bounds([point for points, _, _ in pieces for point in points])
        conductors.append((conductor, height, pieces, overall))

    candidates = []
    for left, right in combinations(conductors, 2):
        height_delta = abs(left[1] - right[1])
        lower = math.hypot(_box_gap(left[3], right[3]), height_delta)
        if lower <= radius:
            candidates.append((lower, left, right))
    candidates.sort(key=lambda row: (row[0], row[1][1], row[1][0]["id"], row[2][0]["id"]))
    budget = EDGE_PAIR_LIMIT
    rows = []
    evaluated = 0
    for _, (a, height, pieces_a, _), (b, other, pieces_b, _) in candidates:
        dz = abs(other - height)
        limit = math.sqrt((radius - dz) * (radius + dz))
        nearest, budget = _nearest(pieces_a, pieces_b, limit, budget)
        if budget < 0:
            break
        evaluated += 1
        if nearest is not None:
            horizontal, start, stop = nearest
            distance = math.hypot(horizontal, dz)
            if distance <= 1e-12 or distance > radius:
                continue
            row = {"object_ids": [a["id"], b["id"]], "object_names": [a["name"], b["name"]],
                   "distance_mm": distance, "z_mm": height, "points_mm": [start, stop]}
            if dz:
                row["other_z_mm"] = other
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
