"""! @brief 제조 자료의 원형 패드와 관통 홀, 기존 적층의 선언 두께를 명시적으로 적용한다."""

import math

from rfad.application.pcb_exchange_projection import point, scalar
from rfad.domain.pcb_features import fail


def _same_center(document, original, expected):
    """! @brief 미정 좌표를 배제하고 파일의 1 nm 정밀도로 중심 위치를 확인한다."""
    xy = point(document, original)
    return None not in xy and math.dist(xy, expected) <= 2e-6


def _bind(candidate, collection, identity):
    """! @brief 기존 객체와 수입 특징 사이의 출처만 새 수입 기록에 연결한다."""
    candidate.record["bindings"].append({"source_object_id": candidate.source, "collection": collection, "id": identity})


def contacts(candidate, data):
    """! @brief 서로 대응하는 원본 핀 특징만 동일 홀의 패드와 넷으로 연결한다."""
    document = candidate.document
    pad_ids = {}
    for item in data.get("editable_pads", []):
        candidate.source = item["source_id"]
        layer, net = candidate.layer(item["layer"]), candidate.net(item["net"])
        matches = [row for row in document["geometry"] if row["kind"] == "pad" and row["layer_id"] == layer
                   and row["frame_id"] == candidate.mapping["frame_id"]
                   and _same_center(document, row["center"], item["center_mm"])]
        if matches:
            row = matches[0]
            dims = point(document, row["size"])
            if (len(matches) != 1 or row["pad_shape"] != "circle" or row["net_id"] != net or None in dims
                    or any(abs(v - item["diameter_mm"]) > 2e-6 for v in dims)):
                fail("같은 위치의 기존 패드와 형상 또는 넷이 다릅니다.", "mapping.nets", "E_CONFLICT")
            _bind(candidate, "geometry", row["id"])
        else:
            row = candidate.geometry("pad", layer, net)
            row.update(pad_shape="circle", center=candidate.point(item["center_mm"]),
                       size=candidate.point([item["diameter_mm"]] * 2), rotation=candidate.quantity(0, "deg"))
            row = candidate.append("geometry", row)
        pad_ids[candidate.source] = row["id"]
    conductor = sorted((row for row in document["stackup"] if row["role"] == "conductor"), key=lambda row: row["order"])
    for item in data.get("editable_holes", []):
        candidate.source = item["source_id"]
        if len(conductor) < 2 or {candidate.layer(s) for s in item["span"]} != {conductor[0]["id"], conductor[-1]["id"]}:
            fail("관통 홀 양끝을 현재 보드의 바깥 도체층에 대응하십시오.", "mapping.layers")
        net = candidate.net(item["net"]) if item["plating"] == "plated" else None
        pads = [pad_ids[key] for key in item["pads"]]
        matches = [row for row in document["pcb"]["holes"] if row["frame_id"] == candidate.mapping["frame_id"]
                   and _same_center(document, row["shape"]["center"], item["center_mm"])]
        if matches:
            row = matches[0]
            bore = scalar(document, row["shape"]["diameter"]) if row["shape"]["kind"] == "circle" else None
            if (len(matches) != 1 or bore is None or abs(bore - item["diameter_mm"]) > 2e-6
                    or row["plating"]["state"] != item["plating"] or row["plating"]["net_id"] != net
                    or not set(pads) <= set(row["plating"]["pad_ids"])):
                fail("같은 위치의 기존 홀과 지름, 도금 또는 패드 연결이 다릅니다.", "mapping", "E_CONFLICT")
            _bind(candidate, "pcb.holes", row["id"])
        else:
            shape = {"kind": "circle", "center": candidate.point(item["center_mm"]),
                     "diameter": candidate.quantity(item["diameter_mm"])}
            candidate.hole(shape, item["plating"], pads, net)
    return pad_ids


def stack(candidate, data):
    """! @brief 원본과 같은 도체/유전체 순서에서 아래 기준면과 층 ID를 유지하며 두께를 채택한다."""
    original = list(reversed(data.get("editable_stack", [])))
    document = candidate.document
    layers = sorted(document["stackup"], key=lambda row: row["order"])
    if not original or [r["role"] for r in original] != [r["role"] for r in layers]:
        fail("원문과 현재 적층의 아래에서 위로 나열한 도체 및 유전체 순서가 다릅니다.", "mapping.adopt_stack")
    current = [scalar(document, row["z_min"]) for row in layers]
    thickness = [scalar(document, row["thickness"]) for row in layers]
    if None in current or None in thickness or any(abs(current[i + 1] - current[i] - thickness[i]) > 2e-6
                                                   for i in range(len(layers) - 1)):
        fail("명시된 아래 기준면과 연속된 기존 층 위치가 있어야 두께를 반영할 수 있습니다.", "mapping.adopt_stack")
    lower = current[0]
    for i, (source, layer) in enumerate(zip(original, layers)):
        candidate.source = "stack:" + source["layer"]
        if source["layer"] in candidate.layers and candidate.layers[source["layer"]] != layer["id"]:
            fail("적층 순서의 도체층과 지정한 원문 대응이 다릅니다.", "mapping.layers", "E_CONFLICT")
        if abs(current[i] - lower) > 1e-9:
            layer["z_min"] = candidate.quantity(lower)
        width = source["thickness_mm"]
        if abs(thickness[i] - width) > 1e-9:
            layer["thickness"] = candidate.quantity(width)
        lower += width
        _bind(candidate, "stackup", layer["id"])


