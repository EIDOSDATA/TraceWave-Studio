"""! @brief 고정 CAD 투영에서 GUI와 교환 파일이 공유하는 mm 기술도면을 만든다.

@details 외부 그래픽 패키지, 파일 IO, 프로젝트 변경 없이 해석형 경계를 유지한다.
도면 주석과 제조 형상을 분리하며 제작 공차나 미정 치수를 생성하지 않는다.
"""

from copy import deepcopy
import math
import re

from rfad.domain.errors import ProjectError
from rfad.domain.curve_boolean import difference
from rfad.domain import drawing_annotations, drawing_dimension_placement


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
    if board.get("kind") == "polygon":
        points = [point(value) for value in board["outer_mm"]]
        return [min(value[0] for value in points), min(value[1] for value in points),
                max(value[0] for value in points), max(value[1] for value in points)]
    return [0.0, 0.0, number(board["width_mm"], positive=True), number(board["height_mm"], positive=True)]


def board_loops(board):
    """! @brief 사각/원형/직선 다각형 외곽을 정확한 원시 도형으로 만든다."""
    if board.get("kind") == "circle":
        return [[arc(point(board["center_mm"]), number(board["radius_mm"], positive=True))]]
    if board.get("kind") == "polygon":
        return [polygon([point(value) for value in board["outer_mm"]])]
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
                if abs(edge["sweep_deg"]) == 360:
                    # @brief 완전한 원은 시작각의 부동소수점 오차 없이 홀수 교차 여부를 판정한다.
                    if math.hypot(x - cx, y - cy) < edge["radius"]:
                        crossings += 1
                    continue
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


def mechanical_loops(shape, offset=0.0):
    """! @brief 기계 원본의 완성 치수와 도금 offset을 해석형 경계로 만든다."""
    kind = shape["kind"]
    if kind == "circle":
        return [[arc(point(shape["center_mm"]), number(shape["diameter_mm"], positive=True) / 2 + offset)]]
    if kind == "capsule":
        center = point(shape["center_mm"])
        length, width = number(shape["finished_length_mm"], positive=True), number(shape["finished_width_mm"], positive=True)
        if length - width < 1e-5:
            fail("슬롯 전체 길이는 폭보다 최소 길이만큼 커야 합니다.", code="E_GEOMETRY")
        angle = number(shape["rotation_deg"])
        return shape_loops({"kind": "line_path", "start_mm": polar(center, (length - width) / 2, angle + 180),
                            "end_mm": polar(center, (length - width) / 2, angle), "width_mm": width + 2 * offset})
    if offset:
        fail("이 기계 경계의 도금 offset은 지원하지 않습니다.")
    if kind == "polygon":
        return [polygon([point(p) for p in loop]) for loop in [shape["outer_mm"], *shape.get("holes_mm", [])]]
    if kind == "rectangle":
        return shape_loops({"kind": "pad", "pad_shape": "rectangle", "center_mm": shape["center_mm"],
                            "size_mm": shape["size_mm"], "rotation_deg": shape["rotation_deg"]})
    fail("지원하지 않는 기계 절삭 경계입니다.")


def _mechanical_removed(loops, projection, *, surface_id=None, outline_only=False):
    """! @brief 실제 절삭 뒤 연결 성분과 원호를 도면에서도 유지한다."""
    data = projection.get("mechanical", {})
    records = [(item, False) for item in data.get("cutouts", [])]
    if not outline_only:
        records += [(item, True) for item in data.get("holes", [])]
    result = loops
    for item, hole in records:
        if surface_id is not None and surface_id not in item["surface_cut_ids"]:
            continue
        offset = 0.0
        if hole:
            plating = item["plating"]
            if plating["state"] not in ("plated", "unplated"):
                fail("도금 여부가 미정인 기계 홀을 도면에서 추정하지 않습니다.")
            if plating["state"] == "plated" and surface_id is None:
                offset = number(plating["thickness_mm"], positive=True)
        result = difference(result, mechanical_loops(item["shape"], offset), _inside)
        if not result:
            fail("기계 절삭으로 도면의 원본 재료 전체가 제거됩니다. 명시적인 형상 수정을 검토하십시오.", code="E_GEOMETRY")
    return result


