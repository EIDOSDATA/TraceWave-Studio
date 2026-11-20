"""! @brief 원문과 고정 실행 근거를 보존하는 측정 기록/정렬/비교 후보를 구성한다."""

from copy import deepcopy
import hashlib
import json
from uuid import UUID, uuid5

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application import measurement_contract as contract, measurement_forms as forms, measurement_records as records
from rfad.application.network_candidates import OPERATIONS as NETWORK_OPERATIONS, build_candidate as network_candidate
from rfad.application.network_records import reference, descriptor, samples
from rfad.application.project_contract import _fields
from rfad.application.result_sources import resolve
from rfad.domain import measurement
from rfad.domain.network_data import validate_dataset
from rfad.domain.network_library import KEY as NETWORK_KEY, library, validate_library
from rfad.domain.object_names import validate_name
from rfad.domain.resource_limits import MAX_DOCUMENT_BYTES


def _reason(value):
    """! @brief 검토/수정 의도는 공백이나 자동 생성 문구로 대체하지 않는다."""
    if type(value) is not str or not value.strip() or len(value) > 512 or any(ord(char) < 32 for char in value):
        contract.fail("512자 이하의 명시 변경 이유가 필요합니다.", field="reason")


def source_files(service, project):
    """! @brief 실행 source는 hash만 남기지 않고 같은 원문 바이트를 게시 후보에 포함한다."""
    source, raw = service.calculation_source(project)
    return source, {source["uri"]: raw}


def _context(recorded, dataset):
    """! @brief 기록 부재와 자료 분류를 물리 정확도 합격으로 해석하지 않는다."""
    record = None if recorded is None else recorded["record"]
    return {"record": None if recorded is None else recorded["record_ref"], "summary": records.summary(record, dataset),
        "assessment": {"status": "unknown", "measurement_validated": False, "diagnostics": []} if record is None else
                      measurement.condition_assessment(record, dataset)}


def comparison(service, state, project, context, data, *, conditions_only=False):
    """! @brief 고정된 두 결과를 계산하고 교정/시료 문맥 차이는 별도 반환한다."""
    left, left_record = records.selected_source(service, state, project, context, data["left"])
    right, right_record = records.selected_source(service, state, project, context, data["right"])
    conditions = records.metadata_conditions(left, right, None if left_record is None else left_record["record"],
                                             None if right_record is None else right_record["record"])
    base = {"profile": contract.PROFILE, "project_id": context["project_id"],
            "left": deepcopy(data["left"]), "right": deepcopy(data["right"])}
    if conditions_only:
        offset, limit = data["offset"], data["limit"]
        if offset > len(conditions):
            contract.fail("측정 조건의 시작 순번이 범위를 벗어났습니다.")
        items = conditions[offset:offset + limit]
        return {**base, "items": items, "offset": offset, "total": len(conditions),
                "next_offset": offset + len(items) if offset + len(items) < len(conditions) else None}
    parameters = {key: deepcopy(data[key]) for key in ("right_port_order", "row", "column", "frequency_policy", "offset", "limit")}
    value, execution = service.calculate("result.compare", {"left": left["dataset"], "right": right["dataset"], "parameters": parameters})
    for point in value["points"]:
        a, b = point["left_index"], point["right_index"]
        point["sample_origins"] = {"left": left["dataset"]["sample_origin"][a],
                                   "right": None if b is None else right["dataset"]["sample_origin"][b]}
        if point["difference_ri"] is not None and "interpolated" in point["sample_origins"].values():
            point["reason"] = "같은 정렬 주파수의 비교 - 기준 차이입니다. 보간 표본을 포함하며 새 실측값이 아닙니다."
    return {**base, **value, "condition_differences": conditions[:32], "condition_count": len(conditions),
        "condition_next_offset": 32 if len(conditions) > 32 else None,
        "historical_assessments": {"left": left["historical_assessments"], "right": right["historical_assessments"]},
        "measurement_context": {"left": _context(left_record, left["dataset"]), "right": _context(right_record, right["dataset"]),
            "physical_acceptance": "not_established", "uncertainty_propagation": "not_performed",
            "reason": "시료/교정/기준면과 불확도 기록을 비교합니다. 독립 실측 정확도 합격은 별도 검증입니다."},
        "engine": {"execution": execution}, "physics_validated": False}


