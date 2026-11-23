"""! @brief 단위와 참조를 서비스에서 해석하여 제한된 2D 표시 및 편집 명령을 제공한다."""

from copy import deepcopy
import json
import math
from uuid import UUID, uuid5

from rfad.domain import sketch_constraints
from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity, QuantityError
from rfad.domain.object_names import allocate_name, display_names, name_dto
from rfad.application.edit_view_contract import result_limit


PROFILE = "rfad.canvas/0.1"
MAX_DTO_BYTES = 60 * 1024
DISPLAY_RANGES = {"max_coordinate_mm": 1e9, "min_line_length_mm": 1e-9, "min_abs_sweep_deg": 1e-10}
OPERATIONS = {
    "create_board": {"id", "width_mm", "height_mm"},
    "create_circular_board": {"id", "center_x_mm", "center_y_mm", "radius_mm"},
    "create_layer": {"id", "name"},
    "create_dielectric_layer": {"id", "name"},
    "create_line": {"id", "layer_id", "width_mm", "start", "end"},
    "create_route": {"id", "layer_id", "source_id", "width_mm", "clearance_mm", "points"},
    "create_arc": {"id", "layer_id", "width_mm", "center", "radius_mm", "start_angle_deg", "sweep_angle_deg"},
    "create_polygon": {"id", "layer_id", "outer", "holes"},
    "create_pad": {"id", "layer_id", "pad_shape", "center", "width_mm", "height_mm", "rotation_deg"},
    "create_via": {"id", "layer_id", "end_layer_id", "center", "finished_hole_diameter_mm", "plating_thickness_mm", "tool_hole_diameter_mm", "pad_ids"},
    "translate": {"id", "dx_mm", "dy_mm"},
    "move_endpoint": {"id", "endpoint", "point"},
    "remove": {"id"},
}


def _fail(message: str, field: str, code: str = "E_SCHEMA") -> None:
    """! @brief 화면 입력과 관련된 진단 경로를 유지한다."""
    raise ProjectError(code, message, details={"field_path": field})


def _uuid(value: object, field: str) -> str:
    """! @brief 생성과 선택에는 정규 UUID만 사용한다."""
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        _fail("정규 UUID 식별자가 필요합니다.", field)
    return value


def _number(value: object, field: str) -> float:
    """! @brief 숫자만 수용하며 bool/문자열과 비유한 값을 차단한다."""
    if type(value) not in (int, float):
        _fail("단위가 명시된 유한 숫자가 필요합니다.", field, "E_UNIT")
    try:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError()
    except (ValueError, OverflowError):
        _fail("숫자가 유한한 float64 범위를 벗어났습니다.", field, "E_UNIT")
    return number


def _quantity(value: object, unit: str, field: str) -> dict:
    """! @brief 화면의 명시적 mm/deg 입력을 SI로 한 번만 변환한다."""
    try:
        return Quantity.from_value(_number(value, field), unit).to_dict()
    except QuantityError as error:
        _fail(str(error), field, "E_UNIT")


def _point(value: object, field: str) -> list[dict]:
    """! @brief 두 좌표의 길이를 각각 명시적으로 검증한다."""
    if type(value) is not list or len(value) != 2:
        _fail("점에는 x/y 좌표 두 개가 필요합니다.", field)
    return [_quantity(number, "mm", f"{field}.{index}") for index, number in enumerate(value)]


def _existing_ids(document: dict) -> set[str]:
    """! @brief 종류가 다른 객체도 새 생성 ID와 충돌하지 않도록 검사한다."""
    identities = {document["project_id"], document["revision_id"], *document["parent_revision_ids"], *document["parameters"]}
    identities.update(frame["id"] for frame in document["frames"].values())
    for collection in ("materials", "stackup", "nets", "geometry", "ports"):
        identities.update(item["id"] for item in document[collection])
    if document["board"] is not None:
        identities.add(document["board"]["id"])
    return identities


