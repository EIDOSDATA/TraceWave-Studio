"""! @brief 검토한 스냅샷, 보고서와 선택 원문을 읽기 전용 인계 묶음으로 게시한다."""

from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO

from rfad.application import handoff_archive as archive, handoff_evidence as evidence
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application import package_publication as publication
from rfad.application.network_records import reference
from rfad.application.project_contract import _fields, _uuid
from rfad.application.result_sources import owned_reference
from rfad.domain.network_library import digest
from rfad.storage.journal import MAX_ARTIFACT_BYTES


PROFILE = archive.PROFILE
MUTATION = "package.build"
READS = {"package.preview", "package.list", "package.read", "package.receipt"}
POLICIES = ("design_and_report", "include_selected_files")
BUILD_FIELDS = {"snapshot", "records", "inclusion", "rights_confirmed"}


def validate_input(method, context, data):
    """! @brief 현재 제품의 한정된 발행 요청과 읽기 입력을 검사한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    if method in (MUTATION, "package.preview"):
        _fields(data, BUILD_FIELDS | ({"review_hash"} if method == MUTATION else set()))
        if method == MUTATION:
            digest(data["review_hash"], "review_hash")
        if data["inclusion"] not in POLICIES or type(data["rights_confirmed"]) is not bool:
            archive.fail("보존 범위와 명시 공유 권한 확인이 필요합니다.")
        if data["inclusion"] == "include_selected_files" and not data["rights_confirmed"]:
            archive.fail("선택 원문을 인계하려면 자료 공유 권한을 확인하십시오.", "E_CONFLICT")
        selections = data["records"]
        if type(selections) is not list or len(selections) > evidence.MAX_SELECTION:
            archive.fail("인계 근거 선택은 최대 64개입니다.", "E_RESOURCE")
        if data["inclusion"] == "include_selected_files" and not selections:
            archive.fail("인계에 포함할 근거를 명시 선택하십시오.")
        used = set()
        for selected in selections:
            _fields(selected, {"kind", "id"})
            kind, identity = selected["kind"], _uuid(selected["id"])
            if type(kind) is not str or kind not in evidence.KINDS or (kind, identity) in used:
                archive.fail("인계 원문의 종류 또는 중복 선택을 확인하십시오.")
            used.add((kind, identity))
    else:
        publication.validate(method.rsplit(".", 1)[-1], data)


def _label(value):
    """! @brief 원래 텍스트를 표에서 읽을 수 있도록 줄 바꿈과 Markdown 구문만 이스케이프한다."""
    value = " ".join(str(value).split())
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")


def _report_text(report):
    """! @brief 외부 렌더러나 스크립트 없이 읽을 수 있는 UTF-8 인계 보고서를 작성한다."""
    lines = ["# TraceWave Studio 인계 보고서", "", "프로젝트 " + _label(report["project_name"]),
             "개정 `" + report["revision_id"] + "`", "스냅샷 `" + report["snapshot_id"] + "`",
             "내용 SHA256 `" + report["content_hash"] + "`", "", "제작 및 실측 검증 미확립", "",
             "| 종류 | 이름 | 기록 상태 | 파일 사본 |", "| --- | --- | --- | --- |"]
    for item in report["items"]:
        lines.append("| " + " | ".join(_label(item[key]) for key in ("kind", "name", "status", "copy_state")) + " |")
    lines.extend(["", "## 적용 범위", ""])
    lines.extend("- " + _label(line) for line in report["limitations"])
    return ("\n".join(lines) + "\n").encode("utf-8")


def prepare(service, state, context, data):
    """! @brief 파일을 게시하지 않고 선택 스냅샷의 결정적 인계 후보를 구성한다."""
    project, snapshot, document = evidence.source(service, state, context, data["snapshot"])
    index = evidence.index(state, snapshot, document)
    selected = {(item["kind"], item["id"]) for item in data["records"]}
    available = {(row["kind"], row["id"]) for row in index}
    if not selected <= available:
        archive.fail("선택한 스냅샷에서 찾을 수 없는 인계 근거가 있습니다.", "E_CONFLICT")
    submitted = {}
    reported = []

    def include(artifact):
        """! @brief 등록한 현재 프로젝트 파일만 한 번 포함한다."""
        raw = owned_reference(project, artifact)
        name = "workspace/" + raw["uri"]
        value = {key: raw[key] for key in ("sha256", "bytes")} | {"uri": name}
        previous = submitted.get(name)
        if previous is not None and previous != value:
            archive.fail("같은 인계 경로의 원문 참조가 서로 다릅니다.", "E_HASH")
        submitted[name] = value

    include(snapshot["artifact"])
    for row in index:
        item = deepcopy(row)
        copy_file = data["inclusion"] == "include_selected_files" and (item["kind"], item["id"]) in selected
        artifact = item["artifact"]
        if item["kind"] == "snapshot":
            item["copy_state"] = "included"
        elif item["kind"] == "output" and copy_file:
            output_files = item["detail"]["artifacts"]
            if output_files and all(row["uri"].startswith(project["path"] + "/") for row in output_files):
                for output in output_files:
                    include(output)
                item["copy_state"] = "included"
            else:
                item["copy_state"] = "external_storage_reference_only" if output_files else "no_file_record"
        elif not copy_file or artifact is None:
            registered = artifact is not None or bool(item["detail"].get("artifacts"))
            item["copy_state"] = "registered_reference_only" if registered else "no_file_record"
        elif not artifact["uri"].startswith(project["path"] + "/"):
            item["copy_state"] = "external_storage_reference_only"
        else:
            include(artifact)
            if item["kind"] == "network":
                for name in ("original", "normalized_hdf5"):
                    if item["detail"][name] is not None:
                        include(item["detail"][name])
            item["copy_state"] = "included"
        item["selected_for_copy"] = copy_file
        reported.append(item)
    limitations = ["고정 설계 스냅샷과 선택 파일의 인계 사본입니다. 전체 프로젝트 이력과 자동 재개 상태는 포함하지 않습니다.",
                   "목록에 등록된 근거와 묶음에 실제 포함한 파일은 파일 사본 열과 manifest에서 확인할 수 있습니다.",
                   "물성, 제작, 환경과 측정의 미정값은 원래 설계에 보존합니다. 물리 정확도 합격은 미확립입니다."]
    report = evidence.summary(snapshot, document, reported)
    report.update(limitations=limitations, inclusion=data["inclusion"], rights_confirmed=data["rights_confirmed"])
    files = {"report.json": canonical_bytes(report), "report.md": _report_text(report),
             "project-index.json": canonical_bytes({"schema": "rfad.handoff-index/0.1", "snapshot": snapshot,
                "project_path": project["path"], "view_only": True, "active_restore_supported": False})}
    entries = sorted([*submitted.values(), *(reference(name, raw) for name, raw in files.items())], key=lambda item: item["uri"])
    plan = archive.manifest({"schema": PROFILE, "project_id": document["project_id"], "project_path": project["path"],
        "snapshot_id": snapshot["snapshot_id"], "revision_id": document["revision_id"], "content_hash": snapshot["content_hash"],
        "files": entries, "limitations": limitations})
    names = [archive.MANIFEST_NAME, *(item["uri"] for item in entries)]
    headers = 22 + sum(76 + 2 * len(name.encode("utf-8")) for name in names)
    size = sum(item["bytes"] for item in entries) + len(canonical_bytes(plan)) + headers
    if size > MAX_ARTIFACT_BYTES:
        archive.fail("현재 인계 발행의 ZIP 크기 한도는 8 MiB입니다. 원문 선택을 줄이십시오.", "E_RESOURCE")
    review = canonical_hash({"input": {key: data[key] for key in BUILD_FIELDS}, "manifest": plan})
    candidate = {"profile": PROFILE, "project_id": document["project_id"], "snapshot_id": snapshot["snapshot_id"],
        "revision_id": document["revision_id"], "content_hash": snapshot["content_hash"], "review_hash": review,
        "files": entries, "estimated_bytes": size, "limitations": limitations, "read_only_handoff": True,
        "evidence_count": len(reported), "included_count": len(submitted), "preview_records": reported[:32]}
    return evidence.bounded(candidate), plan, files, submitted


def admit(service, state, context, data):
    """! @brief 전체 검토와 ZIP 검증이 끝난 뒤 하나의 불변 파일과 영수증을 게시한다."""
    candidate, plan, files, submitted = prepare(service, state, context, data)
    review = candidate["review_hash"]
    if review != data["review_hash"]:
        archive.fail("인계 검토 이후 원본 또는 포함 범위가 변경됐습니다. 다시 검토하세요.", "E_CONFLICT")
    @contextmanager
    def source(name):
        """! @brief 새 보고서나 검증한 소유 프로젝트 파일만 읽는다."""
        if name in files:
            yield BytesIO(files[name])
        else:
            reference_item = {**submitted[name], "uri": name.removeprefix("workspace/")}
            service.journal.verify_file(reference_item)
            with service.journal._safe_path(reference_item["uri"]).open("rb") as stream:
                yield stream

    def pack():
        """! @brief 봉인한 ZIP을 다시 읽고 구조 검증 결과만 게시 저장부에 넘긴다."""
        stream = BytesIO()
        archive.write_archive(stream, plan, source)
        with archive.read_archive(stream):
            return stream.getvalue()

    return publication.publish(service, state, plan, review, "handoff", "TraceWave-" + plan["revision_id"][:8] + ".rfad.zip", pack)


def read(service, method, params):
    """! @brief 소유 프로젝트의 출판물, 청크 또는 원래 접수 결과만 조회한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        archive.fail("지원하지 않는 인계 API 버전입니다.", "E_VERSION")
    context, data = params["context"], params["input"]
    validate_input(method, context, data)
    state = service.journal.read()
    project = service._project(state, context)
    if method == "package.preview":
        return prepare(service, state, context, data)[0]
    return publication.read(service, state, context, project, method.rsplit(".", 1)[-1], data, PROFILE, MUTATION)
