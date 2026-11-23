"""! @brief 제조 원본의 양극성 원형 패드, 관통 원형 홀과 선언 적층을 보존한다."""

import math
import re


def number(text, scale=1):
    """! @brief 지정된 단위의 유한한 입력만 mm 좌표로 변환한다."""
    try:
        result = float(text) * float(scale)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and abs(result) <= 1e6 else None


def point(x, y, scale):
    """! @brief 지정되지 않은 좌표를 원점으로 추정하지 않는다."""
    result = [number(x, scale), number(y, scale)]
    return None if None in result else result


def ipc(root, step, layers, stackups, scale):
    """! @brief 사전의 원형 표준 도형, 홀 span과 단일 적층 그룹을 대응한다."""
    from rfad.adapters.exchange.ipc2581_reader import NS, UNITS_MM

    pads, holes, stack = [], [], []
    primitives, seen = {}, set()
    for table in root.iter(NS + "DictionaryStandard"):
        unit = UNITS_MM.get(table.get("units"))
        for entry in table.findall(NS + "EntryStandard"):
            key = entry.get("id")
            if key in seen:
                primitives.pop(key, None)
                continue
            seen.add(key)
            if unit and len(entry) == 1 and entry[0].tag == NS + "Circle" and not len(entry[0]):
                value = number(entry[0].get("diameter"), unit)
                if value and value > 0:
                    primitives[key] = {"diameter_mm": value}
            if unit and len(entry) == 1 and entry[0].tag == NS + "RectCenter" and not len(entry[0]):
                sizes = [number(entry[0].get(key), unit) for key in ("width", "height")]
                if all(value and value > 0 for value in sizes):
                    primitives[key] = {"pad_shape": "rectangle", "size_mm": sizes}
    by_layer = {layer.get("name"): layer for layer in layers if layer.get("polarity") == "POSITIVE"}
    if len({layer.get("name") for layer in layers}) != len(layers):
        return [], [], []
    def role(layer):
        """! @brief 전기 재료를 추정하지 않고 제조 원문의 층 역할만 대응한다."""
        return {"CONDUCTOR": "conductor", "DIELCORE": "dielectric", "DIELPREG": "dielectric"}.get(layer.get("layerFunction"))
    if len(stackups) == 1:
        groups = stackups[0].findall(NS + "StackupGroup")
        if len(groups) == 1 and groups[0].find(NS + "StackupGroup") is None:
            ordered = []
            for row in groups[0].findall(NS + "StackupLayer"):
                layer = by_layer.get(row.get("layerOrGroupRef"))
                if layer is not None and role(layer):
                    seq = row.get("sequence", "")
                    thickness = number(row.get("thickness"), scale)
                    if not seq.isdecimal() or len(seq) > 8 or thickness is None or thickness <= 0:
                        ordered = []
                        break
                    ordered.append((int(seq), {"layer": layer.get("name"), "role": role(layer), "thickness_mm": thickness}))
                elif layer is None or layer.get("layerFunction") not in {"SOLDERMASK", "SOLDERPASTE", "SILKSCREEN"}:
                    ordered = []
                    break
            if len({order for order, _ in ordered}) == len(ordered) and len({item["layer"] for _, item in ordered}) == len(ordered):
                stack = [item for _, item in sorted(ordered, key=lambda value: value[0])]
    conductor = [row["layer"] for row in stack if row["role"] == "conductor"]
    features = step.findall(NS + "LayerFeature")
    negative = {f.get("layerRef") for f in features if any(n.get("polarity", "POSITIVE") != "POSITIVE" for n in f.iter())}
    for i, feature in enumerate(features):
        name = feature.get("layerRef")
        layer = by_layer.get(name)
        if name in negative or layer is None or set(feature.attrib) != {"layerRef"}:
            continue
        for j, group in enumerate(feature.findall(NS + "Set")):
            if set(group.attrib) - {"net", "geometry", "polarity"} or group.find(NS + "Xform") is not None:
                continue
            net = group.get("net", "")
            for k, item in enumerate(group):
                identity = f"contact:{i}:{j}:{k}"
                if item.tag == NS + "Pad" and role(layer) == "conductor":
                    if any(c.tag not in {NS + "Location", NS + "StandardPrimitiveRef", NS + "PinRef", NS + "Xform"} for c in item):
                        continue
                    transforms = item.findall(NS + "Xform")
                    if len(transforms) > 1 or any(set(t.attrib) - {"rotation", "mirror"} for t in transforms):
                        continue
                    locations, definitions = item.findall(NS + "Location"), item.findall(NS + "StandardPrimitiveRef")
                    if len(locations) != 1 or len(definitions) != 1:
                        continue
                    at = point(locations[0].get("x"), locations[0].get("y"), scale)
                    shape = primitives.get(definitions[0].get("id"))
                    angle = number(transforms[0].get("rotation", "0")) if transforms else 0
                    mirror = transforms[0].get("mirror", "false") if transforms else "false"
                    if shape and "size_mm" in shape and mirror not in ("false", "0"):
                        continue
                    if at and shape and angle is not None:
                        geometry = {**shape, "rotation_deg": math.remainder(angle, 360)} if "size_mm" in shape else shape
                        pads.append({"source_id": identity, "layer": name, "net": net, "center_mm": at,
                                     **geometry, "group": item.get("padstackDefRef")})
                elif item.tag == NS + "Hole" and layer.get("layerFunction") == "DRILL":
                    spans = layer.findall(NS + "Span")
                    if len(spans) != 1 or len(conductor) < 2:
                        continue
                    span = [spans[0].get("fromLayer"), spans[0].get("toLayer")]
                    if set(span) != {conductor[0], conductor[-1]}:
                        continue
                    at = point(item.get("x"), item.get("y"), scale)
                    size = number(item.get("diameter"), scale)
                    state = {"PLATED": "plated", "VIA": "plated", "NONPLATED": "unplated"}.get(item.get("platingStatus"))
                    if at and size and size > 0 and state:
                        holes.append({"source_id": identity, "net": net, "center_mm": at, "diameter_mm": size,
                                      "plating": state, "group": group.get("geometry"), "span": span})
    return finish(pads, holes, stack)


