"""! @brief 단위와 참조를 서비스에서 해석하여 제한된 2D 표시 및 편집 명령을 제공한다."""

from copy import deepcopy
import json
import math
from uuid import UUID

from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity, QuantityError


PROFILE = "rfad.canvas/0.1"
MAX_DTO_BYTES = 60 * 1024
DISPLAY_RANGES = {"max_coordinate_mm": 1e9, "min_line_length_mm": 1e-9, "min_abs_sweep_deg": 1e-10}
OPERATIONS = {
    "create_board": {"id", "width_mm", "height_mm"},
    "create_circular_board": {"id", "center_x_mm", "center_y_mm", "radius_mm"},
    "create_layer": {"id", "name"},
    "create_dielectric_layer": {"id", "name"},
    "create_line": {"id", "layer_id", "width_mm", "start", "end"},
    "create_arc": {"id", "layer_id", "width_mm", "center", "radius_mm", "start_angle_deg", "sweep_angle_deg"},
    "create_polygon": {"id", "layer_id", "outer", "holes"},
    "create_pad": {"id", "layer_id", "pad_shape", "center", "width_mm", "height_mm", "rotation_deg"},
    "create_via": {"id", "layer_id", "end_layer_id", "center", "finished_hole_diameter_mm", "plating_thickness_mm", "tool_hole_diameter_mm", "pad_ids"},
    "translate": {"id", "dx_mm", "dy_mm"},
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


def build_canvas_dto(document: dict) -> dict:
    """! @brief mm/deg의 표시 모델만 만들며 미정 형상과 생략 사유를 분리한다."""
    result = {"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
              "unit": "mm", "angle_unit": "deg", "ranges": dict(DISPLAY_RANGES), "board": None,
              "layers": [{"id": layer["id"], "label": layer["name"], "role": layer["role"]} for layer in document["stackup"]],
              "shapes": [], "omissions": []}
    board = document["board"]
    if board is not None:
        outline = board["outline"]
        circular = outline["kind"] == "circle"
        visible = {"id": board["id"], "kind": "circle", "center": None, "radius": None} if circular else {"id": board["id"], "width": None, "height": None}
        for name in ("center", "radius") if circular else ("width", "height"):
            try:
                visible[name] = _display_point(document, outline[name], "board.outline." + name) if name == "center" else _display_length(document, outline[name], "board.outline." + name)
            except ProjectError as error:
                result["omissions"].append({"id": board["id"], "message": error.message})
        if circular and visible["center"] is not None and visible["radius"] is not None:
            center, radius = visible["center"], visible["radius"]
            if any(abs(coordinate) + radius > DISPLAY_RANGES["max_coordinate_mm"] or coordinate - radius >= coordinate + radius for coordinate in center):
                visible["radius"] = None
                result["omissions"].append({"id": board["id"], "message": "원형 기판 외곽이 2D 좌표 범위 또는 표현 정밀도를 벗어났습니다."})
        result["board"] = visible
    for geometry in document["geometry"]:
        try:
            prefix = "geometry." + geometry["id"]
            kind = geometry["kind"]
            labels = {"line_path": "선 패턴", "arc_path": "원호 패턴", "planar_region": "면 패턴", "pad": "패드", "via": "도금 비아"}
            shape = {"id": geometry["id"], "kind": geometry["kind"],
                     "label": labels[kind] + " " + geometry["id"][:8],
                     "layer_id": geometry["layer_id"], "role": geometry["role"],
                     "movable": _movable(geometry)}
            if kind in ("line_path", "arc_path"):
                shape["width"] = _display_length(document, geometry["width"], prefix + ".width")
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
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_DTO_BYTES:
        _fail("2D 표시 DTO가 초기 전송 크기 상한을 초과했습니다.", "canvas", "E_RESOURCE")
    return result


def canvas_command(document: dict, operation: str, values: dict) -> dict:
    """! @brief 제한된 화면 조작을 기존 도메인 명령 하나로 변환한다."""
    if type(operation) is not str or operation not in OPERATIONS:
        _fail("지원하지 않는 2D 편집 작업입니다.", "operation", "E_UNSUPPORTED")
    if type(values) is not dict or set(values) != OPERATIONS[operation]:
        _fail("작업에 필요한 필드와 허용한 필드를 확인하십시오.", "values")
    identity = _uuid(values["id"], "values.id")
    if operation.startswith("create_") and identity in _existing_ids(document):
        _fail("생성 ID가 기존 객체와 충돌합니다. 원본을 덮어쓰지 않았습니다.", "values.id", "E_CONFLICT")
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
        return {"type": "geometry.set", "payload": {"geometry": geometry}}
    geometry = next((item for item in document["geometry"] if item["id"] == identity), None)
    if geometry is None:
        _fail("선택한 패턴이 없습니다.", "values.id", "E_CONFLICT")
    if operation == "remove":
        return {"type": "geometry.remove", "payload": {"id": identity}}
    if not _movable(geometry):
        _fail("매개변수에 연결되었거나 미정인 좌표는 직접 이동할 수 없습니다. 원래 속성을 편집하십시오.", "values.id", "E_CONFLICT")
    offsets = [Quantity(**_quantity(values[key], "mm", "values." + key)).value_si for key in ("dx_mm", "dy_mm")]
    if offsets == [0.0, 0.0]:
        _fail("이동량이 0입니다.", "values", "E_CONFLICT")
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
    return {"type": "geometry.set", "payload": {"geometry": moved}}
