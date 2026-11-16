"""! @brief 검토된 RF 캠페인의 영속 수명과 불변 판정 조회를 제공한다."""

from copy import deepcopy
import json
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import _fields, _uuid
from rfad.application.rf_validation_plan import PROFILE, definition, display_budget
from rfad.domain.errors import ProjectError
from rfad.domain.network_library import digest


READS = {"rf.validation.preview", "rf.validation.list", "rf.validation.get", "rf.validation.reports"}
MUTATIONS = {"rf.validation.create", "rf.validation.advance", "rf.validation.cancel", "rf.validation.assess"}
FIELDS = {"rf.validation.preview": {"expected_revision", "name"},
    "rf.validation.create": {"expected_revision", "name", "review_hash"},
    "rf.validation.list": {"offset", "limit"}, "rf.validation.get": {"validation_id", "report_id"},
    "rf.validation.reports": {"validation_id", "offset", "limit"},
    "rf.validation.advance": {"validation_id", "case_id", "phase"},
    "rf.validation.cancel": {"validation_id"}, "rf.validation.assess": {"validation_id"}}
PHASES = ("plan", "prepare", "solve", "postprocess")
MAX_BYTES = 256 * 1024


def fail(message, code="E_SCHEMA"):
    """! @brief 공개 오류는 저장소의 기존 진단 계약을 사용한다."""
    raise ProjectError(code, message)


def bounded(value):
    """! @brief 사용자 자료를 버리지 않고 유한 응답 상한을 검사한다."""
    if len(canonical_bytes(value)) > MAX_BYTES:
        fail("검증 기록이 256 KiB 상한을 초과했습니다.", "E_RESOURCE")
    return value


