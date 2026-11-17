"""! @brief writer의 문자열 생성기를 재사용하지 않고 출력 파일의 실제 좌표를 검사한다.

@details DXF는 같은 ezdxf 라이브러리의 별도 읽기 경로이다. 이 검사는 다른 CAD
커널이나 제조 수신 도구에서의 독립 수용을 뜻하지 않는다.
"""

from copy import copy
import math
import re
import xml.etree.ElementTree as ET

from rfad.domain.drawing_layout import fail


EPSILON = 1e-6
PDF_EPSILON_MM = 1e-4


def require(condition, message):
    """! @brief 실제 파일과 검토된 벡터가 다르면 패키지 게시를 차단한다."""
    if not condition:
        fail(message, "exchange.readback", "E_HASH")


def close(a, b, tolerance=EPSILON):
    """! @brief 숫자와 좌표를 NaN 허용 없이 절대 mm 공차로 대조한다."""
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tolerance) for x, y in zip(a, b))
    return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tolerance


def _point(center, radius, angle):
    """! @brief writer와 독립된 원주 끝점 산술을 사용한다."""
    radians = angle * math.pi / 180
    return [center[0] + radius * math.cos(radians), center[1] + radius * math.sin(radians)]


def _normalized(loop):
    """! @brief 360도 원과 SVG의 두 반원을 동등한 해석형 경계로 대조한다."""
    result = []
    for edge in loop:
        if edge["kind"] == "line":
            result.append(edge)
        else:
            count = int(math.ceil(abs(edge["sweep_deg"]) / 180))
            for index in range(count):
                result.append({**edge, "start_deg": edge["start_deg"] + index * edge["sweep_deg"] / count,
                               "sweep_deg": edge["sweep_deg"] / count})
    return result


def _edges_equal(expected, actual):
    """! @brief 시작점/끝점/중점/원 중심으로 원호 방향과 큰 호 선택까지 검증한다."""
    expected = _normalized(expected)
    require(len(expected) == len(actual), "출력 경계의 실제 선/원호 수가 다릅니다.")
    for left, right in zip(expected, actual):
        require(left["kind"] == right["kind"], "원호가 다른 형상으로 바뀌었습니다.")
        if left["kind"] == "line":
            require(close(left["start"], right["start"]) and close(left["end"], right["end"]), "직선 끝점이 원본과 다릅니다.")
        else:
            require(close(left["center"], right["center"]) and close(left["radius"], right["radius"]), "원호 중심 또는 반지름이 원본과 다릅니다.")
            require(close(left["sweep_deg"], right["sweep_deg"], 1e-5), "원호 방향 또는 회전량이 다릅니다.")
            require(close(_point(left["center"], left["radius"], left["start_deg"]),
                          _point(right["center"], right["radius"], right["start_deg"])), "원호 시작점이 다릅니다.")


