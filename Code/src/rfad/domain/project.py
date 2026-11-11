"""! @brief 프로젝트, 표현식과 초기 설계 데이터의 불변 개정 규칙을 제공한다."""

from copy import deepcopy
from datetime import datetime, timezone
import math
from uuid import UUID, uuid4

from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity, QuantityError
from rfad.domain.parameter_graph import evaluate_parameters, expression_record, restore_parameter_command
from rfad.domain.design import apply_design_command, validate_design
from rfad.domain.pcb_selection import validate_project_selection
from rfad.domain.pcb_selection_command import apply_stackup_command
from rfad.domain.targets import TARGET_COMMANDS, apply_target_command, validate_targets


SCHEMA_VERSION = "rfad.project/0.3"
LEGACY_SCHEMA_VERSION = "rfad.project/0.1"
READABLE_SCHEMA_VERSIONS = (LEGACY_SCHEMA_VERSION, "rfad.project/0.2", SCHEMA_VERSION)
MAX_PARAMETERS = 128
_EMPTY_COLLECTIONS = (
    "geometry", "materials", "ports", "stackup", "nets", "connections", "targets",
    "networks", "environment", "analysis_definitions", "optimization_studies",
    "measurement_sets", "manufacturing_profiles", "export_profiles", "source_references",
    "assumptions", "validation_profiles",
)
_PROJECT_FIELDS = {
    "schema_version", "project_id", "revision_id", "parent_revision_ids", "metadata",
    "frames", "parameters", "board", "extensions", *_EMPTY_COLLECTIONS,
}
_QUANTITY_FIELDS = {"value_si", "dimension", "display_unit", "status", "source_refs"}
_IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
_DESIGN_COLLECTIONS = {"geometry", "materials", "ports", "stackup", "nets"}
DESIGN_COMMANDS = tuple(prefix + suffix for prefix in ("material", "layer", "net", "geometry", "port") for suffix in (".set", ".remove")) + ("board.set",)
COMMANDS = ("metadata.rename", "metadata.describe", "metadata.set", "parameter.set", "parameter.set_expression", "parameter.remove", "pcb_stackup.apply", *DESIGN_COMMANDS, *TARGET_COMMANDS)


def _fail(code: str, message: str, field: str) -> None:
    """! @brief 오류 위치를 포함한 구조화된 도메인 오류를 발생시킨다."""
    raise ProjectError(code, message, details={"field_path": field})


def _fields(value: object, fields: set[str], field: str) -> None:
    """! @brief 알려진 필드를 정확히 가진 object만 허용한다."""
    if type(value) is not dict or set(value) != fields:
        _fail("E_SCHEMA", "필수 필드가 없거나 지원하지 않는 필드가 있습니다.", field)


def _uuid(value: object, field: str) -> str:
    """! @brief 표준 소문자 하이픈 UUID 문자열을 검증한다."""
    if type(value) is not str:
        _fail("E_SCHEMA", "식별자는 UUID 문자열이어야 합니다.", field)
    try:
        parsed = UUID(value)
    except ValueError:
        _fail("E_SCHEMA", "유효하지 않은 UUID입니다.", field)
    if str(parsed) != value:
        _fail("E_SCHEMA", "UUID는 표준 소문자 하이픈 형식이어야 합니다.", field)
    return value


def _text(value: object, field: str, *, empty: bool = False, max_chars: int = 256, max_bytes: int = 4096) -> str:
    """! @brief 원문을 바꾸지 않고 문자열의 형식과 크기를 검사한다."""
    if type(value) is not str or (not empty and not value.strip()) or len(value) > max_chars:
        _fail("E_SCHEMA", "문자열이 비어 있거나 길이 제한을 위반했습니다.", field)
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        _fail("E_SCHEMA", "문자열을 UTF-8로 표현할 수 없습니다.", field)
    if len(encoded) > max_bytes or "\x00" in value:
        _fail("E_SCHEMA", "문자열 크기 또는 NUL 문자 규칙을 위반했습니다.", field)
    return value


def _timestamp(value: object, field: str) -> datetime:
    """! @brief UTC offset이 명시된 ISO 시각을 확인한다."""
    _text(value, field, max_chars=64, max_bytes=64)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        _fail("E_SCHEMA", "유효하지 않은 ISO 시각입니다.", field)
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        _fail("E_SCHEMA", "시각은 UTC offset을 명시해야 합니다.", field)
    return parsed


def _quantity(value: object, field: str) -> dict:
    """! @brief 이미 SI인 저장값을 다시 배율 변환하지 않고 검증한다."""
    _fields(value, _QUANTITY_FIELDS, field)
    if type(value["source_refs"]) is not list or len(value["source_refs"]) > 128:
        _fail("E_SCHEMA", "출처 참조는 최대 128개 문자열 목록이어야 합니다.", field + ".source_refs")
    for item in value["source_refs"]:
        _text(item, field + ".source_refs", max_chars=1024, max_bytes=4096)
    try:
        quantity = Quantity(**value)
    except (QuantityError, TypeError, ValueError) as error:
        _fail("E_SCHEMA", str(error), field)
    return quantity.to_dict()