def _plated_mechanical(projection):
    """! @brief 기본 적층을 관통하는 명시 도금 shell만 반환한다."""
    return [item for item in projection.get("mechanical", {}).get("holes", []) if item["plating"]["state"] == "plated"]


def mechanical_shell(item):
    """! @brief 완성 홀과 외부 도금 경계가 만든 중공 단면을 보존한다."""
    return mechanical_loops(item["shape"], number(item["plating"]["thickness_mm"], positive=True)) + mechanical_loops(item["shape"])


def copper_loops(projection, shape):
    """! @brief 도면/CAM이 같은 실제 비아와 기계 절삭 후 도체 경계를 사용한다."""
    if shape["kind"] == "via":
        return shape_loops(shape)
    vias = [item for item in projection["shapes"] if item["kind"] == "via"]
    return _mechanical_removed(_drilled(shape_loops(shape), vias, shape["id"]), projection)


def substrate_loops(projection, *, outline_only=False):
    """! @brief 외곽/기판 절삭과 실제 적층의 관통 제거를 구분해 반환한다."""
    loops = board_loops(projection["board"])
    if not outline_only:
        vias = [item for item in projection["shapes"] if item["kind"] == "via"]
        loops = _drilled(loops, vias, projection["board"]["id"])
    return _mechanical_removed(loops, projection, outline_only=outline_only)


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
            add(_mechanical_removed(_drilled(board_loops(projection["board"]), vias, projection["board"]["id"]), projection), layer["z_min_mm"],
                layer["thickness_mm"], layer["id"], layer["id"], None, [214, 233, 218])
    for shape in projection["shapes"]:
        layer = layers[shape["layer_id"]]
        if shape["kind"] == "via":
            ends = [layer, layers[shape["end_layer_id"]]]
            lower = min(item["z_min_mm"] for item in ends)
            upper = max(item["z_min_mm"] + item["thickness_mm"] for item in ends)
            add(shape_loops(shape), lower, upper - lower, shape["id"], None, shape["net_id"], COPPER)
        else:
            add(_mechanical_removed(_drilled(shape_loops(shape), vias, shape["id"]), projection), layer["z_min_mm"], layer["thickness_mm"],
                shape["id"], layer["id"], shape["net_id"], COPPER)
    for item in _plated_mechanical(projection):
        lower = min(layer["z_min_mm"] for layer in layers.values())
        upper = max(layer["z_min_mm"] + layer["thickness_mm"] for layer in layers.values())
        add(mechanical_shell(item), lower, upper - lower, item["id"], None, item["plating"]["net_id"], COPPER)
    for surface in projection.get("surface_layers", []):
        if surface["coverage"] == "board":
            loops = board_loops(projection["board"])
        else:
            x, yy, width, height = surface["rectangle_mm"]
            loops = [polygon([[x, yy], [x + width, yy], [x + width, yy + height], [x, yy + height]])]
        intervals = _section_intervals(_mechanical_removed(loops, projection, surface_id=surface["id"]), y)
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
            shapes.append(_path(_mechanical_removed(_drilled(shape_loops(shape), vias, shape["id"]), projection), shape["id"], layer_id, shape["net_id"]))
        if layer["role"] == "dielectric":
            shapes.insert(0, _path(_mechanical_removed(_drilled(board_loops(projection["board"]), vias, projection["board"]["id"]), projection),
                                   projection["board"]["id"], layer_id, fill=[214, 233, 218]))
        for via in vias:
            lower = min(layers[via["layer_id"]]["z_min_mm"], layers[via["end_layer_id"]]["z_min_mm"])
            upper = max(layers[via["layer_id"]]["z_min_mm"], layers[via["end_layer_id"]]["z_min_mm"])
            if lower <= layer["z_min_mm"] <= upper:
                shapes.append(_path(shape_loops(via), via["id"], layer_id, via["net_id"]))
        for item in _plated_mechanical(projection):
            shapes.append(_path(mechanical_shell(item), item["id"], layer_id, item["plating"]["net_id"]))
    elif option["kind"] != "outline":
        fail("지원하지 않는 도면 뷰입니다.", "options.views")
    if data["options"]["mode"] == "drawing" or option["kind"] == "outline":
        shapes.insert(0, _path(_mechanical_removed(board_loops(projection["board"]), projection, outline_only=True), projection["board"]["id"], fill=None))
    if option["kind"] == "detail":
        bounds = [number(value) for value in option["bounds_mm"]]
        label = option["label"] + " / 명시 영역 상세 / " + label
    return shapes, bounds, mirror, label


