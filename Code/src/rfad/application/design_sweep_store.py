"""! @brief 스윕의 봉인 원본과 후보별 불변 파일을 작은 journal 참조로 연결한다."""

from copy import deepcopy
import json
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project


PROFILE = "rfad.design-sweep/0.1"
DEFINITION_SCHEMA = "rfad.design-sweep-definition/0.1"
MAX_RESPONSE = 256 * 1024
PAGE_SIZE = 25
ACTIVE = {"running", "resuming", "cancel_requested"}


def fail(message, code="E_SCHEMA"):
    """! @brief 원본 보존 실패와 자원 경계를 공개 오류로 알린다."""
    raise ProjectError(code, message)


def bounded(value):
    """! @brief 조회 응답을 조용히 자르지 않고 명시한 전송 상한을 검사한다."""
    if len(canonical_bytes(value)) > MAX_RESPONSE:
        fail("연구 조회 응답이 256 KiB를 초과했습니다. 더 작은 페이지를 요청하십시오.", "E_RESOURCE")
    return value


def folder(service, study):
    """! @brief 연구의 소유 프로젝트 경로에서만 산출물 위치를 만든다."""
    state = service.journal.read()
    project = state["projects"].get(study["project_id"])
    if project is None:
        fail("연구의 소유 프로젝트를 찾을 수 없습니다.", "E_HASH")
    return project["path"] + "/sweeps/" + study["study_id"]


def read_json(service, reference):
    """! @brief 해시가 검증된 불변 JSON만 읽고 비정규 사본은 거부한다."""
    raw = service.journal.read_artifact(reference)
    try:
        result = json.loads(raw)
        if canonical_bytes(result) != raw:
            fail("연구 자료의 정규 JSON 바이트가 다릅니다.", "E_HASH")
        return result
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ProjectError("E_HASH", "연구 자료를 읽을 수 없습니다.") from error


def load_definition(service, study):
    """! @brief 불변 정의와 작은 journal 색인의 소유권/원본 일치를 확인한다."""
    reference = study["definition"]
    if not reference["uri"].startswith(folder(service, study) + "/"):
        fail("연구 정의가 소유 프로젝트 경로 밖에 있습니다.", "E_HASH")
    definition = read_json(service, reference)
    if (definition.get("schema") != DEFINITION_SCHEMA
            or definition.get("study_id") != study["study_id"]
            or definition.get("snapshot") != study["snapshot"]
            or definition.get("candidate_count") != study["counts"]["total"]
            or canonical_hash(definition.get("runtime_identity")) != study["runtime_identity_hash"]):
        fail("연구 정의와 journal 색인이 일치하지 않습니다.", "E_HASH")
    return definition


def baseline(service, study):
    """! @brief 실행 중 현재 편집본 대신 봉인한 원래 프로젝트를 읽는다."""
    definition = load_definition(service, study)
    snapshot = definition["snapshot"]
    document = service._load({"current": snapshot["artifact"]})
    validate_project(document)
    if canonical_hash(document) != snapshot["content_hash"]:
        fail("연구의 원본 스냅샷 해시가 다릅니다.", "E_HASH")
    return definition, document


def candidate_source(service, study, index):
    """! @brief 후보 하나만 결정적으로 생성하고 프로젝트 원본은 변경하지 않는다."""
    from rfad.domain.design_sweep import candidate_at

    definition, document = baseline(service, study)
    network = definition["network"]
    return candidate_at(document, definition["specification"], index,
                        circuit=None if network is None else network["circuit"])


def load_candidate(service, study, index):
    """! @brief 아직 생성하지 않은 후보는 None으로 반환하며 결과를 꾸며내지 않는다."""
    if type(index) is not int or not 0 <= index < study["counts"]["total"]:
        fail("후보 순번이 연구 범위를 벗어났습니다.")
    reference = study["records"].get(str(index))
    if reference is None:
        return None
    if not reference["uri"].startswith(folder(service, study) + "/candidates/"):
        fail("후보 기록의 소유 경로가 다릅니다.", "E_HASH")
    candidate = read_json(service, reference)
    if candidate.get("ordinal") != index or candidate.get("study_id") != study["study_id"]:
        fail("후보 기록의 순번/연구 식별자가 다릅니다.", "E_HASH")
    return candidate


