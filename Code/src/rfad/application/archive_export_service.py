"""! @brief 현재/저장 개정의 편집 복원 묶음을 실행 없이 검토하고 발행한다."""

from rfad.application import handoff_archive as codec, package_publication as publication, project_archive
from rfad.application.project_archive_model import PROFILE
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.network_library import digest


MUTATION = "archive.export.build"
READS = {"archive.export.preview", "archive.export.list", "archive.export.read", "archive.export.receipt"}


def validate_input(method, context, data):
    """! @brief 현재 개정과 원문 공유 범위를 명시하며 검토 hash를 발행에 고정한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    if method in (MUTATION, "archive.export.preview"):
        _fields(data, {"expected_revision", "include_sources"} | ({"review_hash"} if method == MUTATION else set()))
        _uuid(data["expected_revision"])
        if type(data["include_sources"]) is not bool:
            codec.fail("공유 권한을 확인한 등록 파일의 포함 여부를 명시하십시오.")
        if method == MUTATION:
            digest(data["review_hash"], "review_hash")
    else:
        publication.validate(method.rsplit(".", 1)[-1], data)


def read(service, method, params):
    """! @brief 발행 검토와 프로젝트 범위의 기존 기록을 조회한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        codec.fail("지원하지 않는 프로젝트 보존 묶음 API 버전입니다.", "E_VERSION")
    context, data = params["context"], params["input"]
    validate_input(method, context, data)
    state = service.journal.read()
    project = service._project(state, context)
    suffix = method.rsplit(".", 1)[-1]
    if suffix != "preview":
        return publication.read(service, state, context, project, suffix, data, PROFILE, MUTATION)
    item = project_archive.prepare(service, context["project_id"], data["expected_revision"], data["include_sources"])
    plan = item["plan"]
    return {"profile": PROFILE, "project_id": item["project_id"], "revision_id": item["revision_id"],
            "content_hash": plan["content_hash"], "review_hash": item["review_hash"], "estimated_bytes": item["zip_bytes"],
            "missing_count": item["missing_count"], "limitations": plan["limitations"],
            "omitted_preview": item["omitted"][:16], "files": plan["files"][:32], "file_count": len(plan["files"]) + 1}


def admit(service, state, context, data):
    """! @brief 현재 원본과 검토를 맞춘 뒤 복원용 ZIP을 기존 발행 저장부로 보낸다."""
    project_id = context["project_id"]
    revision, include_sources = data["expected_revision"], data["include_sources"]
    current = project_archive.prepare(service, project_id, revision, include_sources)
    review = current["review_hash"]
    if review != data["review_hash"]:
        codec.fail("묶음의 원본 또는 포함 범위가 달라졌습니다. 다시 검토하십시오.", "E_CONFLICT")
    return publication.publish(service, state, current["plan"], review, "archive", "TraceWave-복원-" + revision[:8] + ".rfad.zip",
                               lambda: project_archive.write_prepared(service, current))
