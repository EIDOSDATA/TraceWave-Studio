"""! @brief IPC-2581 Rev C의 제조 속성과 지원하는 선형 보드 프로파일을 읽는다."""

from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import re
from xml.etree import ElementTree

from rfad.domain.errors import ProjectError


NAMESPACE = "http://webstds.ipc.org/2581"
NS = "{" + NAMESPACE + "}"
SAMPLE_LIMIT = 16
UNITS_MM = {"MILLIMETER": Decimal(1), "INCH": Decimal("25.4"), "MICRON": Decimal("0.001")}


def _measure(node, key, factor):
    """! @brief 명시한 값만 mm 또는 deg로 옮기고 원래 값은 별도로 유지한다."""
    raw = None if node is None else node.get(key)
    if raw is None:
        return None
    try:
        value = Decimal(raw)
        if not value.is_finite() or abs(value) > 1e9:
            raise InvalidOperation
        return {"source": raw, "converted": float(value * factor)}
    except InvalidOperation as error:
        raise ProjectError("E_SCHEMA", f"IPC-2581의 {key} 수치가 유효하지 않습니다.") from error


def _one(node, tag):
    """! @brief 유일한 자식으로 선언하는 요소는 누락과 중복을 구분한다."""
    rows = node.findall(NS + tag)
    if len(rows) > 1:
        raise ProjectError("E_SCHEMA", f"IPC-2581의 {tag} 요소가 중복됩니다.")
    return rows[0] if rows else None


def _attrs(node, *keys):
    """! @brief 원문 명시 속성을 키별로 반환한다."""
    return {key: node.get(key) for key in keys}


def _editable_profile(step, factor):
    """! @brief 단일 보드의 닫힌 직선 외곽과 명시 절삭을 좌표 그대로 읽는다."""
    profile = _one(step, "Profile")
    if profile is None or step.get("type", "BOARD") != "BOARD" or step.find(".//" + NS + "StepRepeat") is not None:
        return None
    polygons = profile.findall(NS + "Polygon")
    cutouts = profile.findall(NS + "Cutout")
    if len(polygons) != 1 or len(cutouts) > 16 or len(profile) != 1 + len(cutouts):
        return None
    loops = []
    for boundary in [*polygons, *cutouts]:
        nodes = list(boundary)
        if (not 4 <= len(nodes) <= 65 or nodes[0].tag != NS + "PolyBegin"
                or any(node.tag != NS + "PolyStepSegment" for node in nodes[1:])):
            return None
        points = []
        for node in nodes:
            coordinates = [_measure(node, key, factor) for key in ("x", "y")]
            if any(value is None for value in coordinates):
                return None
            points.append([value["converted"] for value in coordinates])
        if points[0] != points[-1] or len(set(map(tuple, points[:-1]))) != len(points) - 1:
            return None
        loops.append(points[:-1])
    return {"step": step.get("name"), "outer_mm": loops[0], "cutouts_mm": loops[1:]}


def _editable_traces(step, layers, factor):
    """! @brief 양극성 신호층의 직접 명시한 둥근 직선 및 원호만 좌표 변환 없이 가져온다."""
    from rfad.adapters.exchange.manufacturing_copper import trace

    names = Counter(row.get("name") for row in layers)
    selected = {row.get("name") for row in layers if names[row.get("name")] == 1
                and row.get("layerFunction") == "CONDUCTOR" and row.get("polarity") == "POSITIVE"}
    features = step.findall(NS + "LayerFeature")
    excluded = {feature.get("layerRef") for feature in features
                if any(node.get("polarity", "POSITIVE") != "POSITIVE" for node in feature.iter())}
    items = []
    for layer_index, feature in enumerate(features):
        layer = feature.get("layerRef")
        if layer not in selected or layer in excluded or set(feature.attrib) != {"layerRef"}:
            continue
        for set_index, group in enumerate(feature.findall(NS + "Set")):
            if set(group.attrib) - {"net", "polarity"} or group.find(NS + "Xform") is not None:
                continue
            for group_index, collection in enumerate(group.findall(NS + "Features")):
                if collection.attrib or [node.tag for node in collection] != [NS + "UserSpecial"]:
                    continue
                special = collection[0]
                if special.attrib:
                    continue
                for index, item in enumerate(special):
                    if item.tag not in {NS + "Line", NS + "Arc"} or len(item) != 1 or item[0].tag != NS + "LineDesc":
                        continue
                    allowed = {"startX", "startY", "endX", "endY"}
                    if item.tag == NS + "Arc":
                        allowed.update({"centerX", "centerY", "clockwise"})
                    if set(item.attrib) != allowed:
                        continue
                    desc = item[0]
                    if desc.get("lineEnd") != "ROUND" or set(desc.attrib) != {"lineEnd", "lineWidth"}:
                        continue
                    def coord(key):
                        """! @brief 수치가 없으면 지원하지 않는 원문으로 남긴다."""
                        value = _measure(item, key, factor)
                        return None if value is None else value["converted"]
                    start, end = ([coord(prefix + axis) for axis in "XY"] for prefix in ("start", "end"))
                    center = [coord("center" + axis) for axis in "XY"] if item.tag == NS + "Arc" else None
                    clockwise = {"true": True, "false": False, "1": True, "0": False}.get(item.get("clockwise"))
                    width = _measure(desc, "lineWidth", factor)
                    if width and None not in [*start, *end, *(center or [])]:
                        source = f"copper:{layer_index}:{set_index}:{group_index}:{index}"
                        result = trace(layer, group.get("net", ""), source, width["converted"], start, end, center, clockwise)
                        if result is not None:
                            items.append(result)
                            if len(items) > 128:
                                return []
    return items


