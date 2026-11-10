"""! @brief 기판, 적층, 도체 패턴/패드/비아와 단일 포트의 의미 모델을 검증한다.

@details CAD Boolean, 실제 도체 연결 판정과 해석기 기능 검증은
별도 단계다. 미정 물성은 저장할 수 있으며 목적별 preflight에서 구분한다.
"""

from copy import deepcopy
import math
from uuid import UUID

from rfad.domain.errors import ProjectError
from rfad.domain.planar import MAX_REGION_HOLES, MAX_REGION_POINTS, validate_region
from rfad.domain.units import Quantity, QuantityError


DESIGN_COLLECTIONS = ("materials", "stackup", "nets", "geometry", "ports")
DESIGN_COMMANDS = frozenset({"board.set", *(f"{kind}.{action}" for kind in ("material", "layer", "net", "geometry", "port") for action in ("set", "remove"))})
MAX_ENTITIES = 256
_QUANTITY_FIELDS = {"value_si", "dimension", "display_unit", "status", "source_refs"}
_GEOMETRY_FIELDS = {"id", "kind", "role", "frame_id", "layer_id", "net_id", "material_ref", "source_ref", "include_in_em", "include_in_export"}
_COLLECTION = {"material": "materials", "layer": "stackup", "net": "nets", "geometry": "geometry", "port": "ports"}


def _fail(code: str, message: str, field: str) -> None:
    """! @brief 오류 코드와 원본 필드 위치를 보존한다."""
    raise ProjectError(code, message, details={"field_path": field})


def _fields(value: object, fields: set[str], field: str) -> None:
    """! @brief 알려진 필드를 정확히 가진 object만 허용한다."""
    if type(value) is not dict or set(value) != fields:
        _fail("E_SCHEMA", "필수 필드가 없거나 지원하지 않는 설계 필드가 있습니다.", field)


def _uuid(value: object, field: str) -> str:
    """! @brief 표준 소문자 UUID 문자열을 검증한다."""
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        _fail("E_SCHEMA", "정규 UUID 문자열이 필요합니다.", field)
    return value


def _text(value: object, field: str, *, empty: bool = False, limit: int = 1024) -> str:
    """! @brief 문자열을 정규화하지 않고 원문과 길이를 검사한다."""
    if type(value) is not str or (not empty and not value.strip()) or len(value) > limit or "\0" in value:
        _fail("E_SCHEMA", "설계 문자열이 유효하지 않습니다.", field)
    try:
        if len(value.encode("utf-8")) > 4096:
            _fail("E_RESOURCE", "설계 문자열의 UTF-8 길이가 상한을 초과합니다.", field)
    except UnicodeError:
        _fail("E_SCHEMA", "문자열을 UTF-8로 표현할 수 없습니다.", field)
    return value


def _strings(value: object, field: str) -> None:
    """! @brief 근거와 가정 목록을 보존 가능한 문자열로 제한한다."""
    if type(value) is not list or len(value) > 128:
        _fail("E_RESOURCE", "출처 또는 가정 목록은 최대 128개여야 합니다.", field)
    for item in value:
        _text(item, field)


def resolve_scalar(document: dict, value: object, dimension: str, field: str = "quantity") -> Quantity:
    """! @brief literal 또는 parameter 참조를 이미 정규화된 SI 수량으로 읽는다.

    @param document 현재 평가된 parameter를 포함한 프로젝트.
    @param value Quantity object 또는 parameter_id 참조 object.
    @param dimension 해당 필드에 필요한 물리 차원.
    @param field 진단에 사용할 원본 필드 경로.
    @return 미정 상태를 보존한 불변 Quantity.
    """
    if type(value) is dict and set(value) == {"parameter_id"}:
        parameter_id = _uuid(value["parameter_id"], field + ".parameter_id")
        parameter = document.get("parameters", {}).get(parameter_id)
        if parameter is None:
            _fail("E_SCHEMA", "참조한 매개변수가 없습니다.", field)
        value = parameter.get("quantity")
    _fields(value, _QUANTITY_FIELDS, field)
    _strings(value["source_refs"], field + ".source_refs")
    try:
        result = Quantity(**value)
    except (ValueError, TypeError, QuantityError) as error:
        _fail("E_UNIT", str(error), field)
    if result.dimension.value != dimension:
        _fail("E_UNIT", "필드의 물리 차원과 수량이 일치하지 않습니다.", field)
    if value["value_si"] is not None and type(value["value_si"]) is not float:
        _fail("E_SCHEMA", "저장된 SI 값은 float64여야 합니다.", field)
    return result


