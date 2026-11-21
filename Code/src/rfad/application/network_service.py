"""! @brief 공통 복소 자료의 검토/원자 적용/페이지 조회/교환을 서비스 경계로 제공한다."""

import base64
from copy import deepcopy
import hashlib

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.network_candidates import MAX_IMPORT_BYTES, OPERATIONS, build_candidate
from rfad.application.network_records import assessment_summary, bounded, descriptor, find_record, read_dataset, read_json, samples
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.network_library import COMMAND, KEY, MAX_RECORDS, digest, fail, library
from rfad.domain.resource_limits import MAX_DOCUMENT_BYTES

PROFILE = "rfad.network-workspace/0.1"
READS = {"network.library", "network.get", "network.preview", "network.assessment", "network.assessment.points", "network.export", "network.diagnostics", "network.quantity"}
READS.add("network.compare")
MUTATION = "network.apply"
FIELDS = {
    "network.library": set(),
    "network.get": {"dataset_id", "offset", "limit", "row", "column"},
    "network.preview": {"operation", "parameters"},
    "network.assessment": {"assessment_id"},
    "network.assessment.points": {"assessment_id", "criterion", "offset", "limit"},
    "network.export": {"dataset_id", "format"},
    "network.diagnostics": {"dataset_id", "offset", "limit"},
    "network.quantity": {"quantity", "display_unit"},
    "network.compare": {"left_id", "right_id", "right_port_order", "offset", "limit", "row", "column"},
    MUTATION: {"operation", "parameters", "command_id", "review_hash"},
}


