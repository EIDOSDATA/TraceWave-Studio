"""! @brief 정확한 CAD 기본 고체와 관통 비아를 생성한다.

@details CadQuery 객체는 호출자가 제공하며 native 의존성을 import 시 로드하지 않는다.
"""

import math

from rfad.domain.errors import ProjectError


def _require(condition: bool, message: str, *, code: str = "E_GEOMETRY", field: str = "cad") -> None:
    """! @brief 지원 범위와 native 검사 실패를 원본 필드 진단으로 전달한다."""
    if not condition:
        raise ProjectError(code, message, details={"field_path": field})


def _number(value: object, field: str, *, positive: bool = False) -> float:
    """! @brief native 경계에서도 유한 숫자와 양수 조건을 다시 확인한다."""
    _require(type(value) in (int, float), "CAD 입력에는 유한 숫자가 필요합니다.", field=field)
    number = float(value)
    _require(math.isfinite(number) and abs(number) <= 1e6 and (not positive or number >= 1e-5),
             "CAD 표시 범위 또는 최소 형상 크기를 벗어났습니다.", field=field)
    return number


def _point(values: object, field: str) -> tuple[float, float]:
    """! @brief mm 평면 좌표를 외부 코드 실행 없이 읽는다."""
    _require(type(values) is list and len(values) == 2, "CAD 평면 점에는 좌표 두 개가 필요합니다.", field=field)
    return tuple(_number(value, field) for value in values)


def _circle_arc(cq, radius: float, center: tuple, start: float, sweep: float):
    """! @brief 세 점으로 원을 추정하지 않고 명시한 반지름과 signed 각도로 자른다."""
    if sweep > 0.0:
        return cq.Edge.makeCircle(radius, center, (0, 0, 1), start, start + sweep)
    return cq.Edge.makeCircle(radius, center, (0, 0, 1), start + sweep, start).reverse()


def _line(cq, shape: dict, layer: dict):
    """! @brief 선 중심선에 정확한 반원 끝단을 연결하여 양의 두께 고체를 만든다."""
    start = _point(shape["start_mm"], "geometry." + shape["id"] + ".start")
    end = _point(shape["end_mm"], "geometry." + shape["id"] + ".end")
    width = _number(shape["width_mm"], "geometry." + shape["id"] + ".width", positive=True)
    length = math.dist(start, end)
    _require(length >= 1e-5, "CAD 선 길이가 최소 형상 크기보다 작습니다.")
    ux, uy = ((end[index] - start[index]) / length for index in range(2))
    radius = width / 2.0
    z = layer["z_min_mm"]
    start_left = (start[0] - uy * radius, start[1] + ux * radius, z)
    start_right = (start[0] + uy * radius, start[1] - ux * radius, z)
    end_left = (end[0] - uy * radius, end[1] + ux * radius, z)
    end_right = (end[0] + uy * radius, end[1] - ux * radius, z)
    direction = math.degrees(math.atan2(uy, ux))
    edges = [
        cq.Edge.makeLine(start_left, end_left),
        _circle_arc(cq, radius, (end[0], end[1], z), direction + 90.0, -180.0),
        cq.Edge.makeLine(end_right, start_right),
        _circle_arc(cq, radius, (start[0], start[1], z), direction - 90.0, -180.0),
    ]
    wire = cq.Wire.assembleEdges(edges)
    return cq.Solid.extrudeLinear(wire, [], (0.0, 0.0, layer["thickness_mm"]))