def _number(document: dict, value: object, dimension: str, field: str, *, positive: bool = False, nonnegative: bool = False) -> float | None:
    """! @brief 미정값은 유지하고 이미 입력한 값의 정의역을 검사한다."""
    number = resolve_scalar(document, value, dimension, field).value_si
    if number is not None and ((positive and number <= 0.0) or (nonnegative and number < 0.0)):
        _fail("E_SCHEMA", "수량이 허용된 양수 또는 비음수 범위를 벗어났습니다.", field)
    return number


def _range(document: dict, value: object, field: str) -> tuple[float | None, float | None]:
    """! @brief 명시적 주파수 유효 범위를 검증한다."""
    _fields(value, {"min", "max"}, field)
    lower = _number(document, value["min"], "frequency", field + ".min", positive=True)
    upper = _number(document, value["max"], "frequency", field + ".max", positive=True)
    if lower is not None and upper is not None and lower >= upper:
        _fail("E_SCHEMA", "주파수 유효 범위의 상한은 하한보다 커야 합니다.", field)
    return lower, upper


def _vector2(document: dict, value: object, field: str) -> tuple[float | None, float | None]:
    """! @brief 평면 점의 두 길이 좌표를 검증한다."""
    if type(value) is not list or len(value) != 2:
        _fail("E_SCHEMA", "평면 좌표에는 길이 수량 두 개가 필요합니다.", field)
    return tuple(_number(document, item, "length", f"{field}[{index}]") for index, item in enumerate(value))


def _reference(value: object, mapping: dict, field: str, *, optional: bool = False) -> None:
    """! @brief 안정된 객체 ID만 참조하며 임의 대체 참조를 만들지 않는다."""
    if value is None and optional:
        return
    identity = _uuid(value, field)
    if identity not in mapping:
        _fail("E_SCHEMA", "참조한 설계 객체가 없거나 제거되었습니다.", field)


def _indexes(document: dict) -> dict[str, dict]:
    """! @brief 모든 설계 ID의 중복과 collection 상한을 검사한다."""
    frames = document.get("frames", {})
    used = {document.get("project_id"), document.get("revision_id"), *document.get("parent_revision_ids", [])}
    used.update(frame.get("id") for frame in frames.values())
    used.update(document.get("parameters", {}))
    indexes = {"frames": {frame["id"]: frame for frame in frames.values()}}
    board = document.get("board")
    if board is not None:
        if type(board) is not dict:
            _fail("E_SCHEMA", "board는 object 또는 null이어야 합니다.", "board")
        identity = _uuid(board.get("id"), "board.id")
        if identity in used:
            _fail("E_CONFLICT", "기판 ID가 다른 객체 ID와 충돌합니다.", "board.id")
        used.add(identity)
    total = 0
    for name in DESIGN_COLLECTIONS:
        values = document.get(name)
        if type(values) is not list:
            _fail("E_SCHEMA", "설계 collection은 목록이어야 합니다.", name)
        total += len(values)
        if total > MAX_ENTITIES:
            _fail("E_RESOURCE", "초기 설계 객체 수 상한 256개를 초과했습니다.", name)
        mapping = {}
        names = set()
        for value in values:
            if type(value) is not dict:
                _fail("E_SCHEMA", "설계 객체는 object여야 합니다.", name)
            identity = _uuid(value.get("id"), name + ".id")
            if identity in used:
                _fail("E_CONFLICT", "설계 ID가 다른 객체 ID와 충돌합니다.", name + ".id")
            used.add(identity)
            if "name" in value:
                label = _text(value["name"], name + ".name", limit=256)
                if label in names:
                    _fail("E_CONFLICT", "동일 collection의 이름이 중복됩니다.", name + ".name")
                names.add(label)
            mapping[identity] = value
        if name != "stackup" and list(mapping) != sorted(mapping):
            _fail("E_SCHEMA", "설계 collection은 UUID 오름차순으로 저장해야 합니다.", name)
        indexes[name] = mapping
    return indexes


