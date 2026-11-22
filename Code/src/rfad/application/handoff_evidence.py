"""! @brief 고정 스냅샷의 원본과 등록된 검토 근거를 읽기 전용 인계 목록으로 제공한다."""

from copy import deepcopy
import json
import math

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.measurement_records import creation_reference
from rfad.application.project_contract import _fields, _uuid
from rfad.application.result_sources import read_solver_artifact, snapshot_document
from rfad.domain.errors import ProjectError
from rfad.domain.measurement import registry as measurement_registry
from rfad.domain.network_library import digest, library


PROFILE = "rfad.handoff-evidence/0.1"
METHOD = "evidence.query"
MAX_PAGE = 32
MAX_SELECTION = 64
MAX_BYTES = 256 * 1024
KINDS = {"snapshot", "material", "target", "network", "assessment", "measurement", "alignment", "comparison",
         "solver_result", "verification_report", "output"}


def fail(message, code="E_SCHEMA"):
    """! @brief 미확립 상태를 채우거나 누락된 항목을 자동 대체하지 않는다."""
    raise ProjectError(code, message)


def source(service, state, context, reference):
    """! @brief 읽을 원본 스냅샷의 소유권과 정확한 정규 자료를 확인한다."""
    _fields(context, {"project_id"})
    project_id = _uuid(context["project_id"])
    _fields(reference, {"snapshot_id", "content_hash"})
    _uuid(reference["snapshot_id"])
    digest(reference["content_hash"], "snapshot.content_hash")
    project = service._project(state, context)
    snapshot = state["snapshots"].get(reference["snapshot_id"])
    if snapshot is None or snapshot.get("project_id") != project_id:
        fail("선택한 프로젝트의 보존 스냅샷이 없습니다.", "E_CONFLICT")
    if snapshot["content_hash"] != reference["content_hash"]:
        fail("선택한 스냅샷의 고정 원본 해시가 다릅니다.", "E_HASH")
    return project, snapshot, snapshot_document(service, project, project_id, snapshot)


def _row(kind, identity, name, revision, status, artifact=None, detail=None):
    """! @brief 불변 파일 등록과 내용 검증을 목록에서 서로 다른 상태로 표현한다."""
    return {"kind": kind, "id": identity, "name": name, "listed_in_revision": revision, "status": status,
            "artifact": deepcopy(artifact), "artifact_state": "registered" if artifact is not None else "none",
            "detail": deepcopy(detail) if detail is not None else {}}


def index(state, snapshot, document):
    """! @brief 명시 선택 개정에서 보이는 자료와 같은 스냅샷에서 실행한 결과만 나열한다."""
    project_id = document["project_id"]
    revision = document["revision_id"]
    snapshot_id = snapshot["snapshot_id"]
    rows = [_row("snapshot", snapshot_id, document["metadata"]["name"], revision, "sealed", snapshot["artifact"],
                 {"content_hash": snapshot["content_hash"], "schema_version": document["schema_version"]})]
    rows[0]["artifact_state"] = "verified"
    for family in ("materials", "targets"):
        for item in document[family]:
            kind = "material" if family == "materials" else "target"
            status = "recorded" if kind == "material" else "not_evaluated_here"
            detail = {"source_refs": item.get("source_refs", [])}
            if kind == "material":
                detail.update(model=item["model"], validity_hz=item["validity_hz"], assumptions=item["assumptions"])
            rows.append(_row(kind, item["id"], item.get("name") or item.get("label") or "이름 미정", revision, status, detail=detail))
    model = library(document)
    for dataset in model["datasets"]:
        rows.append(_row("network", dataset["id"], dataset["name"], revision, dataset["kind"], dataset["dataset"],
                         {"original": dataset["raw"], "normalized_hdf5": dataset["normalized_hdf5"],
                          "library_created_revision": dataset["created_revision"]}))
    for record in model["assessments"]:
        rows.append(_row("assessment", record["id"], record["name"], revision, record["status"], record["artifact"],
                         {"dataset_id": record["dataset_id"], "target_revision_id": record["target_revision_id"]}))
    measured = measurement_registry(document)
    for collection, kind in (("records", "measurement"), ("alignments", "alignment"), ("comparisons", "comparison")):
        for record in measured[collection]:
            rows.append(_row(kind, record["id"], record["name"], revision, "recorded", record["artifact"],
                             {"previous_record_id": record.get("previous_record_id"),
                              "record_ref": creation_reference(state, project_id, record)}))
    for identity, record in state.get("solver_results", {}).items():
        if record["project_id"] == project_id and record["snapshot"]["snapshot_id"] == snapshot_id:
            rows.append(_row("solver_result", identity, record["snapshot"]["description"] or "보존 해석 결과", revision,
                             "computed", record["normalized"], {"profile": record.get("metadata", {}).get("profile")}))
    for record in state.get("rf_validations", {}).values():
        if record["project_id"] == project_id and record["snapshot"]["snapshot_id"] == snapshot_id:
            for report in record["reports"]:
                rows.append(_row("verification_report", report["report_id"], record["name"], revision,
                                 report["status"], report["artifact"], {"assessment_hash": report["assessment_hash"]}))
    for job in state["jobs"].values():
        if (job.get("context", {}).get("project_id") != project_id or (job.get("snapshot") or {}).get("snapshot_id") != snapshot_id
                or job.get("operation_method") not in ("geometry.build", "export.build", "export.verify")):
            continue
        terminal = job.get("events", [])[-1:]
        if terminal and terminal[0].get("state") == "completed":
            files = terminal[0].get("operation_result", {}).get("artifacts", [])
            rows.append(_row("output", job["job_id"], job["operation_method"], revision, "completed",
                             detail={"format": job.get("input", {}).get("format"), "artifacts": files}))
    return sorted(rows, key=lambda item: (item["kind"], item["id"]))