def validate_input(method, context, data):
    """! @brief 명시 프로젝트, 페이지와 닫힌 실행 단계만 허용한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    _fields(data, FIELDS[method])
    for key in ("validation_id", "expected_revision", "report_id"):
        if key in data and (key != "report_id" or data[key] is not None):
            _uuid(data[key])
    if "review_hash" in data:
        digest(data["review_hash"], "review_hash")
    if "name" in data and (type(data["name"]) is not str or not data["name"].strip()
            or len(data["name"]) > 80 or any(ord(char) < 32 for char in data["name"])):
        fail("검증 이름은 제어 문자가 없는 1~80자여야 합니다.")
    if "offset" in data and (type(data["offset"]) is not int or data["offset"] < 0
            or type(data["limit"]) is not int or not 1 <= data["limit"] <= 25):
        fail("검증 목록은 0 이상의 시작 순번과 1~25개 페이지가 필요합니다.")
    if "phase" in data and (data["phase"] not in PHASES or type(data["case_id"]) is not str
            or len(data["case_id"]) > 32):
        fail("명시한 검증 사례와 실행 단계를 지원하지 않습니다.")


def load_json(service, reference):
    """! @brief 해시 검사한 불변 JSON만 해석하며 임의 경로를 받지 않는다."""
    if reference["bytes"] > MAX_BYTES:
        fail("검증 기록의 크기 상한을 초과했습니다.", "E_RESOURCE")
    value = json.loads(service.journal.read_artifact(reference))
    return bounded(value)


def owned(service, state, context, identity):
    """! @brief 다른 프로젝트의 캠페인과 판정을 식별자만으로 열지 않는다."""
    service._project(state, context)
    record = state.get("rf_validations", {}).get(identity)
    if record is None or record["project_id"] != context["project_id"]:
        fail("현재 프로젝트의 검증 기록을 찾을 수 없습니다.", "E_CONFLICT")
    return record


def preview(service, state, context, data):
    """! @brief 실제 원본과 런타임을 고정하되 검토만으로 snapshot을 게시하지 않는다."""
    from rfad.application.solver import _reference_source

    project = service._project(state, context)
    raw, document = service.repository.read(project["current"])
    if document["revision_id"] != data["expected_revision"]:
        fail("검토 후 프로젝트 개정이 바뀌었습니다.", "E_CONFLICT")
    snapshot = service.operations.prepare_snapshot(state, project, document, raw, {"description": data["name"]})
    _reference_source(document, snapshot)
    runtime = None if service.solver.runtime is None else service.solver.runtime.identity
    value = definition(document, runtime, data["name"])
    return bounded({"profile": PROFILE, "review_hash": canonical_hash(value), "definition": value,
        "execution_available": runtime is not None, "manufacturing": None, "measurement": None})


def phase_status(state, record, identity):
    """! @brief 영속 작업 상태를 파생하며 읽기 조회로 journal을 수정하지 않는다."""
    result = {}
    for phase, job_id in record["jobs"].get(identity, {}).items():
        job = state["jobs"].get(job_id)
        if job is None or job.get("context", {}).get("project_id") != record["project_id"]:
            fail("검증 단계의 소유 작업이 없거나 다릅니다.", "E_HASH")
        result[phase] = {"job_id": job_id, "state": job["state"],
            "resource_reserved": job.get("solver", {}).get("resource_reserved", False),
            "operation_result": deepcopy(job["events"][-1].get("operation_result")),
            "error": deepcopy(job["events"][-1].get("error"))}
    return result


def current_view(service, state, record):
    """! @brief 계획 상태에는 과거 보고서의 합격이나 암묵적 최신 결과를 섞지 않는다."""
    plan = load_json(service, record["definition"])
    cases = []
    for case in plan["cases"]:
        row = {key: deepcopy(case[key]) for key in
               ("case_id", "name", "group", "axis", "level", "grid_mm", "blocked_reason")}
        phases = phase_status(state, record, case["case_id"])
        last_phase = next((p for p in reversed(PHASES) if p in phases), None)
        last = phases[last_phase]["state"] if last_phase is not None else "not_started"
        if last == "completed":
            last = {"plan": "planned", "prepare": "prepared", "solve": "solved", "postprocess": "postprocessed"}[last_phase]
        row.update(phase_states=phases, execution_state="blocked_before_execution" if row["blocked_reason"] else last,
                   source=None, pin=None)
        cases.append(row)
    status = lifecycle_state(state, record)
    usage = deepcopy(record["usage"])
    usage["wall_seconds"] = 0 if record["started_at"] is None else max(0, service._now() - record["started_at"])
    states = {key: {"state": "unknown" if key in ("manufacturing", "measurement") else "not_established",
                   "reason": "이 계획 조회에는 별도 판정 보고서를 선택하지 않았습니다."}
              for key in ("mesh", "boundary", "termination", "independent_reference", "manufacturing", "measurement")}
    return bounded({"profile": PROFILE, "validation_id": record["validation_id"], "name": record["name"],
        "created_at": record["created_at"], "plan_hash": record["definition"]["sha256"],
        "report_id": None, "assessment_hash": None, "status": status, "cases": cases,
        "rows": [], "validation_states": states, "assumptions": plan["assumptions"],
        "source_refs": plan["source_refs"], "limitations": plan["limitations"],
        "manufacturing": None, "measurement": None, "budget": display_budget(plan["budget"]),
        "usage": display_budget(usage), "snapshot": deepcopy(record["snapshot"]),
        "runtime_identity": plan["runtime_identity"], "assessment_engine": plan["assessment_engine"], "criteria": plan["criteria"]})


def lifecycle_state(state, record):
    """! @brief 목록과 본문 모두 실제 예약이 남은 취소를 완료로 표시하지 않는다."""
    phases = [phase for identity in record["jobs"] for phase in phase_status(state, record, identity).values()]
    active = any(p["resource_reserved"] or p["state"] not in ("completed", "failed", "cancelled", "interrupted") for p in phases)
    if record["cancelled"]:
        return "cancel_requested" if active else "cancelled"
    return "running" if active else "plan"


def _page(items, data):
    """! @brief 목록의 끝을 명시하고 범위 밖 페이지를 거절한다."""
    offset, total = data["offset"], len(items)
    if offset > total:
        fail("검증 목록의 시작 순번이 범위를 벗어났습니다.")
    selected = items[offset:offset + data["limit"]]
    return {"profile": PROFILE, "offset": offset, "total": total, "items": selected,
            "next_offset": offset + len(selected) if offset + len(selected) < total else None}


def read(service, method, params):
    """! @brief native runtime이 없어도 보존 계획과 명시한 과거 판정을 읽는다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 검증 API 버전입니다.", "E_VERSION")
    context, data = params["context"], params["input"]
    validate_input(method, context, data)
    state = service.journal.read()
    service._project(state, context)
    if method == "rf.validation.preview":
        return preview(service, state, context, data)
    if method == "rf.validation.list":
        records = sorted((r for r in state.get("rf_validations", {}).values() if r["project_id"] == context["project_id"]),
                         key=lambda row: (row["created_at"], row["validation_id"]), reverse=True)
        items = [{"validation_id": r["validation_id"], "name": r["name"], "created_at": r["created_at"],
                  "state": "recorded" if lifecycle_state(state, r) == "plan" and r["reports"] else lifecycle_state(state, r),
                  "latest_report_id": r["reports"][-1]["report_id"] if r["reports"] else None,
                  "report_count": len(r["reports"])} for r in records]
        return bounded(_page(items, data))
    record = owned(service, state, context, data["validation_id"])
    if method == "rf.validation.reports":
        return bounded(_page([{key: r[key] for key in ("report_id", "created_at", "status", "assessment_hash")}
                              for r in reversed(record["reports"])], data))
    if data["report_id"] is None:
        return current_view(service, state, record)
    report = next((r for r in record["reports"] if r["report_id"] == data["report_id"]), None)
    if report is None:
        fail("선택한 검증 기록에 해당 판정이 없습니다.", "E_CONFLICT")
    value = load_json(service, report["artifact"])
    if value["validation_id"] != record["validation_id"] or canonical_hash(value) != report["assessment_hash"]:
        fail("판정 보고서의 소유권 또는 내용 해시가 다릅니다.", "E_HASH")
    return {**value, "assessment_hash": report["assessment_hash"]}