def validate_design(document: dict) -> None:
    """! @brief 저장 가능한 설계 의미와 참조 무결성을 검사한다.

    @details 미정값 자체는 저장 오류가 아니다. 실제 CAD 연결성, 해석 지원,
    제조 공차와 장 정확도 판정은 수행하지 않는다.
    """
    if type(document) is not dict:
        _fail("E_SCHEMA", "프로젝트는 object여야 합니다.", "project")
    indexes = _indexes(document)
    board = document.get("board")
    if board is not None:
        _fields(board, {"id", "frame_id", "outline", "thickness_convention"}, "board")
        _reference(board["frame_id"], indexes["frames"], "board.frame_id")
        if board["thickness_convention"] != "finished":
            _fail("E_UNSUPPORTED", "현재 완성 적층 두께 규약만 지원합니다.", "board.thickness_convention")
        outline = board["outline"]
        if type(outline) is not dict:
            _fail("E_SCHEMA", "기판 외곽은 object여야 합니다.", "board.outline")
        if outline.get("kind") == "rectangle":
            _fields(outline, {"kind", "width", "height"}, "board.outline")
            for name in ("width", "height"):
                _number(document, outline[name], "length", "board.outline." + name, positive=True)
        elif outline.get("kind") == "circle":
            _fields(outline, {"kind", "center", "radius"}, "board.outline")
            _vector2(document, outline["center"], "board.outline.center")
            _number(document, outline["radius"], "length", "board.outline.radius", positive=True)
        else:
            _fail("E_UNSUPPORTED", "기판 외곽은 rectangle 또는 circle이어야 합니다.", "board.outline.kind")
    elif document["stackup"] or document["geometry"] or document["ports"]:
        _fail("E_SCHEMA", "적층, 패턴과 포트를 저장하려면 기판이 필요합니다.", "board")

    for material in document["materials"]:
        field = "materials." + material["id"]
        _fields(material, {"id", "name", "model", "epsilon_r", "tan_delta", "conductivity", "validity_hz", "source_refs", "assumptions"}, field)
        if material["model"] != "isotropic_constant":
            _fail("E_UNSUPPORTED", "현재 명시적 등방성 상수 물성만 지원합니다.", field + ".model")
        _number(document, material["epsilon_r"], "dimensionless", field + ".epsilon_r", positive=True)
        _number(document, material["tan_delta"], "dimensionless", field + ".tan_delta", nonnegative=True)
        _number(document, material["conductivity"], "conductivity", field + ".conductivity", nonnegative=True)
        _range(document, material["validity_hz"], field + ".validity_hz")
        _strings(material["source_refs"], field + ".source_refs")
        _strings(material["assumptions"], field + ".assumptions")

    orders = set()
    intervals = []
    for layer in document["stackup"]:
        field = "stackup." + layer["id"]
        _fields(layer, {"id", "name", "role", "order", "z_min", "thickness", "material_id"}, field)
        if layer["role"] not in ("conductor", "dielectric", "coating", "adhesive", "air"):
            _fail("E_UNSUPPORTED", "지원하지 않는 층 역할입니다.", field + ".role")
        order = layer["order"]
        if type(order) is not int or not 0 <= order < MAX_ENTITIES or order in orders:
            _fail("E_SCHEMA", "층 order는 중복되지 않는 범위 내 정수여야 합니다.", field + ".order")
        orders.add(order)
        _reference(layer["material_id"], indexes["materials"], field + ".material_id", optional=True)
        lower = _number(document, layer["z_min"], "length", field + ".z_min")
        thickness = _number(document, layer["thickness"], "length", field + ".thickness", positive=True)
        if lower is not None and thickness is not None:
            upper = lower + thickness
            if not math.isfinite(upper) or upper <= lower:
                _fail("E_SCHEMA", "층의 상부 위치를 float64로 표현할 수 없습니다.", field)
            intervals.append((order, lower, upper, field))
    if [layer["order"] for layer in document["stackup"]] != sorted(orders):
        _fail("E_SCHEMA", "적층은 order 오름차순으로 저장해야 합니다.", "stackup")
    previous = None
    for interval in sorted(intervals):
        if previous is not None:
            tolerance = 8 * max(math.ulp(previous[2]), math.ulp(interval[1]))
            if interval[1] < previous[2] - tolerance:
                _fail("E_GEOMETRY", "적층 순서가 z 위치와 다르거나 층 부피가 겹칩니다.", interval[3])
        previous = interval

    for net in document["nets"]:
        _fields(net, {"id", "name"}, "nets." + net["id"])
    for geometry in document["geometry"]:
        field = "geometry." + geometry["id"]
        kind = geometry.get("kind")
        if kind == "line_path":
            specific = {"start", "end", "width"}
        elif kind == "arc_path":
            specific = {"center", "radius", "start_angle", "sweep_angle", "width"}
        elif kind == "planar_region":
            specific = {"outer", "holes"}
        elif kind == "pad":
            specific = {"pad_shape", "center", "size", "rotation"}
        elif kind == "via":
            specific = {"center", "end_layer_id", "finished_hole_diameter", "plating_thickness", "tool_hole_diameter", "fill", "pad_ids"}
        else:
            _fail("E_UNSUPPORTED", "지원하지 않는 도체 의미 모델입니다.", field + ".kind")
        _fields(geometry, _GEOMETRY_FIELDS | specific, field)
        if geometry["role"] not in ("radiator", "ground", "feed", "short", "conductor"):
            _fail("E_UNSUPPORTED", "지원하지 않는 패턴 역할입니다.", field + ".role")
        _reference(geometry["frame_id"], indexes["frames"], field + ".frame_id")
        _reference(geometry["layer_id"], indexes["stackup"], field + ".layer_id")
        if indexes["stackup"][geometry["layer_id"]]["role"] != "conductor":
            _fail("E_GEOMETRY", "도체 패턴은 conductor 층에 속해야 합니다.", field + ".layer_id")
        _reference(geometry["net_id"], indexes["nets"], field + ".net_id", optional=True)
        _reference(geometry["material_ref"], indexes["materials"], field + ".material_ref", optional=True)
        if geometry["source_ref"] is not None:
            _text(geometry["source_ref"], field + ".source_ref")
        for flag in ("include_in_em", "include_in_export"):
            if type(geometry[flag]) is not bool:
                _fail("E_SCHEMA", "포함 여부는 명시적 bool이어야 합니다.", field + "." + flag)
        width = _number(document, geometry["width"], "length", field + ".width", positive=True) if kind in ("line_path", "arc_path") else None
        if kind == "line_path":
            start = _vector2(document, geometry["start"], field + ".start")
            end = _vector2(document, geometry["end"], field + ".end")
            if None not in (*start, *end) and start == end:
                _fail("E_GEOMETRY", "선 패턴의 길이는 0보다 커야 합니다.", field)
        elif kind == "arc_path":
            _vector2(document, geometry["center"], field + ".center")
            radius = _number(document, geometry["radius"], "length", field + ".radius", positive=True)
            _number(document, geometry["start_angle"], "angle", field + ".start_angle")
            sweep = _number(document, geometry["sweep_angle"], "angle", field + ".sweep_angle")
            if sweep is not None and (sweep == 0.0 or abs(sweep) > 2 * math.pi):
                _fail("E_GEOMETRY", "원호 sweep은 0이 아니고 한 바퀴 이하여야 합니다.", field + ".sweep_angle")
            if radius is not None and width is not None and width >= 2 * radius:
                _fail("E_GEOMETRY", "원호 선폭이 내부 반지름을 없애거나 뒤집습니다.", field + ".width")
        elif kind == "planar_region":
            outer, holes = geometry["outer"], geometry["holes"]
            if type(outer) is not list or type(holes) is not list or len(holes) > MAX_REGION_HOLES:
                _fail("E_GEOMETRY", "다각형 외곽과 최대 8개의 구멍 목록이 필요합니다.", field)
            loops = [outer, *holes]
            if any(type(loop) is not list or len(loop) < 3 for loop in loops) or sum(map(len, loops)) > MAX_REGION_POINTS:
                _fail("E_GEOMETRY", "각 loop는 3점 이상, 전체는 최대 64점이어야 합니다.", field)
            evaluated = [[list(_vector2(document, value, field + f".loop[{i}][{j}]")) for j, value in enumerate(loop)] for i, loop in enumerate(loops)]
            if all(value is not None for loop in evaluated for point in loop for value in point):
                validate_region(evaluated[0], evaluated[1:], field)
        elif kind == "pad":
            if geometry["pad_shape"] not in ("circle", "rectangle"):
                _fail("E_UNSUPPORTED", "초기 패드는 원형과 직사각형을 지원합니다.", field + ".pad_shape")
            _vector2(document, geometry["center"], field + ".center")
            size = _vector2(document, geometry["size"], field + ".size")
            if any(value is not None and value <= 0 for value in size):
                _fail("E_GEOMETRY", "패드 치수는 양수여야 합니다.", field + ".size")
            if geometry["pad_shape"] == "circle" and None not in size and not math.isclose(*size, rel_tol=1e-12, abs_tol=0.0):
                _fail("E_GEOMETRY", "원형 패드의 두 치수는 같은 지름이어야 합니다.", field + ".size")
            _number(document, geometry["rotation"], "angle", field + ".rotation")
        else:
            _vector2(document, geometry["center"], field + ".center")
            _reference(geometry["end_layer_id"], indexes["stackup"], field + ".end_layer_id")
            start_layer, end_layer = (indexes["stackup"][geometry[key]] for key in ("layer_id", "end_layer_id"))
            if end_layer["role"] != "conductor" or start_layer["order"] >= end_layer["order"]:
                _fail("E_GEOMETRY", "비아는 아래쪽 도체층에서 위쪽 도체층으로 연결해야 합니다.", field + ".end_layer_id")
            for name in ("finished_hole_diameter", "plating_thickness", "tool_hole_diameter"):
                _number(document, geometry[name], "length", field + "." + name, positive=True)
            if geometry["fill"] != "none":
                _fail("E_UNSUPPORTED", "초기 비아는 충진하지 않은 도금 관통 구멍을 지원합니다.", field + ".fill")
            pads = geometry["pad_ids"]
            if type(pads) is not list or len(pads) > 8 or any(type(value) is not str for value in pads) or len(set(pads)) != len(pads):
                _fail("E_SCHEMA", "비아 패드는 중복 없는 최대 8개의 참조여야 합니다.", field + ".pad_ids")
            for pad_id in pads:
                _reference(pad_id, indexes["geometry"], field + ".pad_ids")
                pad = indexes["geometry"][pad_id]
                if pad.get("kind") != "pad":
                    _fail("E_GEOMETRY", "비아 패드 참조는 pad 형상이어야 합니다.", field + ".pad_ids")
                _reference(pad.get("layer_id"), indexes["stackup"], "geometry." + pad_id + ".layer_id")
                order = indexes["stackup"][pad["layer_id"]]["order"]
                if not start_layer["order"] <= order <= end_layer["order"]:
                    _fail("E_GEOMETRY", "비아 패드가 연결 층 범위를 벗어났습니다.", field + ".pad_ids")

    if len(document["ports"]) > 1:
        _fail("E_UNSUPPORTED", "초기 profile은 단일 포트만 지원합니다.", "ports")
    for port in document["ports"]:
        field = "ports." + port["id"]
        optional = {"excitation_box"} if "excitation_box" in port else set()
        _fields(port, {"id", "name", "kind", "positive_geometry_id", "reference_geometry_id", "resistance", "reference_plane", "polarity", "direction", "validity_hz"} | optional, field)
        if port["kind"] != "lumped":
            _fail("E_UNSUPPORTED", "현재 lumped 포트 의미 모델만 지원합니다.", field + ".kind")
        for reference in ("positive_geometry_id", "reference_geometry_id"):
            _reference(port[reference], indexes["geometry"], field + "." + reference)
        if port["positive_geometry_id"] == port["reference_geometry_id"]:
            _fail("E_PORT", "포트의 두 도체 참조는 달라야 합니다.", field)
        _number(document, port["resistance"], "impedance", field + ".resistance", positive=True)
        _text(port["reference_plane"], field + ".reference_plane")
        if type(port["polarity"]) is not int or port["polarity"] not in (-1, 1):
            _fail("E_PORT", "포트 극성은 +1 또는 -1이어야 합니다.", field + ".polarity")
        direction = port["direction"]
        if type(direction) is not list or len(direction) != 3 or any(type(v) not in (int, float) for v in direction):
            _fail("E_PORT", "포트 방향은 유한 실수 3개여야 합니다.", field + ".direction")
        try:
            finite = all(math.isfinite(value) for value in direction)
        except OverflowError:
            finite = False
        if not finite:
            _fail("E_PORT", "포트 방향은 float64 범위의 유한 실수여야 합니다.", field + ".direction")
        if not math.isclose(math.hypot(*direction), 1.0, rel_tol=1e-12, abs_tol=1e-12):
            _fail("E_PORT", "포트 방향은 정규화된 단위 벡터여야 합니다.", field + ".direction")
        _range(document, port["validity_hz"], field + ".validity_hz")
        if "excitation_box" in port:
            box = port["excitation_box"]
            _fields(box, {"start", "stop"}, field + ".excitation_box")
            coordinates = {}
            for endpoint in ("start", "stop"):
                point = box[endpoint]
                if type(point) is not list or len(point) != 3:
                    _fail("E_PORT", "급전 영역 끝점에는 길이 수량 세 개가 필요합니다.", field + ".excitation_box." + endpoint)
                coordinates[endpoint] = [_number(document, value, "length", f"{field}.excitation_box.{endpoint}[{index}]") for index, value in enumerate(point)]
            if None not in (*coordinates["start"], *coordinates["stop"]) and coordinates["start"] == coordinates["stop"]:
                _fail("E_PORT", "급전 영역의 두 끝점은 같을 수 없습니다.", field + ".excitation_box")


