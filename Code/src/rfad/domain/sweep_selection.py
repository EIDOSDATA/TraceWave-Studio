"""! @brief 봉인한 연구 후보의 편집용 채택 출처와 한 번의 역명령을 보존한다."""

from copy import deepcopy
import re

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError

KEY = "rfad.sweep-selection"
PROFILE = "rfad.sweep-selection/0.1"
COMMAND = "sweep.selection.apply"
MAX_ORIGIN_BYTES = 64 * 1024


def fail(message, code="E_SCHEMA"):
    """! @brief 출처 및 명령의 손상을 명시적으로 거부한다."""
    raise ProjectError(code, message)


def validate_origin(document):
    """! @brief 원본 프로젝트 참조를 역사 기록으로 보존하고 현재 소유자로 바꾸지 않는다."""
    value = document["extensions"].get(KEY)
    if value is None:
        return
    if type(value) is not dict or set(value) != {"schema", "records"} or value["schema"] != PROFILE:
        fail("후보 채택 출처의 형식/버전이 다릅니다.", "E_VERSION")
    if type(value["records"]) is not list or not 1 <= len(value["records"]) <= 16:
        fail("후보 채택 이력은 최대 16개입니다.", "E_RESOURCE")
    from rfad.domain.project import _quantity, _uuid

    seen = set()
    for row in value["records"]:
        fields = {"id", "source_project_id", "source_revision_id", "snapshot", "definition", "candidate",
                  "study_id", "index", "calculated_ordinal", "source_pin", "values", "reason", "scope", "record_hash"}
        if type(row) is not dict or set(row) != fields:
            fail("후보 채택 출처의 필드가 다릅니다.")
        for key in ("id", "source_project_id", "source_revision_id", "study_id"):
            _uuid(row[key], KEY + "." + key)
        if row["id"] in seen:
            fail("후보 채택 출처 ID가 중복됩니다.")
        seen.add(row["id"])
        if row["scope"] != "editing_copy_only" or type(row["reason"]) is not str or not 1 <= len(row["reason"].strip()) <= 2048:
            fail("편집용 후보 채택의 사유/범위가 유효하지 않습니다.")
        for key in ("index", "calculated_ordinal"):
            if type(row[key]) is not int or not 0 <= row[key] < 128:
                fail("후보 채택의 순번이 유효하지 않습니다.")
        pin = row["source_pin"]
        if (type(pin) is not dict or set(pin) != {"identity_hash", "dataset_sha256"}
                or any(type(item) is not str or re.fullmatch("[0-9a-f]{64}", item) is None for item in pin.values())):
            fail("후보 채택 원본 pin이 유효하지 않습니다.")
        from rfad.domain.network_library import artifact
        artifact(row["definition"], "definition")
        artifact(row["candidate"], "candidate")
        snapshot = row["snapshot"]
        snapshot_fields = {"snapshot_id", "project_id", "revision_id", "schema_version", "canonical_version",
                           "content_hash", "sealed_at", "description", "validation_state", "artifact"}
        if (type(snapshot) is not dict or set(snapshot) != snapshot_fields
                or snapshot["project_id"] != row["source_project_id"] or snapshot["revision_id"] != row["source_revision_id"]):
            fail("후보 채택 원본 스냅샷의 소유자가 다릅니다.")
        _uuid(snapshot["snapshot_id"], "snapshot.snapshot_id")
        artifact(snapshot["artifact"], "snapshot.artifact")
        if (type(snapshot["content_hash"]) is not str or re.fullmatch("[0-9a-f]{64}", snapshot["content_hash"]) is None
                or snapshot["canonical_version"] != "rfad.canonical/1.0"):
            fail("후보 채택 스냅샷의 원본 hash/정규 버전이 다릅니다.", "E_HASH")
        if type(row["values"]) is not list or not 1 <= len(row["values"]) <= 8:
            fail("채택 매개변수 축은 1~8개입니다.")
        for item in row["values"]:
            if type(item) is not dict or set(item) != {"id", "before", "after"}:
                fail("채택 매개변수 출처 형식이 다릅니다.")
            _uuid(item["id"], "values.id")
            _quantity(item["before"], "values.before")
            _quantity(item["after"], "values.after")
        if row["record_hash"] != canonical_hash({key: item for key, item in row.items() if key != "record_hash"}):
            fail("후보 채택 출처의 해시가 다릅니다.", "E_HASH")
    if len(canonical_bytes(value)) > MAX_ORIGIN_BYTES:
        fail("후보 채택 출처가 64 KiB를 초과했습니다. 과거 출처를 삭제하지 않습니다.", "E_RESOURCE")


