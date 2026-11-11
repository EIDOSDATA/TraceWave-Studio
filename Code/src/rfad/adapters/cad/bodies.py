"""! @brief 층/net별 CAD body 집계와 연결/측정 검사를 담당한다."""

from copy import deepcopy
import math
from uuid import NAMESPACE_URL, uuid5

from rfad.adapters.cad.geometry import _require, _number, _planar_solid, _inside_outline, _via_records, _drilled, _material


def _metrics(shape) -> dict:
    """! @brief 비교용 부피, 중심, 경계와 닫힌 고체 수를 mm 단위로 측정한다."""
    solids = shape.Solids()
    _require(bool(solids) and shape.isValid(), "CAD 결과가 유효한 B-rep 고체가 아닙니다.")
    _require(all(solid.Volume() > 0.0 and solid.isValid() and all(shell.Closed() for shell in solid.Shells()) for solid in solids),
             "CAD 결과에 빈 고체, 역방향 고체 또는 열린 외피가 있습니다.")
    box = shape.BoundingBox()
    center = shape.Center()
    top_faces = [face for face in shape.Faces() if face.geomType() == "PLANE" and face.normalAt().z > 0.999999]
    _require(bool(top_faces), "지원 prismatic 고체의 상부 평면 단면이 없습니다.")
    section_area = sum(face.Area() for face in top_faces)
    hole_count = sum(len(face.innerWires()) for face in top_faces)
    values = [box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax, shape.Volume(), center.x, center.y, center.z]
    _require(all(math.isfinite(value) for value in values), "CAD 측정 결과에 유한하지 않은 값이 있습니다.")
    return {"solid_count": len(solids), "volume_mm3": shape.Volume(),
            "bbox_mm": values[:6], "center_mm": [center.x, center.y, center.z], "valid_brep": True,
            "thickness_mm": box.zlen, "section_area_mm2": section_area,
            "section_loop_count": len(top_faces) + hole_count, "through_hole_count": hole_count,
            "section_method": "Upper planar caps, equivalent to normal section for constant-thickness prismatic profile"}


def _make_bodies(cq, projection: dict) -> list[dict]:
    """! @brief dielectric와 도체를 분리하고 같은 net의 명시적 도체만 합친다."""
    layers = {layer["id"]: layer for layer in projection["layers"]}
    _require(len(layers) == len(projection["layers"]) and len(layers) <= 64,
             "중복 층 또는 지원 상한을 넘는 층이 있습니다.")
    board = projection["board"]
    circular = board.get("kind", "rectangle") == "circle"
    _require(board.get("kind", "rectangle") in ("rectangle", "circle"), "해당 기판 외곽은 지원하지 않습니다.", code="E_UNSUPPORTED")
    if circular:
        center = [_number(value, "board.outline.center") for value in board["center_mm"]]
        _require(len(center) == 2, "원형 기판 중심에는 두 좌표가 필요합니다.")
        radius = _number(board["radius_mm"], "board.outline.radius", positive=True)
    else:
        width = _number(board["width_mm"], "board.outline.width", positive=True)
        height = _number(board["height_mm"], "board.outline.height", positive=True)
    bodies = []
    for layer in layers.values():
        _number(layer["z_min_mm"], "stackup." + layer["id"] + ".z_min")
        _number(layer["thickness_mm"], "stackup." + layer["id"] + ".thickness", positive=True)
        _require(layer["role"] in ("dielectric", "conductor"), "해당 층 역할의 CAD coverage를 지원하지 않습니다.", code="E_UNSUPPORTED")
        if layer["role"] == "dielectric":
            solid = (cq.Solid.makeCylinder(radius, layer["thickness_mm"], (center[0], center[1], layer["z_min_mm"])) if circular
                     else cq.Solid.makeBox(width, height, layer["thickness_mm"], (0.0, 0.0, layer["z_min_mm"])))
            bodies.append({"id": layer["id"], "name": "dielectric_" + layer["id"], "role": "dielectric",
                           "layer_id": layer["id"], "net_id": None, "material_id": layer["material_id"],
                           "source_entity_ids": [board["id"], layer["id"]], "shape": solid})
    groups, planar = {}, {}
    _require(len(projection["shapes"]) <= 128, "초기 CAD 형상 상한 128개를 초과했습니다.", code="E_RESOURCE")
    _require(len({source["id"] for source in projection["shapes"]}) == len(projection["shapes"]), "CAD 원본 도체 식별자가 중복되었습니다.")
    for source in projection["shapes"]:
        layer = layers.get(source["layer_id"])
        _require(layer is not None and layer["role"] == "conductor", "도체 형상이 conductor 층에 연결되지 않았습니다.")
        if source["kind"] == "via":
            continue
        solid, expected_area = _planar_solid(cq, source, layer)
        stats = _metrics(solid)
        expected_volume = expected_area * layer["thickness_mm"]
        _require(math.isclose(stats["volume_mm3"], expected_volume, rel_tol=1e-7, abs_tol=1e-18),
                 "CAD 수치 정밀도로 analytic 원본의 체적을 보존하지 못했습니다.", field="geometry." + source["id"])
        _inside_outline(cq, solid, board, layer["z_min_mm"], layer["thickness_mm"], projection["tolerance_mm"], "geometry." + source["id"])
        planar[source["id"]] = (source, solid)
    vias = _via_records(cq, projection, layers, planar)
    for body in bodies:
        body["shape"], drill_ids = _drilled(body["shape"], vias)
        if drill_ids:
            body["source_entity_ids"] += sorted(drill_ids)
            body["drill_source_ids"] = sorted(drill_ids)
    for source, original in planar.values():
        solid, drill_ids = _drilled(original, vias)
        material = _material(source, layers[source["layer_id"]])
        key = (source["layer_id"], source["net_id"], material, None if source["net_id"] is not None else source["id"])
        groups.setdefault(key, []).append((source["id"], solid, drill_ids))
    for (layer_id, net_id, material, _), members in sorted(groups.items(), key=lambda pair: str(pair[0])):
        ids = sorted(identity for identity, _, _ in members)
        solid = members[0][1]
        for _, other, _ in members[1:]:
            solid = solid.fuse(other)
        identity = ids[0] if len(ids) == 1 else str(uuid5(NAMESPACE_URL, "rfad/cad/" + "/".join(ids)))
        bodies.append({"id": identity, "name": "conductor_" + identity, "role": "conductor",
                       "layer_id": layer_id, "net_id": net_id, "material_id": material,
                       "drill_source_ids": sorted({value for _, _, drilling in members for value in drilling}),
                       "source_entity_ids": ids, "shape": solid})
    for via in vias:
        source = via["source"]
        bodies.append({"id": source["id"], "name": "via_barrel_" + source["id"], "role": "conductor",
                       "layer_id": source["layer_id"], "layer_ids": via["layer_ids"], "layer_id_semantics": "start_layer_anchor",
                       "net_id": source["net_id"], "material_id": via["material_id"], "feature_kind": "via_barrel",
                       "source_entity_ids": [source["id"]], "pad_ids": deepcopy(source["pad_ids"]),
                       "vertical_span_mm": [via["z_min_mm"], via["z_max_mm"]], "finished_hole_diameter_mm": 2 * via["inner_radius_mm"],
                       "modeled_drill_diameter_mm": 2 * via["outer_radius_mm"], "tool_hole_diameter_mm": source["tool_hole_diameter_mm"],
                       "drill_basis": "finished_hole_diameter_plus_twice_plating", "fill": "none", "shape": via["shape"]})
    _require(bool(bodies), "내보낼 CAD 고체가 없습니다.")
    tolerance = projection["tolerance_mm"]
    for body in bodies:
        body["metrics"] = _metrics(body["shape"])
    _check_pairs(bodies, tolerance)
    _check_via_contacts(bodies, tolerance)
    return sorted(bodies, key=lambda body: body["name"])