def _normalize_quantities(value: object, depth: int = 0, ancestors: set[int] | None = None) -> object:
    """! @brief 명령의 literal SI 숫자를 한 번만 float64로 정규화한다."""
    if depth > 16:
        _fail("E_RESOURCE", "설계 명령의 입력 깊이 상한을 초과했습니다.", "command.payload")
    if type(value) not in (dict, list):
        return deepcopy(value)
    if len(value) > 256:
        _fail("E_RESOURCE", "설계 명령의 collection 상한을 초과했습니다.", "command.payload")
    if ancestors is None:
        ancestors = set()
    if id(value) in ancestors:
        _fail("E_SCHEMA", "설계 명령에는 순환 참조를 사용할 수 없습니다.", "command.payload")
    ancestors.add(id(value))
    try:
        if type(value) is dict:
            if set(value) == _QUANTITY_FIELDS:
                try:
                    return Quantity(**value).to_dict()
                except (ValueError, TypeError) as error:
                    raise ProjectError("E_UNIT", str(error)) from error
            return {key: _normalize_quantities(item, depth + 1, ancestors) for key, item in value.items()}
        return [_normalize_quantities(item, depth + 1, ancestors) for item in value]
    finally:
        ancestors.remove(id(value))


def apply_design_command(document: dict, command_type: str, payload: dict) -> tuple[list[str], list[str], dict]:
    """! @brief 지원한 설계 명령을 검증한 뒤 전달된 복사본에 적용한다.

    @return 변경 ID, 보수적 영향 목록, type/payload 역명령.
    @details 검증 실패 시 전달된 document도 변경하지 않는다.
    """
    if type(command_type) is not str or command_type not in DESIGN_COMMANDS:
        _fail("E_UNSUPPORTED", "지원하지 않는 설계 명령입니다.", "command.type")
    candidate = deepcopy(document)
    if command_type == "board.set":
        _fields(payload, {"board"}, "command.payload")
        old = deepcopy(candidate["board"])
        candidate["board"] = _normalize_quantities(payload["board"])
        inverse = {"type": "board.set", "payload": {"board": old}}
        changed = [item["id"] for item in (old, candidate["board"]) if type(item) is dict and "id" in item]
        changed = list(dict.fromkeys(changed))
    else:
        kind, action = command_type.split(".")
        collection = _COLLECTION[kind]
        _fields(payload, {kind} if action == "set" else {"id"}, "command.payload")
        if action == "set":
            entity = _normalize_quantities(payload[kind])
            if type(entity) is not dict:
                _fail("E_SCHEMA", "설계 명령의 객체가 유효하지 않습니다.", "command.payload")
            identity = _uuid(entity.get("id"), "command.payload." + kind + ".id")
        else:
            identity = _uuid(payload["id"], "command.payload.id")
        values = candidate[collection]
        previous = next((item for item in values if item["id"] == identity), None)
        inverse = {"type": kind + ".remove", "payload": {"id": identity}} if previous is None else {"type": kind + ".set", "payload": {kind: deepcopy(previous)}}
        if action == "remove" and previous is None:
            _fail("E_SCHEMA", "제거할 설계 객체가 없습니다.", "command.payload.id")
        if previous is not None:
            values.remove(previous)
        if action == "set":
            values.append(entity)
        if collection == "stackup":
            values.sort(key=lambda item: item.get("order", -1) if type(item.get("order")) is int else -1)
        else:
            values.sort(key=lambda item: item["id"])
        changed = [identity]
    validate_design(candidate)
    document.clear()
    document.update(candidate)
    return changed, ["revision", "geometry", "physics", "network", "metrics", "assessment", "exports"], inverse