def _extension_json(value: object, field: str, depth: int = 0, ancestors: set[int] | None = None) -> None:
    """! @brief 미지 extension의 JSON 값을 보존하되 실행하거나 해석하지 않는다."""
    if depth > 32:
        _fail("E_RESOURCE", "extension 최대 깊이 32를 초과했습니다.", field)
    value_type = type(value)
    if value is None or value_type is bool:
        return
    if value_type is int:
        if abs(value) > 2**53 - 1:
            _fail("E_SCHEMA", "extension 정수가 안전한 정수 범위를 벗어났습니다.", field)
        return
    if value_type is float:
        if not math.isfinite(value):
            _fail("E_SCHEMA", "extension에는 비유한 수치를 저장할 수 없습니다.", field)
        return
    if value_type is str:
        _text(value, field, empty=True, max_chars=4096, max_bytes=8192)
        return
    if value_type not in (dict, list):
        _fail("E_SCHEMA", "extension에는 JSON 자료형만 허용합니다.", field)
    if len(value) > 256:
        _fail("E_RESOURCE", "extension collection 상한을 초과했습니다.", field)
    if ancestors is None:
        ancestors = set()
    if id(value) in ancestors:
        _fail("E_SCHEMA", "extension에 순환 참조가 있습니다.", field)
    ancestors.add(id(value))
    try:
        if value_type is dict:
            for key, item in value.items():
                _text(key, field, max_chars=256)
                _extension_json(item, field, depth + 1, ancestors)
        else:
            for item in value:
                _extension_json(item, field, depth + 1, ancestors)
    finally:
        ancestors.remove(id(value))


def _new_frame(parent_frame_id: str | None) -> dict:
    """! @brief SI 원점과 오른손 항등 회전으로 초기 좌표계를 만든다."""
    return {
        "id": str(uuid4()), "parent_frame_id": parent_frame_id, "handedness": "right",
        "translation_si": [0.0, 0.0, 0.0], "rotation": deepcopy(_IDENTITY),
    }