def finish(pads, holes, stack):
    """! @brief 원문에서 대응하는 패드 그룹, 넷 및 동일 중심만 홀 참조에 연결한다."""
    if len(pads) > 128 or len(holes) > 64:
        return [], [], stack
    for hole in holes:
        hole["pads"] = [pad["source_id"] for pad in pads if hole["plating"] == "plated" and hole["group"] is not None
                        and pad["group"] == hole["group"] and hole["net"] == pad["net"]
                        and math.dist(hole["center_mm"], pad["center_mm"]) <= 1e-6]
    return pads, holes, stack


def _pin_groups(lines):
    """! @brief ODB EDA 핀 및 비아의 FID C와 FID H에 동일 서브넷 번호를 기록한다."""
    names, current, group, terminals = [], None, None, {}
    for index, text in enumerate(lines.splitlines()):
        row = text.split(";", 1)[0].split()
        if not row:
            continue
        if row[0] == "LYR":
            if names:
                return {}
            names = [name.casefold() for name in row[1:]]
        elif row[0] == "NET":
            current = ("" if row[1] == "$NONE$" else row[1]) if len(row) == 2 else None
            group = None
        elif row[0] == "SNT":
            group = index if len(row) >= 2 and row[1] in {"TOP", "VIA"} else None
        elif row[0] == "PKG":
            break
        elif row[0] == "FID" and len(row) == 4 and row[1] in ("C", "H") and group is not None and current is not None:
            if not all(token.isdecimal() and len(token) <= 8 for token in row[2:]) or int(row[2]) >= len(names):
                return {}
            key = (row[1], names[int(row[2])], int(row[3]))
            if key in terminals:
                return {}
            terminals[key] = (current, group)
    return terminals


def _odb_pads(text):
    """! @brief 상쇄 특징 없는 레이어에서 순번 보존 원형 플래시와 원형 심벌 치수를 읽는다."""
    from rfad.adapters.exchange.odb_reader import FACTORS

    symbols, found, declared = {}, [], set()
    index, scale = -1, None
    for line in text.splitlines():
        row = line.split(";", 1)[0].split()
        if not row or row[0].startswith(("#", "@", "&")):
            continue
        op = row[0]
        if op.startswith("UNITS="):
            if scale is not None or op[6:] not in FACTORS:
                return []
            scale = FACTORS[op[6:]]
        elif op.startswith("$") and scale is not None:
            if op[1:] in declared:
                return []
            declared.add(op[1:])
            if len(row) == 2 and re.fullmatch(r"r[0-9]+(?:[.][0-9]+)?", row[1]):
                size = number(row[1][1:], scale / 1000)
                if size and size > 0:
                    symbols[op[1:]] = {"diameter_mm": size}
            elif len(row) == 2 and re.fullmatch(r"rect[0-9]+(?:[.][0-9]+)?x[0-9]+(?:[.][0-9]+)?", row[1]):
                sizes = [number(value, scale / 1000) for value in row[1][4:].split("x")]
                if all(value and value > 0 for value in sizes):
                    symbols[op[1:]] = {"pad_shape": "rectangle", "size_mm": sizes}
        elif op in {"L", "A", "P", "S", "T", "B"}:
            index += 1
            polarity = {"L": 6, "A": 8, "P": 4, "S": 1, "T": 5, "B": 5}[op]
            if len(row) <= polarity or row[polarity] != "P":
                return []
            if op == "P" and len(row) in (7, 8) and row[3] in symbols and scale is not None:
                at = point(row[1], row[2], scale)
                shape = symbols[row[3]]
                if "size_mm" in shape:
                    code = row[6]
                    angle = None
                    if code in ("8", "9") and len(row) == 8:
                        angle = number(row[7])
                    elif len(row) == 7 and code in "01234567" and len(code) == 1:
                        angle = (int(code) % 4) * 90
                    if angle is not None and code in ("0", "1", "2", "3", "8"):
                        # @brief ODB 회전 뒤 X축 반사는 중심 사각형의 회전 부호를 다시 바꾼다.
                        angle = -angle
                    if angle is None:
                        continue
                    shape = {**shape, "rotation_deg": math.remainder(angle, 360)}
                if at:
                    found.append((index, at, shape))
        elif op not in {"F", "OB", "OS", "OC", "OE", "SE"}:
            return []
    return found


