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
