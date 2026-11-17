"""! @brief 완료된 설계 후보를 원본과 분리된 새 작업 사본으로 검토하고 원자 등록한다."""

from copy import deepcopy
import re
from uuid import UUID, uuid5

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.canvas import build_canvas_dto
from rfad.application.design_sweep_store import baseline, bounded, load_candidate
from rfad.application.project_contract import MAX_HISTORY, MAX_PROJECTS, _fields, _path, _uuid
from rfad.application.project_history import ProjectHistory
from rfad.application.result_sources import resolve, validate_pin
from rfad.application.sweep_copy import BufferedRepository, prepare_artifacts
from rfad.domain.design_checks import blocking_diagnostics, check_design
from rfad.domain.design_sweep import _evaluation_key, _indices
from rfad.domain.errors import ProjectError
from rfad.domain.parameter_graph import evaluate_parameters
from rfad.domain.project import validate_project
from rfad.domain.sweep_selection import COMMAND, KEY, PROFILE, validate_origin
from rfad.domain.units import Quantity
from rfad.storage.journal import MAX_STATE_BYTES

READS = {"sweep.selection.context", "sweep.selection.preview", "sweep.selection.receipt"}
MUTATIONS = {"sweep.selection.apply"}
SELECTION_FIELDS = {"expected_revision", "study_id", "index", "definition_hash", "source_pin", "name", "path", "reason"}