def _page(width, height):
    """! @brief 고정 용지와 최종 종이좌표 벡터를 함께 담는다."""
    return {"width_mm": width, "height_mm": height, "view_box_mm": [0, 0, width, height],
            "viewports": [], "primitives": [], "title_rows": [], "notes": []}


def _dimension_line(primitives, a, b, metadata):
    """! @brief 영거리선을 생략하고 치수 끝을 종이 크기의 짧은 획으로 표시한다."""
    length = math.dist(a, b)
    if length <= 1e-7:
        return
    perpendicular = [(a[1] - b[1]) / length, (b[0] - a[0]) / length]
    primitives.append(_rule(a, b, BLUE, **metadata))
    for point in (a, b):
        primitives.append(_rule([coordinate - 0.8 * normal for coordinate, normal in zip(point, perpendicular)],
                                [coordinate + 0.8 * normal for coordinate, normal in zip(point, perpendicular)],
                                BLUE, **metadata))


def _reference_layout(primitives, rows, holes, report, transform, bounds):
    """! @brief 선택 뷰의 실제 기준점에 도면 주석과 확인용 치수 목록을 놓는다."""
    x, y, scale, mirror = transform

    def paper(point):
        """! @brief 모델의 치수 기준점에 형상과 같은 축척과 뒤면 방향을 적용한다."""
        return [x + mirror * scale * point[0], y + scale * point[1]]

    def cross(point, radius, **metadata):
        """! @brief 원본 형상에 영향을 주지 않는 홀 중심 또는 기준 마크를 그린다."""
        px, py = point
        primitives.append(_rule([px - radius, py], [px + radius, py], BLUE, **metadata))
        primitives.append(_rule([px, py - radius], [px, py + radius], BLUE, **metadata))

    def inside(point):
        """! @brief 뷰 밖 기준은 수치만 유지하고 용지 바깥으로 치수선을 그리지 않는다."""
        return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]

    datum = report["datum_mm"]
    rows_text = [drawing_annotations.STYLES[report["style"]] + " / 모델 mm"]
    if datum is not None:
        rows_text.append("기준점 X " + format(datum[0], ".9g") + ", Y " + format(datum[1], ".9g"))
        if inside(datum):
            where = paper(datum)
            cross(where, 2.2)
            primitives.append(_text(where[0] + 2.6, where[1] - 2, "0", 2.1))
    marked = set()
    counters = {"linear": 0, "radial": 0}
    x0, y0, x1, y1 = bounds
    for row in rows:
        kind, number_value = row["kind"], row["value"]
        meta = {"source_id": row["source_id"], "dimension_key": row["dimension_key"]}
        title = row["title"]
        if kind == "hole":
            a, b = map(paper, row["anchors_mm"])
            if report["style"] != "ordinate" and inside(row["anchors_mm"][0]):
                elbow = [b[0], a[1]]
                _dimension_line(primitives, a, elbow, meta)
                _dimension_line(primitives, elbow, b, meta)
            cross(b, 1.35, **meta)
            primitives.append(_text(b[0] + 1.7, b[1] + 1.3, title.split(" / ")[0], 2.25, **meta))
            marked.add(row["source_id"])
            rows_text.append(title + "  X " + format(number_value[0], ".9g") + ", Y " + format(number_value[1], ".9g") + " mm")
            continue
        actual = format(number_value, ".9g") + " " + row["unit"]
        if kind in ("board_x", "board_y"):
            a, b = map(paper, row["anchors_mm"])
            if kind == "board_x":
                height = paper([x0, y1])[1] + 4
                p, q = [a[0], height], [b[0], height]
                label, align = [(p[0] + q[0]) / 2, height + 1.5], "center"
            else:
                left = min(paper([x0, y0])[0], paper([x1, y0])[0]) - 4
                p, q = [left, a[1]], [left, b[1]]
                label, align = [left + 1.8, (p[1] + q[1]) / 2], "left"
            for start, end in ((a, p), (b, q)):
                if math.dist(start, end) > 1e-7:
                    primitives.append(_rule(start, end, BLUE, **meta))
            _dimension_line(primitives, p, q, meta)
            primitives.append(_text(*label, actual, 2.35, align, **meta))
        elif kind in counters and all(inside(point) for point in row["anchors_mm"]):
            a, b = map(paper, row["anchors_mm"])
            counters[kind] += 1
            mark = ("R" if kind == "radial" else "D") + str(counters[kind])
            if kind == "linear":
                length = math.dist(a, b)
                if length > 1e-7:
                    normal = [(b[1] - a[1]) / length, (a[0] - b[0]) / length]
                    p, q = [[coordinate + 3 * direction for coordinate, direction in zip(point, normal)] for point in (a, b)]
                    primitives.extend([_rule(a, p, BLUE, **meta), _rule(b, q, BLUE, **meta)])
                    a, b = p, q
            _dimension_line(primitives, a, b, meta)
            primitives.append(_text((a[0] + b[0]) / 2 + 1.4, (a[1] + b[1]) / 2 + 1.6, mark, 2.3, **meta))
            title = mark + " " + title
        rows_text.append(title + " = " + actual)
    for row in holes:
        if row["id"] not in marked and row["center"] is not None:
            where = paper(row["center"])
            cross(where, 1.35, source_id=row["id"])
            primitives.append(_text(where[0] + 1.7, where[1] + 1.3, row["mark"], 2.25, source_id=row["id"]))
    return rows_text


