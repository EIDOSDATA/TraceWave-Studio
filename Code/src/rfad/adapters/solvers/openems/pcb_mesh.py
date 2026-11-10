"""! @brief 실제 CSXCAD 재료와 생성한 Yee 전기 edge에서 도체 연결과 급전 간극을 검사한다."""

import bisect
import itertools
import math

from rfad.application.pcb_solver import _bounds, shape_polygons
from rfad.application.pcb_contacts import _inside, _polygon
from rfad.domain.errors import ProjectError
from rfad.domain.planar import point_in_loop


def audit_native_mesh(csx, case, lines):
    """! @brief 광학 preview 대신 실제 native 재료 우선순위를 Yee edge 중심에서 평가한다.

    @details pinned openEMS Operator::GetYeeCoords와 같은 전기 edge 중심을 사용한다.
    이 검사는 native 재료/격자 연결 검사이며 전체 operator 계수나 RF 수렴 증명은 아니다.
    """
    def reject(message, identity=""):
        """! @brief 잘못된 격자 연결을 계산 완료 상태로 진행하지 않는다."""
        raise ProjectError("E_CONNECTIVITY", message, details={"field_path": "geometry." + identity})
    axes = [lines[axis] for axis in "xyz"]
    shapes, vias = case["shapes"], case.get("vias", [])
    entities = {item["id"]: item for item in shapes + vias}
    properties = {"conductor_" + item["id"]: item for item in shapes}
    properties.update({"via_" + item["id"]: item for item in vias})
    nodes, observed, memberships = {}, {}, {identity: set() for identity in entities}
    edge_counts = {identity: 0 for identity in entities}
    polygons = {item["id"]: [_polygon(poly, item["id"]) for poly in shape_polygons(item, case["settings"]["curve_tolerance_mm"])] for item in shapes}

    def find(node):
        """! @brief path compression으로 실제 도체 edge의 전기 연결 성분을 추적한다."""
        nodes.setdefault(node, node)
        while nodes[node] != node:
            nodes[node] = nodes[nodes[node]]
            node = nodes[node]
        return node

    def point_on_edge(key):
        """! @brief n방향 좌표만 두 격자선의 중간값인 실제 Yee 전기 위치를 구한다."""
        axis, *position = key
        point = [axes[i][position[i]] for i in range(3)]
        point[axis] = (axes[axis][position[axis]] + axes[axis][position[axis] + 1]) / 2
        return point

    def actual_property(key):
        """! @brief 포트/probe를 제외하고 native MATERIAL|METAL 재료 우선순위를 검사한다."""
        if key not in observed:
            # @brief pinned CSProperties.h의 MATERIAL=0x002, METAL=0x004를 명시한다.
            prop = csx.GetPropertyByCoordPriority(point_on_edge(key), prop_type=0x002 | 0x004)
            observed[key] = prop.GetName() if prop is not None else None
        return observed[key]

    def accept(key, identity):
        """! @brief 실제 점유 edge를 끝점 그래프와 원본 entity에 연결한다."""
        material = properties.get(actual_property(key))
        if material is None or material["net_id"] != entities[identity]["net_id"]:
            return
        axis, *position = key
        start, stop = tuple(position), list(position)
        stop[axis] += 1
        stop = tuple(stop)
        left, right = find(start), find(stop)
        if left != right:
            nodes[right] = left
        memberships[identity].update((start, stop))
        edge_counts[identity] += 1

    def indexes(axis, low, high, midpoint=False):
        """! @brief 고정 global 격자의 해당 유한 물체 경계만 순회한다."""
        values = axes[axis]
        if midpoint:
            return range(max(0, bisect.bisect_left(values, low) - 1), min(len(values) - 1, bisect.bisect_right(values, high)))
        return range(bisect.bisect_left(values, low - 1e-8), bisect.bisect_right(values, high + 1e-8))

    def node_at(point):
        """! @brief 포트/접면의 물리 좌표가 실제 격자선에 보존되었는지 확인한다."""
        result = []
        for axis, value in enumerate(point):
            index = min(range(len(axes[axis])), key=lambda i: abs(axes[axis][i] - value))
            if abs(axes[axis][index] - value) > 1e-8:
                reject("포트/접면이 native 격자선에 없습니다.")
            result.append(index)
        return tuple(result)

    for shape in shapes:
        bounds = _bounds(shape)
        iz = node_at([axes[0][0], axes[1][0], shape["sheet_z_mm"]])[2]
        for axis in (0, 1):
            ranges = [indexes(i, *bounds[i], midpoint=i == axis) for i in (0, 1)]
            for ix, iy in itertools.product(*ranges):
                key = (axis, ix, iy, iz)
                point = point_on_edge(key)
                if any(_inside(point[:2], polygon) for polygon in polygons[shape["id"]]):
                    accept(key, shape["id"])
    for via in vias:
        cx, cy = via["center_mm"]
        outer = via["outer_radius_mm"]
        bounds = [(cx - outer, cx + outer), (cy - outer, cy + outer), (via["z_min_mm"], via["z_max_mm"])]
        for axis in (0, 1, 2):
            ranges = [indexes(i, *bounds[i], midpoint=i == axis) for i in range(3)]
            for position in itertools.product(*ranges):
                key = (axis, *position)
                point = point_on_edge(key)
                radius = math.dist(point[:2], via["center_mm"])
                if via["inner_radius_mm"] < radius <= outer + 1e-10 and via["z_min_mm"] <= point[2] <= via["z_max_mm"]:
                    accept(key, via["id"])
    entity_roots = {}
    for identity, members in memberships.items():
        roots = {find(node) for node in members}
        if len(roots) != 1:
            reject(f"native Yee 격자에서 도체가 사라졌거나 여러 연결 성분으로 끊어졌습니다. role={entities[identity]['role']}, edges={edge_counts[identity]}, components={len(roots)}", identity)
        entity_roots[identity] = next(iter(roots))
    groups = {}
    for identity, root in entity_roots.items():
        groups.setdefault(root, []).append(identity)
    components = sorted(sorted(group) for group in groups.values())
    if components != sorted(case["connectivity"]["components"]):
        reject("native Yee 격자의 연결 성분이 계획한 도체/short/비아 연결과 다릅니다.")
    port = case["port"]
    start, stop = node_at(port["start_mm"]), node_at(port["stop_mm"])
    for endpoint, identity in ((start, port["reference_geometry_id"]), (stop, port["positive_geometry_id"])):
        if endpoint not in memberships[identity]:
            reject("포트 단자가 실제 native Yee 도체 edge에 연결되지 않았습니다.", identity)
    axis = "xyz".index(port["axis"])
    gap_edges = abs(stop[axis] - start[axis])
    if gap_edges < 2:
        reject("급전 간극을 실제 native 격자 두 개 이상으로 표현해야 합니다.")
    for index in range(min(start[axis], stop[axis]), max(start[axis], stop[axis])):
        position = list(start)
        position[axis] = index
        if actual_property((axis, *position)) in properties:
            reject("native Yee 급전 간극이 도체로 메워졌습니다.")
    hole_checks = []
    for shape in shapes:
        if shape["kind"] != "planar_region":
            continue
        iz = node_at([axes[0][0], axes[1][0], shape["sheet_z_mm"]])[2]
        for index, hole in enumerate(shape["holes_mm"]):
            count = 0
            for axis in (0, 1):
                ranges = [indexes(i, min(p[i] for p in hole), max(p[i] for p in hole), midpoint=i == axis) for i in (0, 1)]
                for ix, iy in itertools.product(*ranges):
                    key = (axis, ix, iy, iz)
                    if point_in_loop(point_on_edge(key)[:2], hole, include_boundary=False):
                        prop = actual_property(key)
                        if prop == "conductor_" + shape["id"]:
                            reject("native Yee 격자에서 명시적 polygon 구멍이 도체로 메워졌습니다.", shape["id"])
                        if prop not in properties:
                            count += 1
            if count < 2:
                reject("polygon 구멍의 열린 영역을 native Yee 격자로 해상하지 못했습니다.", shape["id"])
            hole_checks.append({"entity_id": shape["id"], "hole_index": index, "open_electric_edges": count})
    return {"schema": "rfad.pcb-native-connectivity/0.1", "method": "CSXCAD material priority at Yee electric edge centers",
            "operator_coefficients_checked": False, "yee_connectivity_checked": True, "components": components,
            "entities": [{"entity_id": identity, "conductor_edge_count": edge_counts[identity], "component_count": 1} for identity in sorted(entities)],
            "port_gap_edge_count": gap_edges, "port_terminals_connected": True, "polygon_holes": hole_checks,
            "physics_validated": False}
