"""! @brief PCB 선택 요청의 작은 명시적 입력과 응답 예산을 정의한다."""

import math
from uuid import UUID, uuid5

from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.errors import ProjectError


PROFILE = "rfad.pcb-selection/0.1"
MAX_RESULT_BYTES = 48 * 1024
READ_METHODS = frozenset({"pcb.selection.preview", "pcb.selection.get"})
MUTATION_METHODS = frozenset({"pcb.selection.apply"})


def text(value, field, *, maximum=256, empty=False):
    """! @brief 식별 문자열과 사용자가 정한 이유를 정규화 없이 검사한다."""
    if type(value) is not str or (not empty and not value.strip()) or len(value) > maximum or "\x00" in value:
        raise ProjectError("E_SCHEMA", "문자열 또는 선택 이유가 올바르지 않습니다.", details={"field_path": field})
    try:
        if len(value.encode("utf-8")) > 4096:
            raise ValueError()
    except (UnicodeError, ValueError) as error:
        raise ProjectError("E_RESOURCE", "선택 문자열의 UTF-8 크기 상한을 초과했습니다.") from error
    return value


def number(value, field, *, positive=False, nullable=False):
    """! @brief 명시적 유한 치수만 허용하고 bool과 단위 없는 문자열을 거절한다."""
    if nullable and value is None:
        return None
    if type(value) not in (int, float):
        raise ProjectError("E_SCHEMA", "명시적 숫자 또는 허용된 미정값이 필요합니다.", details={"field_path": field})
    try:
        result = float(value)
    except OverflowError as error:
        raise ProjectError("E_SCHEMA", "치수가 float64 범위를 벗어났습니다.") from error
    if not math.isfinite(result) or (positive and result <= 0):
        raise ProjectError("E_SCHEMA", "치수의 범위가 올바르지 않습니다.", details={"field_path": field})
    return result


def local_id(selection_id, kind, key):
    """! @brief 같은 미리보기 입력은 같은 새 객체 ID를 만들도록 한다."""
    text(key, kind + ".key", maximum=128)
    return str(uuid5(UUID(selection_id), kind + ":" + key))


def validate_source(source):
    """! @brief 카탈로그 개정과 원시 template 또는 관측을 명시한다."""
    if source is None:
        return
    _fields(source, {"catalog_id", "entity", "id"})
    text(source["catalog_id"], "source.catalog_id")
    text(source["id"], "source.id", maximum=512)
    if source["entity"] not in ("native_templates", "observations"):
        raise ProjectError("E_UNSUPPORTED", "적층 초안은 원시 template 또는 명시적 관측에서 시작합니다.")


def validate_input(method, context, value):
    """! @brief 적용 입력에 미리보기 해시와 기존 명령 ID를 요구한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    if method == "pcb.selection.get":
        _fields(value, set())
        return
    required = {"expected_revision", "selection_id", "specification"}
    if method == "pcb.selection.apply":
        required |= {"command_id", "preview_hash"}
    _fields(value, required)
    for key in ("expected_revision", "selection_id"):
        _uuid(value[key])
    if method == "pcb.selection.apply":
        _uuid(value["command_id"])
        digest = value["preview_hash"]
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ProjectError("E_SCHEMA", "적용에는 미리보기에서 받은 SHA-256이 필요합니다.")
    spec = _fields(value["specification"], {"source", "materials"}, {
        "layers", "layout_reason", "thickness_overrides", "material_assignments", "layer_ids", "material_ids",
        "z_origin_mm", "notes", "port_updates", "catalog_id",
    })
    validate_source(spec["source"])
    if "catalog_id" in spec:
        text(spec["catalog_id"], "specification.catalog_id")
        if spec["source"] is not None and spec["catalog_id"] != spec["source"]["catalog_id"]:
            raise ProjectError("E_CONFLICT", "적층과 재료는 같은 카탈로그 개정에서 선택해야 합니다.")
    if type(spec["materials"]) is not list or len(spec["materials"]) > 16:
        raise ProjectError("E_RESOURCE", "선택 재료는 최대 16개입니다.")
    for field in ("thickness_overrides", "material_assignments", "layer_ids", "material_ids"):
        if type(spec.get(field, {})) is not dict or len(spec.get(field, {})) > 32:
            raise ProjectError("E_SCHEMA", "층/재료 대응은 최대 32개 항목의 객체여야 합니다.")
    notes = spec.get("notes", [])
    if type(notes) is not list or len(notes) > 16:
        raise ProjectError("E_SCHEMA", "선택 설명은 최대 16개입니다.")
    for item in notes:
        text(item, "notes", maximum=1024)


def read_envelope(params):
    """! @brief 조회는 mutation 영수증이나 프로젝트 변경을 만들지 않는다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    return params["context"], params["input"]


def bounded(value):
    """! @brief 일부 출처나 변경을 숨기지 않고 큰 응답을 명시적으로 거부한다."""
    if len(canonical_bytes(value)) > MAX_RESULT_BYTES:
        raise ProjectError("E_RESOURCE", "PCB 선택 결과가 48 KiB를 초과했습니다. 선택 범위를 줄이십시오.")
    return value
