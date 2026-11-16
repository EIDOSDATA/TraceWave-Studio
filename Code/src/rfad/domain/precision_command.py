"""! @brief 정밀 편집 결과와 원본 사본을 한 원자 명령으로 적용하고 복원한다."""

from copy import deepcopy

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.design import _fields, _text, _uuid
from rfad.domain.precision_transform import MAX_SELECTION, fail


COMMANDS = ("geometry.precision.apply",)
EXTENSION_KEY = "rfad.precision-origin"
ORIGIN_SCHEMA = "rfad.precision-origin/0.1"
MAX_RECORDS = 128
MAX_ORIGIN_BYTES = 256 * 1024
RECORD_FIELDS = {"id", "base_revision", "base_content_hash", "operation", "values", "selection_ids",
                 "before", "after", "parameters", "engine", "review_hash", "reason", "record_hash"}


def record_hash(record):
    """! @brief 해시 자체를 제외한 원문/결과/의존 수량 사본을 봉인한다."""
    return canonical_hash({key: value for key, value in record.items() if key != "record_hash"})


def _digest(value, field):
    """! @brief 저장 해시는 소문자 SHA256 형식이어야 한다."""
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        fail("정규 SHA256 해시가 필요합니다.", field, "E_HASH")


def _objects(values, field):
    """! @brief 출처 객체 목록을 유한 크기와 안정 ID로 검사한다."""
    if type(values) is not list or not 1 <= len(values) <= MAX_SELECTION:
        fail("정밀 편집 객체 사본은 1~16개여야 합니다.", field, "E_RESOURCE")
    ids = []
    for value in values:
        if type(value) is not dict:
            fail("객체 사본은 object여야 합니다.", field, "E_SCHEMA")
        ids.append(_uuid(value.get("id"), field + ".id"))
    if len(ids) != len(set(ids)):
        fail("객체 사본의 UUID가 중복됩니다.", field, "E_CONFLICT")
    return ids


def validate_record(record):
    """! @brief 설치된 엔진 없이 과거 편집의 해시와 출처 사본을 검사한다."""
    _fields(record, RECORD_FIELDS, "precision_origin.record")
    _uuid(record["id"], "precision_origin.id")
    _uuid(record["base_revision"], "precision_origin.base_revision")
    _digest(record["base_content_hash"], "precision_origin.base_content_hash")
    _digest(record["review_hash"], "precision_origin.review_hash")
    _text(record["operation"], "precision_origin.operation", limit=64)
    _text(record["reason"], "precision_origin.reason", empty=True, limit=512)
    if any(ord(char) < 32 or ord(char) == 127 for char in record["reason"]):
        fail("편집 메모에는 제어 문자를 사용할 수 없습니다.", "precision_origin.reason", "E_SCHEMA")
    before_ids = _objects(record["before"], "precision_origin.before")
    _objects(record["after"], "precision_origin.after")
    if record["selection_ids"] != before_ids:
        fail("편집 사본과 선택 순서가 다릅니다.", "precision_origin.selection_ids", "E_HASH")
    if type(record["parameters"]) is not dict or len(record["parameters"]) > 128:
        fail("의존 매개변수 사본 상한을 초과했습니다.", "precision_origin.parameters", "E_RESOURCE")
    for identity, parameter in record["parameters"].items():
        _uuid(identity, "precision_origin.parameters.id")
        if type(parameter) is not dict or parameter.get("id") != identity:
            fail("매개변수 사본의 ID가 다릅니다.", "precision_origin.parameters", "E_HASH")
    if type(record["values"]) is not dict or type(record["engine"]) is not dict:
        fail("입력/엔진 출처 사본이 object가 아닙니다.", "precision_origin", "E_SCHEMA")
    if record["record_hash"] != record_hash(record):
        fail("정밀 편집의 원문 또는 결과 사본 해시가 다릅니다.", "precision_origin.record_hash", "E_HASH")


def validate_precision_origins(document):
    """! @brief 현재 형상의 이후 편집과 독립적으로 봉인 사본과 자원 예산을 검사한다."""
    value = document["extensions"].get(EXTENSION_KEY)
    if value is None:
        return
    _fields(value, {"schema", "records"}, "extensions." + EXTENSION_KEY)
    if value["schema"] != ORIGIN_SCHEMA:
        fail("지원하지 않는 정밀 편집 출처 버전입니다.", "precision_origin.schema", "E_VERSION")
    records = value["records"]
    if type(records) is not list or not 1 <= len(records) <= MAX_RECORDS:
        fail("정밀 편집 출처 사본은 1~128개여야 합니다.", "precision_origin.records", "E_RESOURCE")
    ids = []
    for record in records:
        validate_record(record)
        ids.append(record["id"])
    if ids != sorted(set(ids)):
        fail("정밀 편집 출처 UUID가 중복되거나 정렬되지 않았습니다.", "precision_origin.records", "E_CONFLICT")
    if len(canonical_bytes(value)) > MAX_ORIGIN_BYTES:
        fail("정밀 편집 출처가 256 KiB를 초과했습니다. 과거 사본은 삭제하지 않습니다.", "precision_origin", "E_RESOURCE")


