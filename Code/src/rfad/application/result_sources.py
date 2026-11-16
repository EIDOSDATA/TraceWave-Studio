"""! @brief 과거 개정과 실제 계산 원본의 봉인 참조를 공통 읽기 source로 해석한다."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import _fields, _uuid
from rfad.application.network_records import descriptor, read_dataset
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import validate_dataset
from rfad.domain.network_library import digest, library


def fail(message, code="E_SCHEMA"):
    """! @brief 원본과 수학 표시의 오류를 기존 제품 진단으로 반환한다."""
    raise ProjectError(code, message)


def validate_source(source):
    """! @brief 현재 자료 alias나 임의 경로를 받지 않는 닫힌 source 선택 계약이다."""
    if type(source) is not dict:
        fail("결과 자료 선택은 명시적 객체여야 합니다.")
    kind = source.get("kind")
    if kind == "network":
        _fields(source, {"kind", "dataset_id", "revision_id", "snapshot_id"})
        _uuid(source["dataset_id"])
        _uuid(source["revision_id"])
        if source["snapshot_id"] is not None:
            _uuid(source["snapshot_id"])
    elif kind == "solver":
        _fields(source, {"kind", "artifact_id"})
        _uuid(source["artifact_id"])
    elif kind == "sweep":
        _fields(source, {"kind", "study_id", "index"})
        _uuid(source["study_id"])
        if type(source["index"]) is not int or not 0 <= source["index"] < 128:
            fail("연구 후보 순번은 0~127 정수여야 합니다.")
    else:
        fail("지원하지 않는 결과 자료 종류입니다.", "E_UNSUPPORTED")


def validate_pin(pin):
    """! @brief 최초 describe 이후에는 null로 최신 자료를 묵시 채택할 수 없다."""
    _fields(pin, {"identity_hash", "dataset_sha256"})
    for key in pin:
        digest(pin[key], "pin." + key)


def solver_labels(state, project_id):
    """! @brief 실제 완료/입력 봉인 시각만 사용해 같은 설명의 보존 해석을 구분한다."""
    records = {identity: record for identity, record in state["solver_results"].items() if record["project_id"] == project_id}
    times = {}
    for job in state["jobs"].values():
        if job.get("context", {}).get("project_id") != project_id:
            continue
        for event in job.get("events", []):
            operation = event.get("operation_result", {})
            identity = operation.get("artifact_id")
            record = records.get(identity)
            stamp = event.get("timestamp")
            if (record is not None and event.get("state") == "completed" and operation.get("normalized_result") == record["normalized"]
                    and operation.get("snapshot") == record["snapshot"] and type(stamp) in (int, float) and math.isfinite(stamp)):
                times[identity] = (stamp, "calculation_completed")
    for identity, record in records.items():
        if identity not in times:
            stamp = record["snapshot"].get("sealed_at")
            times[identity] = (stamp, "snapshot_sealed") if type(stamp) in (int, float) and math.isfinite(stamp) else (None, None)
    ordered = sorted(records, key=lambda identity: (times[identity][0] is None, times[identity][0] or 0, identity))
    result = {}
    for ordinal, identity in enumerate(ordered, 1):
        stamp, kind = times[identity]
        time_label = "시각 미정"
        if stamp is not None:
            try:
                value = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=stamp)
                time_label = ("완료 " if kind == "calculation_completed" else "입력 봉인 ") + value.isoformat(timespec="seconds").replace("+00:00", " UTC")
            except (OverflowError, ValueError):
                time_label = "기록 시각 표시 범위 초과"
        description = records[identity]["snapshot"].get("description") or "설명 미지정"
        metadata = records[identity].get("metadata", {})
        label = "해석 결과 " + str(ordinal)
        if metadata.get("profile") == "rfad.openems.reference-benchmark/0.1":
            grid = metadata.get("reference_grid_mm")
            level = (3.0, 2.5, 2.0).index(grid) + 1 if type(grid) in (float, int) and grid in (3.0, 2.5, 2.0) else None
            label = "PEC 다이폴 / " + ("격자 수준 " + str(level) + " / " if level is not None else "") + "합성 검증 사례"
        result[identity] = {"label": label + " / " + time_label + " / " + description,
            "source_time": stamp, "source_time_kind": kind}
    return result


def owned_reference(project, reference):
    """! @brief 해시를 읽기 전에 현재 프로젝트의 정규 저장 경계를 확인한다."""
    if type(reference) is not dict or not str(reference.get("uri", "")).startswith(project["path"] + "/"):
        fail("결과 파일이 현재 프로젝트 저장 영역에 속하지 않습니다.", "E_HASH")
    return reference


def read_json(service, project, reference, *, canonical=True):
    """! @brief 봉인 파일을 읽되 native 원문 JSON의 공백은 소급 정규화하지 않는다."""
    raw = service.journal.read_artifact(owned_reference(project, reference))
    try:
        value = json.loads(raw)
        if canonical and canonical_bytes(value) != raw:
            fail("결과 자료의 정규 바이트가 다릅니다.", "E_HASH")
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProjectError("E_HASH", "결과 자료 JSON을 읽을 수 없습니다.") from error


def validate_solver_artifact(project, record, reference):
    """! @brief resolve에서 소유를 검증한 record의 등록 경계를 확인하며 큰 파일은 읽지 않는다."""
    allowed = [record["normalized"]]
    allowed.extend(item["artifact"] for item in record.get("files", []))
    allowed.extend(item["artifact"] for item in record.get("raw_files", []))
    if reference not in allowed:
        fail("선택한 해석 record에 등록되지 않은 산출물입니다.", "E_HASH")
    path = reference["uri"]
    if not path.startswith(project["path"] + "/"):
        parts = path.split("/")
        if len(parts) < 3 or parts[0] != "solver-artifacts":
            fail("해석 산출물이 지원하는 봉인 저장 영역 밖에 있습니다.", "E_HASH")
        _uuid(parts[1])
    return reference


def read_solver_artifact(service, project, record, reference):
    """! @brief 소유 record에 실제 등록된 과거 전역 solver 산출물 경로도 원문 그대로 읽는다."""
    validate_solver_artifact(project, record, reference)
    return service.journal.read_artifact(reference)


def snapshot_document(service, project, project_id, snapshot):
    """! @brief 스냅샷의 파일/내용/소유자/개정을 모두 대조한다."""
    if type(snapshot) is not dict or snapshot.get("project_id") != project_id:
        fail("결과 스냅샷의 소유 프로젝트가 다릅니다.", "E_HASH")
    _, document = service.repository.read(owned_reference(project, snapshot.get("artifact")))
    if (document["project_id"] != project_id or document["revision_id"] != snapshot.get("revision_id")
            or canonical_hash(document) != snapshot.get("content_hash")):
        fail("결과 스냅샷과 실제 원본의 개정/내용이 다릅니다.", "E_HASH")
    return document


def revision_document(service, state, project, project_id, revision_id, snapshot_id=None):
    """! @brief 명시 과거 개정이 없을 때 현재 library로 대체하지 않는다."""
    _uuid(revision_id)
    if snapshot_id is not None:
        _uuid(snapshot_id)
        snapshot = state["snapshots"].get(snapshot_id)
        if snapshot is None:
            fail("보존된 결과 스냅샷을 찾을 수 없습니다.", "E_MISSING_ARTIFACT")
        if snapshot["project_id"] != project_id or snapshot["revision_id"] != revision_id:
            fail("선택한 스냅샷의 소유 프로젝트 또는 개정이 다릅니다.", "E_CONFLICT")
        return snapshot_document(service, project, project_id, snapshot), deepcopy(snapshot)
    reference = project["revisions"].get(revision_id)
    if reference is None:
        fail("보존된 결과 개정을 찾을 수 없습니다. 현재 개정으로 대체하지 않습니다.", "E_MISSING_ARTIFACT")
    _, document = service.repository.read(owned_reference(project, reference))
    if document["project_id"] != project_id or document["revision_id"] != revision_id:
        fail("선택한 개정과 실제 원본의 소유자 또는 개정이 다릅니다.", "E_HASH")
    return document, None


def _solver(service, state, project, project_id, identity):
    """! @brief 실제 normalized와 snapshot 및 복소 투영을 한 번에 검증한다."""
    from rfad.application.network_solver_import import solver_dataset

    record = state["solver_results"].get(identity)
    if record is None:
        fail("봉인된 해석 결과를 찾을 수 없습니다.", "E_MISSING_ARTIFACT")
    if record["project_id"] != project_id:
        fail("다른 프로젝트의 해석 결과를 조회할 수 없습니다.", "E_CONFLICT")
    try:
        original = json.loads(read_solver_artifact(service, project, record, record["normalized"]))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProjectError("E_HASH", "해석 원문 JSON을 읽을 수 없습니다.") from error
    plan = original.get("provenance", {}).get("analysis_plan")
    if type(plan) is not dict:
        fail("해석 결과에 원본 분석 계획이 없습니다.", "E_UNSUPPORTED")
    snapshot = plan.get("snapshot")
    prepared = original.get("provenance", {}).get("prepared_plan", {})
    if (record.get("snapshot") != snapshot or record.get("analysis_plan_id") != plan.get("plan_id")
            or record.get("prepared_plan_id") != prepared.get("prepared_plan_id")):
        fail("해석 색인의 snapshot/계획 식별자가 실제 원문과 다릅니다.", "E_HASH")
    document = snapshot_document(service, project, project_id, snapshot)
    if plan.get("source_semantics") != document:
        fail("해석 계획의 원본 사본이 봉인 스냅샷과 다릅니다.", "E_HASH")
    dataset, _ = solver_dataset(service, state, document, identity)
    return {"source_document": document, "source_document_role": "calculation_snapshot", "source_snapshot": deepcopy(snapshot), "dataset": dataset,
            "solver_result_id": identity, "solver_record": deepcopy(record), "normalized": original}


def _linked_solver(service, state, project, project_id, dataset, raw=None):
    """! @brief solver 출처를 주장하는 자료도 실제 원문과 투영 값이 같을 때만 연결한다."""
    provenance = dataset["provenance"]
    reference = provenance.get("normalized_source")
    if provenance.get("adapter") not in ("rfad.network-pcb-projection/0.1", "rfad.network-reference-projection/0.1") or type(reference) is not dict:
        fail("해석 자료의 원본 투영 근거가 없습니다.", "E_HASH")
    matches = [key for key, value in state["solver_results"].items()
               if value["project_id"] == project_id and value["normalized"] == reference]
    if len(matches) != 1:
        fail("같은 프로젝트에서 정확한 해석 원문을 찾을 수 없습니다.", "E_MISSING_ARTIFACT")
    if raw is not None:
        original = service.journal.read_artifact(owned_reference(project, raw))
        expected = read_solver_artifact(service, project, state["solver_results"][matches[0]], reference)
        if original != expected:
            fail("가져온 해석 원문과 실제 계산 원본이 다릅니다.", "E_HASH")
    linked = _solver(service, state, project, project_id, matches[0])
    if canonical_bytes(linked["dataset"]) != canonical_bytes(dataset):
        fail("보존된 복소 자료가 원래 해석 결과의 정확한 투영과 다릅니다.", "E_HASH")
    return linked


def _sweep(service, state, project, project_id, source):
    """! @brief 현재 후보 생성기를 실행하지 않고 보존 원본과 실제 계산 파일만 읽는다."""
    from rfad.application.design_sweep_store import baseline, load_candidate

    study = state.get("sweeps", {}).get(source["study_id"])
    if study is None:
        fail("보존된 연구를 찾을 수 없습니다.", "E_MISSING_ARTIFACT")
    if study["project_id"] != project_id:
        fail("다른 프로젝트의 연구를 조회할 수 없습니다.", "E_CONFLICT")
    definition, baseline_document = baseline(service, study)
    snapshot_document(service, project, project_id, definition["snapshot"])
    candidate = load_candidate(service, study, source["index"])
    if candidate is None or "dataset" not in candidate.get("results", {}):
        fail("이 후보에 보존된 복소 결과가 없습니다.", "E_MISSING_ARTIFACT")
    reference = candidate["results"]["dataset"]
    root = project["path"] + "/sweeps/" + study["study_id"] + "/results/"
    if not reference["uri"].startswith(root):
        fail("후보 결과가 해당 연구의 저장 영역에 속하지 않습니다.", "E_HASH")
    dataset = read_json(service, project, reference)
    validate_dataset(dataset)
    result = {"study": deepcopy(study), "candidate": deepcopy(candidate), "dataset": dataset,
              "source_document": baseline_document, "source_snapshot": deepcopy(definition["snapshot"]),
              "source_document_role": "study_baseline", "anchor_document": baseline_document,
              "dataset_artifact": deepcopy(reference), "calculated_ordinal": source["index"],
              "selection_values": deepcopy(candidate["values"]),
              "label": study["name"] + " / 후보 " + str(source["index"] + 1),
              "source_record": {"definition": study["definition"], "candidate": study["records"][str(source["index"])]}}
    assessment = candidate.get("results", {}).get("assessment")
    if assessment is not None:
        from rfad.application.network_records import assessment_summary

        if not assessment["uri"].startswith(root):
            fail("후보 평가가 해당 연구의 저장 영역 밖에 있습니다.", "E_HASH")
        saved = read_json(service, project, assessment)
        if saved.get("schema") != "rfad.sweep-assessments/0.1":
            fail("후보 평가 원문의 버전을 지원하지 않습니다.", "E_VERSION")
        result["historical_assessments"] = [assessment_summary(item) for item in saved["assessments"]]
    actual, seen = candidate, {source["index"]}
    while "cached_from_ordinal" in actual:
        index = actual["cached_from_ordinal"]
        if type(index) is not int or index in seen or len(seen) >= 128:
            fail("연구 결과 재사용 참조가 순환하거나 유효하지 않습니다.", "E_HASH")
        seen.add(index)
        actual = load_candidate(service, study, index)
        if actual is None or actual["evaluation_key"] != candidate["evaluation_key"]:
            fail("재사용한 연구 결과의 물리 입력 식별자가 다릅니다.", "E_HASH")
        if not actual.get("results", {}).get("dataset", {}).get("uri", "").startswith(root):
            fail("재사용한 후보 결과가 현재 연구의 저장 영역 밖에 있습니다.", "E_HASH")
        cached = read_json(service, project, actual["results"]["dataset"])
        if canonical_bytes(cached) != canonical_bytes(dataset):
            fail("재사용한 연구 결과의 복소 원문이 다릅니다.", "E_HASH")
        result["calculated_ordinal"] = index
    if study["type"] != "circuit_sweep":
        linked = _linked_solver(service, state, project, project_id, dataset)
        if actual.get("solver_result_id") != linked["solver_result_id"] or actual.get("solver_normalized") != linked["solver_record"]["normalized"]:
            fail("연구 후보의 실제 계산 결과 참조가 다릅니다.", "E_HASH")
        result.update(linked)
    return result


def resolve(service, context, source, pin=None):
    """! @brief 공통 자료를 읽고 source/pin을 검증하며 native 실행이나 새 파일 게시를 하지 않는다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    validate_source(source)
    state = service.journal.read()
    project = service._project(state, context)
    project_id = context["project_id"]
    current = service._load(project)
    result = {"source": deepcopy(source), "project": deepcopy(project), "current_document": current,
              "anchor_document": None, "source_document_role": "library_anchor",
              "source_snapshot": None, "entry": None, "solver_result_id": None, "solver_record": None,
              "normalized": None, "study": None, "candidate": None, "calculated_ordinal": None,
              "selection_values": [], "source_record": {}, "historical_assessments": []}
    if source["kind"] == "network":
        document, snapshot = revision_document(service, state, project, project_id, source["revision_id"], source["snapshot_id"])
        dataset, entry = read_dataset(service, project, library(document), source["dataset_id"])
        result.update(source_document=document, anchor_document=document, source_snapshot=snapshot, dataset=dataset, entry=entry,
                      label=entry["name"], dataset_artifact=entry["dataset"], source_record={"entry": entry, "revision_hash": canonical_hash(document)},
                      historical_assessments=[deepcopy(item) for item in library(document)["assessments"] if item["dataset_id"] == entry["id"]])
        if entry["kind"] == "solver":
            linked = _linked_solver(service, state, project, project_id, dataset, entry["raw"])
            result.update(linked)
    elif source["kind"] == "solver":
        result.update(_solver(service, state, project, project_id, source["artifact_id"]))
        result.update(**solver_labels(state, project_id)[source["artifact_id"]],
                      dataset_artifact={"sha256": canonical_hash(result["dataset"]), "bytes": len(canonical_bytes(result["dataset"])), "uri": None},
                      source_record=deepcopy(result["solver_record"]))
    else:
        result.update(_sweep(service, state, project, project_id, source))
    document = result["source_document"]
    metadata = document["metadata"]
    result["source_revision"] = {"id": document["revision_id"], "hash": canonical_hash(document),
        "name": metadata["name"], "label": metadata["name"] + " / " + metadata["modified_at"], "modified_at": metadata["modified_at"]}
    result["descriptor"] = descriptor(result["dataset"])
    result["pin"] = {"identity_hash": canonical_hash({"source": source, "project_id": project_id,
        "source_revision": result["source_revision"], "source_record": result["source_record"], "dataset_artifact": result["dataset_artifact"]}),
        "dataset_sha256": canonical_hash(result["dataset"])}
    if pin is not None:
        validate_pin(pin)
        if pin != result["pin"]:
            fail("선택한 결과 원본의 고정 식별자가 바뀌었습니다.", "E_HASH")
    candidate, normalized = result["candidate"], result["normalized"]
    result["numerical_details"] = {"formal_convergence": "not_established",
        "solver_assessment": None if normalized is None else deepcopy(normalized.get("assessment")),
        "termination": None if normalized is None else deepcopy(normalized.get("termination")),
        "candidate_state": None if candidate is None else candidate["state"],
        "candidate_outcome": None if candidate is None else candidate.get("outcome"),
        "status": normalized.get("termination", {}).get("status", "not_recorded") if normalized is not None else "not_assessed",
        "reason": "보존된 계산의 종료 기준 상태입니다. 격자/영역 독립 수렴 검증과 물리 정확도 검증은 별도입니다." if normalized is not None else
                  "이 원본에 연결된 전자기 해석 종료 기록이 없습니다. 회로 계산이나 가져온 값을 수렴 검증으로 바꾸지 않습니다."}
    result["states"] = {"computation": candidate["state"] if candidate is not None else "completed" if normalized is not None else result["entry"]["kind"],
        "numerical": "not_established", "physics": "not_established", "manufacturing": "unknown", "measurement": "unknown"}
    return result
