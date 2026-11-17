"""! @brief 공유 종이 벡터를 SVG, DXF, PDF의 실제 도형과 주석으로 기록한다."""

import hashlib
import math
from pathlib import Path
import unicodedata
import xml.etree.ElementTree as ET

from rfad.domain.drawing_layout import fail, polar
from rfad.domain.errors import ProjectError


SVG = "http://www.w3.org/2000/svg"
MM_TO_PT = 72 / 25.4


def _num(value):
    """! @brief 왕복 가능한 유한 좌표를 소수점 지역화 없이 출력한다."""
    return format(float(value), ".17g")


def _color(value):
    """! @brief 불투명 RGB 또는 명시적인 채움 없음만 기록한다."""
    return "none" if value is None else "#" + "".join(format(c, "02x") for c in value)


def _segments(edge, maximum=180):
    """! @brief 원 전체의 SVG 모호성을 피하되 같은 원의 해석형 호만 분할한다."""
    count = max(1, math.ceil(abs(edge["sweep_deg"]) / maximum))
    for index in range(count):
        yield edge["start_deg"] + edge["sweep_deg"] * index / count, edge["sweep_deg"] / count


def _svg_path(loops):
    """! @brief Y 반전은 그룹 한 곳에 두고 원호의 부호와 내부 구멍을 보존한다."""
    commands = []
    for loop in loops:
        first = loop[0]
        start = first["start"] if first["kind"] == "line" else polar(first["center"], first["radius"], first["start_deg"])
        commands.append("M " + " ".join(map(_num, start)))
        for edge in loop:
            if edge["kind"] == "line":
                commands.append("L " + " ".join(map(_num, edge["end"])))
            else:
                for start_angle, sweep in _segments(edge):
                    end = polar(edge["center"], edge["radius"], start_angle + sweep)
                    commands.append("A " + " ".join([_num(edge["radius"]), _num(edge["radius"]), "0", "0", "1" if sweep > 0 else "0", *map(_num, end)]))
        commands.append("Z")
    return " ".join(commands)


def write_svg(page, path):
    """! @brief 실제 mm 용지와 좌표계를 가진 UTF-8 SVG를 기록한다."""
    ET.register_namespace("", SVG)
    x, y, width, height = page["view_box_mm"]
    root = ET.Element("{" + SVG + "}svg", {"version": "1.1", "width": _num(width) + "mm", "height": _num(height) + "mm",
                                           "viewBox": " ".join(map(_num, [x, -y - height, width, height]))})
    defs = ET.SubElement(root, "{" + SVG + "}defs")
    for index, primitive in enumerate(page["primitives"]):
        attributes = {"id": "p" + str(index), "data-source-id": primitive.get("source_id") or "",
                      "data-layer-id": primitive.get("layer_id") or "", "data-net-id": primitive.get("net_id") or "",
                      "data-role": primitive["role"], "fill": _color(primitive.get("fill")),
                      "stroke": _color(primitive.get("stroke")), "stroke-width": _num(primitive["stroke_width_mm"])}
        group = ET.SubElement(root, "{" + SVG + "}g", {"transform": "scale(1,-1)"})
        if "clip_rect_mm" in primitive:
            clip = ET.SubElement(defs, "{" + SVG + "}clipPath", {"id": "clip" + str(index), "clipPathUnits": "userSpaceOnUse"})
            cx, cy, cw, ch = primitive["clip_rect_mm"]
            ET.SubElement(clip, "{" + SVG + "}rect", dict(zip(["x", "y", "width", "height"], map(_num, [cx, cy, cw, ch]))))
            group.set("clip-path", "url(#clip" + str(index) + ")")
        kind = primitive["kind"]
        if kind == "path":
            ET.SubElement(group, "{" + SVG + "}path", {**attributes, "d": _svg_path(primitive["loops"]), "fill-rule": "evenodd"})
        elif kind == "line":
            ET.SubElement(group, "{" + SVG + "}line", {**attributes, **dict(zip(["x1", "y1", "x2", "y2"], map(_num, primitive["start"] + primitive["end"])))})
        elif kind == "text":
            tx, ty = primitive["position"]
            element = ET.SubElement(group, "{" + SVG + "}text", {**attributes, "x": _num(tx), "y": _num(-ty),
                                    "transform": "scale(1,-1)", "font-family": "Malgun Gothic, sans-serif",
                                    "font-size": _num(primitive["height_mm"]), "text-anchor": {"left": "start", "center": "middle", "right": "end"}[primitive["align"]]})
            element.text = primitive["text"]
        else:
            fail("SVG writer의 미지원 도형입니다.")
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def _dxf_path(hatch, loops):
    """! @brief 외곽과 구멍을 DXF 해석형 HATCH edge path에 분리한다."""
    for index, loop in enumerate(loops):
        boundary = hatch.paths.add_edge_path(flags=1 if index == 0 else 0)
        for edge in loop:
            if edge["kind"] == "line":
                boundary.add_line(edge["start"], edge["end"])
            else:
                for start, sweep in _segments(edge):
                    boundary.add_arc(edge["center"], edge["radius"], start_angle=start if sweep > 0 else start + sweep,
                                     end_angle=start + sweep if sweep > 0 else start, ccw=sweep > 0)