def admit(service, state, method, context, data):
    """! @brief 공통 영수증 transaction 안에서 생성/실행/취소/별도 판정을 게시한다."""
    validate_input(method, context, data)
    if method == "rf.validation.create":
        reviewed = preview(service, state, context, data)
        if reviewed["review_hash"] != data["review_hash"]:
            fail("원본, 검증 조건 또는 실행 환경이 검토 이후 바뀌었습니다.", "E_CONFLICT")
        records = state.setdefault("rf_validations", {})
        if len(records) >= 16:
            fail("검증 캠페인 보존 상한 16개에 도달했습니다.", "E_RESOURCE")
        project = service._project(state, context)
        raw, document = service.repository.read(project["current"])
        snapshot = service.operations.prepare_snapshot(state, project, document, raw, {"description": data["name"]})
        identity = str(uuid4())
        plan = {**reviewed["definition"], "validation_id": identity, "snapshot": snapshot, "review_hash": data["review_hash"]}
        encoded = canonical_bytes(bounded(plan))
        artifact = service.journal.put_immutable(project["path"] + "/rf-validations/" + identity + "/definition.json", encoded)
        service.operations.publish_snapshot(state, snapshot, raw)
        record = {"validation_id": identity, "project_id": context["project_id"], "name": data["name"],
            "created_at": service._now(), "definition": artifact, "snapshot": snapshot,
            "started_at": None, "cancelled": False, "jobs": {}, "reports": [],
            "usage": {"native_solves": 0, "worker_calls": 0, "analysis_seconds": 0,
                      "worker_reserved_seconds": 0, "disk_bytes": len(encoded) + len(raw)}}
        records[identity] = record
        return {"validation_id": identity, "state": "plan", "plan_hash": artifact["sha256"], "snapshot": snapshot}
    record = owned(service, state, context, data["validation_id"])
    if method == "rf.validation.advance":
        from rfad.application.rf_validation_execution import advance
        return advance(service, state, record, data)
    if method == "rf.validation.cancel":
        for cases in record["jobs"].values():
            for identity in cases.values():
                service.solver.cancel_job(state["jobs"][identity], "RF 검증 캠페인의 명시적 취소")
        record["cancelled"] = True
        return {"validation_id": record["validation_id"], "status": current_view(service, state, record)["status"]}
    from rfad.application.rf_validation_assessment import assess
    return assess(service, state, record)