def solver_details(service, project, state, rows):
    """! @brief 해석 결과 원본의 조건, 생략과 주파수 표본을 고정 개정에 연결한다."""
    identities = [row["id"] for row in rows if row["kind"] == "solver_result"]
    details = []
    for identity in identities[:12]:
        record = state["solver_results"][identity]
        try:
            result = json.loads(read_solver_artifact(service, project, record, record["normalized"]))
        except ProjectError as error:
            if error.code != "E_MISSING_ARTIFACT" and not isinstance(error.__cause__, FileNotFoundError):
                raise
            details.append({"id": identity, "state": "missing", "artifact": record["normalized"]})
            continue
        plan = result["provenance"]["analysis_plan"]
        case = plan["case"]
        series = []
        for sample in result.get("samples", [])[:201]:
            value = sample.get("s11")
            if value is not None:
                magnitude = math.hypot(*value)
                series.append([sample["frequency_hz"], 20 * math.log10(magnitude) if magnitude else None])
        details.append({"id": identity, "state": "verified", "artifact": record["normalized"],
                        "case_sha256": canonical_hash(case), "settings": case.get("settings", {}),
                        "omissions": [*plan.get("model_report", {}).get("omissions", []),
                                      *plan.get("physical_setup_omissions", [])],
                        "s11_db_by_frequency_hz": series})
    return {"items": details, "total": len(identities)}


def summary(snapshot, document, rows):
    """! @brief 인계 목록은 현재 범위의 확인 상태와 미확립 항목을 함께 기록한다."""
    return {"profile": PROFILE, "project_id": document["project_id"], "project_name": document["metadata"]["name"],
            "revision_id": document["revision_id"], "snapshot_id": snapshot["snapshot_id"],
            "content_hash": snapshot["content_hash"], "items": deepcopy(rows),
            "scope": {"source": "explicit_snapshot", "solver_results": "same_snapshot_only", "physics_recomputed": False,
                      "manufacturing_acceptance": "not_established", "measurement_acceptance": "not_established"}}


def bounded(value):
    """! @brief 상한을 넘는 작은 RPC 응답은 페이지를 줄일 수 있도록 명시 오류로 반환한다."""
    if len(canonical_bytes(value)) > MAX_BYTES:
        fail("검증 근거 응답의 크기 상한을 초과했습니다. 더 작은 페이지를 요청하세요.", "E_RESOURCE")
    return value


def read(service, params):
    """! @brief 명시 ID와 종류의 일치 여부를 검사하고 불변 근거를 페이지로 제공한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 인계 조회 API 계약입니다.", "E_VERSION")
    context, data = params["context"], params["input"]
    _fields(data, {"snapshot", "kinds", "records", "offset", "limit"})
    kinds, selections = data["kinds"], data["records"]
    if (type(kinds) is not list or any(type(kind) is not str or kind not in KINDS for kind in kinds)
            or len(kinds) != len(set(kinds)) or type(selections) is not list or len(selections) > MAX_SELECTION):
        fail("검증 근거의 종류와 명시 선택 범위를 확인하세요.")
    chosen = set()
    for item in selections:
        _fields(item, {"kind", "id"})
        _uuid(item["id"])
        kind = item["kind"]
        if type(kind) is not str or kind not in KINDS or kinds and kind not in kinds or (kind, item["id"]) in chosen:
            fail("검증 근거의 종류, 필터 또는 선택 식별자가 다릅니다.")
        chosen.add((kind, item["id"]))
    offset, limit = data["offset"], data["limit"]
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        fail("검증 근거의 페이지 범위를 확인하세요.", "E_RESOURCE")
    state = service.journal.read()
    _, snapshot, document = source(service, state, context, data["snapshot"])
    rows = index(state, snapshot, document)
    rows = [row for row in rows if (not kinds or row["kind"] in kinds) and (not chosen or (row["kind"], row["id"]) in chosen)]
    if chosen and len(rows) != len(chosen):
        fail("선택한 스냅샷에 없는 근거 식별자가 있습니다.", "E_CONFLICT")
    if offset > len(rows):
        fail("검증 근거 페이지의 시작 순번이 범위를 벗어났습니다.", "E_RESOURCE")
    page = rows[offset:offset + limit]
    result = summary(snapshot, document, page)
    result.update(offset=offset, total=len(rows), index_hash=canonical_hash(rows),
                  next_offset=offset + len(page) if offset + len(page) < len(rows) else None)
    return bounded(result)