def apply_precision_command(document, payload):
    """! @brief 지정 객체 교체와 출처 추가/제거를 한 번에 적용하고 정확한 역명령을 만든다."""
    _fields(payload, {"expected_objects", "replacement_objects", "origin_id", "expected_origin_hash", "replacement_origin"}, "command.payload")
    expected = payload["expected_objects"]
    if type(expected) is not list or not 1 <= len(expected) <= MAX_SELECTION:
        fail("교체 대상은 1~16개여야 합니다.", "command.payload.expected_objects", "E_RESOURCE")
    current = {item["id"]: item for item in document["geometry"]}
    removed = []
    previous_objects = []
    for item in expected:
        _fields(item, {"id", "hash"}, "command.payload.expected_objects")
        identity = _uuid(item["id"], "command.payload.expected_objects.id")
        _digest(item["hash"], "command.payload.expected_objects.hash")
        if identity in removed or identity not in current or canonical_hash(current[identity]) != item["hash"]:
            fail("변경 대상의 현재 원본과 검토한 사본이 다릅니다.", "command.payload.expected_objects", "E_CONFLICT")
        removed.append(identity)
        previous_objects.append(deepcopy(current[identity]))
    replacement = payload["replacement_objects"]
    new_ids = _objects(replacement, "command.payload.replacement_objects")
    if (set(current) - set(removed)) & set(new_ids):
        fail("생성 객체가 기존 UUID와 충돌합니다.", "command.payload.replacement_objects", "E_CONFLICT")
    origin_id = _uuid(payload["origin_id"], "command.payload.origin_id")
    records = document["extensions"].get(EXTENSION_KEY, {"records": []})["records"]
    previous_origin = next((row for row in records if row["id"] == origin_id), None)
    expected_hash = None if previous_origin is None else previous_origin["record_hash"]
    if expected_hash != payload["expected_origin_hash"]:
        fail("원본 출처 사본이 검토한 상태와 다릅니다.", "command.payload.expected_origin_hash", "E_CONFLICT")
    replacement_origin = payload["replacement_origin"]
    if replacement_origin is not None:
        validate_record(replacement_origin)
        if replacement_origin["id"] != origin_id:
            fail("출처 사본 UUID가 명령과 다릅니다.", "command.payload.origin_id", "E_HASH")
        if previous_origin is not None:
            fail("이미 보존한 출처 사본을 다른 사본으로 덮어쓸 수 없습니다.", "command.payload.origin_id", "E_CONFLICT")
        if replacement_origin["before"] != previous_objects or replacement_origin["after"] != replacement:
            fail("출처의 변경 전후 형상이 실제 교체 명령과 다릅니다.", "command.payload.replacement_origin", "E_HASH")
    elif previous_origin is None:
        fail("제거할 정밀 편집 출처 사본이 없습니다.", "command.payload.origin_id", "E_CONFLICT")
    elif previous_origin["after"] != previous_objects or previous_origin["before"] != replacement:
        fail("출처 사본과 실행 취소 대상 형상이 다릅니다.", "command.payload.replacement_objects", "E_HASH")
    candidate = deepcopy(document)
    candidate["geometry"] = sorted([item for item in candidate["geometry"] if item["id"] not in removed] + deepcopy(replacement), key=lambda item: item["id"])
    remaining = [deepcopy(row) for row in records if row["id"] != origin_id]
    if replacement_origin is not None:
        remaining.append(deepcopy(replacement_origin))
    if remaining:
        candidate["extensions"][EXTENSION_KEY] = {"schema": ORIGIN_SCHEMA, "records": sorted(remaining, key=lambda row: row["id"])}
    else:
        candidate["extensions"].pop(EXTENSION_KEY, None)
    validate_precision_origins(candidate)
    document.clear()
    document.update(candidate)
    inverse = {"type": COMMANDS[0], "payload": {
        "expected_objects": [{"id": row["id"], "hash": canonical_hash(row)} for row in replacement],
        "replacement_objects": previous_objects, "origin_id": origin_id,
        "expected_origin_hash": None if replacement_origin is None else replacement_origin["record_hash"],
        "replacement_origin": deepcopy(previous_origin),
    }}
    return list(dict.fromkeys([*removed, *new_ids])), ["revision", "geometry", "physics", "network", "design_checks", "metrics", "assessment", "exports"], inverse