def _check_pairs(bodies: list[dict], tolerance: float) -> None:
    """! @brief 형상 생성과 재입력 양쪽에서 body 간 중첩과 net 접촉을 검사한다."""
    for index, body in enumerate(bodies):
        for other in bodies[index + 1:]:
            bounds = body["metrics"]["bbox_mm"]
            other_bounds = other["metrics"]["bbox_mm"]
            if any(bounds[axis + 3] < other_bounds[axis] - tolerance or other_bounds[axis + 3] < bounds[axis] - tolerance for axis in range(3)):
                continue
            common = body["shape"].intersect(other["shape"])
            _require(abs(common.Volume()) <= tolerance ** 3,
                     "서로 다른 도체 또는 유전체 body의 부피가 중첩합니다.", code="E_CONNECTIVITY")
            if body["role"] == other["role"] == "conductor":
                via_contact = ((body.get("feature_kind") == "via_barrel" and body["id"] in other.get("drill_source_ids", []))
                               or (other.get("feature_kind") == "via_barrel" and other["id"] in body.get("drill_source_ids", [])))
                compatible = body["net_id"] is not None and body["net_id"] == other["net_id"] and body["material_id"] == other["material_id"]
                _require((via_contact and compatible) or body["shape"].distance(other["shape"]) > tolerance,
                         "분리된 net/재료 또는 미지정 net의 도체가 접촉하거나 CAD 허용오차보다 가깝습니다.", code="E_CONNECTIVITY")


def _check_via_contacts(bodies, tolerance):
    """! @brief 생성과 재입력 모두에서 명시적 via-pad 연결이 실제 접면으로 남았는지 확인한다."""
    for barrel in bodies:
        if barrel.get("feature_kind") != "via_barrel":
            continue
        _require(barrel["metrics"]["through_hole_count"] == 1 and barrel["metrics"]["solid_count"] == 1,
                 "관통 비아의 실제 중공 단면 또는 연결 성분이 다릅니다.", code="E_CONNECTIVITY")
        for identity in barrel["pad_ids"]:
            matches = [body for body in bodies if body["role"] == "conductor" and body.get("feature_kind") != "via_barrel" and identity in body["source_entity_ids"]]
            _require(len(matches) == 1 and barrel["shape"].distance(matches[0]["shape"]) <= tolerance,
                     "STEP 기하에서 명시적 via-pad 접속이 끊어졌습니다.", code="E_CONNECTIVITY")