def _display(document: dict, value: dict, dimension: str, unit: str, field: str) -> float:
    """! @brief 미정값을 0으로 추정하지 않고 표현 가능한 표시 수량만 반환한다."""
    quantity = resolve_scalar(document, value, dimension, field)
    if quantity.value_si is None:
        status = {"missing": "미정", "not_applicable": "해당 없음", "unsupported": "미지원"}.get(quantity.status.value, quantity.status.value)
        _fail("치수에 표시할 값이 없습니다 (" + status + "): " + field, field, "E_GEOMETRY")
    try:
        return quantity.as_unit(unit)
    except QuantityError as error:
        _fail("표시 단위의 숫자 범위를 벗어났습니다: " + field + ". " + str(error), field, "E_UNIT")


def _display_point(document: dict, point: list[dict], field: str) -> list[float]:
    """! @brief 2D 좌표의 매개변수 참조를 원본 변경 없이 해석한다."""
    return [_display_length(document, value, f"{field}.{index}") for index, value in enumerate(point)]


def _display_length(document: dict, value: dict, field: str) -> float:
    """! @brief 표시 profile의 좌표/치수 상한만 적용하며 도메인 원본은 제한하지 않는다."""
    number = _display(document, value, "length", "mm", field)
    if abs(number) > DISPLAY_RANGES["max_coordinate_mm"]:
        _fail("2D 표시 profile의 좌표/치수 상한을 벗어났습니다: " + field, field, "E_GEOMETRY")
    return number


def _coordinate_fields(geometry: dict) -> tuple[str, ...]:
    """! @brief 평행 이동이 실제로 바꾸는 좌표만 선택한다."""
    return ("start", "end") if geometry["kind"] == "line_path" else ("center",)


def _coordinate_points(geometry):
    """! @brief 구멍을 포함한 모든 평행 이동 대상 좌표를 원본 참조로 반환한다."""
    if geometry["kind"] == "planar_region":
        for name, loops in (("outer", [geometry["outer"]]), ("holes", geometry["holes"])):
            for index, loop in enumerate(loops):
                for point_index, point in enumerate(loop):
                    yield f"{name}.{index}.{point_index}", point
    else:
        for name in _coordinate_fields(geometry):
            yield name, geometry[name]


def _movable(geometry: dict) -> bool:
    """! @brief 좌표가 매개변수에 결합돼 있으면 직접 이동으로 연결을 해제하지 않는다."""
    return all("parameter_id" not in value and value.get("value_si") is not None for _, point in _coordinate_points(geometry) for value in point)


def _literal(values) -> bool:
    """! @brief 직접 편집은 값이 있는 리터럴만 바꾼다."""
    return all("parameter_id" not in value and value.get("value_si") is not None for value in values)


def _endpoint_mask(geometry: dict) -> int:
    """! @brief 시작점과 끝점이 바꾸는 원본 필드를 독립 검사한다."""
    if geometry["kind"] == "line_path":
        return int(_literal(geometry["start"])) | (int(_literal(geometry["end"])) << 1)
    if geometry["kind"] == "arc_path" and _literal([geometry["sweep_angle"]]):
        return 2 | int(_literal([geometry["start_angle"]]))
    return 0


def _replace_quantity(original: dict, replacement: dict) -> dict:
    """! @brief 변경된 수량에 원래 표시 단위와 출처를 유지한다."""
    return {**original, "value_si": replacement["value_si"], "status": "user_entered"}


