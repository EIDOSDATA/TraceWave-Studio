"""! @brief 선언한 제조 한계와 실제 치수를 비교하고 미정/미지원 규칙을 별도 보고한다."""

from rfad.domain.boundary_distance import point_distance
from rfad.domain.check_connections import _connect
from rfad.domain.check_geometry import scalar, board_clearance
from rfad.domain.design_rules import RULES
from rfad.domain.errors import ProjectError


def _span(document, row):
    """! @brief 실제 시작/끝 도체층의 물리 범위를 읽는다."""
    layers = {layer["id"]:layer for layer in document["stackup"]}
    first, last = layers[row["layer_id"]], layers[row["end_layer_id"]]
    low = scalar(document, first["z_min"])
    high = scalar(document, last["z_min"]) + scalar(document, last["thickness"])
    return low, high


def check_vias(document, shapes, graph, possible, report):
    """! @brief 실제 annular 부착/층 범위를 확인한 명시적 비아 pad만 연결한다."""
    layers = {layer["id"]:layer for layer in document["stackup"]}
    measures = {}
    for identity, shape in shapes.items():
        row = shape.source
        if row["kind"] != "via":
            continue
        outer, center = shape.edges[0].radius, shape.edges[0].center
        field = "geometry." + identity
        try:
            low, high = _span(document,row)
            report.add("via_span", "passed" if high > low else "failed", "실제 도체층 z/thickness의 비아 범위를 검사합니다.",
                       objects=[identity],paths=[field],measured=high-low,limit=0.0,location=list(center))
        except ProjectError:
            low, high = None, None
            report.add("via_span","not_evaluated","비아 층 높이/두께가 미정입니다.",objects=[identity],paths=[field])
        try:
            tool = scalar(document,row["tool_hole_diameter"])
            report.add("via_tool_relation", "passed" if abs(tool-2*outer) <= shape.guard else "failed",
                       "공구 드릴과 finished hole + 2*plating 관계를 검사합니다. 자동 보정하지 않습니다.",
                       objects=[identity],paths=[field+".tool_hole_diameter"],measured=tool,limit=2*outer,location=list(center))
        except ProjectError:
            tool = None
            report.add("via_tool_relation","not_evaluated","공구 드릴 지름이 미정입니다.",objects=[identity],paths=[field+".tool_hole_diameter"])
        rings, attached, unresolved_pad = [], set(), False
        for pad_id in row["pad_ids"]:
            pad = shapes.get(pad_id)
            if pad is None:
                rings.append(None)
                unresolved_pad = True
                report.add("via_pad_attachment","not_evaluated","명시적 pad의 치수/포함 범위가 미정입니다.",objects=[identity,pad_id],paths=[field+".pad_ids"])
                continue
            margin = min(point_distance(center,edge)[0] for edge in pad.edges)
            inside = pad.contains(center)
            signed_margin = margin if inside else -margin
            rings.append(signed_margin - tool/2 if tool is not None else None)
            try:
                layer = layers[pad.source["layer_id"]]
                z, thickness = scalar(document,layer["z_min"]),scalar(document,layer["thickness"])
                valid_z = low is not None and high is not None and low <= z and z + thickness <= high
                status = "passed" if valid_z and inside and margin > outer else "failed"
                if low is None or high is None:
                    status = "not_evaluated"
            except ProjectError:
                status = "not_evaluated"
            unresolved_pad = unresolved_pad or status == "not_evaluated"
            report.add("via_pad_attachment",status,"명시적 pad의 실제 barrel 피복과 층 높이를 검사합니다.",
                       objects=[identity,pad_id],paths=[field+".pad_ids","geometry."+pad_id],measured=signed_margin-outer,
                       limit=0.0,location=list(center))
            if status == "passed":
                _connect(graph,identity,pad_id)
                _connect(possible,identity,pad_id)
                attached.add(pad.source["layer_id"])
                if row["net_id"] is None or pad.source["net_id"] is None:
                    report.add("via_pad_net","not_evaluated","비아/pad의 net이 미정입니다.",objects=[identity,pad_id])
                elif row["net_id"] != pad.source["net_id"]:
                    report.add("different_net_short","failed","실제 부착된 비아와 pad의 net이 다릅니다.",objects=[identity,pad_id],paths=[field+".pad_ids"])
        if not row["pad_ids"]:
            status = "not_evaluated"
        else:
            status = "passed" if {row["layer_id"],row["end_layer_id"]} <= attached else "failed"
            if status == "failed" and (low is None or high is None or unresolved_pad):
                status = "not_evaluated"
        report.add("via_endpoint_pads",status,"양 끝 도체층에 실제 부착된 명시적 pad가 필요합니다.",objects=[identity],paths=[field+".pad_ids"])
        measures[identity] = {"tool":tool,"ring":min(rings) if rings and None not in rings else None,
                              "aspect":(high-low)/tool if tool is not None and tool > 0 and low is not None and high is not None else None}
    return measures


def check_manufacturing(document, profile, shapes, pairs, via_measures, report):
    """! @brief 출처/버전이 명시된 규칙만 적용하고 지원하지 않는 국부 폭은 미평가로 남긴다."""
    prefix = "manufacturing_profiles." + profile["id"] + ".rules."
    for key,(label,dimension) in RULES.items():
        limit = profile["rules"][key]
        raw = {**limit, "source_refs": list(dict.fromkeys([*limit["source_refs"], *profile["source_refs"]]))}
        context = {"paths":[prefix+key], "details":{"profile_id":profile["id"],"version":profile["version"],"label":label}}
        if raw["value_si"] is None:
            report.bound(key,None,raw,unit="1" if dimension == "dimensionless" else "mm",**context)
            continue
        applicable = 0
        if key == "minimum_clearance":
            for a,b,distance,location,uncertain in pairs:
                if a.source["net_id"] is not None and a.source["net_id"] == b.source["net_id"]:
                    continue
                applicable += 1
                measured = None if uncertain or a.source["net_id"] is None or b.source["net_id"] is None else distance
                report.bound(key,measured,raw,guard=max(a.guard,b.guard),objects=[a.source["id"],b.source["id"]],location=location,**context)
        else:
            for identity,shape in shapes.items():
                via = shape.source["kind"] == "via"
                if (key == "minimum_width" and via) or (key in ("minimum_tool_hole","minimum_annular_ring","maximum_via_aspect_ratio") and not via):
                    continue
                applicable += 1
                location = None
                if key == "minimum_width":
                    measured = shape.width
                elif key == "minimum_edge_clearance":
                    try:
                        measured, location = board_clearance(document,shape)
                    except ProjectError:
                        measured = None
                else:
                    measured = via_measures.get(identity,{}).get({"minimum_tool_hole":"tool","minimum_annular_ring":"ring","maximum_via_aspect_ratio":"aspect"}[key])
                report.bound(key,measured,raw,maximum=key == "maximum_via_aspect_ratio",guard=shape.guard if dimension == "length" else 0,
                             objects=[identity],location=location,unit="1" if dimension == "dimensionless" else "mm",**context)
        if applicable == 0:
            report.add(key,"passed" if key == "minimum_clearance" else "not_applicable",
                       "근접 후보 밖의 다른 net 쌍은 AABB 하한으로 제외했습니다." if key == "minimum_clearance" else "해당 규칙을 적용할 객체가 없습니다.",
                       sources=raw["source_refs"],**context)
