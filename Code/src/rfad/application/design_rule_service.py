"""! @brief 규칙 편집/검사를 기존 revision/영수증/undo 경로에 연결한다."""

from copy import deepcopy
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.canvas import build_canvas_dto
from rfad.application.design_rule_forms import SECTIONS, forms, selected
from rfad.application.design_rule_values import edited
from rfad.application.project_contract import _fields, _uuid
from rfad.application.target_editor_values import sources
from rfad.domain.design import _text
from rfad.domain.design_checks import check_design
from rfad.domain.errors import ProjectError
from rfad.domain.target_constraints import empty_constraints


PROFILE = "rfad.design-rules-editor/0.1"
READS = {"design.rules.get", "design.rules.check"}
SELECTION_KEYS = {"section","record_id","target_id","parameter_id"}
MAX_DTO_BYTES = 256 * 1024


def bounded(value):
    """! @brief 원본/출처를 조용히 자르지 않고 응답 예산을 명시적으로 검사한다."""
    if len(canonical_bytes(value)) > MAX_DTO_BYTES:
        raise ProjectError("E_RESOURCE","설계 규칙 응답이 256 KiB 상한을 초과했습니다.")
    return value


def validate_selection(selection):
    """! @brief 네 종류 편집의 안정 ID를 명시적으로 구분한다."""
    _fields(selection,SELECTION_KEYS)
    if selection["section"] not in SECTIONS:
        raise ProjectError("E_UNSUPPORTED","규칙 편집 섹션을 지원하지 않습니다.")
    active_ids = {
        "target": {"target_id"},
        "parameter": {"target_id", "parameter_id"},
        "connection": {"record_id"},
        "manufacturing_profile": {"record_id"},
    }[selection["section"]]
    for key in SELECTION_KEYS - {"section"}:
        if selection[key] is not None:
            if key not in active_ids:
                raise ProjectError("E_SCHEMA", "선택 섹션과 객체 참조가 일치하지 않습니다.")
            _uuid(selection[key])


def validate_input(context,data):
    """! @brief 변경 요청 형식과 명시적 사유를 접수 전에 확인한다."""
    _fields(context,{"project_id"})
    _uuid(context["project_id"])
    _fields(data,{"expected_revision","command_id","selection","operation","values","reason"})
    _uuid(data["expected_revision"])
    _uuid(data["command_id"])
    validate_selection(data["selection"])
    if data["operation"] not in ("set","remove") or type(data["values"]) is not dict:
        raise ProjectError("E_SCHEMA","규칙 변경 operation/values 형식이 다릅니다.")
    if data["operation"] == "remove" and data["values"]:
        raise ProjectError("E_SCHEMA","제거 요청에는 빈 values가 필요합니다.")
    _text(data["reason"],"reason",limit=512)


def _document(service,state,context,data):
    """! @brief 정확히 요청한 프로젝트/현재 개정에서만 조회 또는 변경한다."""
    document = service._load(service._project(state,context))
    if document["revision_id"] != data["expected_revision"]:
        raise ProjectError("E_CONFLICT","규칙 요청의 기준 개정이 현재 개정과 다릅니다.")
    return document


def read(service,method,params):
    """! @brief 읽기는 원본/영수증/worker를 변경하지 않는다."""
    if method not in READS:
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 설계 규칙 조회입니다.")
    _fields(params,{"contract_version","context","input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION","지원하지 않는 API 버전입니다.")
    context,data = params["context"],params["input"]
    _fields(context,{"project_id"})
    _uuid(context["project_id"])
    if method == "design.rules.get":
        _fields(data,{"expected_revision","selection"})
        validate_selection(data["selection"])
    else:
        _fields(data,{"expected_revision","inclusion","target_ids","manufacturing_profile_id"})
        if data["target_ids"] is not None:
            if type(data["target_ids"]) is not list or len(data["target_ids"]) > 32:
                raise ProjectError("E_RESOURCE","검사 목표는 최대 32개입니다.")
            for identity in data["target_ids"]:
                _uuid(identity)
        if data["manufacturing_profile_id"] is not None:
            _uuid(data["manufacturing_profile_id"])
    _uuid(data["expected_revision"])
    document = _document(service,service.journal.read(),context,data)
    if method == "design.rules.check":
        report = check_design(document,**{key:data[key] for key in ("inclusion","target_ids","manufacturing_profile_id")})
        report["revision_hash"] = canonical_hash(document)
        while len(canonical_bytes(report)) > MAX_DTO_BYTES and (report["checks"] or report["issues"]):
            key = "checks" if report["checks"] else "issues"
            del report[key][max(0, len(report[key]) - 16):]
            report[key + "_truncated"] = True
        return bounded(report)
    fields,original,_ = forms(document,data["selection"])
    section = data["selection"]["section"]
    records = document["connections"] if section == "connection" else (document["manufacturing_profiles"] if section == "manufacturing_profile" else [])
    return bounded({"profile":PROFILE,"project_id":document["project_id"],"revision_id":document["revision_id"],
        "selection":deepcopy(data["selection"]),"fields":fields,"exists":original is not None,
        "records":[{"id":row["id"],"label":row["name"]} for row in records],
        "targets":[{key:row[key] for key in ("id","revision_id","name")} for row in document["targets"]],
        "parameters":[{"id":row["id"],"name":row["name"],"dimension":row["quantity"]["dimension"]} for row in document["parameters"].values()],
        "profiles":[{key:row[key] for key in ("id","name","version")} for row in document["manufacturing_profiles"]],
        "scene":build_canvas_dto(document),"physical_defaults_supplied":False,"evaluation_status":"not_evaluated"})


def admit(service,state,context,data):
    """! @brief 동일 writer transaction에서 변경 사유와 한 명령의 이력을 게시한다."""
    validate_input(context,data)
    document = _document(service,state,context,data)
    selection,remove = data["selection"],data["operation"] == "remove"
    original,target,_ = selected(document,selection)
    if remove and original is None:
        raise ProjectError("E_CONFLICT","제거할 규칙 원본이 없습니다.")
    record = None if remove else edited(document,selection,data["values"],data["reason"])
    section,identity = selection["section"],selection["record_id"]
    if section in ("target","parameter"):
        if target is None:
            raise ProjectError("E_CONFLICT","제약을 편집할 목표가 없습니다.")
        constraints = record if section == "target" else deepcopy(target.get("constraints",empty_constraints()))
        if section == "parameter":
            identity = selection["parameter_id"]
            constraints["parameter_bounds"] = [row for row in constraints["parameter_bounds"] if row["parameter_id"] != identity]
            if not remove:
                constraints["parameter_bounds"].append(record)
            constraints["parameter_bounds"].sort(key=lambda row:row["parameter_id"])
            constraints["source_refs"] = sources(constraints["source_refs"],data["reason"])
        command = {"type":"target.constraints.set","payload":{"target_id":target["id"],"constraints":constraints}}
    else:
        identity = identity or str(uuid4())
        if record is not None:
            record["id"] = identity
        command = {"type":section+(".remove" if remove else ".set"),"payload":{"id":identity} if remove else {"record":record}}
    result = service._apply(state,context,{"expected_revision":data["expected_revision"],"command_id":data["command_id"],**command})
    state["commands"][data["command_id"]]["design_rules_editor"] = {"selection":deepcopy(selection),"reason":data["reason"],"operation":data["operation"]}
    return {**result, "selection": {**selection, "record_id": identity if not remove and section in ("connection", "manufacturing_profile") else None}}
