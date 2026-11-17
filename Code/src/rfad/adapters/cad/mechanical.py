"""! @brief 명시 기판 절삭과 관통 홀/슬롯을 실제 CAD 재료 제거로 변환한다.

@details 새 PCB 원본을 기존 도체 비아로 치환하지 않는다. 공구 치수와 물성의
미정값을 보존하고 생성된 고체 및 양단 접속을 별도로 검사한다.
"""

from copy import deepcopy
import math

from rfad.adapters.cad.geometry import _require, _number, _point, _line, _region, _pad, _material


def planar_solid(cq, shape, lower, thickness, *, offset=0.0, identity="mechanical"):
    """! @brief 완성 원형/직선 슬롯/다각형 경계를 해석형 고체로 압출한다."""
    kind = shape.get("kind")
    layer = {"z_min_mm": lower, "thickness_mm": thickness}
    field = "pcb." + identity
    if kind == "circle":
        x, y = _point(shape["center_mm"], field)
        radius = _number(shape["diameter_mm"], field, positive=True) / 2 + offset
        return cq.Solid.makeCylinder(radius, thickness, (x, y, lower)), math.pi * radius ** 2
    if kind == "capsule":
        center = _point(shape["center_mm"], field)
        length = _number(shape["finished_length_mm"], field, positive=True)
        width = _number(shape["finished_width_mm"], field, positive=True)
        _require(length - width >= 1e-5, "슬롯의 전체 길이는 폭보다 CAD 최소 길이 이상 커야 합니다.", field=field)
        angle = math.radians(math.remainder(_number(shape["rotation_deg"], field), 360.0))
        delta = [(length - width) / 2 * math.cos(angle), (length - width) / 2 * math.sin(angle)]
        source = {"id": identity, "start_mm": [center[i] - delta[i] for i in range(2)],
                  "end_mm": [center[i] + delta[i] for i in range(2)], "width_mm": width + 2 * offset}
        return _line(cq, source, layer), (length - width) * source["width_mm"] + math.pi * (source["width_mm"] / 2) ** 2
    _require(offset == 0, "다각형/사각형 절삭의 도금 offset은 지원하지 않습니다.", code="E_UNSUPPORTED", field=field)
    if kind == "polygon":
        return _region(cq, {"id": identity, "outer_mm": shape["outer_mm"], "holes_mm": shape.get("holes_mm", [])}, layer)
    if kind == "rectangle":
        return _pad(cq, {"id": identity, "pad_shape": "rectangle", "center_mm": shape["center_mm"],
                         "size_mm": shape["size_mm"], "rotation_deg": shape["rotation_deg"]}, layer)
    _require(False, "미지원 기계 절삭 형상을 생략할 수 없습니다.", code="E_UNSUPPORTED", field=field)


def board_solid(cq, board, lower, thickness):
    """! @brief 사각/원형/직선 다각형의 원래 외곽만 압출한다."""
    kind = board.get("kind", "rectangle")
    if kind == "circle":
        x, y = _point(board["center_mm"], "board.outline.center")
        return cq.Solid.makeCylinder(_number(board["radius_mm"], "board.outline.radius", positive=True), thickness, (x, y, lower))
    if kind == "polygon":
        return planar_solid(cq, {"kind": "polygon", "outer_mm": board["outer_mm"], "holes_mm": []},
                            lower, thickness, identity=board["id"])[0]
    _require(kind == "rectangle", "지원하지 않는 기판 외곽입니다.", code="E_UNSUPPORTED")
    return cq.Solid.makeBox(_number(board["width_mm"], "board.outline.width", positive=True),
                           _number(board["height_mm"], "board.outline.height", positive=True), thickness, (0, 0, lower))


def _strict_inside(cq, drill, board, lower, thickness, tolerance, field):
    """! @brief 절삭은 외곽 내부에만 두고 접한 notch를 임의로 치유하지 않는다."""
    outline = board_solid(cq, board, lower, thickness)
    outside = drill.cut(outline)
    _require(outside.isValid() and (not outside.Solids() or outside.Volume() <= tolerance ** 3),
             "기계 절삭이 기판 외곽을 벗어납니다.", field=field)
    boundary = [face.outerWire() for face in outline.Faces() if face.geomType() == "PLANE" and face.normalAt().z < -0.999999]
    removed = [face.outerWire() for face in drill.Faces() if face.geomType() == "PLANE" and face.normalAt().z < -0.999999]
    _require(boundary and removed and min(a.distance(b) for a in boundary for b in removed) >= 1e-5,
             "기계 절삭은 기판 외곽에서 CAD 최소 간격만큼 떨어져야 합니다.", field=field)


