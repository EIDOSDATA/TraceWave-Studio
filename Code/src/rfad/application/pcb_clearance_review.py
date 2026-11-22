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
    """! @brief 다각형이 접하거나 내부에 포함되면 양의 간극을 보고하지 않는다."""
    best = None
    for points_a, bounds_a, edges_a in pieces_a:
        for points_b, bounds_b, edges_b in pieces_b:
            lower = _box_gap(bounds_a, bounds_b)
            if lower > (best[0] if best is not None else radius):
                continue
            if lower == 0 and (point_in_loop(points_a[0], points_b) or point_in_loop(points_b[0], points_a)):
                return None, budget
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
                        return None, budget
                    if distance <= radius and (best is None or distance < best[0]):
                        best = distance, a, b
    return best, budget


def _crossed_cells(a, b, lines):
    """! @brief 간극 선분과 길이가 겹치는 XY 셀의 인덱스를 진행 순서대로 반환한다."""
    axes = [lines["x"], lines["y"]]
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
    """! @brief 같은 높이의 해석 도체 중 기본 셀 폭 2배 이내의 양의 간극을 표시한다."""
    radius = 2 * grid_mm
    by_height = {}
    for conductor in included:
        if conductor["role"] != "conductor":
            continue
        primitives = conductor["primitives"]
        if not primitives:
            continue
        height = primitives[0]["z_mm"][0]
        pieces = [_piece(primitive) for primitive in primitives]
        overall = _bounds([point for points, _, _ in pieces for point in points])
        by_height.setdefault(height, []).append((conductor, pieces, overall))

    candidates = []
    for height, conductors in by_height.items():
        for (a, pieces_a, box_a), (b, pieces_b, box_b) in combinations(conductors, 2):
            lower = _box_gap(box_a, box_b)
            if lower <= radius:
                candidates.append((lower, height, a, b, pieces_a, pieces_b))
    candidates.sort(key=lambda row: (row[0], row[1], row[2]["id"], row[3]["id"]))
    budget = EDGE_PAIR_LIMIT
    rows = []
    evaluated = 0
    for _, height, a, b, pieces_a, pieces_b in candidates:
        nearest, budget = _nearest(pieces_a, pieces_b, radius, budget)
        if budget < 0:
            break
        evaluated += 1
        if nearest is not None:
            distance, start, stop = nearest
            rows.append({"object_ids": [a["id"], b["id"]], "object_names": [a["name"], b["name"]],
                         "distance_mm": distance, "z_mm": height, "points_mm": [start, stop]})
    rows.sort(key=lambda row: (row["distance_mm"], row["z_mm"], row["object_ids"]))
    visible = rows[:DISPLAY_LIMIT]
    for row in visible:
        row["cells_xy"] = _crossed_cells(*row["points_mm"], lines)
    return {"search_radius_mm": radius, "pair_total": len(candidates), "pair_evaluated": evaluated,
            "clearance_total": len(rows), "clearances": visible}
