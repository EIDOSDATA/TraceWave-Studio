"""! @brief 제조 원문의 부품 배치와 실제 단자에 대응하는 양극성 원형 패드를 읽는다."""
import math
import re
from rfad.adapters.exchange.manufacturing_contacts import number, point


def _unique(rows):
    """! @brief 참조 번호를 임의로 변경하지 않고 중복과 초과는 미반영 원문으로 둔다."""
    names = [row["reference"] for row in rows]
    return rows if len(rows) <= 32 and len(names) == len(set(names)) else []


def ipc(root, step, layers, scale, pads, bores):
    """! @brief 명시 부품의 위치/면과 Xform을 보드 좌표로 변환하고 PinRef로 실제 패드만 추적한다."""
    from rfad.adapters.exchange.ipc2581_reader import NS
    sides = {r.get("name"): {"TOP": "top", "BOTTOM": "bottom"}[r.get("side")] for r in layers
             if r.get("side") in {"TOP", "BOTTOM"} and r.get("layerFunction") == "CONDUCTOR"}
    kicad = any(software.get("name") == "KiCad" for software in root.iter(NS + "SoftwarePackage"))
    values = {}
    for item in root.iter(NS + "BomItem"):
        declared = [v.get("textualCharacteristicValue") for v in item.iter(NS + "Textual")
                    if v.get("definitionSource") == "KICAD" and v.get("textualCharacteristicName") == "Value"]
        for ref in item.findall(NS + "RefDes"):
            if len(declared) == 1:
                values[ref.get("name")] = declared[0] or None
    through = {identity for hole in bores for identity in hole["pads"]}
    regular = {p["source_id"]: p for p in pads if p["source_id"] not in through}
    pins = {}
    for i, feature in enumerate(step.findall(NS + "LayerFeature")):
        for j, group in enumerate(feature.findall(NS + "Set")):
            for k, item in enumerate(group):
                key = f"contact:{i}:{j}:{k}"
                refs = item.findall(NS + "PinRef")
                if key in regular and len(refs) == 1 and refs[0].get("pin"):
                    pins.setdefault(refs[0].get("componentRef"), []).append(
                        {"source_id": key, "number": refs[0].get("pin"), "side": sides.get(regular[key]["layer"])})
    records = []
    for item in step.findall(NS + "Component"):
        ref, side = item.get("refDes"), sides.get(item.get("layerRef"))
        if not ref or not side or (kicad and re.fullmatch(r"NOREF_[0-9a-fA-F]{8}", ref)):
            continue
        transforms, locations = item.findall(NS + "Xform"), item.findall(NS + "Location")
        if len(transforms) > 1 or len(locations) != 1:
            continue
        transform = transforms[0].attrib if transforms else {}
        mirror = transform.get("mirror", "false")
        angle = number(transform.get("rotation", "0"))
        xy = point(locations[0].get("x"), locations[0].get("y"), scale)
        if (xy is None or angle is None or set(transform) - {"mirror", "rotation"} or
                (side, mirror) not in {("top", "false"), ("top", "0"), ("bottom", "true"), ("bottom", "1")}):
            continue
        records.append({"source_id": "component:" + ref, "reference": ref, "side": side, "origin_mm": xy,
                        "rotation_deg": math.remainder(angle if side == "top" else 180 - angle, 360),
                        "value": values.get(ref), "pins": [p for p in pins.get(ref, []) if p["side"] == side]})
    return _unique(records)


def odb(archive, names, base, matrix, pads, bores, kicad):
    """! @brief 실제 COMPONENT 층의 CMP, TOP과 EDA 서브넷 인덱스를 대응한다."""
    from rfad.adapters.exchange.odb_reader import FACTORS, _text
    if base + "eda/data" not in names:
        return []
    eda = _text(archive, base + "eda/data").splitlines()
    groups, packages = {}, 0
    for index, text in enumerate(eda):
        words = text.split(";", 1)[0].split()
        if words[:1] == ["PKG"]:
            packages += 1
        if len(words) == 5 and words[:2] == ["SNT", "TOP"] and words[2] in {"T", "B"}:
            groups[(words[2], words[3], words[4])] = index
    through = {identity for hole in bores for identity in hole["pads"]}
    records = []
    for block in re.findall(r"(?:^|\n)LAYER\s*\{([^{}]*)\}", matrix):
        layer = dict(v.strip().split("=", 1) for v in block.splitlines() if "=" in v)
        name = layer.get("NAME", "").casefold()
        side = {"comp_+_top": "top", "comp_+_bot": "bottom"}.get(name)
        path = base + "layers/" + name + "/components"
        if not side or layer.get("TYPE") != "COMPONENT" or layer.get("CONTEXT") != "BOARD" or path not in names:
            continue
        unit, current, occurrence = None, None, -1
        lines = _text(archive, path).splitlines()
        units = [line[6:].strip() for line in lines if line.startswith("UNITS=")]
        if len(units) != 1 or units[0] not in FACTORS:
            continue
        unit = FACTORS[units[0]]
        for line in lines:
            words = line.split(";", 1)[0].split()
            if words[:1] == ["CMP"]:
                current = None
                occurrence += 1
                if len(words) != 8 or not re.fullmatch(r"[0-9]{1,8}", words[1]) or int(words[1]) >= packages:
                    continue
                xy, angle, ref = point(words[2], words[3], unit), number(words[4]), words[6]
                if xy is None or angle is None or (side, words[5]) not in {("top","N"),("bottom","M")}:
                    continue
                if kicad and re.fullmatch(r"UNNAMED[0-9]+", ref):
                    continue
                current = {"source_id": "component:" + ref, "reference": ref, "side": side,
                           "origin_mm": xy, "rotation_deg": math.remainder(-angle,360), "value": None, "pins": []}
                records.append(current)
            elif current is not None and words[:2] == ["PRP", "Value"]:
                match = re.fullmatch(r"PRP Value '([^']*)'", line.strip())
                if match and match[1]:
                    current["value"] = match[1]
            elif current is not None and words[:1] == ["TOP"] and len(words) == 9:
                group = groups.get(("T" if side == "top" else "B", str(occurrence), words[1]))
                xy = point(words[2], words[3], unit)
                if group is not None and xy is not None:
                    for pad in pads:
                        if pad["group"] == group and pad["source_id"] not in through and math.dist(xy,pad["center_mm"]) <= 1e-6:
                            current["pins"].append({"source_id": pad["source_id"], "number": words[8], "side": side})
    return _unique(records)