def _record(service, state, project, document, request, identity, model, files):
    """! @brief 새 자료와 기존 자료의 anchor를 구별하여 미래 문서 hash의 순환을 피한다."""
    parameters, operation = request["parameters"], request["operation"]
    _reason(parameters["reason"])
    previous = None
    host_source, host_files = source_files(service, project)
    files.update(host_files)
    engine = {"host_identity_hash": canonical_hash(service.calculation_identity()), "host_source": host_source}
    input_copy = deepcopy(parameters)
    network = None
    if operation == "import_record":
        _fields(parameters["network"], NETWORK_OPERATIONS["import"])
        network, imported_files, output = network_candidate(service, state, project, document,
            {"operation": "import", "parameters": parameters["network"]})
        files.update(imported_files)
        entry = next(row for row in network["datasets"] if row["id"] == output["record_id"])
        dataset = json.loads(files[entry["dataset"]["uri"]])
        anchor = {"kind": "network_artifact", "project_id": document["project_id"], "dataset_id": entry["id"],
                  **{key: deepcopy(entry[key]) for key in ("dataset", "raw", "normalized_hdf5")}}
        encoded = input_copy["network"].pop("source_base64")
        input_copy["network"]["source_transport_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        input_copy["network"]["source_artifact"] = deepcopy(entry["raw"])
        engine, dataset_id = output["engine"], entry["id"]
    else:
        source = resolve(service, {"project_id": document["project_id"]}, parameters["source"], parameters["pin"])
        dataset = source["dataset"]
        dataset_id = source["source"].get("dataset_id")
        anchor = {"kind": "pinned_result", "source": deepcopy(parameters["source"]), "pin": deepcopy(parameters["pin"])}
        if parameters["previous_record"] is not None:
            previous = records.load_record(service, state, project, parameters["previous_record"])
            if previous["source"]["source"] != source["source"] or previous["source"]["pin"] != source["pin"]:
                contract.fail("기록 수정은 이전 기록의 같은 원본에 적용하십시오. 다른 자료에는 새 기록을 만드십시오.", "E_CONFLICT")
            if not any(row["id"] == previous["record"]["id"] for row in model["records"]):
                contract.fail("현재 개정에 이전 측정 기록이 없습니다.", "E_CONFLICT")
    if previous is None:
        record = measurement.record_template(identity=identity, name=parameters["name"], data_anchor=anchor,
            created_at_utc=request["draft_time_utc"], reason=parameters["reason"])
    else:
        record = deepcopy(previous["record"])
        record.update(id=identity, name=parameters["name"], data_anchor=anchor, created_at_utc=request["draft_time_utc"],
                      reason=parameters["reason"], previous_record_id=previous["record"]["id"])
    record = forms.apply_changes(record, parameters["changes"])
    diagnostics = measurement.validate_record(record, dataset, document["project_id"])
    records.validate_evidence(service, state, project, record)
    stored = {"schema": "rfad.measurement-document/0.1", "record": record,
              "input": {"operation": operation, "parameters": input_copy, "draft_time_utc": request["draft_time_utc"],
                        "host_engine": deepcopy(engine)}, "execution": None}
    payload = canonical_bytes(stored)
    if len(payload) > measurement.MAX_BYTES:
        contract.fail("측정 기록과 원문 입력 합계가 64 KiB를 초과했습니다.", "E_RESOURCE")
    path = project["path"] + "/measurement/" + identity + "/record.json"
    files[path] = payload
    entry = {"id": identity, "name": record["name"], "artifact": reference(path, payload), "previous_record_id": record["previous_record_id"]}
    model["records"].append(entry)
    return network, {"record": record, "record_artifact": deepcopy(entry["artifact"]), "dataset_id": dataset_id,
        "descriptor": descriptor(dataset), "page": samples(dataset), "summary": records.summary(record, dataset),
        "context_assessment": measurement.condition_assessment(record, dataset), "issues": diagnostics, "engine": engine,
        "changes": [{"field": "measurement", "label": "시료와 교정 기록", "before": None if previous is None else previous["record"]["name"],
                     "after": record["name"], "original_dataset_preserved": True}]}


def _align(service, state, project, document, request, identity, model, files):
    """! @brief 정렬은 별도 복소 자료와 고정 처리 이력으로 저장하고 원본은 변경하지 않는다."""
    parameters = request["parameters"]
    source, recorded = records.selected_source(service, state, project, {"project_id": document["project_id"]},
        {key: parameters[key] for key in ("source", "pin", "record")})
    specification = forms.alignment_input(parameters["specification"], source["dataset"])
    _reason(specification["reason"])
    result, execution = service.calculate("measurement.align", {"dataset": source["dataset"], "specification": specification})
    host_source, source_payload = source_files(service, project)
    files.update(source_payload)
    dataset = result["dataset"]
    history = dataset["provenance"].setdefault("measurement_alignment_records", [])
    if type(history) is not list or len(history) >= 32:
        contract.fail("측정 정렬 출처의 형식 또는 32개 이력 상한을 확인하십시오. 기존 출처는 덮어쓰지 않습니다.", "E_RESOURCE")
    history.append({"source": deepcopy(parameters["source"]), "pin": deepcopy(parameters["pin"]),
        "record": deepcopy(parameters["record"]), "host_source": host_source, "execution": execution,
        "original_input": deepcopy(parameters["specification"]), "uncertainty_propagation": "not_performed"})
    validate_dataset(dataset)
    from rfad.adapters.network_hdf5 import encode_network_hdf5
    folder = project["path"] + "/measurement/" + identity
    encoded = {"dataset.json": canonical_bytes(dataset), "normalized.h5": encode_network_hdf5(dataset),
               "diagnostics.json": canonical_bytes({"schema": "rfad.network-diagnostics/0.1", "samples": result["diagnostics"]})}
    refs = {}
    for name, raw in encoded.items():
        path = folder + "/" + name
        files[path] = raw
        refs[name] = reference(path, raw)
    network = library(document)
    parent_id = parameters["source"].get("dataset_id")
    inputs = [parent_id] if any(row["id"] == parent_id for row in network["datasets"]) else []
    network["datasets"].append({"id": identity, "name": parameters["name"], "created_revision": document["revision_id"], "kind": "derived",
        "dataset": refs["dataset.json"], "normalized_hdf5": refs["normalized.h5"], "raw": None, "inputs": inputs,
        "circuit_id": None, "diagnostics": refs["diagnostics.json"]})
    stored = {"schema": "rfad.measurement-alignment-record/0.1", "id": identity, "name": parameters["name"],
        "draft_time_utc": request["draft_time_utc"], "input": deepcopy(parameters), "normalized_specification": specification,
        "dataset_id": identity, "dataset": refs["dataset.json"], "lineage": result["lineage"], "execution": execution,
        "host_source": host_source, "original_record": None if recorded is None else recorded["entry"]["artifact"],
        "measurement_validated": False, "uncertainty_propagation": "not_performed"}
    path = folder + "/alignment.json"
    payload = canonical_bytes(stored)
    files[path] = payload
    model["alignments"].append({"id": identity, "name": parameters["name"], "artifact": reference(path, payload)})
    invalid_count = sum(row.get("status") != "valid" for row in result["diagnostics"])
    return network, {"dataset_id": identity, "record": None, "record_artifact": reference(path, payload),
        "descriptor": descriptor(dataset), "page": samples(dataset), "summary": {"name": parameters["name"], "data_class": "derived",
            "measurement_validated": False}, "context_assessment": _context(recorded, source["dataset"]),
        "issues": [] if not invalid_count else [{"code": "E_NUMERIC",
            "message": "정렬 중 무효 수치 진단이 " + str(invalid_count) + "개 발생했습니다. 무효 표본은 합격값이 아니며 전체 진단을 확인하십시오.",
            "details": {"invalid_diagnostic_count": invalid_count, "diagnostic_count": len(result["diagnostics"])}}],
        "diagnostics": result["diagnostics"][:8], "diagnostic_count": len(result["diagnostics"]),
        "diagnostics_artifact": refs["diagnostics.json"], "diagnostics_preview_limit": 8,
        "all_diagnostics_method": "network.diagnostics",
        "engine": {"execution": execution, "host_source": host_source},
        "changes": [{"field": "network", "label": "정렬 파생 자료", "before": source["label"], "after": parameters["name"]}]}


def _compare_record(service, state, project, document, request, identity, model, files):
    """! @brief 표본/조건 페이지 전체를 같은 고정 원본의 불변 보고서로 보존한다."""
    parameters = request["parameters"]
    _reason(parameters["reason"])
    _fields(parameters["comparison"], contract.COMPARISON_FIELDS)
    data = {**parameters["comparison"], "offset": 0, "limit": 201}
    contract.validate_input("measurement.compare", {"project_id": document["project_id"]}, data)
    first = comparison(service, state, project, {"project_id": document["project_id"]}, data)
    points = list(first["points"])
    executions = [first["engine"]["execution"]]
    offset = first["next_offset"]
    while offset is not None:
        page = comparison(service, state, project, {"project_id": document["project_id"]}, {**data, "offset": offset})
        points.extend(page["points"])
        executions.append(page["engine"]["execution"])
        offset = page["next_offset"]
    conditions, offset = [], 0
    while offset is not None:
        page = comparison(service, state, project, {"project_id": document["project_id"]},
                          {"left": data["left"], "right": data["right"], "offset": offset, "limit": 32}, conditions_only=True)
        conditions.extend(page["items"])
        offset = page["next_offset"]
    host_source, source_payload = source_files(service, project)
    files.update(source_payload)
    stored = {"schema": "rfad.measurement-comparison-record/0.1", "id": identity, "name": parameters["name"],
        "draft_time_utc": request["draft_time_utc"], "input": deepcopy(parameters), "source_revision": document["revision_id"],
        "comparison": {**deepcopy(first), "points": points, "offset": 0, "next_offset": None,
            "condition_differences": conditions, "condition_next_offset": None},
        "executions": executions, "host_source": host_source, "physics_validated": False}
    path = project["path"] + "/measurement/" + identity + "/comparison.json"
    payload = canonical_bytes(stored)
    files[path] = payload
    model["comparisons"].append({"id": identity, "name": parameters["name"], "artifact": reference(path, payload)})
    preview = {"total": len(points), "comparable_points": sum(row["difference_ri"] is not None for row in points),
               "points": points[:32]}
    return None, {"dataset_id": None, "record": None, "record_artifact": reference(path, payload),
        "descriptor": None, "page": None, "summary": {"name": parameters["name"], "physics_validated": False},
        "context_assessment": first["measurement_context"], "comparison_preview": preview,
        "issues": [], "engine": {"executions": executions, "host_source": host_source},
        "changes": [{"field": "measurement.comparison", "label": "고정 비교 보고서", "before": None, "after": parameters["name"]}]}


def build(service, state, project, document, request):
    """! @brief 원본 사본/파일 후보만 만들고 preview에서는 게시를 하지 않는다."""
    parameters, operation = request["parameters"], request["operation"]
    validate_name(parameters["name"])
    identity = str(uuid5(UUID(document["project_id"]), "measurement:" + canonical_hash({"base": canonical_hash(document),
        "operation": operation, "parameters": parameters, "draft_time_utc": request["draft_time_utc"]})))
    model, files = measurement.registry(document), {}
    if operation in ("record", "import_record"):
        network, output = _record(service, state, project, document, request, identity, model, files)
    elif operation == "align":
        network, output = _align(service, state, project, document, request, identity, model, files)
    else:
        network, output = _compare_record(service, state, project, document, request, identity, model, files)
    for collection in ("records", "alignments", "comparisons"):
        model[collection].sort(key=lambda row: row["id"])
    measurement.validate_registry(model)
    if network is not None:
        for collection in ("datasets", "circuits", "assessments"):
            network[collection].sort(key=lambda row: row["id"])
        validate_library(network)
    candidate = deepcopy(document)
    candidate["extensions"][measurement.KEY] = model
    if network is not None:
        candidate["extensions"][NETWORK_KEY] = network
    from rfad.domain.project import validate_project
    validate_project(candidate)
    if len(canonical_bytes(candidate)) > MAX_DOCUMENT_BYTES:
        contract.fail("측정 기록을 포함한 프로젝트가 512 KiB를 초과했습니다.", "E_RESOURCE")
    replacement = {"registry": {"expected_hash": canonical_hash(document["extensions"].get(measurement.KEY)), "replacement": model},
        "network": None if network is None else {"expected_hash": canonical_hash(document["extensions"].get(NETWORK_KEY)), "replacement": network}}
    output.update(record_id=identity, source_preserved=True, artifact_count=len(files), operation=operation)
    fingerprint = canonical_hash({"profile": contract.PROFILE, "base": canonical_hash(document), "replacement": replacement,
        "input": {key: request[key] for key in contract.REVIEW_FIELDS}, "engine": output["engine"],
        "files": {path: hashlib.sha256(raw).hexdigest() for path, raw in files.items()}})
    return output, replacement, files, fingerprint
