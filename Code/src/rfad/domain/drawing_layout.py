"""! @brief 고정 CAD 투영에서 GUI와 교환 파일이 공유하는 mm 기술도면을 만든다.

@details 외부 그래픽 패키지, 파일 IO, 프로젝트 변경 없이 해석형 경계를 유지한다.
도면 주석과 제조 형상을 분리하며 제작 공차나 미정 치수를 생성하지 않는다.
"""

from copy import deepcopy
import math
import re

from rfad.domain.errors import ProjectError


PROFILE = "rfad.exchange.drawing/0.1"
MAX_PAGES = 32
MAX_PRIMITIVES = 12000
INK = [35, 48, 64]
COPPER = [238, 178, 84]
BLUE = [36, 94, 153]


def fail(message, field="drawing", code="E_UNSUPPORTED"):
    """! @brief 사용자 입력 위치를 포함한 명시적 출력 거절을 전달한다."""
    raise ProjectError(code, message, details={"field_path": field})


def number(value, field="drawing", positive=False):
    """! @brief bool, 비유한 값, 범위 밖 좌표를 형상 계산 전에 거부한다."""
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
        fail("도면 좌표와 치수는 유한한 mm 값이어야 합니다.", field, "E_GEOMETRY")
    if positive and value <= 0:
        fail("도면 치수는 양수여야 합니다.", field, "E_GEOMETRY")
    return float(value)


def point(value):
    """! @brief 원본의 두 좌표를 암묵적인 축 변환 없이 읽는다."""
    if type(value) is not list or len(value) != 2:
        fail("평면 좌표 두 개가 필요합니다.", code="E_SCHEMA")
    return [number(item) for item in value]


def polar(center, radius, angle):
    """! @brief 부호 있는 해석형 원호의 끝점을 계산한다."""
    angle = math.radians(angle)
    return [center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle)]


def line(start, end):
    """! @brief 방향을 유지하는 선 경계를 만든다."""
    return {"kind": "line", "start": list(start), "end": list(end)}


def arc(center, radius, start=0.0, sweep=360.0):
    """! @brief 원과 원호를 세분화하지 않는 경계를 만든다."""
    return {"kind": "arc", "center": list(center), "radius": radius,
            "start_deg": start, "sweep_deg": sweep}


def polygon(points):
    """! @brief 원문 꼭짓점 순서와 폐곡선을 유지한다."""
    return [line(a, b) for a, b in zip(points, points[1:] + points[:1])]


def board_bounds(board):
    """! @brief 기판의 실제 외곽을 읽으며 자동 여백이나 축척을 적용하지 않는다."""
    if board.get("kind") == "circle":
        x, y = point(board["center_mm"])
        r = number(board["radius_mm"], positive=True)
        return [x - r, y - r, x + r, y + r]
    return [0.0, 0.0, number(board["width_mm"], positive=True), number(board["height_mm"], positive=True)]


def board_loops(board):
    """! @brief 사각 또는 원형 기판 경계를 정확한 원시 도형으로 만든다."""
    if board.get("kind") == "circle":
        return [[arc(point(board["center_mm"]), number(board["radius_mm"], positive=True))]]
    x0, y0, x1, y1 = board_bounds(board)
    return [polygon([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])]