def _aligned_reference_layout(primitives, rows, holes, report, transform, bounds, rect, pins):
    """! @brief 모델 앵커는 고정한 채 배치한 모든 치수선을 동일한 출력 벡터로 옮긴다."""
    x, y, scale, mirror = transform
    x0, y0, x1, y1 = bounds
    plot = [rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]]

    def paper(p):
        """! @brief 도면에 사용한 좌우 반전과 축척을 기준점에도 적용한다."""
        return [x + mirror * scale * p[0], y + scale * p[1]]

    def in_view(p):
        """! @brief 선택 뷰 밖의 모델 좌표에는 치수선을 만들지 않는다."""
        return x0 <= p[0] <= x1 and y0 <= p[1] <= y1

    def cross(p, radius, **metadata):
        """! @brief 기준과 홀 중심 표식을 지정 위치에서만 그린다."""
        px, py = p
        primitives.append(_rule([px - radius, py], [px + radius, py], BLUE, **metadata))
        primitives.append(_rule([px, py - radius], [px, py + radius], BLUE, **metadata))

    notes = [drawing_annotations.STYLES[report["style"]] + " / 모델 mm"]
    datum = report["datum_mm"]
    fixed_labels = []
    if datum is not None:
        notes.append("기준점 X " + format(datum[0], ".9g") + ", Y " + format(datum[1], ".9g"))
        if in_view(datum):
            origin = paper(datum)
            cross(origin, 2.1)
            location = [origin[0] - 2.5, origin[1] - 3.2]
            primitives.append(_text(*location, "0", 2.1, "center"))
            fixed_labels.append(drawing_dimension_placement.fixed_label(location, "0"))

    groups, marked = [], set()
    counts = {"linear": 0, "radial": 0}
    for row in rows:
        source, key = row["placement_source_id"], row["dimension_key"]
        kind, title = row["kind"], row["title"]
        raw_anchors = row["anchors_mm"]
        anchors = list(map(paper, raw_anchors))
        value = row["value"]
        if kind == "hole":
            label = title.split(" / ")[0]
            notes.append(title + "  X " + format(value[0], ".9g") + ", Y " + format(value[1], ".9g") + " mm")
            center = anchors[-1]
            cross(center, 1.25, source_id=source)
            marked.add(source)
            projected = report["style"] != "ordinate" and in_view(raw_anchors[0])
            preferred = [center[0] + 5, center[1] + 8]
        else:
            label = format(value, ".9g") + " " + row["unit"]
            if kind in counts and all(map(in_view, raw_anchors)):
                counts[kind] += 1
                mark = ("R" if kind == "radial" else "D") + str(counts[kind])
                title = mark + " " + title
                label = mark + " " + label
            notes.append(title + " = " + format(value, ".9g") + " " + row["unit"])
            if kind == "value" or len(anchors) != 2 or not all(map(in_view, raw_anchors)):
                continue
            projected = True
            a, b = anchors
            center = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
            if kind == "board_x":
                preferred = [center[0], paper([x0, y1])[1] + 9]
            elif kind == "board_y":
                preferred = [min(paper([x0, y0])[0], paper([x1, y0])[0]) - 14, center[1]]
            elif kind == "radial":
                preferred = [b[0] + 9, b[1] + 8]
            else:
                preferred = [center[0], center[1] + 7]
        groups.append({"source_id": source, "key": key, "title": title, "label": label,
                       "kind": kind, "anchors": anchors, "projected": projected, "preferred": preferred})

    for row in holes:
        if row["id"] not in marked and row["center"] is not None:
            where = paper(row["center"])
            cross(where, 1.25, source_id=row["id"])
            label = [where[0] + 3, where[1] + 1.6]
            primitives.append(_text(*label, row["mark"], 2.25, "center", source_id=row["id"]))
            fixed_labels.append(drawing_dimension_placement.fixed_label(label, row["mark"]))

    arranged, summary = drawing_dimension_placement.arrange(groups, plot, pins, fixed_labels)
    report["placement"] = summary
    items = []
    for item in arranged:
        meta = {"source_id": item["source_id"], "dimension_key": item["key"]}
        for part, a, b in item["segments"]:
            primitives.append(_rule(a, b, BLUE, width=0.15 if part == "extension" else 0.22,
                                    placement_part=part, **meta))
        primitives.append(_text(*item["point_mm"], item["label"], drawing_dimension_placement.TEXT_HEIGHT, "center",
                                placement_part="label", **meta))
        point, box = item["point_mm"], item["label_box"]
        pin_bounds = [plot[0] + point[0] - box[0] + 0.01, plot[1] + point[1] - box[1] + 0.01,
                      plot[2] + point[0] - box[2] - 0.01, plot[3] + point[1] - box[3] - 0.01]
        items.append({**{key: item[key] for key in ("source_id", "key", "title", "label", "point_mm", "label_box", "pinned")},
                      "pin_bounds_mm": pin_bounds})
    return notes, {"bounds_mm": plot, "items": items}


