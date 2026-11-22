"""! @brief IPC-2581 Rev C의 원본 제조 속성을 읽기 전용으로 검토한다."""

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
            "step_repeats": len(repeats), "net_examples": [row.get("name") for row in nets[:SAMPLE_LIMIT]],
            "component_examples": placements, "hole_examples": [
                {**_attrs(row, "name", "platingStatus"), "drill_layer_ref": layer,
                 "diameter_mm": _measure(row, "diameter", factor), "x_mm": _measure(row, "x", factor),
                 "y_mm": _measure(row, "y", factor)} for layer, row in holes[:SAMPLE_LIMIT]]}


def read(raw):
    """! @brief UTF-8 Rev C 원문과 제조 요약을 결합하되 설계 개정에 적용하지 않는다."""
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
    return {"schema": "rfad.ipc2581-read/0.1", "version": "C", "units": units,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "writer": None if history is None else history.get("software"),
            "sections": sorted({element.tag[len(NS):] for element in root if element.tag.startswith(NS)}),
            "samples_per_step_limit": SAMPLE_LIMIT,
            "layers": [_attrs(row, "name", "layerFunction", "side", "polarity") for row in layers],
            "stackups": [{"name": item.get("name"), "thickness_mm": _measure(item, "overallThickness", factor),
                          "layers": [{**_attrs(row, "layerOrGroupRef", "sequence"),
                                      "thickness_mm": _measure(row, "thickness", factor)}
                                     for row in item.iter(NS + "StackupLayer")]} for item in stackups],
            "steps": [_step(step, factor) for step in steps],
            "losses": [{"code": "ipc2581_review_only", "raw_preserved": True,
                        "message": "IPC-2581 Rev C는 층, 넷, 홀 및 부품의 원본 검토를 제공합니다. 설계 반영과 재출력은 추가 작업입니다."}]}
