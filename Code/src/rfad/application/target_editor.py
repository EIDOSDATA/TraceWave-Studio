"""! @brief 목표 편집 조회/변경을 기존 요청 영수증과 프로젝트 명령에 연결한다."""

from copy import deepcopy
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import _fields, _uuid
from rfad.application.target_editor_fields import QUANTITIES, blank_target, fields_for, quantity_at, summary
from rfad.application.target_editor_values import edited_target, fail, sources
from rfad.domain.design import _text
from rfad.domain.errors import ProjectError
from rfad.domain.targets import MAX_SAMPLES, MAX_TARGETS, target_input_status


PROFILE = "rfad.target-editor/0.1"
MAX_DTO_BYTES = 60 * 1024


def input_status(target):
    """! @brief 상세 출처를 접어도 추정/자료 기본값과 미정 상태를 요약에 남긴다."""
    result = target_input_status(target)
    quantities = [quantity_at(target, key) for key in QUANTITIES]
    quantities += target["band"]["sampling"].get("frequencies", [])
    quantities += [row["limit"] for row in target["criteria"]]
    origins = {name: sum(value["status"] == name for value in quantities)
               for name in ("user_entered", "source_default", "estimated", "missing")}
    result.update(input_origins=origins, has_estimated_inputs=origins["estimated"] > 0,
                  has_source_defaults=origins["source_default"] > 0,
                  explicit_sample_count=len(target["band"]["sampling"].get("frequencies", [])),
                  summary=f"미평가 / 추정 입력 {origins['estimated']}개 / 자료 기본값 {origins['source_default']}개 / 미정 조건 {len(result['missing_conditions'])}개")
    return result


def selected(document, target_id):
    """! @brief null 선택은 저장 전 빈 입력이며 기존 목표는 안정 ID로만 찾는다."""
    if target_id is None:
        return blank_target()
    _uuid(target_id)
    target = next((item for item in document["targets"] if item["id"] == target_id), None)
    if target is None:
        fail("선택한 목표가 현재 프로젝트에 없습니다.", "target_id", "E_CONFLICT")
    return target


def read(service, params):
    """! @brief 저장/이력을 바꾸지 않고 현재 개정에 결합한 목표 편집 DTO를 반환한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 API 버전입니다.", "contract_version", "E_VERSION")
    _fields(params["context"], {"project_id"})
    _uuid(params["context"]["project_id"])
    data = _fields(params["input"], {"expected_revision", "target_id"})
    _uuid(data["expected_revision"])
    state = service.journal.read()
    project = service._project(state, params["context"])
    document = service._load(project)
    service._check_history_head(project, document["revision_id"])
    if data["expected_revision"] != document["revision_id"]:
        fail("목표 조회의 기준 개정이 현재 개정과 다릅니다.", "expected_revision", "E_CONFLICT")
    target = selected(document, data["target_id"])
    result = {"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
              "saved_revision": service._saved_revision(project), "history": service._history_status(project),
              "items": [{"id": item["id"], "label": item["name"], "summary": summary(item)} for item in document["targets"]],
              "selection": {"id": data["target_id"], "fields": fields_for(document, target)},
              "input_status": input_status(target),
              "limits": {"max_targets": MAX_TARGETS, "max_samples_per_target": MAX_SAMPLES, "max_dto_bytes": MAX_DTO_BYTES},
              "evaluation_supported": False, "changes_solver_settings": False}
    if len(canonical_bytes(result)) > MAX_DTO_BYTES:
        fail("목표 편집 표시가 60 KiB 상한을 초과했습니다. 원본은 보존되며 출처/표본을 생략하지 않습니다.", "target_id", "E_RESOURCE")
    return result


def validate_input(context, data):
    """! @brief 공개 편집 요청의 키, 식별자와 필수 변경 사유를 검증한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    _fields(data, {"expected_revision", "command_id", "operation", "target_id", "values", "reason"})
    _uuid(data["expected_revision"])
    _uuid(data["command_id"])
    if data["operation"] not in ("set", "remove"):
        fail("목표 작업은 set 또는 remove여야 합니다.", "operation", "E_UNSUPPORTED")
    if data["target_id"] is not None:
        _uuid(data["target_id"])
    if type(data["values"]) is not dict:
        fail("변경 필드는 object여야 합니다.", "values")
    _text(data["reason"], "reason", limit=512)
    if data["operation"] == "remove" and (data["target_id"] is None or data["values"]):
        fail("제거할 목표 ID와 빈 values가 필요합니다.", "target_id")


def _field_error(error, target):
    """! @brief 도메인의 목표 경로를 사용자가 편집한 필드 키로 대응한다."""
    path = error.details.get("field_path", "")
    if not path.startswith("targets[") or "]." not in path:
        return
    path = path.split("].", 1)[1]
    if path.startswith("band.sampling"):
        path = "sampling.explicit" if "frequencies" in path else path.replace("band.", "", 1)
    elif path.startswith("criteria["):
        try:
            index = int(path.split("[", 1)[1].split("]", 1)[0])
            metric = target["criteria"][index]["metric"]
            path = "criteria." + metric + ".value"
        except (ValueError, IndexError, KeyError):
            path = "values"
    elif path in ("band.start", "band.end", "band.reference", "reference_impedance"):
        path += ".value"
    error.details["field_path"] = path


def admit(service, state, context, data):
    """! @brief 영수증과 같은 transaction에서 기존 target 명령/undo 이력을 적용한다.

    @details 호출자는 RequestLedger 안에서 실행해야 한다. 재접수는 handler 전에
    원 영수증을 돌려주므로 신규 목표 UUID와 명령을 중복 생성하지 않는다.
    """
    validate_input(context, data)
    project = service._project(state, context)
    document = service._load(project)
    if document["revision_id"] != data["expected_revision"]:
        fail("목표 편집의 기준 개정이 현재 개정과 다릅니다.", "expected_revision", "E_CONFLICT")
    original = selected(document, data["target_id"])
    identity = data["target_id"]
    if data["operation"] == "remove":
        target = original
        command = {"type": "target.remove", "payload": {"id": identity}}
    else:
        target = edited_target(document, original, data["values"], data["reason"])
        if identity is not None and target == original:
            fail("원본을 변경하지 않는 입력입니다.", "values", "E_CONFLICT")
        identity = identity or str(uuid4())
        target["id"] = identity
        target.pop("revision_id", None)
        target["source_refs"] = sources(target["source_refs"], data["reason"])
        command = {"type": "target.set", "payload": {"target": target}}
    try:
        result = service._apply(state, context, {"expected_revision": data["expected_revision"], "command_id": data["command_id"], **command})
    except ProjectError as error:
        _field_error(error, target)
        raise
    state["commands"][data["command_id"]]["target_editor"] = {"profile": PROFILE, "target_id": identity,
                                                               "operation": data["operation"], "reason": data["reason"]}
    return {**deepcopy(result), "target_id": identity}