def material_input_fields(*, conductor_only=False, volume_conductor=False):
    """! @brief 초기 유전체와 유한 전도 sheet가 실제 소비하는 필수 수량을 공유한다."""
    fields = (("conductivity", "conductivity"),)
    if not conductor_only or volume_conductor:
        fields += (("epsilon_r", "dimensionless"),)
    if not conductor_only:
        fields += (("tan_delta", "dimensionless"),)
    return fields


def preflight_design(document: dict, purpose: str) -> list[dict]:
    """! @brief 목적별 필수 입력 누락을 보고하며 실제 해석기 합격을 선언하지 않는다."""
    if purpose not in ("geometry", "step", "em"):
        _fail("E_SCHEMA", "preflight 목적은 geometry/step/em이어야 합니다.", "purpose")
    validate_design(document)
    diagnostics = []
    def missing(code, field, message):
        """! @brief 수량/참조 누락을 구조화된 차단 진단으로 기록한다."""
        diagnostic = ProjectError(code, message, details={"field_path": field}).diagnostic()
        diagnostic["field_paths"] = [field]
        diagnostics.append(diagnostic)
    def require(value, dimension, field, code="E_SCHEMA"):
        """! @brief 누락 상태를 계산 입력으로 소비하지 않는다."""
        if resolve_scalar(document, value, dimension, field).value_si is None:
            missing(code, field, "해당 목적에 필요한 입력이 미정입니다.")
    board = document["board"]
    if board is None:
        missing("E_GEOMETRY", "board", "기판 형상이 필요합니다.")
    else:
        outline = board["outline"]
        if outline["kind"] == "rectangle":
            for field in ("width", "height"):
                require(outline[field], "length", "board.outline." + field)
        else:
            require(outline["radius"], "length", "board.outline.radius")
            for index, coordinate in enumerate(outline["center"]):
                require(coordinate, "length", f"board.outline.center[{index}]")
    geometries = [item for item in document["geometry"] if item["include_in_em"]] if purpose == "em" else [item for item in document["geometry"] if item["include_in_export"]] if purpose == "step" else document["geometry"]
    if not geometries:
        missing("E_GEOMETRY", "geometry", "목적에 포함할 도체 패턴이 필요합니다.")
    for geometry in geometries:
        prefix = "geometry." + geometry["id"]
        kind = geometry["kind"]
        if kind in ("line_path", "arc_path"):
            require(geometry["width"], "length", prefix + ".width")
        if kind == "planar_region":
            for index, loop in enumerate([geometry["outer"], *geometry["holes"]]):
                for point_index, point in enumerate(loop):
                    for axis, value in enumerate(point):
                        require(value, "length", f"{prefix}.loop[{index}][{point_index}][{axis}]")
        else:
            for field in ("start", "end") if kind == "line_path" else ("center",):
                for index, item in enumerate(geometry[field]):
                    require(item, "length", f"{prefix}.{field}[{index}]")
        if kind == "arc_path":
            require(geometry["radius"], "length", prefix + ".radius")
            for field in ("start_angle", "sweep_angle"):
                require(geometry[field], "angle", prefix + "." + field)
        elif kind == "pad":
            for index, value in enumerate(geometry["size"]):
                require(value, "length", f"{prefix}.size[{index}]")
            require(geometry["rotation"], "angle", prefix + ".rotation")
        elif kind == "via":
            for field in ("finished_hole_diameter", "plating_thickness"):
                require(geometry[field], "length", prefix + "." + field)
            if purpose in ("step", "em") and len(geometry["pad_ids"]) < 2:
                missing("E_CONNECTIVITY", prefix + ".pad_ids", "비아 양끝에 연결할 실제 패드를 지정하십시오.")
    if purpose in ("step", "em"):
        if not document["stackup"]:
            missing("E_GEOMETRY", "stackup", "물리 적층이 필요합니다.")
        for layer in document["stackup"]:
            for field in ("z_min", "thickness"):
                require(layer[field], "length", f"stackup.{layer['id']}.{field}")
    if purpose == "em":
        materials = {item["id"]: item for item in document["materials"]}
        used_materials = set()
        dielectric_materials = set()
        volume_materials = set()
        for layer in document["stackup"]:
            if layer["material_id"] is None:
                missing("E_MATERIAL_UNKNOWN", f"stackup.{layer['id']}.material_id", "층에 명시적 물성 모델이 필요합니다.")
            else:
                used_materials.add(layer["material_id"])
                if layer["role"] != "conductor":
                    dielectric_materials.add(layer["material_id"])
        for geometry in geometries:
            if geometry["net_id"] is None:
                missing("E_CONNECTIVITY", f"geometry.{geometry['id']}.net_id", "도체의 의도된 net을 지정해야 합니다.")
            if geometry["material_ref"] is not None:
                used_materials.add(geometry["material_ref"])
                if geometry["kind"] == "via":
                    volume_materials.add(geometry["material_ref"])
            elif geometry["kind"] == "via":
                missing("E_MATERIAL_UNKNOWN", f"geometry.{geometry['id']}.material_ref", "비아 도금 재료를 명시하십시오.")
        for identity in sorted(used_materials):
            material = materials[identity]
            for field, dimension in material_input_fields(conductor_only=identity not in dielectric_materials, volume_conductor=identity in volume_materials):
                require(material[field], dimension, f"materials.{identity}.{field}", "E_MATERIAL_UNKNOWN")
            for field in ("min", "max"):
                require(material["validity_hz"][field], "frequency", f"materials.{identity}.validity_hz.{field}", "E_MATERIAL_RANGE")
        if not document["ports"]:
            missing("E_PORT", "ports", "단일 급전 포트가 필요합니다.")
        included = {geometry["id"] for geometry in geometries}
        for port in document["ports"]:
            if "excitation_box" not in port:
                missing("E_PORT", f"ports.{port['id']}.excitation_box", "실제 급전 시작/끝 좌표를 지정해야 합니다.")
            else:
                for field in ("start", "stop"):
                    for index, value in enumerate(port["excitation_box"][field]):
                        require(value, "length", f"ports.{port['id']}.excitation_box.{field}[{index}]", "E_PORT")
            require(port["resistance"], "impedance", f"ports.{port['id']}.resistance", "E_PORT")
            for field in ("min", "max"):
                require(port["validity_hz"][field], "frequency", f"ports.{port['id']}.validity_hz.{field}", "E_PORT")
            if port["positive_geometry_id"] not in included or port["reference_geometry_id"] not in included:
                missing("E_PORT", f"ports.{port['id']}", "포트의 두 도체를 EM 모델에 포함해야 합니다.")
            lower, upper = _range(document, port["validity_hz"], f"ports.{port['id']}.validity_hz")
            for identity in sorted(used_materials):
                minimum, maximum = _range(document, materials[identity]["validity_hz"], f"materials.{identity}.validity_hz")
                if None not in (lower, upper, minimum, maximum) and (lower < minimum or upper > maximum):
                    missing("E_MATERIAL_RANGE", f"materials.{identity}.validity_hz", "포트 검증 대역이 재료 모델의 유효 대역을 벗어납니다.")
    return diagnostics
