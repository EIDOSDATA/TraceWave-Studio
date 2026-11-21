"""! @brief AN-B-027의 동박 폐곡선과 확인한 단위를 편집 영역으로 변환한다."""

import math

from rfad.domain.errors import ProjectError


CHORD_ERROR_MM = 0.002


def _entities(raw):
    """! @brief AC1009 ENTITIES의 코드-값과 순번을 원문 그대로 읽는다."""
    lines = raw.decode("ascii").splitlines()
    if len(lines) % 2 or len(lines) > 50000:
        raise ProjectError("E_RESOURCE", "공급사 DXF 코드-값 쌍의 상한 또는 형식이 다릅니다.")
    pairs = [(key.strip(), value.strip()) for key, value in zip(lines[::2], lines[1::2])]
    start = pairs.index(("2", "ENTITIES"))
    stop = pairs.index(("0", "ENDSEC"), start + 1)
    records = []
    for key, value in pairs[start + 1:stop]:
        if key == "0":
            records.append((value, {}))
        elif records:
            records[-1][1][key] = value
    return records


def _outline(vertices):
    """! @brief DXF bulge에 해당하는 원호의 끝점을 보존하고 최대 현 오차를 제한한다."""
    points = [(float(v["10"]), float(v["20"])) for v in vertices]
    outline, arcs = [], 0
    for index, first in enumerate(points):
        if not outline or first != outline[-1]:
            outline.append(first)
        bulge = float(vertices[index].get("42", 0))
        last = points[(index + 1) % len(points)]
        if not bulge or first == last:
            continue
        arcs += 1
        dx, dy = last[0] - first[0], last[1] - first[1]
        turn = 4 * math.atan(bulge)
        height = (1 / bulge - bulge) / 4
        cx = (first[0] + last[0]) / 2 - dy * height
        cy = (first[1] + last[1]) / 2 + dx * height
        radius = math.hypot(first[0] - cx, first[1] - cy)
        angle = math.atan2(first[1] - cy, first[0] - cx)
        step = 2 * math.acos(max(-1.0, 1 - CHORD_ERROR_MM / radius))
        count = math.ceil(abs(turn) / step)
        if count > 256:
            raise ProjectError("E_RESOURCE", "공급사 원호가 변환 보간 상한을 초과했습니다.")
        for part in range(1, count):
            current = angle + turn * part / count
            outline.append((cx + radius * math.cos(current), cy + radius * math.sin(current)))
    return outline, arcs


def read_renesas(raw):
    """! @brief 파일에 명시된 동박층만 읽고 다른 DXF 레이어의 원문 역할을 반환한다."""
    from shapely import Polygon
    records = _entities(raw)
    regions, skipped, arcs = [], set(), 0
    copper = {"ET_TOP": "top", "ET_BOTTOM": "bottom", "TOP": "top", "BOTTOM": "bottom"}
    index = 0
    while index < len(records):
        name, fields = records[index]
        index += 1
        layer = fields.get("8")
        if layer not in copper:
            if layer is not None:
                skipped.add(layer)
            continue
        if name == "INSERT" and fields.get("2") in ("V55H20", "C100"):
            skipped.add(layer + ":" + fields["2"])
            continue
        if name == "ATTRIB" and fields.get("2") in ("CDN_TYPE", "PIN"):
            continue
        if name != "POLYLINE" or fields.get("70") != "1":
            raise ProjectError("E_UNSUPPORTED", "Renesas 동박에서 닫힌 평면 POLYLINE 이외의 항목을 발견했습니다.")
        vertices = []
        while index < len(records) and records[index][0] == "VERTEX":
            vertices.append(records[index][1])
            index += 1
        if len(vertices) < 3 or index >= len(records) or records[index][0] != "SEQEND":
            raise ProjectError("E_GEOMETRY", "Renesas 동박에 유효한 정점과 SEQEND가 필요합니다.")
        for vertex in vertices:
            if float(vertex.get("30", 0)) or float(vertex.get("40", 0)) or float(vertex.get("41", 0)):
                raise ProjectError("E_UNSUPPORTED", "Renesas 동박에 Z 좌표 또는 획 폭이 있습니다.")
        outline, arc_count = _outline(vertices)
        arcs += arc_count
        if outline[0] == outline[-1]:
            outline.pop()
        polygon = Polygon(outline)
        if not polygon.is_valid or polygon.area <= 0:
            raise ProjectError("E_GEOMETRY", "Renesas 도체의 닫힌 경계가 단순 영역을 만들지 않습니다.")
        regions.append((layer, copper[layer], polygon))
        index += 1
    if not regions:
        raise ProjectError("E_GEOMETRY", "Renesas DXF의 확인된 동박을 찾지 못했습니다.")
    return regions, sorted(skipped), arcs