def shape_loops(shape):
    """! @brief 선과 원호의 둥근 끝단, 패드, 영역 구멍, 비아 원통 단면을 보존한다."""
    kind = shape["kind"]
    if kind == "planar_region":
        return [polygon([point(p) for p in loop]) for loop in [shape["outer_mm"], *shape["holes_mm"]]]
    if kind == "line_path":
        a, b = point(shape["start_mm"]), point(shape["end_mm"])
        width = number(shape["width_mm"], positive=True)
        if math.dist(a, b) < 1e-5:
            fail("길이가 없는 선은 출력할 수 없습니다.", code="E_GEOMETRY")
        angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        radius = width / 2
        return [[line(polar(a, radius, angle - 90), polar(b, radius, angle - 90)),
                 arc(b, radius, angle - 90, 180),
                 line(polar(b, radius, angle + 90), polar(a, radius, angle + 90)),
                 arc(a, radius, angle + 90, 180)]]
    if kind == "arc_path":
        c = point(shape["center_mm"])
        radius, half = number(shape["radius_mm"], positive=True), number(shape["width_mm"], positive=True) / 2
        start, sweep = number(shape["start_angle_deg"]), number(shape["sweep_angle_deg"])
        if not 1e-5 <= abs(sweep) <= 360 or radius - half < 1e-5:
            fail("원호의 반지름 또는 회전량이 출력 범위를 벗어났습니다.", code="E_GEOMETRY")
        if abs(sweep) == 360:
            return [[arc(c, radius + half)], [arc(c, radius - half)]]
        if abs(sweep) > 180 and radius * math.sin(math.radians((360 - abs(sweep)) / 2)) <= half:
            fail("원호의 둥근 끝단이 서로 겹치는 경우는 현재 해석형 출력 범위 밖입니다.", code="E_GEOMETRY")
        if sweep < 0:
            start, sweep = start + sweep, -sweep
        end = start + sweep
        return [[arc(c, radius + half, start, sweep),
                 arc(polar(c, radius, end), half, end, 180),
                 arc(c, radius - half, end, -sweep),
                 arc(polar(c, radius, start), half, start + 180, 180)]]
    if kind == "pad":
        center = point(shape["center_mm"])
        width, height = [number(value, positive=True) for value in shape["size_mm"]]
        if shape["pad_shape"] == "circle":
            if width != height:
                fail("원형 패드의 두 지름이 다릅니다.", code="E_GEOMETRY")
            return [[arc(center, width / 2)]]
        if shape["pad_shape"] != "rectangle":
            fail("지원하지 않는 패드 형상입니다.")
        angle = math.radians(number(shape["rotation_deg"]))
        vertices = []
        for x, y in [[-width / 2, -height / 2], [width / 2, -height / 2], [width / 2, height / 2], [-width / 2, height / 2]]:
            vertices.append([center[0] + x * math.cos(angle) - y * math.sin(angle), center[1] + x * math.sin(angle) + y * math.cos(angle)])
        return [polygon(vertices)]
    if kind == "via":
        center = point(shape["center_mm"])
        bore = number(shape["finished_hole_diameter_mm"], positive=True) / 2
        plating = number(shape["plating_thickness_mm"], positive=True)
        return [[arc(center, bore + plating)], [arc(center, bore)]]
    fail("지원하지 않는 도면 형상을 조용히 생략하지 않습니다.", "geometry." + str(shape.get("id")))


def _edge_distance(center, edge):
    """! @brief 원형 구멍과 해석형 경계의 교차 여부를 최소 거리로 판정한다."""
    if edge["kind"] == "line":
        a, b = edge["start"], edge["end"]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = 0 if length2 == 0 else max(0, min(1, ((center[0] - a[0]) * dx + (center[1] - a[1]) * dy) / length2))
        return math.dist(center, [a[0] + t * dx, a[1] + t * dy])
    angle = math.degrees(math.atan2(center[1] - edge["center"][1], center[0] - edge["center"][0]))
    sweep = edge["sweep_deg"]
    delta = ((angle - edge["start_deg"]) * (1 if sweep > 0 else -1)) % 360
    if delta <= abs(sweep):
        return abs(math.dist(center, edge["center"]) - edge["radius"])
    return min(math.dist(center, polar(edge["center"], edge["radius"], value))
               for value in [edge["start_deg"], edge["start_deg"] + sweep])


def _inside(center, loops):
    """! @brief 직선과 원호의 수평 반직선 교차를 세어 even-odd 내부를 판정한다."""
    x, y = center
    crossings = 0
    for loop in loops:
        for edge in loop:
            if edge["kind"] == "line":
                a, b = edge["start"], edge["end"]
                if (a[1] > y) != (b[1] > y) and x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                    crossings += 1
            else:
                cx, cy = edge["center"]
                q = (y - cy) / edge["radius"]
                if abs(q) >= 1:
                    continue
                angle = math.degrees(math.asin(q))
                for theta in [angle, 180 - angle]:
                    delta = ((theta - edge["start_deg"]) * (1 if edge["sweep_deg"] > 0 else -1)) % 360
                    if delta < abs(edge["sweep_deg"]) and polar([cx, cy], edge["radius"], theta)[0] > x:
                        crossings += 1
    return crossings % 2 == 1