def _svg_loops(value):
    """! @brief 명시 프로파일의 실제 SVG M/L/A/Z 문법을 별도로 해석한다."""
    tokens = re.findall(r"[MLAZ]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?", value)
    require(re.sub(r"[\s,]", "", value) == "".join(tokens), "지원 범위 밖 SVG 경로 명령이 있습니다.")
    loops, current, position, origin, index = [], [], None, None, 0
    while index < len(tokens):
        command = tokens[index]
        index += 1
        count = {"M": 2, "L": 2, "A": 7, "Z": 0}.get(command)
        require(count is not None and index + count <= len(tokens), "SVG 경로 문법이 잘못되었습니다.")
        values = [float(item) for item in tokens[index:index + count]]
        index += count
        require(all(math.isfinite(item) for item in values), "SVG 좌표가 유한하지 않습니다.")
        if command == "M":
            require(not current, "SVG 폐곡선이 닫히지 않았습니다.")
            position, origin = values, values
        elif command == "L":
            current.append({"kind": "line", "start": position, "end": values})
            position = values
        elif command == "A":
            rx, ry, rotation, large, direction, ex, ey = values
            require(rx > 0 and rx == ry and rotation == 0 and large == 0 and direction in (0, 1), "원형 해석 경계가 변경되었습니다.")
            end = [ex, ey]
            dx, dy = end[0] - position[0], end[1] - position[1]
            chord = math.hypot(dx, dy)
            require(chord > 0 and chord <= 2 * rx + EPSILON, "SVG 원호의 현 길이가 잘못되었습니다.")
            arithmetic = 64 * max(math.ulp(value) for value in [*position, *end, rx])
            semicircle = abs(chord - 2 * rx) <= arithmetic
            height = 0.0 if semicircle else math.sqrt(max(0.0, rx * rx - chord * chord / 4))
            side = 1 if direction else -1
            center = [(position[0] + ex) / 2 - side * dy / chord * height,
                      (position[1] + ey) / 2 + side * dx / chord * height]
            start = math.degrees(math.atan2(position[1] - center[1], position[0] - center[0]))
            sweep = side * (180 if semicircle else math.degrees(2 * math.asin(min(1.0, chord / (2 * rx)))))
            current.append({"kind": "arc", "center": center, "radius": rx, "start_deg": start, "sweep_deg": sweep})
            position = end
        else:
            require(current and close(position, origin), "SVG 내부 경계의 끝점이 닫히지 않았습니다.")
            loops.append(current)
            current = []
    require(not current, "SVG의 마지막 경계가 열려 있습니다.")
    return loops


def read_svg(path, page):
    """! @brief physical mm/viewBox/축 반전과 실제 선, 호, 구멍, 텍스트를 검사한다."""
    raw = path.read_bytes()
    require(b"<!DOCTYPE" not in raw and b"<!ENTITY" not in raw, "SVG 외부 참조는 지원하지 않습니다.")
    root = ET.fromstring(raw)
    ns = "{http://www.w3.org/2000/svg}"
    require(root.tag == ns + "svg", "SVG 루트가 다릅니다.")
    require(all(element.tag in {ns + name for name in ("svg", "defs", "clipPath", "rect", "g", "path", "line", "text")}
                and not any(key.endswith("href") or key in ("style", "opacity", "onload") for key in element.attrib)
                for element in root.iter()), "검토 범위 밖 SVG 실행/스타일/외부 참조가 있습니다.")
    x, y, width, height = page["view_box_mm"]
    require(root.get("width", "").endswith("mm") and root.get("height", "").endswith("mm"), "SVG 물리 단위가 mm가 아닙니다.")
    require(close(float(root.get("width")[:-2]), width) and close(float(root.get("height")[:-2]), height), "SVG 실제 용지 크기가 다릅니다.")
    require(close(list(map(float, root.get("viewBox", "").split())), [x, -y - height, width, height]), "SVG viewBox와 물리 크기의 축척이 다릅니다.")
    groups = root.findall(ns + "g")
    require(len(groups) == len(page["primitives"]), "SVG 객체가 누락되거나 추가되었습니다.")
    for index, (group, expected) in enumerate(zip(groups, page["primitives"])):
        require(group.get("transform") == "scale(1,-1)" and len(group) == 1, "SVG 축 방향 또는 객체 구조가 다릅니다.")
        element = group[0]
        require(element.get("id") == "p" + str(index), "SVG 객체 순서가 다릅니다.")
        for attribute in ("fill", "stroke"):
            value = expected.get(attribute)
            color = "none" if value is None else "#" + "".join(format(c, "02x") for c in value)
            require(element.get(attribute) == color, "SVG 채움이나 외곽선 색/유무가 다릅니다.")
        require(close(float(element.get("stroke-width")), expected["stroke_width_mm"]), "SVG 외곽선 폭이 다릅니다.")
        for key in ("source_id", "layer_id", "net_id", "role"):
            require(element.get("data-" + key.replace("_", "-"), "") == (expected.get(key) or ""), "SVG 객체의 원본 바인딩이 다릅니다.")
        if "clip_rect_mm" in expected:
            clip_id = "clip" + str(index)
            require(group.get("clip-path") == "url(#" + clip_id + ")", "SVG 상세 영역 자르기가 누락되었습니다.")
            rect = root.find(ns + "defs/" + ns + "clipPath[@id='" + clip_id + "']/" + ns + "rect")
            require(rect is not None and close([float(rect.get(k)) for k in ("x", "y", "width", "height")], expected["clip_rect_mm"]), "SVG 상세 영역이 다릅니다.")
        else:
            require(group.get("clip-path") is None, "검토하지 않은 SVG 자르기가 있습니다.")
        if expected["kind"] == "path":
            require(element.tag == ns + "path" and element.get("fill-rule") == "evenodd", "SVG 구멍의 채움 규칙이 다릅니다.")
            loops = _svg_loops(element.get("d", ""))
            require(len(loops) == len(expected["loops"]), "SVG 외곽 또는 구멍 수가 다릅니다.")
            for left, right in zip(expected["loops"], loops):
                _edges_equal(left, right)
        elif expected["kind"] == "line":
            require(element.tag == ns + "line" and close([float(element.get(k)) for k in ("x1", "y1", "x2", "y2")], expected["start"] + expected["end"]), "SVG 선 좌표가 다릅니다.")
        else:
            require(element.tag == ns + "text" and element.text == expected["text"], "SVG 주석 원문이 다릅니다.")
            require(close([float(element.get("x")), -float(element.get("y"))], expected["position"]) and close(float(element.get("font-size")), expected["height_mm"]), "SVG 주석 위치나 높이가 다릅니다.")
            require(element.get("transform") == "scale(1,-1)", "SVG 주석 방향이 다릅니다.")
            require(element.get("text-anchor") == {"left": "start", "center": "middle", "right": "end"}[expected["align"]], "SVG 문자 정렬이 다릅니다.")
    return {"reader": "stdlib ElementTree + 독립 SVG M/L/A/Z 해석", "objects": len(groups), "coordinate_tolerance_mm": EPSILON}