def _arc(cq, shape: dict, layer: dict):
    """! @brief signed sweep의 원호 양쪽 offset과 반원 끝단을 analytic wire로 만든다."""
    cx, cy = _point(shape["center_mm"], "geometry." + shape["id"] + ".center")
    radius = _number(shape["radius_mm"], "geometry." + shape["id"] + ".radius", positive=True)
    width = _number(shape["width_mm"], "geometry." + shape["id"] + ".width", positive=True)
    start_degrees = math.remainder(_number(shape["start_angle_deg"], "geometry." + shape["id"] + ".start_angle"), 360.0)
    start = math.radians(start_degrees)
    sweep = _number(shape["sweep_angle_deg"], "geometry." + shape["id"] + ".sweep_angle")
    _require(1e-6 <= abs(sweep) <= 360.0, "CAD 원호 회전량은 0보다 크고 360도 이하여야 합니다.")
    outer, inner = radius + width / 2.0, radius - width / 2.0
    _require(inner >= 1e-5, "원호 안쪽 반지름이 CAD 최소 형상 크기보다 작습니다.")
    z = layer["z_min_mm"]
    height = layer["thickness_mm"]
    if abs(sweep) == 360.0:
        outer_wire = cq.Wire.makeCircle(outer, (cx, cy, z), (0, 0, 1))
        inner_wire = cq.Wire.makeCircle(inner, (cx, cy, z), (0, 0, 1))
        return cq.Solid.extrudeLinear(outer_wire, [inner_wire], (0.0, 0.0, height))
    if abs(sweep) > 180.0:
        gap = 2.0 * radius * math.sin(math.radians(360.0 - abs(sweep)) / 2.0)
        _require(gap > width + 1e-5,
                 "근접한 원호 끝단의 반원 cap이 겹치거나 최소 간격보다 가깝습니다. 이 profile은 해당 자기 중첩을 지원하지 않습니다.",
                 code="E_UNSUPPORTED", field="geometry." + shape["id"] + ".sweep_angle")
    angle = math.radians(sweep)
    end = start + angle
    sign = 1.0 if sweep > 0.0 else -1.0
    end_degrees = start_degrees + sweep
    edges = [
        _circle_arc(cq, outer, (cx, cy, z), start_degrees, sweep),
        _circle_arc(cq, width / 2.0, (cx + radius * math.cos(end), cy + radius * math.sin(end), z), end_degrees, sign * 180.0),
        _circle_arc(cq, inner, (cx, cy, z), end_degrees, -sweep),
        _circle_arc(cq, width / 2.0, (cx + radius * math.cos(start), cy + radius * math.sin(start), z), start_degrees + 180.0, sign * 180.0),
    ]
    wire = cq.Wire.assembleEdges(edges)
    return cq.Solid.extrudeLinear(wire, [], (0.0, 0.0, height))


def _loop_area(points):
    """! @brief 큰 원점의 상쇄 오차를 줄여 polygon의 signed 면적을 계산한다."""
    origin = points[0]
    return sum((a[0] - origin[0]) * (b[1] - origin[1]) - (b[0] - origin[0]) * (a[1] - origin[1])
               for a, b in zip(points, points[1:] + points[:1])) / 2


def _region(cq, shape, layer):
    """! @brief 선분 경계와 명시적 holes를 실제 OCCT inner wire로 압출한다."""
    from rfad.domain.planar import validate_region

    field = "geometry." + shape["id"]
    outer = [list(_point(point, field + ".outer")) for point in shape["outer_mm"]]
    holes = [[list(_point(point, field + ".holes")) for point in loop] for loop in shape["holes_mm"]]
    validate_region(outer, holes, field)
    for loop in [outer, *holes]:
        _require(all(math.dist(a, b) >= 1e-5 for a, b in zip(loop, loop[1:] + loop[:1])),
                 "영역 경계의 변이 최소 형상 길이보다 짧습니다.", field=field)
    z = layer["z_min_mm"]
    def wire(points, positive):
        oriented = points if (_loop_area(points) > 0) == positive else list(reversed(points))
        return cq.Wire.makePolygon([(x, y, z) for x, y in oriented], close=True)
    outer_wire, inner_wires = wire(outer, True), [wire(hole, False) for hole in holes]
    for index, boundary in enumerate([outer_wire, *inner_wires]):
        for other in [outer_wire, *inner_wires][index + 1:]:
            _require(boundary.distance(other) >= 1e-5, "영역 경계 간격이 CAD 최소 형상보다 작습니다.", field=field)
    for loop in [outer, *holes]:
        edges = [cq.Edge.makeLine((a[0], a[1], z), (b[0], b[1], z)) for a, b in zip(loop, loop[1:] + loop[:1])]
        for index, edge in enumerate(edges):
            for other_index in range(index + 2, len(edges)):
                if index == 0 and other_index == len(edges) - 1:
                    continue
                _require(edge.distance(edges[other_index]) >= 1e-5, "영역의 좁은 간격 또는 연결 폭이 CAD 최소 형상보다 작습니다.", field=field)
    solid = cq.Solid.extrudeLinear(outer_wire, inner_wires, (0, 0, layer["thickness_mm"]))
    area = abs(_loop_area(outer)) - sum(abs(_loop_area(hole)) for hole in holes)
    _require(area >= 1e-10, "도체 영역의 면적이 CAD 최소 형상보다 작습니다.", field=field)
    return solid, area