def _poly_vertices(loop):
    """! @brief 외곽선의 원호를 bulge로 기록하며 임의 선분 근사를 만들지 않는다."""
    result = []
    for edge in loop:
        if edge["kind"] == "line":
            result.append((*edge["start"], 0))
        else:
            for start, sweep in _segments(edge):
                result.append((*polar(edge["center"], edge["radius"], start), math.tan(math.radians(sweep) / 4)))
    return result


def write_dxf(page, path):
    """! @brief mm 원본 객체와 net/layer 바인딩을 DXF XDATA 및 실제 도형에 보존한다."""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment
    from ezdxf.xclip import XClip
    document = ezdxf.new("R2018", setup=False)
    document.units = 4
    document.header["$MEASUREMENT"] = 1
    document.appids.new("TRACEWAVE")
    document.styles.new("TRACEWAVE", dxfattribs={"font": "malgun.ttf"})
    model = document.modelspace()
    for index, primitive in enumerate(page["primitives"]):
        layer = "G_" + primitive["layer_id"] if primitive.get("layer_id") else ("BOARD" if primitive["role"] == "geometry" else "ANNOTATION")
        if layer not in document.layers:
            document.layers.new(layer)
        rgb = primitive.get("fill") or primitive.get("stroke") or [0, 0, 0]
        attrs = {"layer": layer, "true_color": (rgb[0] << 16) + (rgb[1] << 8) + rgb[2]}
        destination = model
        if "clip_rect_mm" in primitive:
            destination = document.blocks.new("TW_CLIP_" + str(index))
            insert = model.add_blockref(destination.name, (0, 0), dxfattribs=attrs)
            x, y, width, height = primitive["clip_rect_mm"]
            XClip(insert).set_block_clipping_path([(x, y), (x + width, y + height)])
        entities = []
        if primitive["kind"] == "path":
            if primitive["fill"] is not None:
                hatch = destination.add_hatch(dxfattribs=attrs)
                hatch.dxf.hatch_style = 0
                _dxf_path(hatch, primitive["loops"])
                entities.append(hatch)
            else:
                for loop in primitive["loops"]:
                    entities.append(destination.add_lwpolyline(_poly_vertices(loop), format="xyb", close=True, dxfattribs=attrs))
        elif primitive["kind"] == "line":
            entities.append(destination.add_line(primitive["start"], primitive["end"], dxfattribs=attrs))
        elif primitive["kind"] == "text":
            text = destination.add_text(primitive["text"], dxfattribs={**attrs, "height": primitive["height_mm"], "style": "TRACEWAVE"})
            text.set_placement(primitive["position"], align={"left": TextEntityAlignment.LEFT, "center": TextEntityAlignment.CENTER, "right": TextEntityAlignment.RIGHT}[primitive["align"]])
            entities.append(text)
        else:
            fail("DXF writer의 미지원 도형입니다.")
        for part, entity in enumerate(entities):
            entity.set_xdata("TRACEWAVE", [(1070, index), (1070, part), (1000, primitive.get("source_id") or ""),
                                           (1000, primitive.get("layer_id") or ""), (1000, primitive.get("net_id") or ""), (1000, primitive["role"])])
    document.set_modelspace_vport(height=page["height_mm"], center=(page["width_mm"] / 2, page["height_mm"] / 2))
    document.saveas(path, encoding="utf-8")


def _pdf_curve(path, edge):
    """! @brief PDF의 3차 곡선 제한에 맞춰 최대 15도 호로 분할한다.

    @details PDF는 원의 해석형 교환 형식이 아니다. 원형 Bézier 근사임을 검증 보고서에 명시한다.
    """
    cx, cy = edge["center"]
    radius = edge["radius"]
    for start, sweep in _segments(edge, 15):
        a, b = math.radians(start), math.radians(start + sweep)
        k = 4 / 3 * math.tan((b - a) / 4)
        p0, p3 = polar([cx, cy], radius, start), polar([cx, cy], radius, start + sweep)
        path.curveTo(p0[0] - radius * k * math.sin(a), p0[1] + radius * k * math.cos(a),
                     p3[0] + radius * k * math.sin(b), p3[1] - radius * k * math.cos(b), *p3)