def _drilled(loops, vias, entity_id):
    """! @brief 완전히 포함된 관통 구멍만 정확히 자르고 경계 교차는 명시 거절한다."""
    result = deepcopy(loops)
    for via in vias:
        center = point(via["center_mm"])
        radius = via["finished_hole_diameter_mm"] / 2 + via["plating_thickness_mm"]
        distance = min(_edge_distance(center, edge) for loop in loops for edge in loop)
        if distance <= radius + 1e-6:
            fail("관통 구멍이 객체 경계를 가로지르는 도면 Boolean은 현재 출력 profile 밖입니다.", "geometry." + entity_id)
        if _inside(center, loops):
            result.append([arc(center, radius)])
    return result


def _transform_edge(edge, scale, x, y, mirror):
    """! @brief 뒤면 반전 시 원호의 방향까지 함께 바꾼다."""
    def transform(value):
        return [x + scale * value[0] * mirror, y + scale * value[1]]
    if edge["kind"] == "line":
        return line(transform(edge["start"]), transform(edge["end"]))
    return arc(transform(edge["center"]), edge["radius"] * scale,
               180 - edge["start_deg"] if mirror < 0 else edge["start_deg"], edge["sweep_deg"] * mirror)


def _path(loops, source_id, layer_id=None, net_id=None, fill=COPPER):
    """! @brief 독립 파일의 객체 추적에 필요한 원본 ID를 경계와 함께 둔다."""
    return {"kind": "path", "loops": loops, "closed": True, "fill_rule": "evenodd",
            "source_id": source_id, "layer_id": layer_id, "net_id": net_id,
            "stroke": INK, "stroke_width_mm": 0.12, "fill": fill, "role": "geometry"}


def _text(x, y, text, height=3.0, align="left", **metadata):
    """! @brief 글꼴 높이와 기준선을 종이 mm로 명시한다."""
    return {"kind": "text", "position": [x, y], "text": str(text), "height_mm": height,
            "align": align, "rotation_deg": 0, "fill": INK, "stroke": None,
            "stroke_width_mm": 0, "role": "annotation", **metadata}


def _rule(a, b, color=INK, width=0.18, **metadata):
    """! @brief 실제 구리 형상과 구별한 도면 선을 만든다."""
    return {**line(a, b), "stroke": color, "stroke_width_mm": width, "fill": None,
            "role": "annotation", **metadata}


def _wrapped(text, width, height=3):
    """! @brief 단어와 값/단위 쌍을 우선 보존하고 긴 무공백 원문만 문자 단위로 나눈다."""
    def text_width(value):
        """! @brief 한글 전각과 라틴 문자의 보수적 표시 폭을 mm로 계산한다."""
        return sum(height * (1.05 if ord(char) > 255 else 0.62) for char in value)
    result = []
    number_pattern = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    unit_pattern = r"(?:mm(?:\^[23])?|deg|rad|m|um|mil|in)"
    # @brief 단위 토큰과 수치 사이의 공백만 묶고 원문은 그대로 결과에 쓴다.
    pattern = (r"[^\s]*?" + number_pattern + r"[ \t]+" + unit_pattern
               + r"(?=$|[\s,;:)\]])[,;:)\]]*|[^\s]+")
    for paragraph in str(text).split("\n"):
        tokens = list(re.finditer(pattern, paragraph))
        current, previous_end = "", 0
        for match in tokens:
            token = match.group(0)
            separator = paragraph[previous_end:match.start()]
            previous_end = match.end()
            if text_width(token) <= width:
                candidate = current + separator + token
                if current and text_width(candidate) > width:
                    result.append(current.rstrip())
                    current = token
                else:
                    current = candidate
                continue
            if current:
                result.append(current.rstrip())
                current = ""
            for char in token:
                if current and text_width(current + char) > width:
                    result.append(current)
                    current = ""
                current += char
        if current or not tokens:
            result.append(current)
    return result


def _dimension_rows(data, identities):
    """! @brief 실제 연관 값과 미정 상태를 표로 표시하고 표시 숫자를 덮어쓰지 않는다."""
    rows = []
    for group in data["dimensions"]:
        if group["entity_id"] not in identities:
            continue
        for item in group["items"]:
            value = item.get("value")
            value_text = "미정" if value is None else format(number(value), ".9g") + " " + item["unit"]
            rows.append({"source_id": group["entity_id"], "dimension_key": item["key"],
                         "text": group["label"] + " / " + item["label"] + ": " + value_text,
                         "value": value, "unit": item["unit"], "status": item["status"],
                         "anchors_mm": deepcopy(item.get("anchors_mm", [])),
                         "field_path": item.get("field_path"), "parameter_id": item.get("parameter_id"),
                         "source_refs": deepcopy(item.get("source_refs", []))})
    return rows