def apply_selection_command(document, payload):
    """! @brief 리터럴 매개변수와 출처만 교체하며 식 평가는 공통 명령 처리기가 한 번 수행한다."""
    fields = {"parameters", "expected_origin_hash", "origin"}
    if type(payload) is not dict or set(payload) != fields or type(payload["parameters"]) is not list:
        fail("후보 채택 내부 명령의 필드가 다릅니다.")
    if not 1 <= len(payload["parameters"]) <= 8:
        fail("후보 채택은 최대 8개 리터럴 매개변수만 지원합니다.")
    previous = deepcopy(document["extensions"].get(KEY))
    if canonical_hash(previous) != payload["expected_origin_hash"]:
        fail("후보 채택 출처가 검토 이후 변경됐습니다.", "E_CONFLICT")
    probe = deepcopy(document)
    if payload["origin"] is None:
        probe["extensions"].pop(KEY, None)
    else:
        probe["extensions"][KEY] = deepcopy(payload["origin"])
    validate_origin(probe)
    before_records = [] if previous is None else previous["records"]
    after_records = [] if payload["origin"] is None else payload["origin"]["records"]
    forward = len(after_records) == len(before_records) + 1 and after_records[:-1] == before_records
    backward = len(before_records) == len(after_records) + 1 and before_records[:-1] == after_records
    if not forward and not backward:
        fail("후보 채택 출처는 마지막 기록 한 개만 추가하거나 실행 취소할 수 있습니다.", "E_CONFLICT")
    record = after_records[-1] if forward else before_records[-1]
    expected_rows = [{"id": row["id"], "expected": row["before" if forward else "after"],
                      "replacement": row["after" if forward else "before"]} for row in record["values"]]
    if payload["parameters"] != expected_rows:
        fail("채택 출처의 이전/다음 값이 실제 단일 명령과 다릅니다.", "E_HASH")
    inverse_rows, changed = [], []
    from rfad.domain.project import _quantity
    for row in payload["parameters"]:
        if type(row) is not dict or set(row) != {"id", "expected", "replacement"}:
            fail("후보 채택 매개변수 명령의 필드가 다릅니다.")
        identity = row["id"]
        parameter = document["parameters"].get(identity)
        if identity in changed or parameter is None or "expression" in parameter:
            fail("후보 채택은 서로 다른 기존 리터럴 매개변수만 변경합니다.", "E_UNSUPPORTED")
        if parameter["quantity"] != row["expected"]:
            fail("후보 채택 매개변수의 이전 값이 다릅니다.", "E_CONFLICT")
        value = _quantity(row["replacement"], "parameters.replacement")
        if value["dimension"] != parameter["quantity"]["dimension"]:
            fail("후보 채택 매개변수의 차원이 다릅니다.")
        inverse_rows.append({"id": identity, "expected": deepcopy(value), "replacement": deepcopy(parameter["quantity"])})
        parameter["quantity"] = deepcopy(value)
        changed.append(identity)
    if payload["origin"] is None:
        document["extensions"].pop(KEY, None)
    else:
        document["extensions"][KEY] = deepcopy(payload["origin"])
    validate_origin(document)
    inverse = {"type": COMMAND, "payload": {"parameters": inverse_rows,
               "expected_origin_hash": canonical_hash(payload["origin"]), "origin": previous}}
    return changed, ["revision", "geometry", "physics", "network", "metrics", "assessment", "exports"], inverse