def _step(node, factor):
    """! @brief 각 보드 정의의 넷, 부품, 홀과 윤곽의 명시 범위를 집계한다."""
    features = node.findall(NS + "LayerFeature")
    nets = node.findall(NS + "LogicalNet")
    physical = sum(1 for item in node.iter(NS + "PhyNet"))
    components = node.findall(NS + "Component")
    holes = [(feature.get("layerRef"), hole) for feature in features for hole in feature.iter(NS + "Hole")]
    plating = Counter(hole.get("platingStatus", "unspecified") for _, hole in holes)
    placements = []
    for component in components[:SAMPLE_LIMIT]:
        location = _one(component, "Location")
        transform = _one(component, "Xform")
        placements.append({**_attrs(component, "refDes", "packageRef", "layerRef", "part", "mountType"),
                           "x_mm": _measure(location, "x", factor), "y_mm": _measure(location, "y", factor),
                           "rotation_deg": _measure(transform, "rotation", Decimal(1)),
                           "mirror": None if transform is None else transform.get("mirror")})
    profile = _one(node, "Profile")
    repeats = node.findall(".//" + NS + "StepRepeat")
    return {"name": node.get("name"), "logical_nets": len(nets), "physical_nets": physical,
            "components": len(components), "holes": len(holes), "hole_plating": dict(sorted(plating.items())),
            "slots": sum(1 for child in node.iter(NS + "SlotCavity")), "layer_features": len(features),
            "profile": None if profile is None else {
                "outer": len(profile.findall(NS + "Polygon")), "cutouts": len(profile.findall(NS + "Cutout"))},
            "step_repeats": len(repeats),
            "repeat_source_examples": [dict(row.attrib) for row in repeats[:SAMPLE_LIMIT]], "net_examples": [row.get("name") for row in nets[:SAMPLE_LIMIT]],
            "component_examples": placements, "hole_examples": [
                {**_attrs(row, "name", "platingStatus"), "drill_layer_ref": layer,
                 "diameter_mm": _measure(row, "diameter", factor), "x_mm": _measure(row, "x", factor),
                 "y_mm": _measure(row, "y", factor)} for layer, row in holes[:SAMPLE_LIMIT]]}


