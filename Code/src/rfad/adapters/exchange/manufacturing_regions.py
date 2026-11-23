"""! @brief 명시한 양극성 동박의 직선 경계와 절연 구멍을 넷 및 층별로 복원한다."""
from collections import Counter, defaultdict
import math
import re

from rfad.domain.planar import MAX_REGION_HOLES, MAX_REGION_POINTS


def _point(x, y, scale):
    """! @brief 원본 단위를 적용하고 유한한 보드 좌표 한계를 확인한다."""
    xy = [float(x) * scale, float(y) * scale]
    if not all(math.isfinite(v) and abs(v) <= 1e6 for v in xy):
        raise ValueError("동박 경계 좌표 범위")
    return xy


def _closed(points):
    """! @brief 중복 시작점을 제외하고 원문에서 명시적으로 닫은 고리만 받는다."""
    loop = []
    for pt in points:
        if not loop or pt != loop[-1]:
            loop.append(pt)
    if not 4 <= len(loop) <= 2049 or loop[0] != loop[-1]:
        raise ValueError("닫히지 않은 경계 또는 꼭짓점 수")
    return loop[:-1]


def _omitted(layer, source, reason):
    """! @brief 적용할 수 없는 원문의 층, 도형 위치와 사유를 남긴다."""
    return {"layer": layer, "source_id": source, "reason": reason}


def _regions(groups, skipped):
    """! @brief 같은 넷과 도체층의 양극성 조각을 합치고 실제 외곽과 구멍을 분리한다."""
    if not groups:
        return [], skipped
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        from shapely.errors import ShapelyError
    except ImportError:
        for layer, net in groups:
            skipped.append(_omitted(layer, net, "동박 합집합을 확인할 수 있는 교환 Python이 필요합니다."))
        return [], skipped
    result = []
    for (layer, net), pieces in groups.items():
        if len(pieces) > 512 or sum(len(ring) for _, loops in pieces for ring in loops) > 8192:
            skipped.append(_omitted(layer, net, "동일 넷의 동박 조각/꼭짓점 한도를 넘습니다."))
            continue
        polygons = []
        for source, rings in pieces:
            try:
                shape = Polygon(rings[0], rings[1:])
                if shape.is_valid and not shape.is_empty and shape.area > 0:
                    polygons.append((source, shape))
                else:
                    skipped.append(_omitted(layer, source, "자가 교차, 겹친 구멍 또는 0 면적 경계입니다."))
            except (ValueError, ShapelyError):
                skipped.append(_omitted(layer, source, "원문의 외곽과 절연 구멍을 확인할 수 없습니다."))
        if not polygons:
            continue
        try:
            merged = unary_union([polygon for _, polygon in polygons]).simplify(0, preserve_topology=True)
            islands = [merged] if merged.geom_type == "Polygon" else list(merged.geoms)
        except (ValueError, ShapelyError):
            skipped.append(_omitted(layer, net, "같은 넷의 양극성 동박 합집합을 계산할 수 없습니다."))
            continue
        for index, island in enumerate(sorted(islands, key=lambda g: g.bounds)):
            if island.geom_type != "Polygon" or not island.is_valid or len(island.interiors) > MAX_REGION_HOLES:
                skipped.append(_omitted(layer, net, "연결 동박의 외곽 또는 절연 구멍 수가 프로젝트 한도를 넘습니다."))
                continue
            rings = [[list(xy) for xy in ring.coords[:-1]] for ring in (island.exterior, *island.interiors)]
            if sum(map(len, rings)) > MAX_REGION_POINTS:
                skipped.append(_omitted(layer, net, "동박 외곽과 구멍을 합한 꼭짓점 수가 프로젝트 한도를 넘습니다."))
                continue
            origins = [source for source, shape in polygons if island.covers(shape.representative_point())]
            if origins:
                result.append({"layer": layer, "net": net, "source_id": origins[0] + ":island:" + str(index),
                               "source_features": origins, "outer_mm": rings[0], "holes_mm": rings[1:],
                               "area_mm2": island.area})
    return result, skipped