def odb(archive, names, prefix, step, matrix, info):
    """! @brief 전도층 원형 패드와 보드 양끝을 관통하는 드릴의 도금, 완성 지름, 망을 연결한다."""
    from rfad.adapters.exchange.odb_reader import FACTORS, _text

    base = prefix + "steps/" + step + "/"
    blocks = [dict(row.strip().split("=", 1) for row in block.splitlines() if "=" in row)
              for block in re.findall(r"(?:^|\n)LAYER\s*\{([^{}]*)\}", matrix)]
    if any(not layer.get("ROW", "").isdecimal() or len(layer["ROW"]) > 8 or not layer.get("NAME") for layer in blocks):
        return [], [], []
    blocks.sort(key=lambda layer: int(layer["ROW"]))
    if len({b["NAME"].casefold() for b in blocks}) != len(blocks) or len({int(b["ROW"]) for b in blocks}) != len(blocks):
        return [], [], []
    copper = [b["NAME"].casefold() for b in blocks if b.get("TYPE") == "SIGNAL" and b.get("CONTEXT") == "BOARD"]
    pins = _pin_groups(_text(archive, base + "eda/data")) if base + "eda/data" in names else {}
    pads, holes, stack = [], [], []
    kicad = info.get("SAVE_APP") == "KiCad EDA 10.0.8"
    unit = FACTORS.get(info.get("UNITS"))
    physical_layers = {"SIGNAL", "DIELECTRIC", "SOLDER_MASK", "SOLDER_PASTE", "SILK_SCREEN", "COMPONENT", "DRILL"}
    stack_ok = kicad and unit is not None and all(b.get("TYPE") in physical_layers for b in blocks if b.get("CONTEXT") == "BOARD")
    for layer in blocks:
        name = layer["NAME"].casefold()
        if layer.get("CONTEXT") != "BOARD" or "/" in name:
            continue
        path = base + "layers/" + name + "/"
        kind = layer.get("TYPE")
        if kind in {"SIGNAL", "DIELECTRIC"} and stack_ok:
            meta = _text(archive, path + "attrlist") if path + "attrlist" in names else ""
            rows = [row.split("=", 1)[1] for row in meta.splitlines() if row.startswith(".layer_dielectric=")]
            thickness = number(rows[0], unit) if len(rows) == 1 else None
            if thickness and thickness > 0:
                stack.append({"layer": name, "role": "conductor" if kind == "SIGNAL" else "dielectric",
                              "thickness_mm": thickness})
            else:
                stack_ok = False
        if kind not in {"SIGNAL", "DRILL"} or layer.get("POLARITY") != "POSITIVE" or path + "features" not in names:
            continue
        tools = []
        if kind == "DRILL":
            if (len(copper) < 2 or {layer.get("START_NAME", "").casefold(), layer.get("END_NAME", "").casefold()}
                    != {copper[0], copper[-1]} or layer.get("ADD_TYPE") or path + "tools" not in names):
                continue
            raw = _text(archive, path + "tools")
            tool_unit = FACTORS.get(next((v[6:] for v in raw.splitlines() if v.startswith("UNITS=")), ""))
            if tool_unit is None:
                continue
            # @brief KiCad 10.0.8은 FINISH_SIZE에 파일 길이 단위를 쓴다. 다른 원본은 사양의 mil/um를 사용한다.
            scale = tool_unit if kicad else tool_unit / 1000
            for tool in re.findall(r"(?:^|\n)TOOLS\s*\{([^{}]*)\}", raw):
                attr = dict(v.strip().split("=", 1) for v in tool.splitlines() if "=" in v)
                diameter = number(attr.get("FINISH_SIZE"), scale)
                state = {"VIA": "plated", "PLATED": "plated", "NON_PLATED": "unplated"}.get(attr.get("TYPE"))
                if diameter and diameter > 0 and state:
                    tools.append((diameter, state))
        for index, at, shape in _odb_pads(_text(archive, path + "features")):
            relation = pins.get(("C" if kind == "SIGNAL" else "H", name, index))
            identity = f"contact:{name}:{index}"
            if kind == "SIGNAL" and relation:
                pads.append({"source_id": identity, "center_mm": at, "net": relation[0], "group": relation[1],
                             **shape, "layer": name})
            elif kind == "DRILL" and "diameter_mm" in shape:
                diameter = shape["diameter_mm"]
                matches = {state for size, state in tools if abs(size - diameter) <= 1e-6}
                if len(matches) == 1:
                    state, = matches
                    if state == "plated" and relation is None:
                        continue
                    holes.append({"source_id": identity, "center_mm": at, "diameter_mm": diameter,
                                  "net": relation[0] if relation else "", "group": relation[1] if relation else None,
                                  "plating": state, "span": [copper[0], copper[-1]]})
    return finish(pads, holes, stack if stack_ok else [])