def records(cq, projection, layers, planar, vias):
    """! @brief 제거 고체와 명시 도금 shell을 만들고 기존 비아와 중복을 차단한다."""
    source = projection.get("mechanical", {})
    cutouts, holes = source.get("cutouts", []), source.get("holes", [])
    _require(type(cutouts) is list and type(holes) is list and len(cutouts) + len(holes) <= 128,
             "기계 절삭 목록 또는 개수 상한이 유효하지 않습니다.", code="E_RESOURCE")
    if not cutouts and not holes:
        return []
    _require(len(cutouts) + len(holes) + len(projection["shapes"]) <= 128,
             "도체와 기계 절삭을 합한 CAD 형상 상한 128개를 초과했습니다.", code="E_RESOURCE")
    ids = [item["id"] for item in cutouts + holes]
    _require(len(set(ids)) == len(ids) and not set(ids).intersection(item["id"] for item in projection["shapes"]),
             "기계 절삭과 도체의 원본 식별자가 중복되었습니다.")
    lower = min(item["z_min_mm"] for item in layers.values())
    upper = max(item["z_min_mm"] + item["thickness_mm"] for item in layers.values())
    span, tolerance = upper - lower, projection["tolerance_mm"]
    conductors = sorted((item for item in layers.values() if item["role"] == "conductor"), key=lambda item: item["z_min_mm"])
    result = []
    for item in cutouts + holes:
        field = "pcb." + item["id"]
        is_hole = item in holes
        state = item["plating"]["state"] if is_hole else "unplated"
        _require(state in ("unplated", "plated"), "도금 여부가 미정인 홀은 CAD 실체를 만들 수 없습니다.", code="E_UNSUPPORTED", field=field)
        if is_hole:
            _require(item["shape"]["kind"] in ("circle", "capsule"), "현재 홀은 원형/직선 슬롯만 지원합니다.", code="E_UNSUPPORTED", field=field)
        plated = state == "plated"
        offset = _number(item["plating"]["thickness_mm"], field + ".plating.thickness", positive=True) if plated else 0.0
        drill, outer_area = planar_solid(cq, item["shape"], lower, span, offset=offset, identity=item["id"])
        _strict_inside(cq, drill, projection["board"], lower, span, tolerance, field)
        for previous in vias + result:
            _require(drill.distance(previous["drill"]) > tolerance, "겹치거나 접한 기계 절삭/비아는 지원하지 않습니다.", code="E_UNSUPPORTED", field=field)
        record = {"source": item, "drill": drill, "shape": None, "z_min_mm": lower, "z_max_mm": upper,
                  "kind": "hole" if is_hole else "cutout"}
        if plated:
            plating = item["plating"]
            _require(len(conductors) >= 2 and plating["net_id"] is not None,
                     "도금 홀에는 두 외부 도체층과 명시적 net이 필요합니다.", code="E_CONNECTIVITY", field=field)
            _require(abs(conductors[0]["z_min_mm"] - lower) <= tolerance and
                     abs(conductors[-1]["z_min_mm"] + conductors[-1]["thickness_mm"] - upper) <= tolerance,
                     "관통 도금 홀은 기본 적층 양 끝의 외부 도체층을 연결해야 합니다.", code="E_UNSUPPORTED", field=field)
            finished_width = item["shape"]["diameter_mm"] if item["shape"]["kind"] == "circle" else item["shape"]["finished_width_mm"]
            tool = item["tool_diameter_mm"]
            _require(tool is None or math.isclose(_number(tool, field + ".tool_diameter", positive=True), finished_width + 2 * offset, rel_tol=0, abs_tol=tolerance),
                     "명시 공구와 완성 폭/도금 두께의 관계가 현재 CAD profile과 다릅니다.", code="E_UNSUPPORTED", field=field)
            inner, inner_area = planar_solid(cq, item["shape"], lower, span, identity=item["id"])
            shell = drill.cut(inner)
            _require(shell.isValid() and len(shell.Solids()) == 1 and
                     math.isclose(shell.Volume(), (outer_area - inner_area) * span, rel_tol=1e-7, abs_tol=1e-18),
                     "실제 도금 홀 shell의 부피가 독립 단면 산술과 다릅니다.", field=field)
            material = plating["material_ref"] if plating["material_ref"] is not None else conductors[0]["material_id"]
            pad_ids, pad_layers = plating["pad_ids"], set()
            _require(type(pad_ids) is list and 2 <= len(pad_ids) <= 8 and len(set(pad_ids)) == len(pad_ids),
                     "도금 홀에 명시적인 고유 양단 패드 2~8개가 필요합니다.", code="E_CONNECTIVITY", field=field)
            for identity in pad_ids:
                _require(identity in planar and planar[identity][0]["kind"] == "pad", "도금 홀의 출력 패드가 없습니다.", code="E_CONNECTIVITY", field=field)
                pad, solid = planar[identity]
                layer = layers[pad["layer_id"]]
                _require(pad["net_id"] == plating["net_id"] and _material(pad, layer) == material,
                         "도금 홀과 패드의 net/재료가 다릅니다.", code="E_CONNECTIVITY", field=field)
                coverage = planar_solid(cq, item["shape"], layer["z_min_mm"], layer["thickness_mm"], offset=offset + 1e-5, identity=item["id"])[0]
                outside = coverage.cut(solid)
                _require(outside.isValid() and (not outside.Solids() or outside.Volume() <= tolerance ** 3),
                         "도금 홀 양단 패드에 양의 annular 접속 여유가 없습니다.", code="E_CONNECTIVITY", field=field)
                pad_layers.add(layer["id"])
            _require({conductors[0]["id"], conductors[-1]["id"]} <= pad_layers,
                     "도금 홀 양 끝의 명시적 패드가 누락되었습니다.", code="E_CONNECTIVITY", field=field)
            record.update(shape=shell, material_id=material, net_id=plating["net_id"], layer_id=conductors[0]["id"],
                          layer_ids=[layer["id"] for layer in conductors], pad_ids=deepcopy(pad_ids),
                          section_area_mm2=outer_area - inner_area)
        result.append(record)
    return result