def ipc(step, layers, factor, ns):
    """! @brief IPC 도체층에서 직접 기입한 단일 넷 Contour의 Polygon 및 Cutout을 읽는다."""
    groups, skipped = defaultdict(list), []
    factor = float(factor)
    names = [l.get("name") for l in layers if l.get("layerFunction") == "CONDUCTOR"]
    positive = {l.get("name") for l in layers if l.get("layerFunction") == "CONDUCTOR"
                and names.count(l.get("name")) == 1 and l.get("polarity") == "POSITIVE"}
    features = step.findall(ns + "LayerFeature")
    negative = {f.get("layerRef") for f in features if any(n.get("polarity", "POSITIVE") != "POSITIVE" for n in f.iter())}
    for fi, feature in enumerate(features):
        layer = feature.get("layerRef")
        if layer not in names:
            continue
        for si, group in enumerate(feature.findall(ns + "Set")):
            net = group.get("net")
            direct = {contour for collection in group.findall(ns + "Features") if not collection.attrib
                      and [n.tag for n in collection] == [ns + "UserSpecial"] and not collection[0].attrib
                      for contour in collection[0].findall(ns + "Contour")}
            transformed = group.find(".//" + ns + "Xform") is not None
            for ci, item in enumerate(group.iter(ns + "Contour")):
                source = f"region:{fi}:{si}:{ci}"
                if (layer not in positive or layer in negative or not net or set(feature.attrib) != {"layerRef"}
                        or set(group.attrib) - {"net", "polarity"} or item not in direct or transformed):
                    skipped.append(_omitted(layer, source, "도체층/넷/양극성 또는 직접 배치된 경계를 확정할 수 없습니다."))
                    continue
                try:
                    tags = [c.tag for c in item]
                    if item.attrib or not tags or tags[0] != ns + "Polygon" or any(t != ns + "Cutout" for t in tags[1:]):
                        raise ValueError("외곽 및 구멍")
                    loops = []
                    for ring in item:
                        if (ring.attrib or not len(ring) or ring[0].tag != ns + "PolyBegin"
                                or any(n.tag != ns + "PolyStepSegment" for n in list(ring)[1:])
                                or any(set(n.attrib) != {"x", "y"} or len(n) for n in ring)):
                            raise ValueError("직선 경계")
                        loops.append(_closed([_point(n.get("x"), n.get("y"), factor) for n in ring]))
                    groups[layer, net].append((source, loops))
                except (ValueError, TypeError):
                    skipped.append(_omitted(layer, source, "명시적으로 닫힌 직선 외곽과 절연 구멍만 적용합니다."))
    return _regions(groups, skipped)


def odb(archive, members, base, matrix):
    """! @brief ODB++ 양극성 금속층에서 SNT PLN 및 FID C로 연결한 표면만 읽는다."""
    from rfad.adapters.exchange.odb_reader import _text, _trace_nets
    groups, skipped = defaultdict(list), []
    nets = _trace_nets(_text(archive, base + "eda/data"), planes=True) if base + "eda/data" in members else {}
    definitions = [dict(line.strip().split("=", 1) for line in block.splitlines() if "=" in line)
                   for block in re.findall(r"(?:^|\n)LAYER\s*\{([^{}]*)\}", matrix)]
    occurrences = Counter(layer.get("NAME", "").casefold() for layer in definitions)
    for attrs in definitions:
        if attrs.get("CONTEXT") != "BOARD" or attrs.get("TYPE") not in ("SIGNAL", "POWER_GROUND", "MIXED"):
            continue
        layer = attrs.get("NAME", "").casefold()
        path = base + "layers/" + layer + "/features"
        if not layer or "/" in layer or path not in members:
            continue
        if occurrences[layer] != 1:
            skipped.append(_omitted(layer, layer, "행렬에 같은 층 이름이 둘 이상 있어 도체층을 특정할 수 없습니다."))
            continue
        rows = [line.split(";", 1)[0].split() for line in _text(archive, path).splitlines()]
        polar = {"L": 6, "A": 8, "P": 4, "S": 1, "T": 5, "B": 5}
        negative = attrs.get("POLARITY") != "POSITIVE" or any(r and r[0] in polar and
            (len(r) <= polar[r[0]] or r[polar[r[0]]] != "P") for r in rows)
        units = [r[0] for r in rows if r and r[0].startswith("UNITS=")]
        scale = {"UNITS=MM": 1, "UNITS=INCH": 25.4}.get(units[0]) if len(units) == 1 else None
        features = [(pos, row) for pos, row in enumerate(rows) if row and row[0] in polar]
        for seq, (start, row) in enumerate(features):
            if row[0] != "S":
                continue
            source = f"region:{layer}:{seq}"
            net = nets.get((layer, seq))
            if negative or not scale or not net or row != ["S", "P", "0"]:
                skipped.append(_omitted(layer, source, "명시한 넷의 평면 참조, 단위 또는 양극성 도체층을 확인할 수 없습니다."))
                continue
            loops, current = [], None
            try:
                end = features[seq + 1][0] if seq + 1 < len(features) else len(rows)
                body = [record for record in rows[start + 1:end] if record and not record[0].startswith("#")]
                if not body or body[-1] != ["SE"]:
                    raise ValueError("표면 종료")
                for data in body[:-1]:
                    if data[0] == "OB" and len(data) == 4 and current is None and data[3] == ("I" if not loops else "H"):
                        current = [_point(data[1], data[2], scale)]
                    elif data[0] == "OS" and len(data) == 3 and current is not None:
                        current.append(_point(data[1], data[2], scale))
                    elif data == ["OE"] and current is not None:
                        loops.append(_closed(current))
                        current = None
                    else:
                        raise ValueError("직선 표면 항목")
                if current is not None or not loops:
                    raise ValueError("표면 종료")
                groups[layer, net].append((source, loops))
            except (ValueError, TypeError):
                skipped.append(_omitted(layer, source, "명시적으로 닫힌 직선 I 외곽 및 H 구멍만 적용합니다."))
    return _regions(groups, skipped)