def _move_endpoint(document: dict, geometry: dict, endpoint: object, point: object) -> dict:
    """! @brief 끝점 하나를 바꾸는 원본 후보를 만들고 다른 필드는 보존한다."""
    if geometry["kind"] not in ("line_path", "arc_path"):
        _fail("선과 원호의 끝점만 직접 편집할 수 있습니다.", "values.id", "E_UNSUPPORTED")
    if endpoint not in ("start", "end"):
        _fail("시작점 또는 끝점을 선택하십시오.", "values.endpoint")
    if not _endpoint_mask(geometry) & (1 if endpoint == "start" else 2):
        _fail("매개변수에 연결되었거나 미정인 끝점은 속성에서 편집하십시오.", "values.endpoint", "E_CONFLICT")
    changed = deepcopy(geometry)
    quantities = _point(point, "values.point")
    target = _display_point(document, quantities, "values.point")
    other = "end" if endpoint == "start" else "start"
    if geometry["kind"] == "line_path":
        previous = _display_point(document, geometry[endpoint], "geometry." + endpoint)
        fixed = _display_point(document, geometry[other], "geometry." + other)
        if math.dist(target, fixed) <= DISPLAY_RANGES["min_line_length_mm"]:
            _fail("선의 양 끝점은 서로 달라야 합니다.", "values.point", "E_GEOMETRY")
        for index, value in enumerate(point):
            if value != previous[index] and quantities[index]["value_si"] != geometry[endpoint][index]["value_si"]:
                changed[endpoint][index] = _replace_quantity(geometry[endpoint][index], quantities[index])
    else:
        _retarget_arc(document, changed, endpoint, target)
    if changed == geometry:
        _fail("끝점이 바뀌지 않았습니다.", "values.point", "E_CONFLICT")
    return {"type": "geometry.set", "payload": {"geometry": changed}}


def _move_coincident_endpoints(document, geometry, endpoint, point):
    """! @brief 접한 끝점만 원자적으로 바꾸고 나머지 기하와 저장 구속을 검증한다."""
    if endpoint not in ("start", "end"):
        return _move_endpoint(document, geometry, endpoint, point)
    selected = (geometry["id"], endpoint)
    anchors = sketch_constraints.coincident_anchors(document, selected)
    if len(anchors) == 1:
        return _move_endpoint(document, geometry, endpoint, point)

    original = {row["id"]: row for row in document["geometry"]}
    members = {identity for identity, _ in anchors}
    if len(members) != len(anchors) or any(name not in ("start", "end") for _, name in anchors):
        _fail("한 객체의 두 끝점이나 고정 중심을 함께 이동할 수 없습니다.", "values.endpoint", "E_CONFLICT")
    blocked = _translation_block(document, members, original, require_movable=False)
    if blocked:
        _fail(blocked, "values.id", "E_CONFLICT")

    # @brief 원호가 있으면 고정한 중심과 반경에 투영한 실제 끝점을 같은 접속의 목표로 사용한다.
    lead, lead_endpoint = next(((key, name) for key, name in anchors if original[key]["kind"] == "arc_path"),
                                selected)
    first = _move_endpoint(document, original[lead], lead_endpoint, point)["payload"]["geometry"]
    model = sketch_constraints.Model(document)
    model.geometry[lead] = first
    target = list(model.location(sketch_constraints.anchor(lead, lead_endpoint)))
    moved = {lead: first}
    for identity, name in anchors:
        if identity != lead:
            row = _move_endpoint(document, original[identity], name, target)["payload"]["geometry"]
            moved[identity] = row

    from rfad.domain.pcb_features import COMMAND, finalize_pcb_edits, make_patch

    candidate = deepcopy(document)
    candidate["geometry"] = [moved.get(row["id"], row) for row in candidate["geometry"]]
    finalize_pcb_edits(document, candidate, "geometry.set")
    return {"type": COMMAND, "payload": make_patch(document, candidate, "sketch.move_endpoint",
                                                   "일치하는 스케치 끝점 연동 이동")}