def _dxf_edges(boundary):
    """! @brief ezdxf가 읽은 원호 방향을 실제 진행 방향으로 복구한다."""
    result = []
    for edge in boundary.edges:
        if edge.EDGE_TYPE == "LineEdge":
            result.append({"kind": "line", "start": list(edge.start), "end": list(edge.end)})
        elif edge.EDGE_TYPE == "ArcEdge":
            sweep = (edge.end_angle - edge.start_angle) % 360
            result.append({"kind": "arc", "center": list(edge.center), "radius": edge.radius,
                           "start_deg": edge.start_angle if edge.ccw else edge.end_angle, "sweep_deg": sweep if edge.ccw else -sweep})
        else:
            fail("DXF 경계에 미지원 곡선이 포함되어 있습니다.", code="E_HASH")
    return result


def _dxf_poly(entity):
    """! @brief bulge와 끝점으로 원호 중심/반지름을 독립 산출한다."""
    vertices = list(entity.get_points("xyb"))
    require(entity.closed and len(vertices) >= 2, "DXF 폐곡선이 열렸습니다.")
    result = []
    for start, end in zip(vertices, vertices[1:] + vertices[:1]):
        ax, ay, bulge = start
        bx, by = end[:2]
        if bulge == 0:
            result.append({"kind": "line", "start": [ax, ay], "end": [bx, by]})
        else:
            dx, dy = bx - ax, by - ay
            factor = (1 - bulge * bulge) / (4 * bulge)
            center = [(ax + bx) / 2 - dy * factor, (ay + by) / 2 + dx * factor]
            result.append({"kind": "arc", "center": center, "radius": math.hypot(ax - center[0], ay - center[1]),
                           "start_deg": math.degrees(math.atan2(ay - center[1], ax - center[0])), "sweep_deg": math.degrees(4 * math.atan(bulge))})
    return result


