"""! @brief IPC-2581C 단일 보드를 보존하는 반복 패널과 특수 제조 선언을 다룬다."""

from decimal import Decimal
import hashlib
import math
from xml.etree import ElementTree as ET

from rfad.adapters.exchange import ipc2581_reader as ipc
from rfad.domain.errors import ProjectError
from rfad.domain.planar import validate_region


PANEL_NAME = "TW_PANEL"
MAX_REPEAT_INSTANCES = 512
MAX_DETAILS = 256


def _fail(message, code="E_SCHEMA"):
    """! @brief 원문 패널을 임의로 수정하지 않고 형식 또는 배치 오류를 반환한다."""
    raise ProjectError(code, message)


def _tree(raw):
    """! @brief 기존 IPC 원문 검사를 사용하고 패널이 속한 요소를 구한다."""
    summary = ipc.read(raw)
    root = ET.fromstring(raw.decode("utf-8-sig"))
    ecad = ipc._one(root, "Ecad")
    if ecad is None:
        _fail("IPC-2581C의 Ecad 제조 데이터가 필요합니다.")
    header, data = ipc._one(ecad, "CadHeader"), ipc._one(ecad, "CadData")
    if header is None or data is None:
        _fail("IPC-2581C의 CadHeader와 CadData가 필요합니다.")
    factor = ipc.UNITS_MM.get(header.get("units"))
    if factor is None:
        _fail("제조 단위를 확인하십시오.", "E_UNIT")
    steps = {node.get("name"): node for node in data.findall(ipc.NS + "Step")}
    if None in steps or "" in steps or len(steps) != len(data.findall(ipc.NS + "Step")):
        _fail("각 Step에 고유한 참조 이름이 필요합니다.")
    return summary, root, header, data, factor, steps