def new_project(name: str, project_id: str | None = None, revision_id: str | None = None) -> dict:
    """! @brief 물성이나 결과 기본값 없이 빈 프로젝트 원본을 생성한다.

    @param name 사용자가 정한 프로젝트 이름.
    @param project_id 지정하지 않으면 새로 발급하는 프로젝트 UUID.
    @param revision_id 지정하지 않으면 새로 발급하는 개정 UUID.
    @return 초기 profile의 검증된 프로젝트 원본.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    world = _new_frame(None)
    document = {
        "schema_version": SCHEMA_VERSION,
        "project_id": str(uuid4()) if project_id is None else project_id,
        "revision_id": str(uuid4()) if revision_id is None else revision_id,
        "parent_revision_ids": [],
        "metadata": {"name": name, "description": "", "created_at": timestamp, "modified_at": timestamp},
        "frames": {"world": world, "board": _new_frame(world["id"])},
        "parameters": {}, "board": None, "extensions": {},
    }
    for field in _EMPTY_COLLECTIONS:
        document[field] = []
    validate_project(document)
    return document


def validate_project(document: dict) -> None:
    """! @brief 초기 프로젝트 profile의 필수 필드와 의미 제약을 검사한다.

    @param document 원본을 변경하지 않고 검사할 프로젝트.
    @throws ProjectError 미지원 schema/필드/형상 또는 유효하지 않은 값.
    """
    if type(document) is not dict:
        _fail("E_SCHEMA", "프로젝트는 object여야 합니다.", "project")
    if document.get("schema_version") not in READABLE_SCHEMA_VERSIONS:
        _fail("E_VERSION", "지원하지 않는 프로젝트 schema입니다.", "schema_version")
    legacy = document["schema_version"] == LEGACY_SCHEMA_VERSION
    _fields(document, _PROJECT_FIELDS, "project")
    project_id = _uuid(document["project_id"], "project_id")
    revision_id = _uuid(document["revision_id"], "revision_id")
    if project_id == revision_id:
        _fail("E_SCHEMA", "프로젝트와 개정의 UUID는 달라야 합니다.", "revision_id")
    parents = document["parent_revision_ids"]
    if type(parents) is not list or len(parents) > 1:
        _fail("E_SCHEMA", "초기 profile은 부모 개정을 최대 하나 지원합니다.", "parent_revision_ids")
    for parent in parents:
        _uuid(parent, "parent_revision_ids")
        if parent in (project_id, revision_id):
            _fail("E_SCHEMA", "부모 개정 UUID가 현재 식별자와 충돌합니다.", "parent_revision_ids")
    metadata = document["metadata"]
    _fields(metadata, {"name", "description", "created_at", "modified_at"}, "metadata")
    _text(metadata["name"], "metadata.name")
    _text(metadata["description"], "metadata.description", empty=True, max_chars=4096)
    created = _timestamp(metadata["created_at"], "metadata.created_at")
    modified = _timestamp(metadata["modified_at"], "metadata.modified_at")
    if modified < created:
        _fail("E_SCHEMA", "수정 시각이 생성 시각보다 빠릅니다.", "metadata.modified_at")
    frames = document["frames"]
    _fields(frames, {"world", "board"}, "frames")
    ids = {project_id, revision_id, *parents}
    for role in ("world", "board"):
        frame = frames[role]
        field = "frames." + role
        _fields(frame, {"id", "parent_frame_id", "handedness", "translation_si", "rotation"}, field)
        frame_id = _uuid(frame["id"], field + ".id")
        if frame_id in ids:
            _fail("E_SCHEMA", "좌표계 UUID가 다른 식별자와 충돌합니다.", field + ".id")
        ids.add(frame_id)
        expected_parent = None if role == "world" else frames["world"]["id"]
        if frame["parent_frame_id"] != expected_parent or frame["handedness"] != "right":
            _fail("E_UNSUPPORTED", "초기 오른손 world/board 관계만 지원합니다.", field)
        translation = frame["translation_si"]
        rotation = frame["rotation"]
        if type(translation) is not list or len(translation) != 3 or any(type(v) is not float for v in translation):
            _fail("E_SCHEMA", "좌표계 이동은 SI float64 3개여야 합니다.", field)
        if type(rotation) is not list or len(rotation) != 3 or any(type(row) is not list or len(row) != 3 or any(type(v) is not float for v in row) for row in rotation):
            _fail("E_SCHEMA", "좌표계 회전은 float64 3 x 3 행렬이어야 합니다.", field)
        if translation != [0.0, 0.0, 0.0] or rotation != _IDENTITY:
            _fail("E_UNSUPPORTED", "초기 profile은 항등 좌표계만 지원합니다.", field)
    parameters = document["parameters"]
    if type(parameters) is not dict or len(parameters) > MAX_PARAMETERS:
        _fail("E_RESOURCE", "매개변수는 최대 128개의 object여야 합니다.", "parameters")
    names = set()
    for parameter_id, parameter in parameters.items():
        _uuid(parameter_id, "parameters")
        fields = {"id", "name", "quantity"}
        if not legacy and type(parameter) is dict and "expression" in parameter:
            fields.add("expression")
        _fields(parameter, fields, "parameters." + parameter_id)
        if parameter["id"] != parameter_id or parameter_id in ids:
            _fail("E_SCHEMA", "매개변수 UUID가 key와 다르거나 충돌합니다.", "parameters." + parameter_id)
        ids.add(parameter_id)
        name = _text(parameter["name"], "parameters." + parameter_id + ".name")
        if name in names:
            _fail("E_CONFLICT", "매개변수 이름이 중복됩니다.", "parameters." + parameter_id + ".name")
        names.add(name)
        quantity = parameter["quantity"]
        _quantity(quantity, "parameters." + parameter_id + ".quantity")
        if quantity["value_si"] is not None and type(quantity["value_si"]) is not float:
            _fail("E_SCHEMA", "저장된 SI 스칼라는 float64여야 합니다.", "parameters." + parameter_id + ".quantity.value_si")
    if legacy and document["board"] is not None:
        _fail("E_UNSUPPORTED", "기판 형상 편집은 아직 지원하지 않습니다.", "board")
    for field in _EMPTY_COLLECTIONS:
        if not legacy and field in _DESIGN_COLLECTIONS:
            continue
        if document["schema_version"] == SCHEMA_VERSION and field == "targets":
            continue
        if type(document[field]) is not list:
            _fail("E_SCHEMA", "미구현 컬렉션은 빈 목록이어야 합니다.", field)
        if document[field]:
            _fail("E_UNSUPPORTED", "해당 컬렉션의 의미 모델은 아직 지원하지 않습니다.", field)
    if not legacy:
        evaluate_parameters(parameters)
        validate_design(document)
    if document["schema_version"] == SCHEMA_VERSION:
        validate_targets(document)
    if type(document["extensions"]) is not dict:
        _fail("E_SCHEMA", "extensions는 object여야 합니다.", "extensions")
    _extension_json(document["extensions"], "extensions")
    validate_project_selection(document)


def apply_command(document: dict, command: dict, expected_revision: str) -> tuple[dict, list[str], list[str], dict]:
    """! @brief 복제본에 명령을 검증 적용하고 새로운 개정과 역명령을 반환한다.

    @param document 변경하지 않을 현재 프로젝트 원본.
    @param command command_id/type/payload를 가진 명시적 명령.
    @param expected_revision 사용자가 편집한 기준 개정 UUID.
    @return 새 원본, 변경 ID, 보수적 무효화 목록, type/payload 역명령.
    @throws ProjectError stale 명령, 미지원 명령 또는 검증 오류.
    """
    validate_project(document)
    _uuid(expected_revision, "expected_revision")
    if document["revision_id"] != expected_revision:
        _fail("E_CONFLICT", "기준 개정이 현재 개정과 다릅니다.", "expected_revision")
    _fields(command, {"command_id", "type", "payload"}, "command")
    _uuid(command["command_id"], "command.command_id")
    command_type = command["type"]
    if type(command_type) is not str:
        _fail("E_SCHEMA", "명령 type은 문자열이어야 합니다.", "command.type")
    payload = command["payload"]
    result = deepcopy(document)
    result["schema_version"] = SCHEMA_VERSION
    if command_type == "metadata.set":
        _fields(payload, {"name", "description"}, "command.payload")
        _text(payload["name"], "command.payload.name")
        _text(payload["description"], "command.payload.description", empty=True, max_chars=4096)
        inverse = {"type": command_type, "payload": {key: result["metadata"][key] for key in ("name", "description")}}
        result["metadata"].update(payload)
        changed_ids = [result["project_id"]]
        invalidation_set = ["revision", "exports.metadata"]
    elif command_type in ("metadata.rename", "metadata.describe"):
        field = "name" if command_type == "metadata.rename" else "description"
        _fields(payload, {field}, "command.payload")
        _text(payload[field], "command.payload." + field, empty=field == "description", max_chars=256 if field == "name" else 4096)
        inverse = {"type": command_type, "payload": {field: result["metadata"][field]}}
        result["metadata"][field] = payload[field]
        changed_ids = [result["project_id"]]
        invalidation_set = ["revision", "exports.metadata"]
    elif command_type in ("parameter.set", "parameter.set_expression", "parameter.remove"):
        required = {"id", "name", "quantity"} if command_type == "parameter.set" else {"id"}
        if command_type == "parameter.set_expression":
            required = {"id", "name", "expression", "bindings", "dimension", "display_unit"}
        _fields(payload, required, "command.payload")
        parameter_id = _uuid(payload["id"], "command.payload.id")
        previous = result["parameters"].get(parameter_id)
        if previous is None:
            inverse = {"type": "parameter.remove", "payload": {"id": parameter_id}}
        else:
            inverse = restore_parameter_command(previous)
        if command_type == "parameter.set":
            name = _text(payload["name"], "command.payload.name")
            quantity = _quantity(payload["quantity"], "command.payload.quantity")
            result["parameters"][parameter_id] = {"id": parameter_id, "name": name, "quantity": quantity}
        elif command_type == "parameter.set_expression":
            name = _text(payload["name"], "command.payload.name")
            record = expression_record(payload["expression"], payload["bindings"])
            try:
                quantity = Quantity.missing(payload["dimension"], payload["display_unit"]).to_dict()
            except (QuantityError, ValueError, TypeError) as error:
                _fail("E_UNIT", str(error), "command.payload.dimension")
            result["parameters"][parameter_id] = {"id": parameter_id, "name": name, "quantity": quantity, "expression": record}
        else:
            if previous is None:
                _fail("E_SCHEMA", "제거할 매개변수가 없습니다.", "command.payload.id")
            del result["parameters"][parameter_id]
        changed_ids = [parameter_id]
        invalidation_set = ["revision", "geometry", "physics", "network", "metrics", "assessment", "exports"]
    elif command_type == "pcb_stackup.apply":
        changed_ids, invalidation_set, inverse = apply_stackup_command(result, payload)
    elif command_type in TARGET_COMMANDS:
        changed_ids, invalidation_set, inverse = apply_target_command(result, command_type, payload)
    elif command_type in DESIGN_COMMANDS:
        changed_ids, invalidation_set, inverse = apply_design_command(result, command_type, payload)
    else:
        _fail("E_UNSUPPORTED", "지원하지 않는 프로젝트 명령입니다.", "command.type")
    derived_changes = evaluate_parameters(result["parameters"], update=True)
    changed_ids = list(dict.fromkeys([*changed_ids, *derived_changes]))
    result["parent_revision_ids"] = [document["revision_id"]]
    result["revision_id"] = str(uuid4())
    previous_time = _timestamp(document["metadata"]["modified_at"], "metadata.modified_at")
    result["metadata"]["modified_at"] = max(datetime.now(timezone.utc), previous_time).isoformat()
    validate_project(result)
    return result, changed_ids, invalidation_set, inverse