def _section_intervals(loops, ordinate):
    """! @brief 명시 Y 단면에서 해석형 외곽과 구멍의 실제 X 구간을 계산한다."""
    crossings = []
    for loop in loops:
        for edge in loop:
            if edge["kind"] == "line":
                a, b = edge["start"], edge["end"]
                if (a[1] > ordinate) != (b[1] > ordinate):
                    crossings.append(a[0] + (ordinate - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
            else:
                cx, cy = edge["center"]
                q = (ordinate - cy) / edge["radius"]
                if abs(q) >= 1:
                    continue
                theta = math.degrees(math.asin(q))
                for angle in [theta, 180 - theta]:
                    delta = ((angle - edge["start_deg"]) * (1 if edge["sweep_deg"] > 0 else -1)) % 360
                    if delta < abs(edge["sweep_deg"]):
                        crossings.append(polar([cx, cy], edge["radius"], angle)[0])
    crossings = sorted(set(crossings))
    return [[a, b] for a, b in zip(crossings, crossings[1:]) if b - a > 1e-9 and _inside([(a + b) / 2, ordinate], loops)]


def _section(data, vias, bounds):
    """! @brief 기판 중앙 Y의 실제 도체/유전체/표면층/PTH 절단면을 만든다."""
    projection = data["projection"]
    layers = {item["id"]: item for item in projection["layers"]}
    y = (bounds[1] + bounds[3]) / 2
    shapes = []
    def add(loops, lower, thickness, identity, layer_id, net, fill):
        for x0, x1 in _section_intervals(loops, y):
            shapes.append(_path([polygon([[x0, lower], [x1, lower], [x1, lower + thickness], [x0, lower + thickness]])],
                                identity, layer_id, net, fill))
    for layer in layers.values():
        if layer["role"] == "dielectric":
            add(_drilled(board_loops(projection["board"]), vias, projection["board"]["id"]), layer["z_min_mm"],
                layer["thickness_mm"], layer["id"], layer["id"], None, [214, 233, 218])
    for shape in projection["shapes"]:
        layer = layers[shape["layer_id"]]
        if shape["kind"] == "via":
            ends = [layer, layers[shape["end_layer_id"]]]
            lower = min(item["z_min_mm"] for item in ends)
            upper = max(item["z_min_mm"] + item["thickness_mm"] for item in ends)
            add(shape_loops(shape), lower, upper - lower, shape["id"], None, shape["net_id"], COPPER)
        else:
            add(_drilled(shape_loops(shape), vias, shape["id"]), layer["z_min_mm"], layer["thickness_mm"],
                shape["id"], layer["id"], shape["net_id"], COPPER)
    for surface in projection.get("surface_layers", []):
        if surface["coverage"] == "board":
            loops = board_loops(projection["board"])
        else:
            x, yy, width, height = surface["rectangle_mm"]
            loops = [polygon([[x, yy], [x + width, yy], [x + width, yy + height], [x, yy + height]])]
        intervals = _section_intervals(loops, y)
        for x, yy, width, height in surface["openings_mm"]:
            if yy <= y <= yy + height:
                remaining = []
                for a, b in intervals:
                    if x > a:
                        remaining.append([a, min(b, x)])
                    if x + width < b:
                        remaining.append([max(a, x + width), b])
                intervals = [[a, b] for a, b in remaining if b > a]
        z0, z1 = surface["z_min_mm"], surface["z_min_mm"] + surface["thickness_mm"]
        for a, b in intervals:
            shapes.append(_path([polygon([[a, z0], [b, z0], [b, z1], [a, z1]])], surface["id"], fill=[181, 198, 224]))
    vertical = [item for item in projection["layers"] + projection.get("surface_layers", [])]
    section_bounds = [bounds[0], min(item["z_min_mm"] for item in vertical), bounds[2],
                      max(item["z_min_mm"] + item["thickness_mm"] for item in vertical)]
    return shapes, section_bounds, 1, "실제 X-Z 절단면 / Y=" + format(y, ".9g") + " mm / 두께 과장 없음"


def _view(data, option):
    """! @brief 선택 층의 실제 단면과 알려진 관통 구멍만 투영한다."""
    projection = data["projection"]
    bounds = board_bounds(projection["board"])
    layers = {layer["id"]: layer for layer in projection["layers"]}
    vias = [shape for shape in projection["shapes"] if shape["kind"] == "via"]
    shapes, mirror, label = [], 1, "기판 외형"
    if option["kind"] == "stackup":
        return _section(data, vias, bounds)
    if option["kind"] in ("layer", "detail"):
        layer_id = option["layer_id"]
        if layer_id not in layers:
            fail("선택한 도면 층이 고정 스냅샷에 없습니다.", "options.views.layer_id", "E_REFERENCE")
        layer = layers[layer_id]
        selected = [shape for shape in projection["shapes"] if shape["layer_id"] == layer_id and shape["kind"] != "via"]
        conductors = sorted((item for item in layers.values() if item["role"] == "conductor"), key=lambda item: item["z_min_mm"])
        bottom = len(conductors) > 1 and layer_id == conductors[0]["id"]
        mirror = -1 if bottom and data["options"]["mode"] == "drawing" else 1
        label = layer["name"] + (" / 뒤면에서 봄 / X 반전" if mirror < 0 else " / 위에서 봄")
        for shape in selected:
            shapes.append(_path(_drilled(shape_loops(shape), vias, shape["id"]), shape["id"], layer_id, shape["net_id"]))
        if layer["role"] == "dielectric":
            shapes.insert(0, _path(_drilled(board_loops(projection["board"]), vias, projection["board"]["id"]),
                                   projection["board"]["id"], layer_id, fill=[214, 233, 218]))
        for via in vias:
            lower = min(layers[via["layer_id"]]["z_min_mm"], layers[via["end_layer_id"]]["z_min_mm"])
            upper = max(layers[via["layer_id"]]["z_min_mm"], layers[via["end_layer_id"]]["z_min_mm"])
            if lower <= layer["z_min_mm"] <= upper:
                shapes.append(_path(shape_loops(via), via["id"], layer_id, via["net_id"]))
    elif option["kind"] != "outline":
        fail("지원하지 않는 도면 뷰입니다.", "options.views")
    if data["options"]["mode"] == "drawing" or option["kind"] == "outline":
        shapes.insert(0, _path(board_loops(projection["board"]), projection["board"]["id"], fill=None))
    if option["kind"] == "detail":
        bounds = [number(value) for value in option["bounds_mm"]]
        label = option["label"] + " / 명시 영역 상세 / " + label
    return shapes, bounds, mirror, label


def _page(width, height):
    """! @brief 고정 용지와 최종 종이좌표 벡터를 함께 담는다."""
    return {"width_mm": width, "height_mm": height, "view_box_mm": [0, 0, width, height],
            "viewports": [], "primitives": [], "title_rows": [], "notes": []}


def layout(data):
    """! @brief 축척을 자동 변경하지 않는 읽기 전용 최종 용지 배열을 반환한다."""
    if data.get("profile") != PROFILE or data.get("schema") != "rfad.exchange-input/0.1":
        fail("지원하지 않는 기술도면 입력입니다.", "profile")
    options, projection = data["options"], data["projection"]
    scale = number(options["scale"], "options.scale", True)
    if not 0.01 <= scale <= 100 or not 1 <= len(options["views"]) <= 8:
        fail("축척 또는 뷰 수가 출력 profile 상한을 벗어났습니다.", "options", "E_RESOURCE")
    if options["mode"] not in ("drawing", "fabrication_geometry"):
        fail("도면과 제조 형상 모드를 명시하십시오.", "options.mode")
    fabrication = options["mode"] == "fabrication_geometry"
    if fabrication and (scale != 1 or options["notes"] or options["dimensions"] or len(options["views"]) != 1
                        or options["views"][0]["kind"] not in ("layer", "outline") or data["format"] == "pdf"):
        fail("제조 형상은 단일 층/외형의 1:1 SVG 또는 DXF이며 주석을 포함하지 않습니다.", "options")
    size = {"A4": [210.0, 297.0], "A3": [297.0, 420.0]}.get(options["sheet"])
    if size is None or options["orientation"] not in ("portrait", "landscape"):
        fail("용지와 방향을 명시하십시오.", "options")
    width, height = sorted(size, reverse=options["orientation"] == "landscape")
    pages = []
    for option in options["views"]:
        shapes, bounds, mirror, label = _view(data, option)
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            fail("도면 영역의 폭과 높이는 양수여야 합니다.", "options.views", "E_GEOMETRY")
        if fabrication:
            page = _page(bounds[2] - bounds[0], bounds[3] - bounds[1])
            page["view_box_mm"] = [bounds[0], bounds[1], page["width_mm"], page["height_mm"]]
            page["primitives"] = shapes
            for primitive in shapes:
                if primitive["fill"] is not None:
                    primitive["stroke"] = None
                    primitive["stroke_width_mm"] = 0
            page["viewports"] = [{"rect_mm": deepcopy(page["view_box_mm"]), "world_bounds_mm": bounds,
                                  "label": label, "transform": {"scale": 1, "x_mm": 0, "y_mm": 0, "mirror_x": False},
                                  "dimensions": [], "primitives": []}]
            pages.append(page)
            continue
        page = _page(width, height)
        primitives = page["primitives"]
        rect = [12.0, 54.0, width - 96.0, height - 76.0]
        actual_width, actual_height = (bounds[2] - bounds[0]) * scale, (bounds[3] - bounds[1]) * scale
        if actual_width > rect[2] - 8 or actual_height > rect[3] - 8:
            fail("지정 축척에서 형상이 용지를 벗어납니다. 용지, 축척 또는 상세 영역을 명시적으로 바꾸십시오.", "options.scale", "E_RESOURCE")
        x = rect[0] + rect[2] / 2 - mirror * scale * (bounds[0] + bounds[2]) / 2
        y = rect[1] + rect[3] / 2 - scale * (bounds[1] + bounds[3]) / 2
        ids = {shape["source_id"] for shape in shapes}
        dimensions = _dimension_rows(data, ids) if options["dimensions"] else []
        page["viewports"] = [{"rect_mm": rect, "world_bounds_mm": bounds, "label": label,
                              "transform": {"scale": scale, "x_mm": x, "y_mm": y, "mirror_x": mirror < 0},
                              "dimensions": dimensions, "primitives": []}]
        for shape in shapes:
            rendered = deepcopy(shape)
            rendered["loops"] = [[_transform_edge(edge, scale, x, y, mirror) for edge in loop] for loop in shape["loops"]]
            if option["kind"] == "detail":
                rendered["clip_rect_mm"] = [min(x + mirror * scale * bounds[0], x + mirror * scale * bounds[2]),
                                            y + scale * bounds[1], actual_width, actual_height]
            primitives.append(rendered)
        primitives.extend([_text(12, height - 13, label, 4),
                           _rule([12, height - 18], [width - 12, height - 18], BLUE),
                           _rule([width - 78, 54], [width - 78, height - 22], [177, 187, 199])])
        # 실제 50 mm의 종이 길이를 축척과 함께 표시하고 자동 축소하지 않는다.
        bar_length = 50 * scale
        if bar_length > rect[2] - 12:
            fail("50 mm 축척 막대가 용지를 벗어납니다. 축척 또는 용지를 바꾸십시오.", "options.scale", "E_RESOURCE")
        primitives.extend([_rule([16, 48], [16 + bar_length, 48], width=0.35),
                           _rule([16, 46.5], [16, 49.5]), _rule([16 + bar_length, 46.5], [16 + bar_length, 49.5]),
                           _text(16, 42, "50 mm / 모델 길이", 2.8),
                           _text(width - 74, height - 27, "연관 치수 / 원본 값", 3.2)])
        # 기준축은 미러 방향을 명시하고 실제 기하 형상과 분리된 주석으로 남긴다.
        ax, ay = 20.0, height - 32
        primitives.extend([_rule([ax, ay], [ax + 9 * mirror, ay], BLUE), _rule([ax, ay], [ax, ay + 7], BLUE),
                           _text(ax + 10 * mirror, ay - 1, "+X", 2.5), _text(ax - 2, ay + 8, "+Z" if option["kind"] == "stackup" else "+Y", 2.5)])
        note_rows = []
        if option["kind"] == "stackup" and options["dimensions"]:
            for layer in projection["layers"]:
                note_rows.append(layer["name"] + ": z=" + format(layer["z_min_mm"], ".9g") + " mm, t=" + format(layer["thickness_mm"], ".9g") + " mm")
        elif options["dimensions"]:
            original_bounds = board_bounds(projection["board"])
            note_rows += ["외형 X 범위: " + format(original_bounds[2] - original_bounds[0], ".9g") + " mm",
                          "외형 Y 범위: " + format(original_bounds[3] - original_bounds[1], ".9g") + " mm"]
            if projection["board"].get("kind") == "circle":
                note_rows.append("기판 반지름: " + format(projection["board"]["radius_mm"], ".9g") + " mm")
        note_rows += [row["text"] for row in dimensions]
        if not note_rows:
            note_rows = ["선택한 연관 치수가 없습니다." if options["dimensions"] else "치수 주석 끔"]
        lines = [line_text for text in note_rows for line_text in _wrapped(text, 63, 2.8)]
        capacity = max(1, int((height - 90) / 4.4))
        for index, text in enumerate(lines[:capacity]):
            primitives.append(_text(width - 74, height - 34 - index * 4.4, text, 2.8))
        pages.append(page)
        # 연관된 선 길이/반지름에는 실제 두 기준점을 잇는 읽기 전용 치수선을 둔다.
        drawn = set()
        if option["kind"] not in ("stackup", "detail"):
            for row in dimensions:
                if drawn or len(row["anchors_mm"]) != 2 or row["unit"] != "mm" or row["value"] is None:
                    continue
                a, b = [[x + mirror * scale * p[0], y + scale * p[1]] for p in row["anchors_mm"]]
                if not all(rect[0] <= p[0] <= rect[0] + rect[2] and rect[1] <= p[1] <= rect[1] + rect[3] for p in [a, b]):
                    continue
                drawn.add(row["source_id"])
                delta = 3.0
                start, end = [a[0], a[1] + delta], [b[0], b[1] + delta]
                primitives.extend([_rule(a, start, BLUE), _rule(b, end, BLUE), _rule(start, end, BLUE),
                                   _text((start[0] + end[0]) / 2, max(start[1], end[1]) + 1.5,
                                         format(row["value"], ".9g") + " mm", 2.5, "center", source_id=row["source_id"],
                                         dimension_key=row["dimension_key"])])
        for primitive in primitives:
            if primitive.get("source_id") and primitive["role"] == "geometry":
                primitive["source_name"] = data["names"].get(primitive["source_id"], "")
        for offset in range(capacity, len(lines), capacity):
            continuation = _page(width, height)
            continuation["primitives"].append(_text(12, height - 13, label + " / 연관 치수 계속", 4))
            for index, text in enumerate(lines[offset:offset + capacity]):
                continuation["primitives"].append(_text(14, height - 30 - index * 4.4, text, 2.8))
            pages.append(continuation)
    if len(pages) > MAX_PAGES:
        fail("도면이 최대 32쪽을 초과했습니다. 원문을 생략하지 않습니다.", code="E_RESOURCE")
    if not fabrication:
        for index, page in enumerate(pages):
            w, h = page["width_mm"], page["height_mm"]
            name = projection["source_semantics"]["metadata"]["name"]
            title = ["TraceWave Studio / " + name,
                     "축척 " + format(scale, ".9g") + ":1 / 단위 mm / " + options["sheet"] + " / " + str(index + 1) + "/" + str(len(pages)),
                     "개정 " + projection["revision_id"], "스냅샷 " + data["snapshot"]["content_hash"]]
            page["title_rows"] = [{"label": "원본", "value": text} for text in title]
            page["primitives"].append(_rule([12, 38], [w - 12, 38], BLUE))
            for line_index, text in enumerate(title):
                page["primitives"].append(_text(12, 32 - line_index * 5, text, 2.6))
            if options["notes"]:
                note = "제작/측정 조건: 원문 확인, 미기록 값은 미정 / CAD 수치 공차 " + format(projection["tolerance_mm"], ".9g") + " mm"
                page["notes"] = [note, "출력 형식 검사는 RF 성능 또는 제작 적합성 검증이 아닙니다."]
                page["primitives"].append(_text(12, 7, note, 2.5))
    if sum(len(page["primitives"]) for page in pages) > MAX_PRIMITIVES:
        fail("도면 벡터 수가 유한 자원 상한을 초과했습니다.", code="E_RESOURCE")
    def finite(value):
        if type(value) is dict:
            for item in value.values():
                finite(item)
        elif type(value) is list:
            for item in value:
                finite(item)
        elif type(value) in (int, float):
            number(value)
    finite(pages)
    return pages
