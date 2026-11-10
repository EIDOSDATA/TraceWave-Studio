"""! @brief 실제 solver polygon의 급전 접촉과 서로 다른 도체 의미의 간극을 검사한다.

@details 이 검사는 고정 line/arc 투영의 유한 polygon에 적용한다. 임의 CAD의
완전한 연결성 또는 제조 DRC를 대신하지 않으며 다른 sheet 높이의 접속은 판정하지 않는다.
"""

import math

from rfad.domain.errors import ProjectError


CONTACT_EPSILON_MM = 1e-7
SHEET_EPSILON_MM = 1e-8


def _fail(code, message, field):
    """! @brief 접촉 오류와 관련된 원본 식별 위치를 유지한다."""
    raise ProjectError(code, message, details={"field_path": field})


def _point_segment_distance_squared(point, start, stop):
    """! @brief 퇴화된 선분을 포함하여 점과 닫힌 선분의 제곱 거리를 계산한다."""
    dx, dy = stop[0] - start[0], stop[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator == 0:
        return (point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2
    fraction = min(1.0, max(0.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator))
    return (point[0] - start[0] - fraction * dx) ** 2 + (point[1] - start[1] - fraction * dy) ** 2


def _cross(start, stop, point):
    """! @brief 세 평면 점의 방향을 유한 double 외적으로 구한다."""
    return (stop[0] - start[0]) * (point[1] - start[1]) - (stop[1] - start[1]) * (point[0] - start[0])


def _segment_distance_squared(a, b, c, d):
    """! @brief 내부 교차와 평행/끝점 접촉을 포함한 두 선분의 최소 제곱 거리를 구한다."""
    abc, abd, cda, cdb = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    if ((abc < 0 < abd or abd < 0 < abc) and (cda < 0 < cdb or cdb < 0 < cda)):
        return 0.0
    return min(_point_segment_distance_squared(a, c, d), _point_segment_distance_squared(b, c, d),
               _point_segment_distance_squared(c, a, b), _point_segment_distance_squared(d, a, b))


def _bounds(points):
    """! @brief polygon 또는 선분의 축 정렬 경계를 한 번 계산한다."""
    return (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))


def _near_bounds(left, right, distance):
    """! @brief 실제 거리 검사 전에 확장 bounding box로 확실히 떨어진 후보를 제거한다."""
    return not (left[2] + distance < right[0] or right[2] + distance < left[0]
                or left[3] + distance < right[1] or right[3] + distance < left[1])


def _polygon(points, field):
    """! @brief 입력 polygon의 유한 좌표와 비어 있지 않은 면을 검사하고 경계를 캐시한다."""
    if type(points) is not list or len(points) < 3 or any(type(p) is not list or len(p) != 2 or any(type(v) not in (float, int) or not math.isfinite(v) for v in p) for p in points):
        _fail("E_GEOMETRY", "해석 polygon의 유한 평면 좌표가 필요합니다.", field)
    if len(points) > 8192:
        _fail("E_RESOURCE", "접촉 검사의 전체 polygon 점 상한 8192개를 초과했습니다.", "geometry")
    edges = [(a, b, _bounds((a, b))) for a, b in zip(points, points[1:] + points[:1]) if a != b]
    if len(edges) < 3 or sum(_cross(points[0], a, b) for a, b, _ in edges) == 0:
        _fail("E_GEOMETRY", "해석 polygon의 경계가 퇴화했습니다.", field)
    return {"points": points, "edges": edges, "bounds": _bounds(points)}


def _on_boundary(point, polygon):
    """! @brief 원래 analytic 곡선이 아닌 실제 native polygon 경계의 접촉을 검사한다."""
    return any(_point_segment_distance_squared(point, a, b) <= CONTACT_EPSILON_MM ** 2 for a, b, _ in polygon["edges"])


def _inside(point, polygon):
    """! @brief 닫힌 경계를 포함하는 홀수 교차 규칙으로 polygon 내부를 판정한다."""
    if _on_boundary(point, polygon):
        return True
    x, y = point
    inside = False
    for a, b, _ in polygon["edges"]:
        if (a[1] > y) != (b[1] > y):
            crossing_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < crossing_x:
                inside = not inside
    return inside


def _segment_hits_polygon(start, stop, polygon):
    """! @brief 유한 표본 대신 모든 경계 선분과 내부 포함으로 급전 간극을 검사한다."""
    bounds = _bounds((start, stop))
    if not _near_bounds(bounds, polygon["bounds"], CONTACT_EPSILON_MM):
        return False
    if _inside(start, polygon) or _inside(stop, polygon):
        return True
    for a, b, edge_bounds in polygon["edges"]:
        if _near_bounds(bounds, edge_bounds, CONTACT_EPSILON_MM) and _segment_distance_squared(start, stop, a, b) <= CONTACT_EPSILON_MM ** 2:
            return True
    return False


def _polygons_too_close(left, right, clearance):
    """! @brief 교차/접촉/완전 포함과 두 곡선 근사 오차 이내 간격을 보수적으로 차단한다."""
    if not _near_bounds(left["bounds"], right["bounds"], clearance):
        return False
    if _inside(left["points"][0], right) or _inside(right["points"][0], left):
        return True
    squared = clearance * clearance
    for a, b, left_bounds in left["edges"]:
        for c, d, right_bounds in right["edges"]:
            if _near_bounds(left_bounds, right_bounds, clearance) and _segment_distance_squared(a, b, c, d) <= squared:
                return True
    return False


def _same_sheet(left, right):
    """! @brief 다른 높이의 도체를 평면 접촉으로 오인하지 않는다."""
    return math.isclose(left["sheet_z_mm"], right["sheet_z_mm"], rel_tol=0.0, abs_tol=SHEET_EPSILON_MM)


def _compatible(left, right):
    """! @brief 같은 net과 유효 sheet 재료일 때만 중첩/접촉을 의도한 합집합으로 허용한다."""
    return left.get("net_id") is not None and all(left.get(key) == right.get(key) for key in ("net_id", "material_id", "thickness_m", "conductivity_s_per_m"))


def validate_native_contacts(shapes, port, tolerance, polygons_by_id, vias=None):
    """! @brief native polygon의 양단 접촉, 열린 급전 간극과 도체별 전기 의미를 검증한다.

    @param shapes 단위가 mm이고 실제 sheet 높이와 유효 재료를 갖는 계획 도체.
    @param port 실제 native 입력의 start/stop 및 positive/reference 도체 식별.
    @param tolerance analytic 도체를 polygon으로 바꿀 때의 최대 거리 오차 mm.
    @param polygons_by_id 도체 UUID별 실제 소비할 polygon 목록.
    @throws ProjectError E_PORT 급전 영역 누락/단절/겹침, E_CONNECTIVITY 도체 의미 충돌.
    """
    vias = vias or []
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance <= 0:
        _fail("E_SCHEMA", "양수 native 곡선 근사 오차가 필요합니다.", "settings.curve_tolerance_mm")
    if type(shapes) is not list or not 1 <= len(shapes) <= 64:
        _fail("E_RESOURCE", "도체 접촉 검사는 최대 64개 형상을 지원합니다.", "geometry")
    shape_map = {shape["id"]: shape for shape in shapes}
    if len(shape_map) != len(shapes) or set(shape_map) != set(polygons_by_id):
        _fail("E_SCHEMA", "native polygon과 원본 도체 목록이 다릅니다.", "geometry")
    polygons = {}
    point_count = 0
    for shape in shapes:
        identity = shape["id"]
        raw = polygons_by_id[identity]
        if type(raw) is not list or not raw:
            _fail("E_GEOMETRY", "도체의 native polygon이 없습니다.", "geometry." + identity)
        polygons[identity] = [_polygon(points, "geometry." + identity) for points in raw]
        point_count += sum(len(p["points"]) for p in polygons[identity])
        if point_count > 8192:
            _fail("E_RESOURCE", "접촉 검사의 전체 polygon 점 상한 8192개를 초과했습니다.", "geometry")
    field = "ports." + port["id"]
    start, stop = port["start_mm"], port["stop_mm"]
    if any(type(p) is not list or len(p) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in (start, stop)):
        _fail("E_PORT", "급전 양끝의 유한 좌표가 필요합니다.", field)
    vertical = port.get("axis") == "z"
    if not vertical and start[2] != stop[2]:
        _fail("E_PORT", "평면 급전 양끝의 sheet 높이가 다릅니다.", field)
    for point, identity in ((start, port["reference_geometry_id"]), (stop, port["positive_geometry_id"])):
        if identity not in polygons or not math.isclose(point[2], shape_map[identity]["sheet_z_mm"], rel_tol=0.0, abs_tol=SHEET_EPSILON_MM):
            _fail("E_PORT", "급전 양끝의 native 도체 높이 또는 식별이 다릅니다.", field)
        predicate = _inside if vertical else _on_boundary
        if not any(predicate(point[:2], polygon) for polygon in polygons[identity]):
            _fail("E_PORT", "급전 양끝이 실제 native polygon 경계에 닿지 않습니다. 곡선 근사 접촉점을 보존하거나 급전 위치를 수정하십시오.", field)
    gap = math.dist(start, stop)
    if gap <= 8 * CONTACT_EPSILON_MM:
        _fail("E_PORT", "급전 간극이 접촉 판정 정밀도보다 작습니다.", field)
    # @brief 허용한 끝점 접촉만 제외하며 간극 전체는 표본 누락 없이 검사한다.
    fraction = 4 * CONTACT_EPSILON_MM / gap
    open_start = [start[i] + fraction * (stop[i] - start[i]) for i in range(3)]
    open_stop = [stop[i] - fraction * (stop[i] - start[i]) for i in range(3)]
    for shape in shapes:
        if vertical:
            if min(open_start[2], open_stop[2]) <= shape["sheet_z_mm"] <= max(open_start[2], open_stop[2]) and any(_inside(start[:2], polygon) for polygon in polygons[shape["id"]]):
                _fail("E_PORT", "수직 급전 간극 내부에 도체 sheet가 있습니다.", field)
        elif math.isclose(shape["sheet_z_mm"], start[2], rel_tol=0.0, abs_tol=SHEET_EPSILON_MM):
            if any(_segment_hits_polygon(open_start[:2], open_stop[:2], polygon) for polygon in polygons[shape["id"]]):
                _fail("E_PORT", "열린 급전 간극이 native 도체 polygon과 교차하거나 접합니다.", field)
    clearance = 2 * tolerance + CONTACT_EPSILON_MM
    connections = {shape["id"]: set() for shape in shapes + vias}
    for index, left in enumerate(shapes):
        for right in shapes[index + 1:]:
            if not _same_sheet(left, right):
                continue
            compatible = _compatible(left, right)
            distance = CONTACT_EPSILON_MM if compatible else clearance
            if any(_polygons_too_close(a, b, distance) for a in polygons[left["id"]] for b in polygons[right["id"]]):
                if compatible:
                    connections[left["id"]].add(right["id"])
                    connections[right["id"]].add(left["id"])
                    continue
                _fail("E_CONNECTIVITY", "서로 다른 net 또는 sheet 재료의 도체가 접촉하거나 곡선 근사 오차 이내로 가깝습니다.", "geometry." + right["id"])
    for index, via in enumerate(vias):
        via_field = "geometry." + via["id"]
        center, outer = via["center_mm"], via["outer_radius_mm"]
        if (max(start[2], stop[2]) >= via["z_min_mm"] and min(start[2], stop[2]) <= via["z_max_mm"]
                and _point_segment_distance_squared(center, start[:2], stop[:2]) <= (outer + clearance) ** 2):
            _fail("E_PORT", "급전 영역이 비아 배럴 또는 물리 구멍과 겹칩니다.", field)
        for other in vias[index + 1:]:
            if math.dist(center, other["center_mm"]) <= outer + other["outer_radius_mm"] + clearance:
                _fail("E_CONNECTIVITY", "비아 구멍/배럴이 겹치거나 너무 가깝습니다.", via_field)
        heights = []
        for identity in via["pad_ids"]:
            pad = shape_map.get(identity)
            if pad is None or pad.get("kind") != "pad" or pad["net_id"] != via["net_id"] or pad["material_id"] != via["material_id"]:
                _fail("E_CONNECTIVITY", "비아 양단에는 같은 net/재료의 명시적 pad가 필요합니다.", via_field + ".pad_ids")
            pad_polygons = polygons[identity]
            if len(pad_polygons) != 1 or not _inside(center, pad_polygons[0]) or min(_point_segment_distance_squared(center, a, b) for a, b, _ in pad_polygons[0]["edges"]) < (outer + tolerance) ** 2:
                _fail("E_CONNECTIVITY", "비아 배럴이 양단 pad의 실제 native 면적에 완전히 부착되지 않습니다.", via_field + ".pad_ids")
            heights.append(pad["sheet_z_mm"])
        if len(heights) != 2 or any(not math.isclose(a, b, abs_tol=SHEET_EPSILON_MM, rel_tol=0) for a, b in zip(sorted(heights), (via["z_min_mm"], via["z_max_mm"]))):
            _fail("E_CONNECTIVITY", "비아 pad의 실제 높이가 배럴 양끝과 다릅니다.", via_field + ".pad_ids")
        for shape in shapes:
            if not via["z_min_mm"] - SHEET_EPSILON_MM <= shape["sheet_z_mm"] <= via["z_max_mm"] + SHEET_EPSILON_MM:
                continue
            close = any(_inside(center, poly) or any(_point_segment_distance_squared(center, a, b) <= (outer + clearance) ** 2 for a, b, _ in poly["edges"]) for poly in polygons[shape["id"]])
            if close:
                if shape["net_id"] != via["net_id"] or shape["material_id"] != via["material_id"]:
                    _fail("E_CONNECTIVITY", "비아가 다른 net 또는 재료의 sheet와 접합니다. 명시적 antipad가 필요합니다.", via_field)
                # @brief 평면 면적과 배럴의 최종 연결은 생성된 Yee 격자에서 다시 확인한다.
                connections[via["id"]].add(shape["id"])
                connections[shape["id"]].add(via["id"])
    components = []
    pending = set(connections)
    while pending:
        reached, frontier = set(), {min(pending)}
        while frontier:
            identity = frontier.pop()
            if identity in reached:
                continue
            reached.add(identity)
            frontier.update(connections[identity] - reached)
        pending.difference_update(reached)
        components.append(sorted(reached))
    short_ids = [shape["id"] for shape in shapes + vias if shape.get("role") == "short"]
    if short_ids:
        all_shapes = {shape["id"]: shape for shape in shapes + vias}
        for identity in short_ids:
            component = next(set(group) for group in components if identity in group)
            roles = {all_shapes[member].get("role") for member in component}
            if not {port["positive_geometry_id"], port["reference_geometry_id"]}.issubset(component) or not {"ground", "radiator"}.issubset(roles):
                _fail("E_CONNECTIVITY", "명시적 short는 ground/radiator와 포트 양단의 같은 전기 연결 성분에 속해야 합니다.", "geometry." + identity)
    return {"schema": "rfad.pcb-connectivity/0.1", "components": components, "short_entity_ids": sorted(short_ids),
            "same_net_port_allowed": True, "native_polygon_contacts_checked": True, "yee_connectivity_checked": False}