def read_dxf(path, page):
    """! @brief INSUNITS와 실제 엔티티 및 XDATA를 읽어 바인딩/구멍/치수를 대조한다."""
    import ezdxf
    from ezdxf.xclip import XClip
    document = ezdxf.readfile(path)
    require(document.header.get("$INSUNITS") == 4 and document.header.get("$MEASUREMENT") == 1, "DXF 단위가 mm가 아닙니다.")
    audit = document.audit()
    require(not audit.errors and not audit.fixes, "DXF reader가 오류를 발견하거나 자동 수리를 요구했습니다.")
    grouped = {}
    for top in document.modelspace():
        clipping = None
        if top.dxftype() == "INSERT":
            require(tuple(top.dxf.insert) == (0, 0, 0) and top.dxf.xscale == 1 and top.dxf.yscale == 1 and top.dxf.rotation == 0, "DXF 상세 블록의 숨은 변환이 있습니다.")
            vertices = XClip(top).get_block_clipping_path().vertices
            xs, ys = [p[0] for p in vertices], [p[1] for p in vertices]
            clipping = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
            entities = list(document.blocks[top.dxf.name])
        else:
            entities = [top]
        for entity in entities:
            require(entity.has_xdata("TRACEWAVE"), "DXF 원본 바인딩이 없는 도형이 있습니다.")
            tags = list(entity.get_xdata("TRACEWAVE"))
            require([tag.code for tag in tags] == [1070, 1070, 1000, 1000, 1000, 1000], "DXF 바인딩 구조가 다릅니다.")
            index, part, source, layer, net, role = [tag.value for tag in tags]
            require(0 <= index < len(page["primitives"]), "DXF 객체 인덱스가 범위를 벗어났습니다.")
            expected = page["primitives"][index]
            require([source, layer, net, role] == [expected.get(k) or "" for k in ("source_id", "layer_id", "net_id", "role")], "DXF 객체의 원본 ID/net/layer가 다릅니다.")
            expected_layer = "G_" + layer if layer else ("BOARD" if role == "geometry" else "ANNOTATION")
            require(entity.dxf.layer == expected_layer and entity.dxf.extrusion == (0, 0, 1), "DXF 실제 층 또는 평면 축이 원본과 다릅니다.")
            require(clipping == expected.get("clip_rect_mm") or (clipping is not None and expected.get("clip_rect_mm") is not None and close(clipping, expected["clip_rect_mm"])), "DXF 상세 자르기 영역이 다릅니다.")
            grouped.setdefault(index, []).append((part, entity))
    require(set(grouped) == set(range(len(page["primitives"]))), "DXF 도형이 누락되었습니다.")
    for index, expected in enumerate(page["primitives"]):
        entities = sorted(grouped[index], key=lambda item: item[0])
        require([part for part, _ in entities] == list(range(len(entities))), "DXF 분할 경계 순서가 다릅니다.")
        if expected["kind"] == "path":
            if expected["fill"] is not None:
                require(len(entities) == 1 and entities[0][1].dxftype() == "HATCH", "실제 구리 면이 DXF HATCH가 아닙니다.")
                hatch = entities[0][1]
                require(hatch.dxf.hatch_style == 0 and hatch.dxf.solid_fill == 1, "DXF 구멍의 채움 의미가 다릅니다.")
                loops = [_dxf_edges(boundary) for boundary in hatch.paths]
            else:
                require(all(entity.dxftype() == "LWPOLYLINE" for _, entity in entities), "DXF 외형선이 해석형 폐곡선이 아닙니다.")
                loops = [_dxf_poly(entity) for _, entity in entities]
            require(len(loops) == len(expected["loops"]), "DXF 구멍 또는 외곽 경계 수가 다릅니다.")
            for left, right in zip(expected["loops"], loops):
                _edges_equal(left, right)
        elif expected["kind"] == "line":
            require(len(entities) == 1 and entities[0][1].dxftype() == "LINE", "DXF 치수선 형식이 다릅니다.")
            entity = entities[0][1]
            require(close(list(entity.dxf.start)[:2], expected["start"]) and close(list(entity.dxf.end)[:2], expected["end"]), "DXF 선 끝점이 다릅니다.")
        else:
            require(len(entities) == 1 and entities[0][1].dxftype() == "TEXT", "DXF 주석이 TEXT가 아닙니다.")
            entity = entities[0][1]
            location = entity.dxf.insert if expected["align"] == "left" else entity.dxf.align_point
            require(entity.dxf.text == expected["text"] and close(list(location)[:2], expected["position"]) and close(entity.dxf.height, expected["height_mm"]), "DXF 한글 원문/위치/높이가 다릅니다.")
    return {"reader": "ezdxf 별도 readfile + 독립 bulge 산술", "objects": len(grouped), "coordinate_tolerance_mm": EPSILON, "same_library": True}