def publish_candidate(service, state, study, candidate):
    """! @brief 호출자의 단일 transaction 안에서 새 후보 버전 참조만 게시한다."""
    ordinal = candidate["ordinal"]
    if type(ordinal) is not int or not 0 <= ordinal < study["counts"]["total"]:
        fail("게시할 후보 순번이 유효하지 않습니다.")
    payload = deepcopy(candidate)
    payload["study_id"] = study["study_id"]
    if any(key in payload for key in ("document", "source_semantics")):
        fail("후보 기록에 원본 프로젝트를 반복 복제할 수 없습니다.", "E_RESOURCE")
    raw = canonical_bytes(payload)
    if len(raw) > MAX_RESPONSE:
        fail("후보 기록이 256 KiB를 초과했습니다.", "E_RESOURCE")
    root = state["projects"][study["project_id"]]["path"] + "/sweeps/" + study["study_id"]
    reference = service.journal.put_immutable(root + f"/candidates/{ordinal}/{uuid4()}.json", raw)
    study["records"][str(ordinal)] = reference
    study["usage"]["disk_bytes"] += len(raw)
    return reference


def seal_result(service, study, index, role_bytes):
    """! @brief 결과 파일을 별도로 봉인하고 원본 자료 목록에는 자동 등록하지 않는다."""
    if type(index) is not int or not 0 <= index < study["counts"]["total"]:
        fail("결과 후보 순번이 유효하지 않습니다.")
    if type(role_bytes) is not dict or not 1 <= len(role_bytes) <= 16:
        fail("결과 파일 목록은 1~16개여야 합니다.")
    service.verify_calculation()
    root = folder(service, study) + f"/results/{index}/{uuid4()}"
    result = {}
    for role, raw in role_bytes.items():
        if (type(role) is not str or not role or len(role) > 64
                or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in role)
                or type(raw) is not bytes):
            fail("결과 역할/바이트 계약이 유효하지 않습니다.")
        result[role] = service.journal.put_immutable(root + "/" + role + ".json", raw)
    return result


def verify_retained(service, study):
    """! @brief 재개 전에 완료 근거와 시도 계획을 읽고 변조를 자동 복구하지 않는다."""
    definition, _ = baseline(service, study)
    if "calculation_source" in definition:
        import hashlib
        engine = definition["engine_identity"]["application_source"]
        project = service.journal.read()["projects"][study["project_id"]]
        if definition["calculation_source"]["uri"] != project["path"] + "/host-calculation-sources/" + engine["bundle_sha256"] + ".json":
            fail("연구 계산 source의 소유 프로젝트/경로가 다릅니다.", "E_HASH")
        source = service.journal.read_artifact(definition["calculation_source"])
        if len(source) != engine["bundle_bytes"] or hashlib.sha256(source).hexdigest() != engine["bundle_sha256"]:
            fail("연구의 보존 계산 source와 고정 환경이 다릅니다.", "E_HASH")
    network = definition["network"]
    if network is not None:
        service.journal.read_artifact(network["dataset"])
        for key in ("raw", "normalized_hdf5", "diagnostics"):
            reference = network["entry"].get(key)
            if reference is not None:
                service.journal.read_artifact(reference)
    state = service.journal.read()
    for ordinal in study["records"]:
        candidate = load_candidate(service, study, int(ordinal))
        for reference in candidate.get("results", {}).values():
            if not reference["uri"].startswith(folder(service, study) + "/results/"):
                fail("후보 결과가 현재 연구의 저장 경로에 속하지 않습니다.", "E_HASH")
            service.journal.read_artifact(reference)
        for key in ("analysis_plan", "prepared_plan"):
            reference = candidate.get(key)
            if reference is not None:
                plan = read_json(service, reference["artifact"])
                if canonical_hash(plan) != reference["content_hash"]:
                    fail("재개할 후보 계획의 해시가 다릅니다.", "E_HASH")
        for attempt in candidate.get("attempts", []):
            job = state["jobs"].get(attempt["job_id"])
            if job is None or job["context"]["project_id"] != study["project_id"]:
                fail("후보 실행 시도의 작업 소유권이 다릅니다.", "E_HASH")
            from rfad.application.solver_capture import hydrate_job

            hydrated = hydrate_job(service.journal, job)
            if hydrated["solver"]["runtime"] != definition["runtime_identity"]:
                fail("후보 실행 시도의 runtime이 연구 정의와 다릅니다.", "E_HASH")
    return definition