def _digest(node):
    """! @brief 접두사 표기가 다른 XML에서 같은 보드 정의를 정규화하여 대조한다."""
    text = ET.canonicalize(ET.tostring(node, encoding="unicode"), rewrite_prefixes=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _xy(node, keys, factor):
    """! @brief 원문 길이를 유한 mm로 환산하며 명시하지 않은 축은 거절한다."""
    values = [ipc._measure(node, key, factor) for key in keys]
    if any(value is None for value in values):
        _fail("IPC 반복 기준점과 피치의 좌표가 필요합니다.")
    return [value["converted"] for value in values]


def _count(values):
    """! @brief 1개 이상의 반복과 전체 인스턴스 예산을 검사한다."""
    if (len(values) != 2 or any(type(n) is not int or n < 1 or n > MAX_REPEAT_INSTANCES for n in values)
            or math.prod(values) > MAX_REPEAT_INSTANCES):
        _fail("X/Y에 양의 반복 횟수를 지정하고 전체 배치를 512개 이내로 제한하십시오.", "E_RESOURCE")
    return list(values)


def _repeat(node, factor, steps, board_hashes):
    """! @brief IPC의 위치, 피치, 회전, 반사와 참조 보드의 정규 해시를 읽는다."""
    target = node.get("stepRef")
    source = steps.get(target)
    if source is None or source.get("type", "BOARD") != "BOARD" or source.find(ipc.NS + "StepRepeat") is not None:
        _fail("중첩, 순환 또는 없는 참조를 제외한 단일 BOARD 반복을 지원합니다.", "E_UNSUPPORTED")
    try:
        counts = _count([int(node.get(key, "")) for key in ("nx", "ny")])
    except ValueError as error:
        raise ProjectError("E_SCHEMA", "IPC의 nx와 ny는 양의 정수여야 합니다.") from error
    origin = _xy(node, ("x", "y"), factor)
    pitch = _xy(node, ("dx", "dy"), factor)
    if any(value < 0 or (count > 1 and value == 0) for count, value in zip(counts, pitch)):
        _fail("배열 피치는 음수가 될 수 없으며 반복 축에는 양수여야 합니다.")
    numeric = ipc._measure(node, "angle", Decimal(1))
    if numeric is None or not 0 <= numeric["converted"] < 360:
        _fail("IPC의 angle은 0 이상 360 미만입니다.")
    mirrors = {"true": True, "false": False, "1": True, "0": False}
    if node.get("mirror") not in mirrors:
        _fail("IPC의 명시적 mirror 속성이 필요합니다.")
    if target not in board_hashes:
        board_hashes[target] = _digest(source)
    return {"board": target, "board_sha256": board_hashes[target], "count": counts,
            "origin_mm": origin, "pitch_mm": pitch, "angle_deg": numeric["converted"],
            "mirror": mirrors[node.get("mirror")], "source": dict(node.attrib)}


def _special(header, data, steps):
    """! @brief 시작/끝 층, 백드릴 명세, 깊이와 안티패드 원문 구조를 보존한다."""
    rows = []

    def record(kind, parent, node):
        """! @brief 명시 형상과 속성을 원래 IPC 구조의 해시와 함께 남긴다."""
        row = {"kind": kind, "location": parent, "attributes": dict(node.attrib),
               "children": [{"tag": item.tag.removeprefix(ipc.NS), "attributes": dict(item.attrib)}
                            for item in node], "sha256": _digest(node)}
        rows.append(row)
        if len(rows) > MAX_DETAILS:
            _fail("특수 제조 선언의 검토 예산을 넘었습니다.", "E_RESOURCE")

    for layer in data.findall(ipc.NS + "Layer"):
        span = ipc._one(layer, "Span")
        if span is not None:
            record("layer_span", [layer.get("name"), layer.get("layerFunction")], span)
    for spec in header.findall(ipc.NS + "Spec"):
        for row in spec.findall(ipc.NS + "Backdrill"):
            record("backdrill", [spec.get("name")], row)
    for name, step in steps.items():
        for feature in step.findall(ipc.NS + "LayerFeature"):
            for row in feature.iter():
                if row.tag not in (ipc.NS + "MaterialCut", ipc.NS + "MaterialLeft"):
                    continue
                record("z_axis_dimension", [name, feature.get("layerRef")], row)
        for padstack in step.findall(ipc.NS + "PadStackDef"):
            for row in padstack.findall(ipc.NS + "PadstackPadDef"):
                if row.get("padUse", "").upper() == "ANTIPAD":
                    record("antipad", [name, padstack.get("name"), row.get("layerRef")], row)
    return rows


def read(raw):
    """! @brief 단일 보드 참조의 패널 반복과 원래 적층 제조 선언을 읽는다."""
    summary, _, header, data, factor, steps = _tree(raw)
    panels, exclusions = [], []
    board_hashes = {}
    for name, node in steps.items():
        repeats = node.findall(ipc.NS + "StepRepeat")
        if not repeats:
            continue
        try:
            if len(repeats) > MAX_REPEAT_INSTANCES:
                _fail("반복 선언의 수가 512개를 넘습니다.", "E_RESOURCE")
            rows = [_repeat(row, factor, steps, board_hashes) for row in repeats]
            if sum(math.prod(row["count"]) for row in rows) > MAX_REPEAT_INSTANCES:
                _fail("패널의 전체 배치가 512개를 넘습니다.", "E_RESOURCE")
            datum = _xy(ipc._one(node, "Datum"), ("x", "y"), factor)
            profile = ipc._one(node, "Profile")
            polygon = None if profile is None else ipc._one(profile, "Polygon")
            if polygon is not None and len(polygon) > 65:
                _fail("패널 외곽에 최대 65개 좌표를 지원합니다.", "E_RESOURCE")
            outline = None if polygon is None or any(child.tag not in (ipc.NS + "PolyBegin", ipc.NS + "PolyStepSegment") for child in polygon) else [
                _xy(child, ("x", "y"), factor) for child in polygon]
            panels.append({"step": name, "datum_mm": datum, "outline_mm": outline, "repeats": rows})
        except ProjectError as error:
            exclusions.append({"step": name, "code": error.code, "reason": str(error)})
    return {"source_sha256": summary["source_sha256"], "units": header.get("units"),
            "steps": summary["steps"], "panels": panels, "panel_exclusions": exclusions,
            "manufacturing_declarations": _special(header, data, steps)}


def _native(value, unit):
    """! @brief 원본 단위에 맞춰 새 좌표를 유한 십진수로 작성한다."""
    return format(Decimal(str(value)) / unit, "f")


def build(raw, count, pitch, margin, angle=0):
    """! @brief 한 보드 정의를 그대로 참조하는 새 IPC 패널 후보를 작성하고 다시 읽는다."""
    if (len(pitch) != 2 or any(type(v) not in (int, float) or not 0 <= v <= 10000 for v in pitch)
            or type(margin) not in (int, float) or not 0 <= margin <= 1000 or type(angle) is not int or angle not in (0, 90, 180, 270)):
        _fail("피치, 여백과 0/90/180/270도 회전을 확인하십시오.")
    counts = _count(count)
    _, root, _, data, unit, steps = _tree(raw)
    if len(steps) != 1 or PANEL_NAME in steps:
        _fail("패널을 만들 원본에는 이름이 다른 BOARD 정의 하나가 필요합니다.", "E_UNSUPPORTED")
    name, original = next(iter(steps.items()))
    shape = ipc._editable_profile(original, unit)
    if shape is None:
        _fail("직선으로 닫힌 하나의 보드 프로파일이 필요합니다.", "E_GEOMETRY")
    validate_region(shape["outer_mm"], shape["cutouts_mm"], "board.profile")
    datum = _xy(ipc._one(original, "Datum"), ("x", "y"), unit)
    transformations = {0: lambda x, y: (x, y), 90: lambda x, y: (-y, x),
                       180: lambda x, y: (-x, -y), 270: lambda x, y: (y, -x)}
    points = [transformations[angle](x - datum[0], y - datum[1]) for x, y in shape["outer_mm"]]
    lower = [min(axis) for axis in zip(*points)]
    spans = [max(axis) - min(axis) for axis in zip(*points)]
    if any(n > 1 and distance < span - 1e-9 for n, distance, span in zip(counts, pitch, spans)):
        _fail("회전한 반복 보드의 경계 상자가 겹칩니다.", "E_GEOMETRY")
    size = [2 * margin + length + (n - 1) * distance for n, length, distance in zip(counts, spans, pitch)]
    origin = [margin - low for low in lower]
    content = ipc._one(root, "Content")
    if content is None or not len(content) or content[0].tag != ipc.NS + "FunctionMode":
        _fail("IPC의 Content 및 FunctionMode가 필요합니다.")
    if any(node.get("name") == PANEL_NAME for node in content.findall(ipc.NS + "StepRef")):
        _fail("IPC 원문에서 패널 참조 이름을 이미 사용합니다.", "E_CONFLICT")
    content.insert(1, ET.Element(ipc.NS + "StepRef", {"name": PANEL_NAME}))
    panel = ET.SubElement(data, ipc.NS + "Step", {"name": PANEL_NAME})
    ET.SubElement(panel, ipc.NS + "Datum", {"x": "0", "y": "0"})
    profile = ET.SubElement(panel, ipc.NS + "Profile")
    boundary = ET.SubElement(profile, ipc.NS + "Polygon")
    for index, (x, y) in enumerate(((0, 0), (size[0], 0), tuple(size), (0, size[1]), (0, 0))):
        tag = "PolyBegin" if index == 0 else "PolyStepSegment"
        ET.SubElement(boundary, ipc.NS + tag, {"x": _native(x, unit), "y": _native(y, unit)})
    ET.SubElement(panel, ipc.NS + "StepRepeat", {
        "stepRef": name, "x": _native(origin[0], unit), "y": _native(origin[1], unit),
        "nx": str(counts[0]), "ny": str(counts[1]), "dx": _native(pitch[0], unit),
        "dy": _native(pitch[1], unit), "angle": str(angle), "mirror": "false",
    })
    result = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    rebuilt = read(result)
    if len(rebuilt["panels"]) != 1 or rebuilt["panel_exclusions"]:
        _fail("작성한 IPC 패널을 다시 읽을 수 없습니다.", "E_CONFLICT")
    [verified] = rebuilt["panels"]
    [row] = verified["repeats"]
    outline = verified["outline_mm"]
    if outline is None or len(outline) != 5 or any(not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
                                                    for a, b in zip(outline[2], size)):
        _fail("IPC 패널 외곽이 왕복에서 달라졌습니다.", "E_CONFLICT")
    if (row["board_sha256"] != _digest(original) or row["count"] != counts or row["angle_deg"] != angle
            or row["mirror"] or any(not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
                                   for a, b in zip(row["origin_mm"] + row["pitch_mm"], origin + list(pitch)))):
        _fail("IPC 반복, 단위 또는 참조 보드가 왕복에서 달라졌습니다.", "E_CONFLICT")
    return result