def _retarget_arc(document: dict, arc: dict, endpoint: str, target: list[float]) -> None:
    """! @brief 고정 중심/반지름과 반대쪽 끝점에서 기존 회전 방향을 유지한다."""
    center = _display_point(document, arc["center"], "geometry.center")
    _display_length(document, arc["radius"], "geometry.radius")
    if math.dist(center, target) <= DISPLAY_RANGES["min_line_length_mm"]:
        _fail("원호 중심과 다른 끝 방향을 선택하십시오.", "values.point", "E_GEOMETRY")
    start = _display(document, arc["start_angle"], "angle", "deg", "geometry.start_angle")
    sweep = _display(document, arc["sweep_angle"], "angle", "deg", "geometry.sweep_angle")
    phase = start % 360.0
    end = (phase + sweep) % 360.0
    direction = math.degrees(math.atan2(target[1] - center[1], target[0] - center[0]))
    precision = DISPLAY_RANGES["min_abs_sweep_deg"]
    old_direction = phase if endpoint == "start" else end
    if abs(math.remainder(direction - old_direction, 360.0)) <= precision:
        return
    if endpoint == "start":
        updated_start = _quantity(start + math.remainder(direction - phase, 360.0), "deg", "geometry.start_angle")
        new_phase = _display(document, updated_start, "angle", "deg", "geometry.start_angle") % 360.0
        if abs(math.remainder(new_phase - direction, 360.0)) > precision:
            _fail("원래 시작각의 표현 정밀도로 새 방향을 보존할 수 없습니다.", "values.point", "E_UNIT")
        arc["start_angle"] = _replace_quantity(arc["start_angle"], updated_start)
        phase = new_phase
    else:
        end = direction
    ccw = (end - phase) % 360.0
    if ccw <= precision or ccw >= 360.0 - precision:
        _fail("원호의 양 끝 방향은 서로 달라야 합니다.", "values.point", "E_GEOMETRY")
    new_sweep = ccw if sweep > 0.0 else ccw - 360.0
    arc["sweep_angle"] = _replace_quantity(arc["sweep_angle"], _quantity(new_sweep, "deg", "geometry.sweep_angle"))


def _port_marker(document: dict, port: dict) -> dict:
    """! @brief 명시한 급전 영역을 2D 선택용 위치로만 투영한다."""
    marker = {"id": port["id"], "terminal_ids": [port["positive_geometry_id"], port["reference_geometry_id"]],
              "point_mm": None, "reason": "급전 시작/끝 좌표가 미정입니다."}
    box = port.get("excitation_box")
    if box is not None:
        try:
            start, stop = [_display_point(document, box[key], "excitation_box." + key) for key in ("start", "stop")]
            marker.update(point_mm=[(left + right) / 2 for left, right in zip(start[:2], stop[:2])], reason="")
        except ProjectError as error:
            marker["reason"] = error.message
    return marker


def _translation_block(document, members, geometry, *, require_movable=True):
    """! @brief 연결된 급전, 비아 패드 및 입력 위치가 잠긴 묶음의 이동을 막는다."""
    if require_movable and any(not _movable(geometry[identity]) for identity in members):
        return "연결된 도체에 매개변수에 연결되었거나 미정인 좌표가 있습니다."
    if any(any(port[key] in members for key in ("positive_geometry_id", "reference_geometry_id"))
           for port in document["ports"]):
        return "연결된 도체가 급전 단자를 포함합니다. 급전 위치를 유지하려면 이 묶음을 이동할 수 없습니다."
    if any(any(identity in members for identity in row.get("pad_ids", [])) for row in geometry.values()):
        return "연결된 도체가 비아에 연결된 패드를 포함합니다. 해당 접합을 유지해야 합니다."
    member_ids = set(members)
    if any(member_ids.intersection(row["object_ids"]) and not member_ids.issuperset(row["object_ids"])
           for row in document["connections"] if row["kind"] == "connected"):
        return "연결된 도체에 묶음 밖의 접속 대상이 있습니다. 접속을 유지하려면 이 묶음을 이동할 수 없습니다."
    return ""