def _pad(cq, shape, layer):
    """! @brief 실제 층 두께만 사용하는 원형/회전 사각 패드를 생성한다."""
    field = "geometry." + shape["id"]
    cx, cy = _point(shape["center_mm"], field + ".center")
    sizes = shape["size_mm"]
    _require(type(sizes) is list and len(sizes) == 2, "패드에는 두 치수가 필요합니다.", field=field + ".size")
    width, height = [_number(value, field + ".size", positive=True) for value in sizes]
    rotation = _number(shape["rotation_deg"], field + ".rotation")
    z, thickness = layer["z_min_mm"], layer["thickness_mm"]
    if shape["pad_shape"] == "circle":
        _require(math.isclose(width, height, rel_tol=0, abs_tol=1e-9), "원형 패드의 두 지름이 다릅니다.", field=field + ".size")
        return cq.Solid.makeCylinder(width / 2, thickness, (cx, cy, z)), math.pi * (width / 2) ** 2
    _require(shape["pad_shape"] == "rectangle", "지원하지 않는 패드 외형입니다.", code="E_UNSUPPORTED", field=field)
    solid = cq.Solid.makeBox(width, height, thickness, (cx - width / 2, cy - height / 2, z))
    return solid.rotate((cx, cy, z), (cx, cy, z + 1), math.remainder(rotation, 360)), width * height


def _planar_solid(cq, source, layer):
    """! @brief 원본 도체별 정확한 고체와 독립 산술 면적을 반환한다."""
    kind = source["kind"]
    if kind == "planar_region":
        return _region(cq, source, layer)
    if kind == "pad":
        return _pad(cq, source, layer)
    _require(kind in ("line_path", "arc_path"), "해당 CAD 형상은 지원하지 않습니다.", code="E_UNSUPPORTED")
    if kind == "line_path":
        area = math.dist(source["start_mm"], source["end_mm"]) * source["width_mm"] + math.pi * (source["width_mm"] / 2) ** 2
        return _line(cq, source, layer), area
    area = source["radius_mm"] * source["width_mm"] * math.radians(abs(source["sweep_angle_deg"]))
    if abs(source["sweep_angle_deg"]) != 360:
        area += math.pi * (source["width_mm"] / 2) ** 2
    return _arc(cq, source, layer), area


def _inside_outline(cq, solid, board, z_min, thickness, tolerance, field):
    """! @brief 실제 생성 고체를 기판 외곽과 비교하며 자동 clipping을 금지한다."""
    box = solid.BoundingBox()
    if board.get("kind", "rectangle") == "circle":
        cx, cy = board["center_mm"]
        coverage = cq.Solid.makeCylinder(board["radius_mm"] + tolerance, thickness + 2 * tolerance, (cx, cy, z_min - tolerance))
        outside = solid.cut(coverage)
        _require(outside.isValid(), "원형 기판 외곽의 Boolean 포함 검증이 실패했습니다.", field=field)
        contained = not outside.Solids() or outside.Volume() <= 1e-18
    else:
        contained = box.xmin >= -tolerance and box.ymin >= -tolerance and box.xmax <= board["width_mm"] + tolerance and box.ymax <= board["height_mm"] + tolerance
    _require(contained, "도체 또는 비아 drill이 기판 외곽을 벗어납니다. 자동 절개하지 않습니다.", field=field)


def _material(source, layer):
    """! @brief 명시한 도체 재료 override 또는 원본 층의 재료 참조만 사용한다."""
    return source["material_ref"] if source["material_ref"] is not None else layer["material_id"]