def placements(candidate, data, pad_ids):
    """! @brief 원문 실장 위치와 명시 핀만 연결하고 미지 부품 외곽 및 3D 모델을 생성하지 않는다."""
    import math
    from rfad.application.pcb_exchange_service import new_record
    document = candidate.document
    footprints = document["pcb"]["footprints"]
    owners = {m["id"]: f["id"] for f in footprints for m in f["members"] if m["collection"] == "geometry"}
    for item in data.get("editable_components", []):
        candidate.source = item["source_id"]
        found = [f for f in footprints if f["reference"] == item["reference"]]
        if found:
            row = found[0]
            place = row["placement"]
            angle = scalar(document, place["rotation"], "angle")
            if (len(found) != 1 or place["side"] != item["side"] or angle is None
                    or not _same_center(document, place["origin"], item["origin_mm"])
                    or abs(math.remainder(angle - item["rotation_deg"], 360)) > 1e-5
                    or (row["value"] and item["value"] and row["value"] != item["value"])):
                fail("같은 참조 번호의 기존 실장 면, 위치, 회전 또는 표시값이 다릅니다. " + item["reference"], "mapping.include_components", "E_CONFLICT")
            _bind(candidate, "pcb.footprints", row["id"])
        else:
            row = new_record(document, "footprint")
            row.update(name=item["reference"], reference=item["reference"], value=item["value"], edit_state="original",
                       placement={"origin": candidate.point(item["origin_mm"]), "side": item["side"],
                                  "rotation": candidate.quantity(item["rotation_deg"], "deg")})
            row = candidate.append("footprint", row)
        for pin in item["pins"]:
            identity = pad_ids.get(pin["source_id"])
            if identity is None:
                continue
            if identity in owners and owners[identity] != row["id"]:
                fail("원문 핀이 다른 풋프린트의 패드를 가리킵니다.", "mapping.include_components", "E_CONFLICT")
            members = {v["id"] for v in row["members"] if v["collection"] == "geometry"}
            if identity not in members:
                row["members"].append({"collection": "geometry", "id": identity})
                owners[identity] = row["id"]
            prior = next((p for p in row["pins"] if identity in p["pad_ids"]), None)
            if prior and prior["number"] != pin["number"]:
                fail("기존 핀 번호와 원문 핀 번호가 다릅니다.", "mapping.include_components", "E_CONFLICT")
            target = next((p for p in row["pins"] if p["number"] == pin["number"]), None)
            if target is None:
                row["pins"].append({"number": pin["number"], "pad_ids": [identity], "hole_id": None})
            elif identity not in target["pad_ids"]:
                target["pad_ids"].append(identity)


def _boundary_key(loop):
    """! @brief 동일 경계의 시작점, 진행 방향과 공선 중간점 차이를 1 nm 좌표에서 정규화한다."""
    if len(loop) < 3 or any(None in pt for pt in loop):
        return ()
    points = [tuple(round(v * 1e6) for v in pt) for pt in loop]
    points = [b for a, b, c in zip(points[-1:] + points[:-1], points, points[1:] + points[:1])
              if (b[0] - a[0]) * (c[1] - b[1]) != (b[1] - a[1]) * (c[0] - b[0])]
    if len(points) < 3:
        return ()
    def rotated(items):
        """! @brief 사전식 최소 꼭짓점에서 고리를 시작한다."""
        start = items.index(min(items))
        return tuple(items[start:] + items[:start])
    return min(rotated(points), rotated(list(reversed(points))))


def regions(candidate, items):
    """! @brief 닫힌 양극성 동박의 외곽과 절연 구멍을 동일 좌표계와 명시한 넷에 연결한다."""
    for item in items:
        candidate.source = item["source_id"]
        layer, net = candidate.layer(item["layer"]), candidate.net(item["net"])
        if net is None:
            fail("채움 동박에는 대응할 대상 넷을 지정하십시오.", "mapping.nets", "E_CONFLICT")
        outline = _boundary_key(item["outer_mm"])
        holes = sorted(_boundary_key(loop) for loop in item["holes_mm"])
        matches = [r for r in candidate.document["geometry"] if r["kind"] == "planar_region" and r["layer_id"] == layer
                   and r["frame_id"] == candidate.mapping["frame_id"]
                   and _boundary_key([point(candidate.document, pt) for pt in r["outer"]]) == outline]
        if matches:
            shape = matches[0]
            existing = sorted(_boundary_key([point(candidate.document, pt) for pt in loop]) for loop in shape["holes"])
            if len(matches) != 1 or shape["net_id"] != net or existing != holes:
                fail("같은 외곽의 기존 동박과 넷 또는 절연 구멍이 다릅니다.", "mapping.nets", "E_CONFLICT")
            _bind(candidate, "geometry", shape["id"])
        else:
            shape = candidate.geometry("planar_region", layer, net)
            shape.update(outer=[candidate.point(pt) for pt in item["outer_mm"]],
                         holes=[[candidate.point(pt) for pt in loop] for loop in item["holes_mm"]])
            candidate.append("geometry", shape)