def project_canvas(document: dict) -> dict:
    """! @brief mm/deg의 표시 모델만 만들며 미정 형상과 생략 사유를 분리한다."""
    result = {"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
              "unit": "mm", "angle_unit": "deg", "ranges": dict(DISPLAY_RANGES), "board": None,
              "layers": [{"id": layer["id"], "label": layer["name"], "role": layer["role"]} for layer in document["stackup"]],
              "shapes": [], "omissions": []}
    board = document["board"]
    if board is not None:
        outline = board["outline"]
        circular = outline["kind"] == "circle"
        polygon = outline["kind"] == "polygon"
        visible = {"id": board["id"], "kind": "polygon", "outer": None} if polygon else {"id": board["id"], "kind": "circle", "center": None, "radius": None} if circular else {"id": board["id"], "width": None, "height": None}
        visible.update(name_dto(document, board, "board"))
        for name in ("outer",) if polygon else ("center", "radius") if circular else ("width", "height"):
            try:
                visible[name] = [_display_point(document, point, "board.outline.outer") for point in outline[name]] if polygon else _display_point(document, outline[name], "board.outline." + name) if name == "center" else _display_length(document, outline[name], "board.outline." + name)
            except ProjectError as error:
                result["omissions"].append({"id": board["id"], "message": error.message})
        if circular and visible["center"] is not None and visible["radius"] is not None:
            center, radius = visible["center"], visible["radius"]
            if any(abs(coordinate) + radius > DISPLAY_RANGES["max_coordinate_mm"] or coordinate - radius >= coordinate + radius for coordinate in center):
                visible["radius"] = None
                result["omissions"].append({"id": board["id"], "message": "원형 기판 외곽이 2D 좌표 범위 또는 표현 정밀도를 벗어났습니다."})
        result["board"] = visible
    if document["ports"]:
        result["port_marker"] = _port_marker(document, document["ports"][0])
    labels = display_names(document)
    translation_groups = sketch_constraints.translation_groups(document)
    by_id = {row["id"]: row for row in document["geometry"]} if translation_groups else {}
    blockers = {members[0]: _translation_block(document, members, by_id)
                for identity, members in translation_groups.items() if identity == members[0]}
    for geometry in document["geometry"]:
        try:
            prefix = "geometry." + geometry["id"]
            kind = geometry["kind"]
            shape = {"id": geometry["id"], "kind": geometry["kind"],
                     **name_dto(document, geometry, labels=labels),
                     "layer_id": geometry["layer_id"], "role": geometry["role"],
                     "movable": _movable(geometry)}
            members = translation_groups.get(geometry["id"])
            if members:
                shape["translation_group"] = members[0]
                if blockers[members[0]]:
                    shape["movable"] = False
                    shape["translation_block"] = blockers[members[0]]
            if kind in ("line_path", "arc_path"):
                shape["width"] = _display_length(document, geometry["width"], prefix + ".width")
                shape["endpoint_mask"] = _endpoint_mask(geometry)
            if kind == "planar_region":
                shape["outer"] = [_display_point(document, point, prefix + f".outer.{index}") for index, point in enumerate(geometry["outer"])]
                shape["holes"] = [[_display_point(document, point, prefix + f".holes.{i}.{j}") for j, point in enumerate(loop)] for i, loop in enumerate(geometry["holes"])]
            else:
                for name in _coordinate_fields(geometry):
                    shape[name] = _display_point(document, geometry[name], prefix + "." + name)
            if kind == "pad":
                shape.update(pad_shape=geometry["pad_shape"], size=_display_point(document, geometry["size"], prefix + ".size"),
                             rotation=_display(document, geometry["rotation"], "angle", "deg", prefix + ".rotation"))
            elif kind == "via":
                layer_map = {layer["id"]: layer for layer in document["stackup"]}
                lower, upper = (layer_map[geometry[name]]["order"] for name in ("layer_id", "end_layer_id"))
                shape["span_layer_ids"] = [layer["id"] for layer in document["stackup"] if layer["role"] == "conductor" and lower <= layer["order"] <= upper]
                for name in ("finished_hole_diameter", "plating_thickness", "tool_hole_diameter"):
                    shape[name] = None
                    try:
                        shape[name] = _display_length(document, geometry[name], prefix + "." + name)
                    except ProjectError as error:
                        result["omissions"].append({"id": geometry["id"], "message": error.message})
            elif kind == "arc_path":
                shape["radius"] = _display_length(document, geometry["radius"], prefix + ".radius")
                shape["start_angle"] = _display(document, geometry["start_angle"], "angle", "deg", prefix + ".start_angle")
                shape["sweep_angle"] = _display(document, geometry["sweep_angle"], "angle", "deg", prefix + ".sweep_angle")
                if abs(shape["sweep_angle"]) <= DISPLAY_RANGES["min_abs_sweep_deg"]:
                    _fail("2D 표시 profile의 원호 회전량 하한 이하입니다: " + prefix + ".sweep_angle", prefix + ".sweep_angle", "E_GEOMETRY")
            elif kind == "line_path" and math.hypot(shape["end"][0] - shape["start"][0], shape["end"][1] - shape["start"][1]) <= DISPLAY_RANGES["min_line_length_mm"]:
                _fail("2D 표시 profile의 선 길이 하한 이하입니다: " + prefix, prefix, "E_GEOMETRY")
            result["shapes"].append(shape)
        except ProjectError as error:
            result["omissions"].append({"id": geometry["id"], "message": error.message})
    if "pcb" in document or (board is not None and "cutouts" in board):
        from rfad.application.pcb_exchange_projection import feature_scene
        from rfad.domain.pcb_features import owner_map
        result["pcb_features"] = feature_scene(document)
        owners = owner_map(document)
        for row in result["shapes"]:
            row["owner_footprint_id"] = owners.get(("geometry", row["id"]))
    return result