def _via_records(cq, projection, layers, planar):
    """! @brief through-PTH의 실제 span, 중공 barrel과 명시적 양단 패드 접속을 검증한다."""
    conductors = sorted((layer for layer in layers.values() if layer["role"] == "conductor"), key=lambda layer: layer["z_min_mm"])
    records = []
    for source in projection["shapes"]:
        if source["kind"] != "via":
            continue
        field = "geometry." + source["id"]
        _require(len(conductors) >= 2 and {source["layer_id"], source["end_layer_id"]} == {conductors[0]["id"], conductors[-1]["id"]},
                 "초기 CAD 비아는 최하/최상 conductor 층 사이의 관통 PTH만 지원합니다.", code="E_UNSUPPORTED", field=field)
        _require(source["fill"] == "none" and source["net_id"] is not None, "관통 비아에는 미충진 상태와 명시적 net이 필요합니다.", code="E_CONNECTIVITY", field=field)
        pads = source["pad_ids"]
        _require(type(pads) is list and 2 <= len(pads) <= 8 and len(set(pads)) == len(pads), "비아 양 끝의 고유 pad 참조 2~8개가 필요합니다.", code="E_CONNECTIVITY", field=field + ".pad_ids")
        cx, cy = _point(source["center_mm"], field + ".center")
        inner = _number(source["finished_hole_diameter_mm"], field + ".finished_hole_diameter", positive=True) / 2
        plating = _number(source["plating_thickness_mm"], field + ".plating_thickness", positive=True)
        outer = inner + plating
        tool = source["tool_hole_diameter_mm"]
        if tool is not None:
            _require(math.isclose(_number(tool, field + ".tool_hole_diameter", positive=True), 2 * outer, rel_tol=0, abs_tol=projection["tolerance_mm"]),
                     "tool bore와 finished bore/plating의 관계가 초기 CAD profile과 다릅니다.", code="E_UNSUPPORTED", field=field)
        low = conductors[0]["z_min_mm"]
        high = conductors[-1]["z_min_mm"] + conductors[-1]["thickness_mm"]
        span = high - low
        _require(all(layer["z_min_mm"] >= low and layer["z_min_mm"] + layer["thickness_mm"] <= high for layer in layers.values()),
                 "초기 관통 PTH의 양 끝 conductor 밖에 추가 적층이 있습니다.", code="E_UNSUPPORTED", field=field)
        drill = cq.Solid.makeCylinder(outer, span, (cx, cy, low))
        _inside_outline(cq, drill, projection["board"], low, span, projection["tolerance_mm"], field)
        outer_wire = cq.Wire.makeCircle(outer, (cx, cy, low), (0, 0, 1))
        inner_wire = cq.Wire.makeCircle(inner, (cx, cy, low), (0, 0, 1))
        barrel = cq.Solid.extrudeLinear(outer_wire, [inner_wire], (0, 0, span))
        _require(math.isclose(barrel.Volume(), math.pi * (outer ** 2 - inner ** 2) * span, rel_tol=1e-7, abs_tol=1e-18),
                 "실제 비아 barrel의 체적이 중공 원통과 다릅니다.", field=field)
        material = _material(source, layers[source["layer_id"]])
        pad_layers = set()
        for identity in pads:
            _require(identity in planar and planar[identity][0]["kind"] == "pad", "비아가 참조한 출력 pad 형상이 없습니다.", code="E_CONNECTIVITY", field=field + ".pad_ids")
            pad, solid = planar[identity]
            layer = layers[pad["layer_id"]]
            _require(pad["net_id"] == source["net_id"] and _material(pad, layer) == material,
                     "비아와 명시적 pad의 net 또는 재료가 다릅니다.", code="E_CONNECTIVITY", field=field + ".pad_ids")
            _require(low <= layer["z_min_mm"] and layer["z_min_mm"] + layer["thickness_mm"] <= high,
                     "비아 pad가 실제 barrel 범위를 벗어납니다.", code="E_CONNECTIVITY", field=field)
            coverage = cq.Solid.makeCylinder(outer + 1e-5, layer["thickness_mm"], (cx, cy, layer["z_min_mm"]))
            outside = coverage.cut(solid)
            _require(outside.isValid() and (not outside.Solids() or outside.Volume() <= 1e-18),
                     "비아의 명시적 pad에 양의 annular 접속 여유가 없습니다.", code="E_CONNECTIVITY", field=field + ".pad_ids")
            pad_layers.add(layer["id"])
        _require({conductors[0]["id"], conductors[-1]["id"]} <= pad_layers, "관통 비아 양 끝에 명시적 pad가 필요합니다.", code="E_CONNECTIVITY", field=field)
        for previous in records:
            _require(drill.distance(previous["drill"]) > projection["tolerance_mm"],
                     "겹치거나 접한 비아 drill은 초기 CAD profile에서 지원하지 않습니다.", code="E_UNSUPPORTED", field=field)
        records.append({"source": source, "drill": drill, "shape": barrel, "material_id": material,
                        "z_min_mm": low, "z_max_mm": high, "outer_radius_mm": outer, "inner_radius_mm": inner,
                        "layer_ids": [layer["id"] for layer in conductors]})
    return records


def _drilled(solid, records):
    """! @brief 명시적 관통 PTH의 실제 outer barrel 공간을 해당 body에서 제거한다."""
    sources = []
    for record in records:
        common = solid.intersect(record["drill"])
        _require(common.isValid(), "비아 drill 교집합 계산이 실패했습니다.")
        if common.Volume() > 1e-18:
            solid = solid.cut(record["drill"])
            _require(solid.isValid() and bool(solid.Solids()), "drill 후 원본 도체 또는 유전체가 사라지거나 유효하지 않습니다.")
            sources.append(record["source"]["id"])
    return solid, sources