def validate_input(context, data, method=MUTATION):
    """! @brief 모든 조회와 쓰기는 현재 프로젝트 개정과 닫힌 입력 계약을 요구한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    _fields(data, {"expected_revision", *FIELDS[method]})
    _uuid(data["expected_revision"])
    for key in ("dataset_id", "assessment_id", "command_id", "left_id", "right_id"):
        if key in data:
            _uuid(data[key])
    if "operation" in data:
        operation = data["operation"]
        if type(operation) is not str or operation not in OPERATIONS:
            fail("지원하지 않는 네트워크 작업입니다.", "operation", "E_UNSUPPORTED")
        _fields(data["parameters"], OPERATIONS[operation])
    if "review_hash" in data:
        digest(data["review_hash"], "review_hash")


def current(service, state, context, data):
    """! @brief 동일한 journal snapshot의 권위 프로젝트와 개정을 확인한다."""
    project = service._project(state, context)
    document = service._load(project)
    service._check_history_head(project, document["revision_id"])
    if document["revision_id"] != data["expected_revision"]:
        fail("현재 설계 개정이 바뀌었습니다. 자료를 다시 조회하십시오.", "expected_revision", "E_CONFLICT")
    return project, document


def preview(service, state, project, document, data):
    """! @brief 실패 후보는 원본/이력을 바꾸지 않고 적용 불가 이유를 반환한다."""
    base = {"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"]}
    try:
        model, files, output = build_candidate(service, state, project, document, data)
        candidate = deepcopy(document)
        candidate["extensions"][KEY] = model
        from rfad.domain.project import validate_project
        validate_project(candidate)
        if len(canonical_bytes(candidate)) > MAX_DOCUMENT_BYTES:
            fail("자료 참조를 포함한 프로젝트가 512 KiB를 초과했습니다.", "project", "E_RESOURCE")
        fingerprint = canonical_hash({"profile": PROFILE, "base": canonical_hash(document),
                                      "operation": data["operation"], "parameters": data["parameters"],
                                      "replacement": model, "engine": output["engine"]})
        response = bounded({**base, **output, "can_apply": True, "review_hash": fingerprint,
                            "issues": [], "artifact_count": len(files), "source_preserved": True})
        return response, model, files
    except ProjectError as error:
        return {**base, "can_apply": False, "review_hash": None, "descriptor": None, "page": None,
                "assessment": None, "issues": [{"code": error.code, "message": error.message, "details": error.details}]}, None, {}


def overview(document):
    """! @brief 결과 목록과 입력 대상을 표시하며 아직 없는 결과를 만들지 않는다."""
    model = library(document)
    from rfad.application.network_forms import circuit_display
    for row in model["circuits"]:
        row["display"] = circuit_display(row["definition"])
    targets = [{"id": row["id"], "name": row["name"], "revision_id": row["revision_id"],
                "port_id": row["port_id"], "reference_impedance": deepcopy(row["reference_impedance"]),
                "reference_plane": row.get("reference_plane")} for row in document["targets"]]
    return bounded({"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
                    **model, "targets": targets,
                    "ports": [{"id": row["id"], "name": row["name"], "reference_plane": row["reference_plane"]} for row in document["ports"]],
                    "limits": {"records_per_kind": MAX_RECORDS, "source_bytes": MAX_IMPORT_BYTES,
                               "ports": 2, "samples": 1001, "page_size": 201},
                    "physical_validation": "not_established"})


def exported(service, project, document, data):
    """! @brief 원본 참조를 보존한 교환 파일과 조건 sidecar를 생성한다."""
    from rfad.application.result_export import encode_files
    network, entry = read_dataset(service, project, library(document), data["dataset_id"])
    raw, file_name, mapping = encode_files(service, project, network, entry, data["format"])
    sidecar = {"schema": "rfad.network-export/0.1", "dataset": deepcopy(entry), "descriptor": descriptor(network),
               "provenance": deepcopy(network["provenance"]), "mapping": mapping,
               "physical_validation": "not_established", "source_unmodified": True}
    response = {"profile": PROFILE, "file_name": file_name, "content_base64": base64.b64encode(raw).decode("ascii"),
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "sidecar": sidecar}
    if len(canonical_bytes(response)) > 900 * 1024:
        fail("내보내기와 출처 응답이 전송 상한을 초과했습니다.", "response", "E_RESOURCE")
    return response


def read(service, method, params):
    """! @brief 조회/검토/교환은 명령 영수증이나 프로젝트 저장을 발생시키지 않는다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 API 버전입니다.", "contract_version", "E_VERSION")
    data, context = params["input"], params["context"]
    validate_input(context, data, method)
    state = service.journal.read()
    project, document = current(service, state, context, data)
    if method == "network.compare":
        from rfad.application.network_compare import compare
        return compare(service, project, document, data)
    if method == "network.quantity":
        from rfad.domain.units import Quantity, QuantityError
        from rfad.application.network_forms import input_quantity
        try:
            original = data["quantity"]
            if type(original) is dict and set(original) == {"text", "unit", "source_refs"}:
                dimension = Quantity.from_value(1.0, original["unit"]).dimension.value
                original = input_quantity(original, dimension, "quantity")
            _fields(original, {"value_si", "dimension", "display_unit", "status", "source_refs"})
            Quantity(**original)
            updated = deepcopy(original)
            updated["display_unit"] = data["display_unit"]
            quantity = Quantity(**updated)
            text = "" if quantity.value_si is None else format(quantity.as_unit(quantity.display_unit), ".15g")
        except (TypeError, ValueError, QuantityError) as error:
            fail("표시 단위를 바꿀 수 없습니다: " + str(error), "display_unit", "E_UNIT")
        return bounded({"profile": PROFILE, "quantity": updated, "text": text, "unit": quantity.display_unit})
    if method == "network.library":
        result = overview(document)
        result["solver_results"] = [{"artifact_id": row["artifact_id"], "snapshot": deepcopy(row["snapshot"]),
                                     "profile": row["metadata"]["profile"], "sample_count": row["metadata"]["sample_count"],
                                     "physics_validation_state": row["metadata"]["physics_validation_state"]}
                                    for row in state["solver_results"].values() if row["project_id"] == document["project_id"]]
        return bounded(result)
    if method == "network.preview":
        return preview(service, state, project, document, data)[0]
    if method == "network.export":
        return exported(service, project, document, data)
    model = library(document)
    if method in ("network.assessment", "network.assessment.points"):
        entry = find_record(model, "assessments", data["assessment_id"])
        assessment = read_json(service, project, entry["artifact"])
        target = next((row for row in document["targets"] if row["id"] == entry["target_id"]), None)
        if method == "network.assessment.points":
            criteria = assessment["criteria"]
            index, offset, limit = data["criterion"], data["offset"], data["limit"]
            if type(index) is not int or not 0 <= index < len(criteria):
                fail("평가 기준의 위치가 범위를 벗어났습니다.", "criterion")
            points = criteria[index].get("points", [])
            if type(offset) is not int or not 0 <= offset <= len(points) or type(limit) is not int or not 1 <= limit <= 201:
                fail("평가 표본 조회는 유효한 시작 위치와 1~201개 크기가 필요합니다.", "offset")
            return bounded({"profile": PROFILE, "points": points[offset:offset + limit], "offset": offset,
                            "total": len(points), "next_offset": offset + limit if offset + limit < len(points) else None})
        return bounded({"profile": PROFILE, "entry": entry, "assessment": assessment_summary(assessment),
                        "current_target_revision": target["revision_id"] if target else None,
                        "target_changed": target is None or target["revision_id"] != entry["target_revision_id"]})
    network, entry = read_dataset(service, project, model, data["dataset_id"])
    if method == "network.diagnostics":
        diagnostics = [] if entry["diagnostics"] is None else read_json(service, project, entry["diagnostics"])["samples"]
        offset, limit = data["offset"], data["limit"]
        if type(offset) is not int or not 0 <= offset <= len(diagnostics) or type(limit) is not int or not 1 <= limit <= 32:
            fail("계산 진단 조회는 유효한 시작 위치와 1~32개 크기가 필요합니다.", "offset")
        return bounded({"profile": PROFILE, "diagnostics": diagnostics[offset:offset + limit], "offset": offset,
                        "total": len(diagnostics), "next_offset": offset + limit if offset + limit < len(diagnostics) else None,
                        "artifact": entry["diagnostics"]})
    return bounded({"profile": PROFILE, "entry": entry, "descriptor": descriptor(network),
                    "page": samples(network, data["offset"], data["limit"], data["row"], data["column"])})


def admit(service, state, context, data):
    """! @brief 검토 재계산과 파일 봉인/명령/영수증을 동일 writer에서 게시한다."""
    validate_input(context, data)
    project, document = current(service, state, context, data)
    reviewed, model, files = preview(service, state, project, document, data)
    if not reviewed["can_apply"]:
        fail("자료 후보의 차단 원인을 해결한 뒤 다시 검토하십시오.", "parameters", "E_CONFLICT")
    if reviewed["review_hash"] != data["review_hash"]:
        fail("원본/입력/엔진 또는 검토한 결과가 바뀌었습니다.", "review_hash", "E_CONFLICT")
    service.verify_calculation()
    for path, payload in files.items():
        service.journal.put_immutable(path, payload)
    result = service._apply(state, context, {"expected_revision": data["expected_revision"], "command_id": data["command_id"],
        "type": COMMAND, "payload": {"expected_hash": canonical_hash(document["extensions"].get(KEY)), "replacement": model}})
    state["commands"][data["command_id"]]["host_calculation"] = deepcopy(reviewed["engine"])
    return {**result, "record_id": reviewed["record_id"], "operation": data["operation"], "review_hash": reviewed["review_hash"]}