def build_canvas_dto(document: dict, *, extended: bool = False) -> dict:
    """! @brief 기존 한 응답 계약에만 이전 전송 예산을 적용한다."""
    result = project_canvas(document)
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > result_limit(MAX_DTO_BYTES, extended):
        _fail("2D 표시 DTO가 해당 전송 크기 상한을 초과했습니다.", "canvas", "E_RESOURCE")
    return result


def _with_drawing_relations(document, command, geometry, requested):
    """! @brief 사용자가 채택한 관계만 새 도체와 하나의 명령으로 묶는다."""
    if type(requested) is not list or not 1 <= len(requested) <= 3:
        _fail("한 번에 그리기 관계를 1~3개 선택하세요.", "values.relations")
    existing = {row["id"]: row for row in document["geometry"]}
    identity = geometry["id"]
    origin = sketch_constraints.anchor(identity, "start")
    rows = []
    keys = set()
    for spec in requested:
        kind = spec.get("kind") if type(spec) is dict else None
        if kind == "parallel" and spec.keys() == {"kind", "axis"} and geometry["kind"] == "line_path":
            if spec["axis"] not in ("x", "y"):
                _fail("수평 또는 수직 기준축을 선택하세요.", "values.relations")
            key = "axis"
            constraint = sketch_constraints.relation(kind, origin, axis=spec["axis"])
        elif kind in ("coincident", "midpoint", "tangent") and spec.keys() == {"kind", "endpoint", "target"}:
            endpoint, target = spec["endpoint"], spec["target"]
            sketch_constraints.validate_anchor(target)
            candidate = existing.get(target["id"])
            if (endpoint not in ("start", "end") or candidate is None or candidate["layer_id"] != geometry["layer_id"]
                    or candidate["frame_id"] != geometry["frame_id"] or candidate["kind"] not in ("line_path", "arc_path")
                    or target["point"] not in ("start", "end")
                    or (kind == "midpoint" and (candidate["kind"] != "line_path" or target["point"] != "start"))
                    or (kind == "tangent" and
                        (geometry["kind"] != "line_path" or candidate["kind"] != "arc_path" or endpoint != "start"))):
                _fail("같은 층에서 그리기 관계를 연결할 끝점이나 중점을 선택하세요.", "values.relations", "E_CONFLICT")
            refs = [sketch_constraints.anchor(identity, endpoint), target]
            if kind == "midpoint":
                refs.append(sketch_constraints.anchor(target["id"], "end"))
            key = "tangent" if kind == "tangent" else endpoint
            constraint = sketch_constraints.relation(kind, *refs)
        else:
            _fail("지원하는 그리기 관계를 선택하세요.", "values.relations")
        if key in keys:
            _fail("같은 기준에 관계를 중복 지정했습니다.", "values.relations", "E_CONFLICT")
        keys.add(key)
        rows.append(constraint)
    for row in rows:
        if row["kind"] == "tangent" and not any(item["kind"] == "coincident" and item["refs"] == row["refs"] for item in rows):
            _fail("접선과 함께 같은 원호 끝점의 일치 관계가 필요합니다.", "values.relations", "E_CONFLICT")
    group_id = str(uuid5(UUID(identity), "rfad.sketch.drawing"))
    group = {"id": group_id, "name": geometry["name"] + " 그리기 관계", "selection_ids": [identity],
             "datum": origin, "axis": "x", "constraints": rows, "protected": []}
    return {"type": sketch_constraints.DRAW_COMMAND,
            "payload": {"geometry": command, "sketch": {"id": group_id, "expected": None, "replacement": group}}}


