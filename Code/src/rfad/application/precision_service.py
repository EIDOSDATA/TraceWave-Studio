"""! @brief 정밀 치수/변환/평면 후보를 검토 해시와 영속 원자 명령에 연결한다."""

from copy import deepcopy
from uuid import UUID, uuid5

from rfad.adapters.planar_backend import installation_metadata, runtime
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.canvas import build_canvas_dto
from rfad.application.precision_candidates import (OPERATIONS, PLANAR_OPERATIONS, item_label,
                                                  operation_reason, parameter_copies, replacements, selected)
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.design import _text
from rfad.domain.errors import ProjectError
from rfad.domain import pattern_features as patterns
from rfad.domain.object_names import display_names, name_dto
from rfad.domain.precision_command import (COMMANDS, EXTENSION_KEY, MAX_ORIGIN_BYTES, MAX_RECORDS,
                                          apply_precision_command, record_hash)
from rfad.domain.precision_dimensions import dimensions
from rfad.domain.precision_transform import MAX_SELECTION, fail
from rfad.domain.resource_limits import MAX_DOCUMENT_BYTES


PROFILE = "rfad.precision-editor/0.1"
READS = {"precision.get", "precision.preview"}
MUTATION = "precision.apply"
MAX_DTO_BYTES = 256 * 1024
LIMITS = {"max_selection": MAX_SELECTION, "max_output_regions": 16, "max_region_points": 64,
          "max_region_holes": 8, "max_dto_bytes": MAX_DTO_BYTES, "max_coordinate_mm": 1e6,
          "max_origin_bytes": MAX_ORIGIN_BYTES, "max_origin_records": MAX_RECORDS}


def bounded(value):
    """! @brief 장면과 출처를 포함한 한 응답 전체를 생략 없이 제한한다."""
    if len(canonical_bytes(value)) > MAX_DTO_BYTES:
        fail("정밀 편집 응답이 256 KiB를 초과했습니다. 원문이나 장면을 자르지 않습니다.", "selection_ids", "E_RESOURCE")
    return value


def _hash(value):
    """! @brief 적용 시 사용자가 실제 검토한 SHA256을 요구한다."""
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        fail("검토한 review_hash가 필요합니다.", "review_hash", "E_HASH")