def validate_input(method, context, data):
    """! @brief 새 사본의 요청과 이전 영수증 조회를 서로 다른 닫힌 형식으로 검증한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    if method == "sweep.selection.receipt":
        _fields(data, {"request_key", "request_key_epoch"})
        _uuid(data["request_key_epoch"])
        if type(data["request_key"]) is not str or not 1 <= len(data["request_key"]) <= 128 or any(ord(c) < 32 for c in data["request_key"]):
            raise ProjectError("E_SCHEMA", "권위 조회할 요청 키가 유효하지 않습니다.")
        return
    _fields(data, {"study_id", "index"} if method == "sweep.selection.context" else
            SELECTION_FIELDS | ({"review_hash", "command_id"} if method in MUTATIONS else set()))
    _uuid(data["study_id"])
    if type(data["index"]) is not int or not 0 <= data["index"] < 128:
        raise ProjectError("E_SCHEMA", "연구 후보의 순번은 0~127입니다.")
    if method == "sweep.selection.context":
        return
    _uuid(data["expected_revision"])
    validate_pin(data["source_pin"])
    for key in ("definition_hash",) + (("review_hash",) if method in MUTATIONS else ()):
        if type(data[key]) is not str or re.fullmatch("[0-9a-f]{64}", data[key]) is None:
            raise ProjectError("E_SCHEMA", "후보 검토 해시가 유효하지 않습니다.")
    for key, limit in (("name", 256), ("reason", 2048)):
        if type(data[key]) is not str or len(data[key]) > limit or any(ord(c) < 32 and c not in "\n\t" for c in data[key]):
            raise ProjectError("E_SCHEMA", "사본 이름/사유의 길이 또는 문자가 유효하지 않습니다.")
    _path(data["path"])
    if method in MUTATIONS:
        _uuid(data["command_id"])


def _selection(service, state, context, data):
    """! @brief 현재 생성기를 실행하지 않고 선택 행과 실제 계산 원본의 물리 입력을 대조한다."""
    project = service._project(state, context)
    current = service._load(project)
    study = state.get("sweeps", {}).get(data["study_id"])
    if study is None or study["project_id"] != context["project_id"]:
        raise ProjectError("E_CONFLICT", "선택한 연구의 소유 프로젝트가 다릅니다.")
    definition, original = baseline(service, study)
    spec = definition["specification"]
    if study["type"] != "grid_sweep" or spec["type"] != "grid_sweep" or any(axis["kind"] != "parameter" for axis in spec["variables"]):
        raise ProjectError("E_UNSUPPORTED", "리터럴 매개변수만 변경한 설계 스윕의 완료 후보만 새 작업 사본으로 채택합니다. 수치/회로/혼합 축은 지원하지 않습니다.")
    candidate = load_candidate(service, study, data["index"])
    if candidate is None or candidate.get("state") != "completed" or candidate.get("validation_status") != "valid":
        raise ProjectError("E_UNSUPPORTED", "유효 입력으로 완료되고 복소 결과가 봉인된 후보가 필요합니다.")
    selected = deepcopy(original)
    expected_indices = _indices(spec, data["index"])
    expected_values = [{"kind": axis["kind"], "id": axis["id"], "index": index, "value": axis["values"][index]}
                       for axis, index in zip(spec["variables"], expected_indices)]
    if candidate["indices"] != expected_indices or candidate["values"] != expected_values:
        raise ProjectError("E_HASH", "선택 순번의 봉인 값이 연구 정의의 정확한 행과 다릅니다.")
    changes = []
    for item in candidate["values"]:
        parameter = selected["parameters"].get(item["id"])
        if parameter is None or "expression" in parameter:
            raise ProjectError("E_UNSUPPORTED", "식으로 계산되는 매개변수는 후보 채택으로 직접 덮어쓰지 않습니다.")
        changes.append({"id": item["id"], "label": parameter["name"], "before": deepcopy(parameter["quantity"]),
                        "after": deepcopy(item["value"])})
        parameter["quantity"] = deepcopy(item["value"])
    evaluate_parameters(selected["parameters"], update=True)
    validate_project(selected)
    blocking = blocking_diagnostics(check_design(selected, inclusion="em", target_ids=spec["target_ids"]))
    if blocking:
        raise ProjectError("E_DESIGN_CONSTRAINT", "채택할 후보가 현재 명시 제약을 통과하지 못했습니다.", details={"diagnostics": blocking})
    source = {"kind": "sweep", "study_id": study["study_id"], "index": data["index"]}
    resolved = resolve(service, context, source, data.get("source_pin"))
    actual = resolved["source_document"]
    current_key = _evaluation_key(selected, spec["settings"], None, spec)
    if (current_key != candidate["evaluation_key"]
            or current_key != _evaluation_key(actual, spec["settings"], None, spec)):
        raise ProjectError("E_VERSION", "현재 해석한 선택 행의 물리 입력이 당시 봉인 계산 원본과 다릅니다. 과거 결과로 대체하지 않습니다.")
    for row in changes:
        row["unit"] = row["after"]["display_unit"]
        for key in ("before", "after"):
            quantity = Quantity(**row[key])
            row[key + "_display"] = "미정" if quantity.value_si is None else format(quantity.as_unit(row["unit"]), ".15g")
    return project, current, study, definition, original, selected, candidate, resolved, changes


def _destination(service, state, path):
    """! @brief 다른 프로젝트와 기존 실제 디렉터리를 새 사본으로 덮어쓰지 않는다."""
    if len(state["projects"]) >= MAX_PROJECTS:
        raise ProjectError("E_RESOURCE", "프로젝트 수 32개 상한에 도달했습니다.")
    if any(key.casefold() == path.casefold() for key in state["paths"]) or (service.workspace / path).exists():
        raise ProjectError("E_CONFLICT", "새 작업 사본의 경로가 이미 존재합니다. 기존 파일은 덮어쓰지 않습니다.")


def _prepare(service, state, context, data, command_id):
    """! @brief 복사 폐쇄/단일 명령/역명령까지 모든 확정 검증을 파일 게시 전에 수행한다."""
    values = _selection(service, state, context, data)
    project, current, study, definition, original, selected, candidate, resolved, changes = values
    if current["revision_id"] != data["expected_revision"]:
        raise ProjectError("E_CONFLICT", "후보를 검토한 원본 프로젝트의 현재 개정이 바뀌었습니다.")
    if study["definition"]["sha256"] != data["definition_hash"]:
        raise ProjectError("E_HASH", "검토한 연구 정의의 hash가 다릅니다.")
    if not data["name"].strip() or not data["reason"].strip():
        raise ProjectError("E_SCHEMA", "새 작업 사본의 이름과 채택 사유를 입력하십시오.")
    _destination(service, state, data["path"])
    copied, blobs, copied_refs = prepare_artifacts(service, project, original, data["path"])
    copied["project_id"] = str(uuid5(UUID(command_id), "sweep-selection-project"))
    copied["revision_id"] = str(uuid5(UUID(command_id), "sweep-selection-baseline"))
    copied["parent_revision_ids"] = []
    copied["metadata"]["name"] = data["name"]
    validate_project(copied)
    origin = deepcopy(copied["extensions"].get(KEY, {"schema": PROFILE, "records": []}))
    record = {"id": command_id, "source_project_id": context["project_id"], "source_revision_id": original["revision_id"],
              "snapshot": deepcopy(definition["snapshot"]), "definition": deepcopy(study["definition"]),
              "candidate": deepcopy(study["records"][str(data["index"])]) , "study_id": study["study_id"],
              "index": data["index"], "calculated_ordinal": resolved["calculated_ordinal"], "source_pin": deepcopy(resolved["pin"]),
              "values": [{key: deepcopy(row[key]) for key in ("id", "before", "after")} for row in changes],
              "reason": data["reason"], "scope": "editing_copy_only"}
    record["record_hash"] = canonical_hash(record)
    origin["records"].append(record)
    payload = {"parameters": [{"id": row["id"], "expected": row["before"], "replacement": row["after"]} for row in changes],
               "expected_origin_hash": canonical_hash(copied["extensions"].get(KEY)), "origin": origin}
    repository = BufferedRepository(service.repository)
    reference = repository.store(data["path"], copied)
    staged = deepcopy(state)
    project_id = copied["project_id"]
    if project_id in staged["projects"]:
        raise ProjectError("E_CONFLICT", "같은 명령으로 생성된 사본이 이미 존재합니다. 이전 영수증을 조회하십시오.")
    staged["projects"][project_id] = {"path": data["path"], "current": reference, "saved": deepcopy(reference),
        "revisions": {copied["revision_id"]: reference}, "history": {"undo": [], "redo": [], "head_revision": copied["revision_id"]}}
    staged["paths"][data["path"]] = project_id
    applied = ProjectHistory(repository).apply(staged, {"project_id": project_id}, {
        "command_id": command_id, "expected_revision": copied["revision_id"], "type": COMMAND, "payload": payload}, limit=MAX_HISTORY)
    final_project = staged["projects"][project_id]
    final_project["saved"] = deepcopy(final_project["current"])
    final_document = repository.load(final_project)
    validate_origin(final_document)
    blobs.update(repository.blobs)
    review = canonical_hash({"profile": PROFILE, "input": {key: data[key] for key in SELECTION_FIELDS},
                            "baseline_hash": canonical_hash(original), "candidate_hash": canonical_hash(candidate),
                            "pin": resolved["pin"], "copy_references": copied_refs, "changes": changes})
    response = {"source_project_id": context["project_id"], "source_revision_id": current["revision_id"],
                "new_project_id": project_id, "path": data["path"], "revision_id": applied["new_revision"],
                "revision_hash": applied["revision_hash"], "history": applied["history"], "source_pin": deepcopy(resolved["pin"]),
                "study_id": study["study_id"], "index": data["index"], "scope": "editing_copy_only"}
    preview = {"project_id": context["project_id"], "revision_id": current["revision_id"], "can_apply": True,
               "review_hash": review, "study_id": study["study_id"], "index": data["index"], "source": resolved["source"],
               "source_pin": resolved["pin"], "label": resolved["label"], "calculated_ordinal": resolved["calculated_ordinal"], "changes": changes,
               "scene": build_canvas_dto(selected), "before_scene": build_canvas_dto(original), "states": resolved["states"],
               "historical_assessments": resolved["historical_assessments"], "numerical_details": resolved["numerical_details"],
               "copy_summary": {"artifact_count": len(copied_refs), "artifact_bytes": sum(row["copy"]["bytes"] for row in copied_refs),
                                "total_bytes": sum(len(raw) for raw in blobs.values()), "source_revision_matches_current": original["revision_id"] == current["revision_id"],
                                "scope": "editing_copy_only", "saved_state": "adopted", "undo_state": "copied_baseline"},
               "issues": [], "notice": "편집용 후보 채택입니다. 새 사본의 해석/수렴/제작/측정 검증은 별도이며 과거 합격 상태를 승계하지 않습니다."}
    #! 요청 키 최대 128자와 고정 envelope/시각/hash를 포함한 영수증 상한을 게시 전에 예약한다.
    state_bytes = len(canonical_bytes(staged)) + len(canonical_bytes(response)) + 4096
    if state_bytes > MAX_STATE_BYTES:
        raise ProjectError("E_RESOURCE", "새 사본과 접수 영수증이 journal 8 MiB 상한을 초과합니다.")
    service.journal._check_space(sum(len(raw) for raw in blobs.values()) + state_bytes + 4096)
    return bounded(preview), staged, blobs, bounded(response)


def _receipt(service, state, context, data):
    """! @brief 영수증 없음/만료를 미생성으로 단정하지 않으며 새 요청의 자동 중복 생성을 허용하지 않는다."""
    service._project(state, context)
    receipt = state["receipts"].get(canonical_hash([data["request_key_epoch"], data["request_key"]]))
    if receipt is not None:
        if receipt["method"] != "sweep.selection.apply" or receipt["scope"] != context:
            raise ProjectError("E_CONFLICT", "요청 영수증이 해당 프로젝트의 후보 채택 작업에 속하지 않습니다.")
        if receipt["expires_at"] > service._now():
            return {"status": "found", "authoritative": True, "response": deepcopy(receipt["response"]), "reason": "보존된 원자 접수 영수증을 확인했습니다."}
    status = "expired" if receipt is not None or data["request_key_epoch"] not in state["epochs"] or state["epochs"][data["request_key_epoch"]]["expires_at"] <= service._now() else "unresolved"
    return {"status": status, "authoritative": True, "response": None,
            "reason": "생성 여부를 확정할 보존 영수증이 없습니다. 원 작업 확인 전 새 요청 키로 다시 생성하지 마십시오."}


def read(service, method, params):
    """! @brief 검토/복구 조회는 원본과 파일을 쓰지 않는다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    context, data = params["context"], params["input"]
    validate_input(method, context, data)
    state = service.journal.read()
    if method == "sweep.selection.receipt":
        return _receipt(service, state, context, data)
    project = service._project(state, context)
    current = service._load(project)
    if method == "sweep.selection.context":
        response = {"project_id": context["project_id"], "revision_id": current["revision_id"], **data,
                    "definition_hash": None, "source_pin": None, "calculated_ordinal": None, "source": {"kind": "sweep", **data}, "label": "연구 후보",
                    "defaults": {"name": current["metadata"]["name"][:220] + " 후보 " + str(data["index"] + 1),
                                 "path": "projects/후보_" + str(data["index"] + 1), "reason": ""},
                    "eligibility": {"can_select": False, "issues": []}}
        for number in range(1, 1025):
            path = "projects/후보_" + str(data["index"] + 1) + "_사본_" + str(number)
            if not any(key.casefold() == path.casefold() for key in state["paths"]) and not (service.workspace / path).exists():
                response["defaults"]["path"] = path
                break
        try:
            values = _selection(service, state, context, data)
            _, _, study, _, original, _, _, resolved, _ = values
            response.update(definition_hash=study["definition"]["sha256"], source_pin=resolved["pin"], label=resolved["label"], calculated_ordinal=resolved["calculated_ordinal"])
            prepare_artifacts(service, project, original, response["defaults"]["path"])
            response["eligibility"]["can_select"] = True
        except ProjectError as error:
            response["eligibility"]["issues"] = [error.diagnostic()]
        return bounded(response)
    try:
        identity = str(uuid5(UUID(context["project_id"]), "selection-preview:" + canonical_hash(data)))
        return _prepare(service, state, context, data, identity)[0]
    except ProjectError as error:
        return {"project_id": context["project_id"], "revision_id": current["revision_id"], "study_id": data["study_id"],
                "index": data["index"], "can_apply": False, "review_hash": None, "issues": [error.diagnostic()]}


def admit(service, state, method, context, data):
    """! @brief 사본 파일과 단일 명령을 준비한 후 기존 영수증과 동일 commit에 등록한다."""
    preview, staged, blobs, response = _prepare(service, state, context, data, data["command_id"])
    if preview["review_hash"] != data["review_hash"]:
        raise ProjectError("E_CONFLICT", "검토한 후보/사본 입력이 변경됐습니다. 다시 검토하십시오.")
    for path, raw in blobs.items():
        service.journal.put_immutable(path, raw)
    for key in ("projects", "paths", "commands"):
        state[key] = staged[key]
    return response