def read_pdf(path, pages):
    """! @brief 별도 PDF parser로 용지/폰트/주석과 실제 경로 제어점을 검수한다."""
    from pypdf import PdfReader
    from pypdf.generic import ContentStream, DecodedStreamObject, NameObject
    reader = PdfReader(path, strict=True)
    require(not reader.is_encrypted and len(reader.pages) == len(pages), "PDF 쪽 수나 암호화 상태가 다릅니다.")
    maximum_radial_error = 0.0
    for actual, page in zip(reader.pages, pages):
        require(actual.rotation == 0 and float(actual.get("/UserUnit", 1)) == 1, "PDF에 검토하지 않은 페이지 회전/단위가 있습니다.")
        require(close([float(actual.mediabox.width) * 25.4 / 72, float(actual.mediabox.height) * 25.4 / 72],
                      [page["width_mm"], page["height_mm"]], PDF_EPSILON_MM), "PDF 용지 단위/크기가 다릅니다.")
        fonts = actual["/Resources"]["/Font"]
        require(any(font.get_object().get("/FontDescriptor", {}).get("/FontFile2") for font in fonts.values()), "PDF에 한글 TTF가 부분 포함되지 않았습니다.")
        groups, current, scales = {}, None, []
        for operands, operator in actual.get_contents().operations:
            if operator == b"BDC":
                require(current is None and str(operands[0]) == "/TraceWave", "PDF 객체 태그가 다릅니다.")
                current = int(operands[1]["/Id"])
                require(current not in groups, "PDF 객체 태그가 중복됩니다.")
                groups[current] = []
            elif operator == b"EMC":
                current = None
            elif current is not None:
                groups[current].append((operands, operator))
                require(operator != b"cm", "PDF 객체 안의 숨은 좌표 변환이 있습니다.")
            elif operator == b"cm":
                scales.append([float(value) for value in operands])
            else:
                require(operator not in (b"m", b"l", b"c", b"re", b"S", b"f", b"f*", b"B", b"B*", b"Do", b"Tj", b"TJ"),
                        "검토 객체 밖에 추가 PDF 도형/그림/문자가 있습니다.")
        require(len(scales) == 2 and close(scales[0], [1, 0, 0, 1, 0, 0])
                and close(scales[1], [72/25.4, 0, 0, 72/25.4, 0, 0]), "PDF의 실제 mm 변환 행렬이 다릅니다.")
        require(set(groups) == set(range(len(page["primitives"]))), "PDF 도형이 누락되거나 추가되었습니다.")
        for index, expected in enumerate(page["primitives"]):
            operations = groups[index]
            clipping = [list(map(float, values)) for values, op in operations if op == b"re"]
            require((not clipping and "clip_rect_mm" not in expected)
                    or (len(clipping) == 1 and "clip_rect_mm" in expected and close(clipping[0], expected["clip_rect_mm"], PDF_EPSILON_MM)
                        and any(op in (b"W", b"W*") for _, op in operations)), "PDF 상세 자르기 영역이 다릅니다.")
            if expected["kind"] == "text":
                # @brief 같은 페이지에 문자열이 있다는 이유로 다른 객체의 문자를 인정하지 않는다.
                isolated = copy(actual)
                content = ContentStream(None, reader)
                content.operations = operations
                raw_content = DecodedStreamObject()
                raw_content.set_data(content.get_data())
                isolated[NameObject("/Contents")] = raw_content
                recovered = isolated.extract_text()
                if recovered.endswith("\n"):
                    recovered = recovered[:-1]
                require(recovered == expected["text"], "PDF 주석이 해당 원본 객체/위치의 문자와 다릅니다.")
                matrices = [list(map(float, values)) for values, op in operations if op == b"Tm"]
                sizes = [float(values[1]) for values, op in operations if op == b"Tf"]
                require(matrices and close(matrices[-1][:4], [1, 0, 0, 1]) and close(matrices[-1][5], expected["position"][1], PDF_EPSILON_MM)
                        and sizes and close(sizes[-1], expected["height_mm"], PDF_EPSILON_MM), "PDF 주석 위치/높이가 다릅니다.")
                if expected["align"] == "left":
                    require(close(matrices[-1][4], expected["position"][0], PDF_EPSILON_MM), "PDF 왼쪽 정렬 위치가 다릅니다.")
                continue
            paths = [(values, op) for values, op in operations if op in (b"m", b"l", b"c", b"h")]
            # 사각 clip은 re 연산이므로 실제 객체 경로와 혼합되지 않는다.
            expected_loops = expected.get("loops", [[expected]])
            cursor = 0
            for loop in expected_loops:
                first = loop[0]
                start = first["start"] if first["kind"] == "line" else _point(first["center"], first["radius"], first["start_deg"])
                require(cursor < len(paths) and paths[cursor][1] == b"m" and close(list(paths[cursor][0]), start, PDF_EPSILON_MM), "PDF 경로 시작점이 다릅니다.")
                position = list(paths[cursor][0])
                cursor += 1
                for edge in loop:
                    count = 1 if edge["kind"] == "line" else math.ceil(abs(edge["sweep_deg"]) / 15)
                    for part in range(count):
                        require(cursor < len(paths), "PDF 경로가 중간에서 끊겼습니다.")
                        values, op = paths[cursor]
                        values = [float(value) for value in values]
                        cursor += 1
                        if edge["kind"] == "line":
                            require(op == b"l" and close(values, edge["end"], PDF_EPSILON_MM), "PDF 직선 끝점이 다릅니다.")
                            position = values
                        else:
                            require(op == b"c" and len(values) == 6, "PDF 원호가 3차 곡선이 아닙니다.")
                            end = _point(edge["center"], edge["radius"], edge["start_deg"] + (part + 1) * edge["sweep_deg"] / count)
                            require(close(values[4:], end, PDF_EPSILON_MM), "PDF 원호 끝점이 다릅니다.")
                            for t in [0.125, 0.25, 0.5, 0.75, 0.875]:
                                p = [(1-t)**3 * position[k] + 3*(1-t)**2*t * values[k] + 3*(1-t)*t*t * values[k+2] + t**3 * values[k+4] for k in range(2)]
                                error = abs(math.dist(p, edge["center"]) - edge["radius"])
                                maximum_radial_error = max(maximum_radial_error, error)
                                require(error <= PDF_EPSILON_MM, "PDF 원호 Bézier 근사 오차가 표시 profile을 넘었습니다.")
                            position = values[4:]
                if expected["kind"] == "path":
                    require(cursor < len(paths) and paths[cursor][1] == b"h", "PDF 외곽/구멍이 닫히지 않았습니다.")
                    cursor += 1
            require(cursor == len(paths), "검토하지 않은 PDF 경로가 추가되었습니다.")
            if expected.get("fill") is not None:
                require(any(op in (b"f*", b"B*") for _, op in operations), "PDF 구멍의 even-odd 채움이 다릅니다.")
    return {"reader": "pypdf ContentStream + 독립 좌표/원주 표본 산술", "pages": len(pages),
            "coordinate_tolerance_mm": PDF_EPSILON_MM, "pdf_arc_encoding": "cubic_bezier_maximum_15_deg",
            "sampled_maximum_radial_error_mm": maximum_radial_error,
            "deviation_measurement": "각 Bézier 구간의 다섯 내부 표본; 연속 오차 증명 아님"}