def _hole_table_pages(holes, datum, width, height):
    """! @brief 개별 홀, 기준 좌표와 미정 공구를 제조 원본에서 그대로 표로 나눈다."""
    def text(value):
        """! @brief 주어지지 않은 공구 크기와 좌표는 미정으로 표시한다."""
        return "미정" if value is None else format(value, ".9g")

    pages = []
    columns = [14, 29, 59, 85, 111, 140, 166]
    headings = ["기호", "형상", "X (mm)", "Y (mm)", "완성 (mm)", "공구 (mm)", "도금"]
    kinds = {"circle": "원형", "slot": "슬롯", "via": "비아"}
    states = {"unplated": "비도금", "plated": "도금"}
    capacity = max(1, int((height - 95) / 6))
    for offset in range(0, max(1, len(holes)), capacity):
        page = _page(width, height)
        primitives = page["primitives"]
        page["page_role"] = "hole_table"
        primitives.append(_text(14, height - 15, "홀 표", 4))
        coordinate_label = "기준점 확인 필요" if datum is None else "기판 기준점 X " + text(datum[0]) + ", Y " + text(datum[1]) + " mm"
        primitives.append(_text(14, height - 24, coordinate_label + " / 중심 좌표는 기준점 대비", 2.8))
        primitives.append(_text(14, height - 31, "슬롯 완성 치수는 폭 x 전체 길이 / 각 행의 수량은 1", 2.7))
        for x, heading in zip(columns, headings):
            primitives.append(_text(x, height - 41, heading, 2.8))
        primitives.append(_rule([12, height - 43], [width - 12, height - 43], BLUE))
        if not holes:
            primitives.append(_text(14, height - 50, "이 뷰에 표시할 홀이 없습니다.", 2.8))
        for index, row in enumerate(holes[offset:offset + capacity]):
            coords = [None, None] if datum is None or row["center"] is None else [c - d for c, d in zip(row["center"], datum)]
            size = text(row["finished"]) if row["length"] is None else text(row["finished"]) + " x " + text(row["length"])
            fields = [row["mark"], kinds.get(row["kind"], row["kind"]), *map(text, coords), size, text(row["tool"]),
                      states.get(row["plating"], "미정")]
            for x, field in zip(columns, fields):
                primitives.append(_text(x, height - 49 - 6 * index, field, 2.55, source_id=row["id"]))
        pages.append(page)
    return pages


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
    if fabrication and ("annotations" in options or scale != 1 or options["notes"] or options["dimensions"] or len(options["views"]) != 1
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
        if options["dimensions"]:
            mechanical = projection.get("mechanical", {})
            ids.update(item["id"] for item in mechanical.get("cutouts", []))
            if option["kind"] != "outline":
                ids.update(item["id"] for item in mechanical.get("holes", []))
        annotation = options.get("annotations")
        active = annotation is not None and annotation["view"] == option
        dimensions = _dimension_rows(data, ids) if options["dimensions"] and not active else []
        holes = []
        if active:
            rows, holes, report = drawing_annotations.evaluation(data, option, bounds, ids)
            page["annotation_review"] = report
            dimensions = rows
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
                           _text(width - 74, height - 27, "참조 치수" if active else "연관 치수 / 원본 값", 3.2)])
        # 기준축은 미러 방향을 명시하고 실제 기하 형상과 분리된 주석으로 남긴다.
        ax, ay = 20.0, height - 32
        primitives.extend([_rule([ax, ay], [ax + 9 * mirror, ay], BLUE), _rule([ax, ay], [ax, ay + 7], BLUE),
                           _text(ax + 10 * mirror, ay - 1, "+X", 2.5), _text(ax - 2, ay + 8, "+Z" if option["kind"] == "stackup" else "+Y", 2.5)])
        note_rows = []
        if active and "placement" in annotation:
            view_id = option.get("layer_id", option["kind"])
            pins = [row for row in annotation["placement"]["pins"] if row["view_id"] == view_id]
            note_rows, placements = _aligned_reference_layout(primitives, dimensions, holes if annotation["hole_table"] else [],
                                                               report, (x, y, scale, mirror), bounds, rect, pins)
            page["dimension_placements"] = placements
        elif active:
            note_rows = _reference_layout(primitives, dimensions, holes if annotation["hole_table"] else [],
                                          report, (x, y, scale, mirror), bounds)
        elif option["kind"] == "stackup" and options["dimensions"]:
            for layer in projection["layers"]:
                note_rows.append(layer["name"] + ": z=" + format(layer["z_min_mm"], ".9g") + " mm, t=" + format(layer["thickness_mm"], ".9g") + " mm")
        elif options["dimensions"]:
            original_bounds = board_bounds(projection["board"])
            note_rows += ["외형 X 범위: " + format(original_bounds[2] - original_bounds[0], ".9g") + " mm",
                          "외형 Y 범위: " + format(original_bounds[3] - original_bounds[1], ".9g") + " mm"]
            if projection["board"].get("kind") == "circle":
                note_rows.append("기판 반지름: " + format(projection["board"]["radius_mm"], ".9g") + " mm")
        if not active:
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
        if not active and option["kind"] not in ("stackup", "detail"):
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
        if active and annotation["hole_table"]:
            pages.extend(_hole_table_pages(holes, report["datum_mm"], width, height))
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


def pcb_layer_targets(projection, format_name, layer_ids=None):
    """! @brief GUI 검토와 writer가 같은 명시 층 대응을 공유하며 없는 층을 만들지 않는다."""
    if format_name in ("kicad_pcb", "kicad_mod"):
        copper = sorted((row for row in projection["layers"] if row["role"] == "conductor"), key=lambda row: row["z_min_mm"], reverse=True)
        if not 2 <= len(copper) <= 32 or len(copper) % 2:
            raise ProjectError("E_UNSUPPORTED", "KiCad 교환은 짝수 2~32개 명시 구리층을 지원합니다.")
        names = ["F.Cu", *["In" + str(index) + ".Cu" for index in range(1, len(copper) - 1)], "B.Cu"]
        output = {row["id"]: name for row, name in zip(copper, names)}
        for row in projection.get("artwork_layers", []):
            if row["use_state"] == "used":
                output[row["id"]] = ("F." if row["side"] == "top" else "B.") + ("Mask" if row["role"] == "solder_mask" else "Paste")
        return output
    return {identity: "layer-" + str(index + 1).zfill(2) + ".gbr" for index, identity in enumerate(layer_ids or [])}