def write_pdf(pages, path, font_path):
    """! @brief worker가 고정한 한글 글꼴을 부분 포함하고 실제 용지 크기의 PDF를 만든다."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    if font_path is None or not Path(font_path).is_file():
        fail("PDF 출력에는 검증된 한글 TTF 글꼴이 필요합니다.", "runtime.font")
    name = "TraceWave_" + hashlib.sha256(Path(font_path).read_bytes()).hexdigest()[:16]
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(Path(font_path).resolve())))
    selected_font = pdfmetrics.getFont(name)
    actual_font_name = selected_font.face.name.decode("utf-8", errors="replace") if isinstance(selected_font.face.name, bytes) else str(selected_font.face.name)
    for page_index, page in enumerate(pages):
        for primitive_index, primitive in enumerate(page["primitives"]):
            if primitive["kind"] != "text":
                continue
            text = primitive["text"]
            missing = sorted({ord(char) for char in text if not selected_font.face.charToGlyph.get(ord(char), 0)})
            details = {"field_path": "drawing.text", "page_index": page_index, "primitive_index": primitive_index,
                       "font": actual_font_name, "source_modified": False}
            if missing:
                raise ProjectError("E_UNSUPPORTED", "선택한 PDF 글꼴에 없는 문자가 있습니다. 원문을 빈 글자로 대체하지 않습니다.",
                                   details={**details, "codepoints": ["U+" + format(value, "04X") for value in missing],
                                            "reason": "missing_font_glyph"})
            complex_text = {ord(char) for char in text if unicodedata.category(char) in ("Cf", "Cc")
                            or unicodedata.combining(char) or unicodedata.bidirectional(char) in ("R", "AL", "AN")}
            if unicodedata.normalize("NFC", text) != text:
                complex_text.update(ord(char) for char in text if ord(char) > 127)
            if complex_text:
                raise ProjectError("E_UNSUPPORTED", "현재 PDF 문자 배치는 결합문자/방향제어 조판을 지원하지 않습니다. 원문을 정규화하지 않습니다.",
                                   details={**details, "codepoints": ["U+" + format(value, "04X") for value in sorted(complex_text)],
                                            "reason": "complex_text_shaping_not_supported", "normalization_applied": False})
    document = Canvas(str(path), invariant=1, pageCompression=1)
    document.setTitle("TraceWave Studio 기술도면")
    document.setAuthor("TraceWave Studio")
    for page in pages:
        document.setPageSize((page["width_mm"] * MM_TO_PT, page["height_mm"] * MM_TO_PT))
        document.scale(MM_TO_PT, MM_TO_PT)
        for index, primitive in enumerate(page["primitives"]):
            document.saveState()
            document._code.append("/TraceWave << /Id " + str(index) + " >> BDC")
            if "clip_rect_mm" in primitive:
                clip = document.beginPath()
                clip.rect(*primitive["clip_rect_mm"])
                document.clipPath(clip, stroke=0, fill=0)
            if primitive.get("stroke") is not None:
                document.setStrokeColorRGB(*(value / 255 for value in primitive["stroke"]))
            if primitive.get("fill") is not None:
                document.setFillColorRGB(*(value / 255 for value in primitive["fill"]))
            document.setLineWidth(primitive["stroke_width_mm"])
            if primitive["kind"] == "text":
                document.setFont(name, primitive["height_mm"])
                text = primitive["text"]
                width = pdfmetrics.stringWidth(text, name, primitive["height_mm"])
                x, y = primitive["position"]
                x -= width * {"left": 0, "center": 0.5, "right": 1}[primitive["align"]]
                if x < 0 or x + width > page["width_mm"] or y < 0 or y + primitive["height_mm"] > page["height_mm"]:
                    fail("원문 주석이 용지를 벗어납니다. 원문을 잘라내지 않습니다.", "drawing.text", "E_RESOURCE")
                document.drawString(x, y, text)
            else:
                path_object = document.beginPath()
                loops = primitive.get("loops", [[primitive]])
                for loop in loops:
                    first = loop[0]
                    start = first["start"] if first["kind"] == "line" else polar(first["center"], first["radius"], first["start_deg"])
                    path_object.moveTo(*start)
                    for edge in loop:
                        if edge["kind"] == "line":
                            path_object.lineTo(*edge["end"])
                        else:
                            _pdf_curve(path_object, edge)
                    if primitive["kind"] == "path":
                        path_object.close()
                document.drawPath(path_object, stroke=int(primitive.get("stroke") is not None), fill=int(primitive.get("fill") is not None), fillMode=0)
            document._code.append("EMC")
            document.restoreState()
        document.showPage()
    document.save()