def barrel_bodies(mechanical):
    """! @brief 독립 PCB 홀 ID와 완성 형상/미정 공구를 STEP body에 보존한다."""
    result = []
    for record in mechanical:
        if record["shape"] is None:
            continue
        source = record["source"]
        result.append({"id": source["id"], "name": "plated_hole_" + source["id"], "role": "conductor",
                       "feature_kind": "plated_hole_barrel", "layer_id": record["layer_id"], "layer_ids": record["layer_ids"],
                       "layer_id_semantics": "lower_conductor_anchor", "net_id": record["net_id"], "material_id": record["material_id"],
                       "source_entity_ids": [source["id"]], "pad_ids": record["pad_ids"],
                       "vertical_span_mm": [record["z_min_mm"], record["z_max_mm"]],
                       "finished_shape": deepcopy(source["shape"]), "plating_thickness_mm": source["plating"]["thickness_mm"],
                       "tool_hole_diameter_mm": source["tool_diameter_mm"], "drill_basis": "finished_shape_offset_by_plating",
                       "fill": "none", "shape": record["shape"]})
    return result


def cut_surface(cq, solid, row, mechanical):
    """! @brief 사용자가 지정한 표면에만 완성 홀/절삭의 개구를 적용한다."""
    ids = []
    for record in mechanical:
        item = record["source"]
        if row["id"] not in item["surface_cut_ids"]:
            continue
        cutter = planar_solid(cq, item["shape"], row["z_min_mm"], row["thickness_mm"], identity=item["id"])[0]
        common = solid.intersect(cutter)
        _require(common.isValid() and common.Volume() > 1e-18,
                 "명시한 표면 절삭이 실제 표면 재료와 만나지 않습니다.", field="surface." + row["id"])
        solid = solid.cut(cutter)
        _require(solid.isValid() and bool(solid.Solids()), "표면 절삭 후 유효한 재료가 남지 않습니다.", field="surface." + row["id"])
        ids.append(item["id"])
    return solid, sorted(ids)