def validate_input(context, data, method=MUTATION):
    """! @brief 공개 요청은 닫힌 필드와 명시적 기준 개정을 사용한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    fields = {"expected_revision", "selection_ids"}
    if method != "precision.get":
        fields |= {"operation", "values"}
    if method == MUTATION:
        fields |= {"command_id", "review_hash", "reason"}
    _fields(data, fields)
    _uuid(data["expected_revision"])
    identities = data["selection_ids"]
    if type(identities) is not list or len(identities) > MAX_SELECTION:
        fail("선택은 최대 16개 UUID 목록이어야 합니다.", "selection_ids", "E_RESOURCE")
    for identity in identities:
        _uuid(identity)
    if len(identities) != len(set(identities)):
        fail("선택 객체가 중복됩니다.", "selection_ids", "E_CONFLICT")
    if method != "precision.get":
        if type(data["operation"]) is not str or data["operation"] not in OPERATIONS:
            fail("지원하지 않는 정밀 편집 작업입니다.", "operation", "E_UNSUPPORTED")
        _fields(data["values"], OPERATIONS[data["operation"]][1])
    if method == MUTATION:
        _uuid(data["command_id"])
        _hash(data["review_hash"])
        _text(data["reason"], "reason", empty=True, limit=512)
        if any(ord(char) < 32 or ord(char) == 127 for char in data["reason"]):
            fail("변경 메모에는 제어 문자를 사용할 수 없습니다.", "reason", "E_SCHEMA")


def _document(service, state, context, data):
    """! @brief writer 또는 읽기 snapshot의 동일 프로젝트/개정에서만 작업한다."""
    project = service._project(state, context)
    document = service._load(project)
    service._check_history_head(project, document["revision_id"])
    if document["revision_id"] != data["expected_revision"]:
        fail("정밀 편집의 기준 개정이 현재 개정과 다릅니다.", "expected_revision", "E_CONFLICT")
    return document


def _dimension_rows(document, rows):
    """! @brief 치수 키와 객체 UUID를 함께 반환하여 다른 객체에 잘못 적용하지 않는다."""
    return [{**dimension, "object_id": row["id"]} for row in rows for dimension in dimensions(document, row)]


def get(document, identities):
    """! @brief 선택의 이름/연관 치수/실행 가능 사유와 기존 매개변수 목록을 반환한다."""
    rows = selected(document, identities)
    operations = []
    for operation, (label, _) in OPERATIONS.items():
        reason = operation_reason(document, rows, operation)
        item = {"id": operation, "label": label, "enabled": not reason, "reason": reason}
        if operation in patterns.REGENERATE and not reason:
            item["values"] = patterns.match(document, rows, operation)["head"]["values"]
        operations.append(item)
    labels = display_names(document)
    return bounded({"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
                    "selection": [{"id": row["id"], **name_dto(document, row, labels=labels), "kind": row["kind"]} for row in rows],
                    "items": [{"id": row["id"], **name_dto(document, row, labels=labels), "kind": row["kind"], "layer_id": row["layer_id"]} for row in document["geometry"]],
                    "operations": operations, "dimensions": _dimension_rows(document, rows),
                    "parameters": [{"id": identity, "label": row["name"], "dimension": row["quantity"]["dimension"],
                                    "status": row["quantity"]["status"], "derived": "expression" in row}
                                   for identity, row in document["parameters"].items()],
                    "limits": LIMITS, "planar_engine": runtime()[1], "geometry_solver_supported": False,
                    "constraint_editor": "design.rules.get", "constraints_checked": False})


def preview(document, data):
    """! @brief 원본/영수증을 바꾸지 않고 재계산 가능한 후보와 검토 해시를 만든다."""
    from rfad.domain.project import SCHEMA_VERSION, validate_project

    base = {"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
            "operation": data["operation"], "selection_ids": deepcopy(data["selection_ids"]),
            "limits": LIMITS, "physics_verified": False, "constraints_checked": False}
    try:
        rows = selected(document, data["selection_ids"])
        if not rows:
            fail("선택 객체가 없습니다.", "selection_ids", "E_CONFLICT")
        base_hash = canonical_hash(document)
        seed = canonical_hash({"base_content_hash": base_hash, "operation": data["operation"], "values": data["values"], "selection_ids": data["selection_ids"]})
        origin_id = str(uuid5(UUID(document["project_id"]), "precision:" + seed))
        operation = data["operation"]
        if operation in patterns.REGENERATE or operation == "detach_pattern":
            rows, output, engine = patterns.editing(document, rows, operation, data["values"])
        else:
            output, engine = replacements(document, rows, operation, data["values"], origin_id)
            if operation in patterns.PATTERNS:
                engine["linked_pattern"] = True
        if output == rows and operation != "detach_pattern":
            fail("현재 원본과 같은 결과입니다. 변경할 값을 입력하십시오.", "values", "E_CONFLICT")
        dependencies = parameter_copies(document, [*rows, *output])
        digest = canonical_hash({"profile": PROFILE, "base_content_hash": base_hash, "expected_revision": data["expected_revision"],
                                 "selection_ids": data["selection_ids"], "operation": data["operation"], "values": data["values"],
                                 "engine": engine, "before": rows, "after": output, "parameters": dependencies})
        record = {"id": origin_id, "base_revision": document["revision_id"], "base_content_hash": base_hash,
                  "operation": data["operation"], "values": deepcopy(data["values"]), "selection_ids": [row["id"] for row in rows],
                  "before": deepcopy(rows), "after": deepcopy(output), "parameters": dependencies,
                  "engine": deepcopy(engine), "review_hash": digest, "reason": data.get("reason", "")}
        record["record_hash"] = record_hash(record)
        payload = {"expected_objects": [{"id": row["id"], "hash": canonical_hash(row)} for row in rows],
                   "replacement_objects": output, "origin_id": origin_id, "expected_origin_hash": None, "replacement_origin": record}
        candidate = deepcopy(document)
        candidate["schema_version"] = SCHEMA_VERSION
        apply_precision_command(candidate, payload)
        propagated = patterns.propagate(document, candidate)
        validate_project(candidate)
        size = len(canonical_bytes(candidate))
        if size > MAX_DOCUMENT_BYTES:
            fail("출처 사본을 포함한 프로젝트가 512 KiB 상한을 초과했습니다.", "selection_ids", "E_RESOURCE")
        source = {row["id"]: row for row in rows}
        source_ids = set(source)
        output_ids = {row["id"] for row in output}
        changes = [{"id": row["id"], "label": item_label(document, row), "action": "remove"} for row in rows if row["id"] not in output_ids]
        changes += [{"id": row["id"], "label": item_label(candidate, row), "action": "modify" if row["id"] in source_ids else "create"} for row in output if row != source.get(row["id"])]
        if propagated:
            generated = {row["id"]: row for row in candidate["geometry"] if row["id"] in propagated}
            changes.extend({"id": key, "label": item_label(candidate, generated[key]), "action": "modify"} for key in propagated)
        notices = [{"severity": "info", "code": "I_PRECISION_ONLY", "message": "명시 기하 편집 후보입니다. 연결/목표 제약/제조 규칙은 적용 후 현재 개정에서 다시 검사하십시오."}]
        if data["operation"] in PLANAR_OPERATIONS:
            notices.append({"severity": "info", "code": "I_PLANAR_REPLACEMENT", "message": "선택 영역을 새 다각형 UUID로 교체합니다. 원본/결과/출처 사본을 보존하며 자동 복구나 단순화는 수행하지 않습니다."})
        scene = build_canvas_dto(candidate)
        for omission in scene["omissions"]:
            if omission["id"] in output_ids:
                notices.append({"severity": "warning", "code": "W_DISPLAY_OMISSION", "message": omission["message"], "object_id": omission["id"]})
        return bounded({**base, "can_apply": True, "review_hash": digest, "scene": scene,
                        "changes": changes, "result_ids": [row["id"] for row in output], "dimensions": _dimension_rows(candidate, output),
                        "notices": notices, "engine": engine, "size": {"document_bytes": size, "document_limit_bytes": MAX_DOCUMENT_BYTES}}), payload
    except ProjectError as error:
        return bounded({**base, "can_apply": False, "review_hash": None, "scene": None, "changes": [], "result_ids": [], "dimensions": [],
                        "engine": None, "notices": [{"severity": "blocker", "code": error.code, "message": error.message, "details": error.details}]}), None


def read(service, method, params):
    """! @brief 읽기 요청에는 command_id/receipt가 없으며 현재 개정만 조회한다."""
    if method not in READS:
        fail("지원하지 않는 정밀 조회입니다.", "method", "E_UNSUPPORTED")
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 API 버전입니다.", "contract_version", "E_VERSION")
    context, data = params["context"], params["input"]
    validate_input(context, data, method)
    document = _document(service, service.journal.read(), context, data)
    return get(document, data["selection_ids"]) if method == "precision.get" else preview(document, data)[0]


def admit(service, state, context, data):
    """! @brief 동일 writer transaction 안에서 재검토하고 한 이력과 영수증으로 게시한다."""
    validate_input(context, data)
    document = _document(service, state, context, data)
    reviewed, payload = preview(document, data)
    if not reviewed["can_apply"]:
        fail("정밀 편집 후보의 차단 원인을 해결하십시오.", "values", "E_CONFLICT")
    if reviewed["review_hash"] != data["review_hash"]:
        fail("검토한 후보와 입력/원본/엔진이 다릅니다. 다시 미리 보십시오.", "review_hash", "E_CONFLICT")
    result = service._apply(state, context, {"expected_revision": data["expected_revision"], "command_id": data["command_id"],
                                            "type": COMMANDS[0], "payload": payload})
    state["commands"][data["command_id"]]["precision_editor"] = {"operation": data["operation"], "values": deepcopy(data["values"]),
                                                                 "review_hash": reviewed["review_hash"], "reason": data["reason"]}
    return {**result, "review_hash": reviewed["review_hash"], "selection_ids": reviewed["result_ids"], "origin_id": payload["origin_id"]}