def canvas_command(document: dict, operation: str, values: dict) -> dict:
    """! @brief 제한된 화면 조작을 기존 도메인 명령 하나로 변환한다."""
    if type(operation) is not str or operation not in OPERATIONS:
        _fail("지원하지 않는 2D 편집 작업입니다.", "operation", "E_UNSUPPORTED")
    optional = set()
    if operation in ("create_line", "create_arc") and isinstance(values, dict) and "relations" in values:
        optional.add("relations")
    if type(values) is not dict or set(values) != OPERATIONS[operation] | optional:
        _fail("작업에 필요한 필드와 허용한 필드를 확인하십시오.", "values")
    identity = _uuid(values["id"], "values.id")
    if operation.startswith("create_") and identity in _existing_ids(document):
        _fail("생성 ID가 기존 객체와 충돌합니다. 원본을 덮어쓰지 않았습니다.", "values.id", "E_CONFLICT")
    if operation == "create_route":
        from rfad.application.interactive_route import command
        return command(document, values)
    if operation in ("create_board", "create_circular_board"):
        if document["board"] is not None:
            _fail("기판이 이미 있습니다. 속성 편집으로 기존 기판을 수정하십시오.", "board", "E_CONFLICT")
        if operation == "create_circular_board":
            outline = {"kind": "circle", "center": [_quantity(values[name], "mm", "values." + name) for name in ("center_x_mm", "center_y_mm")],
                       "radius": _quantity(values["radius_mm"], "mm", "values.radius_mm")}
        else:
            outline = {"kind": "rectangle", "width": _quantity(values["width_mm"], "mm", "values.width_mm"),
                       "height": _quantity(values["height_mm"], "mm", "values.height_mm")}
        board = {"id": identity, "frame_id": document["frames"]["board"]["id"], "thickness_convention": "finished", "outline": outline}
        board["name"] = allocate_name(document, board, "board")
        return {"type": "board.set", "payload": {"board": board}}
    if operation in ("create_layer", "create_dielectric_layer"):
        dielectric = operation == "create_dielectric_layer"
        layer = {"id": identity, "name": values["name"], "role": "dielectric" if dielectric else "conductor",
                 "order": max((item["order"] for item in document["stackup"]), default=-1) + 1,
                 "z_min": Quantity.missing("length", "mm").to_dict(),
                 "thickness": Quantity.missing("length", "mm" if dielectric else "um").to_dict(), "material_id": None}
        return {"type": "layer.set", "payload": {"layer": layer}}
    if operation in ("create_line", "create_arc", "create_polygon", "create_pad", "create_via"):
        if document["board"] is None:
            _fail("패턴을 만들기 전에 기판을 생성하십시오.", "board", "E_GEOMETRY")
        kinds = {"create_line": "line_path", "create_arc": "arc_path", "create_polygon": "planar_region", "create_pad": "pad", "create_via": "via"}
        geometry = {"id": identity, "kind": kinds[operation], "role": "ground" if operation == "create_polygon" else "conductor",
                    "frame_id": document["board"]["frame_id"], "layer_id": _uuid(values["layer_id"], "values.layer_id"),
                    "net_id": None, "material_ref": None, "source_ref": None, "include_in_em": True, "include_in_export": True}
        if operation in ("create_line", "create_arc"):
            geometry["width"] = _quantity(values["width_mm"], "mm", "values.width_mm")
        if operation == "create_line":
            geometry["start"] = _point(values["start"], "values.start")
            geometry["end"] = _point(values["end"], "values.end")
        elif operation == "create_arc":
            geometry["center"] = _point(values["center"], "values.center")
            geometry["radius"] = _quantity(values["radius_mm"], "mm", "values.radius_mm")
            geometry["start_angle"] = _quantity(values["start_angle_deg"], "deg", "values.start_angle_deg")
            geometry["sweep_angle"] = _quantity(values["sweep_angle_deg"], "deg", "values.sweep_angle_deg")
        elif operation == "create_polygon":
            if type(values["outer"]) is not list or type(values["holes"]) is not list or any(type(loop) is not list for loop in values["holes"]):
                _fail("외곽과 구멍은 점 목록으로 입력하십시오.", "values.outer")
            geometry["outer"] = [_point(point, f"values.outer.{i}") for i, point in enumerate(values["outer"])]
            geometry["holes"] = [[_point(point, f"values.holes.{i}.{j}") for j, point in enumerate(loop)] for i, loop in enumerate(values["holes"])]
        elif operation == "create_pad":
            geometry.update(pad_shape=values["pad_shape"], center=_point(values["center"], "values.center"),
                            size=[_quantity(values[key], "mm", "values." + key) for key in ("width_mm", "height_mm")],
                            rotation=_quantity(values["rotation_deg"], "deg", "values.rotation_deg"))
        else:
            geometry.update(center=_point(values["center"], "values.center"), end_layer_id=_uuid(values["end_layer_id"], "values.end_layer_id"),
                            fill="none", pad_ids=deepcopy(values["pad_ids"]))
            for name in ("finished_hole_diameter", "plating_thickness", "tool_hole_diameter"):
                value = values[name + "_mm"]
                geometry[name] = Quantity.missing("length", "mm").to_dict() if value is None else _quantity(value, "mm", "values." + name + "_mm")
        geometry["name"] = allocate_name(document, geometry)
        command = {"type": "geometry.set", "payload": {"geometry": geometry}}
        return _with_drawing_relations(document, command, geometry, values["relations"]) if optional else command
    geometry = next((item for item in document["geometry"] if item["id"] == identity), None)
    if geometry is None:
        _fail("선택한 패턴이 없습니다.", "values.id", "E_CONFLICT")
    if operation == "remove":
        return {"type": "geometry.remove", "payload": {"id": identity}}
    if operation == "move_endpoint":
        return _move_coincident_endpoints(document, geometry, values["endpoint"], values["point"])
    if not _movable(geometry):
        _fail("매개변수에 연결되었거나 미정인 좌표는 직접 이동할 수 없습니다. 원래 속성을 편집하십시오.", "values.id", "E_CONFLICT")
    offsets = [Quantity(**_quantity(values[key], "mm", "values." + key)).value_si for key in ("dx_mm", "dy_mm")]
    if offsets == [0.0, 0.0]:
        _fail("이동량이 0입니다.", "values", "E_CONFLICT")
    members = sketch_constraints.translation_groups(document).get(identity)
    if members:
        from rfad.domain.pcb_features import COMMAND, finalize_pcb_edits, make_patch

        original = {row["id"]: row for row in document["geometry"]}
        blocked = _translation_block(document, members, original)
        if blocked:
            _fail(blocked, "values.id", "E_CONFLICT")
        candidate = deepcopy(document)
        candidate["geometry"] = [_translated(row, offsets) if row["id"] in members else row
                                 for row in candidate["geometry"]]
        finalize_pcb_edits(document, candidate, "geometry.set")
        patch = make_patch(document, candidate, "sketch.translate", "보존한 스케치 관계의 도체 연동 이동")
        return {"type": COMMAND, "payload": patch}
    return {"type": "geometry.set", "payload": {"geometry": _translated(geometry, offsets)}}


def _translated(geometry, offsets):
    """! @brief mm에서 환산한 이동량을 원래 수량 단위와 출처를 유지하여 더한다."""
    identity = geometry["id"]
    moved = deepcopy(geometry)
    for name, point in _coordinate_points(moved):
        for index, offset in enumerate(offsets):
            if offset == 0.0:
                continue
            original = Quantity(**point[index])
            number = original.value_si + offset
            if number == original.value_si:
                _fail("이동량이 현재 좌표의 표현 정밀도보다 작습니다.", f"geometry.{identity}.{name}.{index}", "E_UNIT")
            try:
                point[index] = Quantity(number, original.dimension, original.display_unit, "user_entered", original.source_refs).to_dict()
            except QuantityError as error:
                _fail(str(error), f"geometry.{identity}.{name}.{index}", "E_UNIT")
    return moved