def read(raw):
    """! @brief 원문 제조 요약과 검토 후 적용 가능한 범위를 분리한다."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise ProjectError("E_UNSUPPORTED", "IPC-2581 검토는 UTF-8 Rev C XML 원문을 입력받습니다.") from error
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        raise ProjectError("E_UNSUPPORTED", "DTD 또는 사용자 정의 엔티티가 있는 XML은 지원하지 않습니다.")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise ProjectError("E_SCHEMA", "IPC-2581 XML을 읽을 수 없습니다.", details={"line": error.position[0]}) from error
    if root.tag != NS + "IPC-2581" or root.get("revision") != "C":
        raise ProjectError("E_UNSUPPORTED", "IPC-2581 표준 네임스페이스와 Rev C 선언을 확인하십시오.")
    ecad = _one(root, "Ecad")
    header = None if ecad is None else _one(ecad, "CadHeader")
    data = None if ecad is None else _one(ecad, "CadData")
    units = None if header is None else header.get("units")
    if data is not None and units not in UNITS_MM:
        raise ProjectError("E_UNIT", "PCB 형상 좌표에 명시한 mm, inch 또는 micron 단위를 확인하십시오.")
    factor = UNITS_MM.get(units)
    steps = [] if data is None else data.findall(NS + "Step")
    layers = [] if data is None else data.findall(NS + "Layer")
    stackups = [] if data is None else data.findall(NS + "Stackup")
    if len(steps) > 32 or len(layers) > 256 or len(stackups) > 32:
        raise ProjectError("E_RESOURCE", "IPC-2581 보드 정의, 층 또는 적층 수의 읽기 한도를 초과했습니다.")
    total_layers = sum(1 for stack in stackups for _ in stack.iter(NS + "StackupLayer"))
    if total_layers > 512:
        raise ProjectError("E_RESOURCE", "IPC-2581 적층의 세부 층이 검토 한도 512개를 초과했습니다.")
    history = _one(root, "HistoryRecord")
    editable = _editable_profile(steps[0], factor) if len(steps) == 1 else None
    loss = ({"code": "ipc2581_profile_only", "raw_preserved": True,
             "message": "단일 보드의 직선 외곽을 대조하고 내부 절삭만 추가합니다. 적층·넷·홀·실장 등은 원문에 보존합니다."}
            if editable else {"code": "ipc2581_review_only", "raw_preserved": True,
                              "message": "현재 지원하는 단일 보드의 닫힌 직선 프로파일이 없어 원문을 읽기만 합니다."})
    from rfad.adapters.exchange import manufacturing_regions
    regions, omitted = manufacturing_regions.ipc(steps[0], layers, factor, NS) if editable else ([], [])
    traces = _editable_traces(steps[0], layers, factor) if editable else []
    if traces:
        loss = {"code": "ipc2581_partial_copper", "raw_preserved": True,
                "message": f"외곽과 절삭을 대조합니다. 층과 넷을 지정하면 둥근 직선 및 원호 동박 {len(traces)}개를 반영합니다. 나머지 제조 정보는 원문에 보존합니다."}
    from rfad.adapters.exchange.manufacturing_contacts import ipc
    pads, bores, stack = ipc(root, steps[0], layers, stackups, factor) if editable else ([], [], [])
    from rfad.adapters.exchange import manufacturing_placements
    components = manufacturing_placements.ipc(root, steps[0], layers, factor, pads, bores) if editable else []
    if pads or bores or stack or components:
        loss = {**loss, "message": loss["message"] + f" 선택 가능한 원형 및 사각 패드 {len(pads)}개, 원형 홀 {len(bores)}개, 적층 {len(stack)}개, 실장 위치 {len(components)}개."}
    if regions or omitted:
        reasons = sorted({row["reason"] for row in omitted})
        summary = f" 적용 가능한 채움 동박 {len(regions)}개, 제외 {len(omitted)}건."
        loss = {**loss, "message": loss["message"] + summary + (" " + " ".join(reasons) if reasons else "")}
    return {"editable_regions": regions, "region_exclusions": omitted[:128], "region_exclusion_count": len(omitted),
            "editable_components": components, "editable_pads": pads, "editable_holes": bores, "editable_stack": stack,
            "editable_traces": traces, "schema": "rfad.ipc2581-read/0.1", "version": "C", "units": units,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "writer": None if history is None else history.get("software"),
            "sections": sorted({element.tag[len(NS):] for element in root if element.tag.startswith(NS)}),
            "samples_per_step_limit": SAMPLE_LIMIT,
            "layers": [_attrs(row, "name", "layerFunction", "side", "polarity") for row in layers],
            "stackups": [{"name": item.get("name"), "thickness_mm": _measure(item, "overallThickness", factor),
                          "layers": [{**_attrs(row, "layerOrGroupRef", "sequence"),
                                      "thickness_mm": _measure(row, "thickness", factor)}
                                     for row in item.iter(NS + "StackupLayer")]} for item in stackups],
            "steps": [_step(step, factor) for step in steps], "editable_profile": editable, "losses": [loss]}
