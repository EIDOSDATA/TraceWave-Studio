"""! @brief 원본과 같은 개정 및 소유 영역을 검토하고 새 journal에 원자 등록한다."""

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unicodedata import normalize

from rfad.application import handoff_archive as codec, project_archive_model as model
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.network_records import reference as byte_reference
from rfad.application.project_contract import MAX_PROJECTS, MAX_SNAPSHOTS, _fields, _uuid
from rfad.domain.network_library import digest
from rfad.storage.journal import MAX_ARTIFACT_BYTES, MAX_STATE_BYTES


OMISSION_REASONS = {"external_reference", "source_missing", "source_omitted"}
MAX_RECEIPTS = 32


def _size(files, plan):
    """! @brief 압축하지 않은 결정적 ZIP의 크기를 게시 전에 제한한다."""
    names = [codec.MANIFEST_NAME, *files]
    return 22 + len(canonical_bytes(plan)) + sum(row["bytes"] for row in files.values()) + sum(
        76 + 2 * len(name.encode("utf-8")) for name in names)


def prepare(service, project_id, expected_revision, include_sources):
    """! @brief 특정 개정의 보존 범위와 원래 문서/등록 원문 참조를 결정한다."""
    _uuid(project_id)
    _uuid(expected_revision)
    if type(include_sources) is not bool:
        codec.fail("등록 원문을 포함할지 명시하십시오.")
    state = service.journal.read()
    project = service.repository.project(state, {"project_id": project_id})
    current = service.repository.load(project)
    if current["revision_id"] != expected_revision:
        codec.fail("묶음을 검토할 현재 개정이 변경됐습니다.", "E_CONFLICT")
    index = model.make_index(state, project_id)
    plan = {"schema": model.PROFILE, "project_id": project_id, "project_path": project["path"],
            "revision_id": expected_revision, "content_hash": canonical_hash(current),
            "limitations": deepcopy(model.LIMITATIONS), "files": []}
    documents, references = model.validate_index(index, plan, service.journal.read_artifact)
    omitted = {}

    def retain(row, *, read=False):
        """! @brief 등록된 소유 원문만 읽고 누락된 것은 검토 목록에 남긴다."""
        uri = row["uri"]
        if uri in references:
            if references[uri] != row:
                codec.fail("같은 원문의 등록 해시 또는 크기가 다릅니다.", "E_HASH")
        else:
            if uri in omitted:
                if omitted[uri]["reference"] != row:
                    codec.fail("같은 누락 원문의 등록 내용이 다릅니다.", "E_HASH")
                return None
            reason = None
            if not uri.startswith(project["path"] + "/"):
                reason = "external_reference"
            elif not include_sources:
                reason = "source_omitted"
            elif not service.journal._safe_path(uri).exists():
                reason = "source_missing"
            if reason is not None:
                omitted[uri] = {"reference": row, "reason": reason}
                if len(omitted) > codec.MAX_FILES:
                    codec.fail("누락 원문 목록의 개수 상한에 도달했습니다.", "E_RESOURCE")
                return None
            if len(references) >= codec.MAX_FILES - 1:
                codec.fail("묶음의 파일 개수 상한에 도달했습니다.", "E_RESOURCE")
            references[uri] = row
        return service.journal.read_artifact(row) if read else None

    model.assets(documents, index["commands"], retain)
    index["omitted"] = [omitted[key] for key in sorted(omitted)]
    index["unavailable_parents"] = model.unavailable_parents(documents)
    index_raw = canonical_bytes(index)
    if len(index_raw) > model.INDEX_LIMIT:
        codec.fail("복원 색인이 4 MiB를 초과했습니다.", "E_RESOURCE")
    files = {row["uri"]: row for row in map(model.archived, references.values())}
    files[model.INDEX_FILE] = byte_reference(model.INDEX_FILE, index_raw)
    plan["files"] = [files[key] for key in sorted(files)]
    model.manifest(plan)
    size = _size(files, plan)
    if size > MAX_ARTIFACT_BYTES:
        codec.fail("현재 복원 묶음은 최대 8 MiB입니다.", "E_RESOURCE")
    return {"profile": model.PROFILE, "plan": plan, "references": references, "index_raw": index_raw,
            "review_hash": canonical_hash({"manifest": plan, "include_sources": include_sources}),
            "project_id": project_id, "revision_id": expected_revision, "zip_bytes": size,
            "missing_count": len(omitted), "omitted": index["omitted"]}


def build(service, project_id, expected_revision, include_sources, review_hash):
    """! @brief 검토와 같은 파일 집합을 검증하고 복원 가능한 ZIP 바이트를 반환한다."""
    digest(review_hash, "review_hash")
    reviewed = prepare(service, project_id, expected_revision, include_sources)
    if reviewed["review_hash"] != review_hash:
        codec.fail("복원 묶음의 원본 또는 포함 범위가 달라졌습니다.", "E_CONFLICT")
    return write_prepared(service, reviewed)


def write_prepared(service, reviewed):
    """! @brief 검토한 파일 집합의 실제 바이트와 원본 폐쇄를 다시 확인한다."""

    @contextmanager
    def source(uri):
        """! @brief 프로젝트 파일 외의 원문을 묶음에 추가하지 않는다."""
        if uri == model.INDEX_FILE:
            yield BytesIO(reviewed["index_raw"])
        else:
            row = reviewed["references"][uri.removeprefix("workspace/")]
            service.journal.verify_file(row)
            with service.journal._safe_path(row["uri"]).open("rb") as stream:
                yield stream

    raw = BytesIO()
    codec.write_archive(raw, reviewed["plan"], source, validate_plan=model.manifest)
    payload = raw.getvalue()
    if len(payload) != reviewed["zip_bytes"]:
        codec.fail("게시할 묶음의 실제 길이와 검토 바이트 수가 다릅니다.", "E_HASH")
    with read_verified(payload):
        return payload


def _validate_archive_contents(archive, plan):
    """! @brief 전체 ZIP 검증 뒤 폐쇄와 누락 목록을 원래 문서 위치에 대조한다."""
    files = {row["uri"]: row for row in plan["files"]}
    index = codec.read_canonical(archive, model.INDEX_FILE, model.INDEX_LIMIT)
    omitted = index["omitted"]
    if type(omitted) is not list or len(omitted) > codec.MAX_FILES:
        codec.fail("누락 목록의 크기가 다릅니다.", "E_RESOURCE")
    by_uri = {}
    for item in omitted:
        _fields(item, {"reference", "reason"})
        row = model.reference(item["reference"])
        uri = row["uri"]
        local = uri.startswith(plan["project_path"] + "/")
        if (uri in by_uri or "workspace/" + uri in files or item["reason"] not in OMISSION_REASONS
                or local == (item["reason"] == "external_reference")):
            codec.fail("누락 원문의 소유 범위, 사유 또는 파일 목록이 다릅니다.", "E_HASH")
        by_uri[uri] = row

    visited, expected_omissions = {model.INDEX_FILE}, set()

    def load(row, *, read=True):
        """! @brief 내용 참조를 검증된 항목과 대조한 다음 필요한 작은 JSON만 읽는다."""
        name = "workspace/" + row["uri"]
        if name in files:
            if files[name] != model.archived(row):
                codec.fail("복원 대상의 등록 원문 해시가 다릅니다.", "E_HASH")
            visited.add(name)
            return archive.read(name) if read else None
        if by_uri.get(row["uri"]) != row:
            codec.fail("복원 색인의 원문 참조가 파일 및 누락 목록 양쪽에 없습니다.", "E_HASH")
        expected_omissions.add(row["uri"])
        return None

    docs, _ = model.validate_index(index, plan, load)
    if index["unavailable_parents"] != model.unavailable_parents(docs):
        codec.fail("묶음에 보존한 상위 개정의 누락 목록이 다릅니다.", "E_HASH")
    model.assets(docs, index["commands"], load)
    if visited != files.keys() or expected_omissions != by_uri.keys():
        codec.fail("복원 묶음에 등록 원문 폐쇄 밖의 자료가 있습니다.", "E_HASH")
    return index


@contextmanager
def read_verified(raw):
    """! @brief 구조와 데이터의 정합성이 검증된 활성 복원 묶음만 연다."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ARTIFACT_BYTES:
        codec.fail("복원 묶음 크기는 1 B~8 MiB입니다.", "E_RESOURCE")
    checks = []

    def verify(archive, plan):
        """! @brief ZIP 파일 무결성을 확인한 다음 복원할 상태 값을 검증한다."""
        checks.append(_validate_archive_contents(archive, plan))

    with codec.read_archive(BytesIO(raw), validate_plan=model.manifest, verify_metadata=verify) as (archive, plan):
        yield archive, plan, checks[0]


def _details(service, raw, plan, index):
    """! @brief 목적지와 파일 바이트를 이후 적용에 고정하는 검토 자료다."""
    archive_hash = sha256(raw).hexdigest()
    saved = next(key for key, row in index["project"]["revisions"].items() if row == index["project"]["saved"])
    workspace = str(service.workspace.resolve())
    return {"profile": model.PROFILE, "target_workspace": workspace, "project_id": plan["project_id"], "path": plan["project_path"],
            "revision_id": plan["revision_id"], "saved_revision": saved, "content_hash": plan["content_hash"],
            "archive_sha256": archive_hash, "review_hash": canonical_hash([archive_hash, workspace, plan["project_path"]]),
            "files": len(plan["files"]) - 1, "commands": len(index["commands"]), "snapshots": len(index["snapshots"]),
            "missing_count": len(index["omitted"]), "unavailable_parent_count": len(index["unavailable_parents"]),
            "scope": deepcopy(index["scope"])}


def _normalized(path):
    return normalize("NFC", path).casefold()


def _destination(service, state, details, index):
    """! @brief 다른 프로젝트 및 파일을 보존하고 같은 미완료 복원만 재개한다."""
    identity, path, archive_hash = (details[key] for key in ("project_id", "path", "archive_sha256"))
    receipts = state.get("archive_restores", {})
    previous = receipts.get(archive_hash)
    if previous is not None and previous["status"] == "restored":
        return previous
    if identity in state["projects"] or any(_normalized(old) == _normalized(path) for old in state["paths"]):
        codec.fail("같은 ID 또는 경로의 프로젝트가 이미 있습니다.", "E_CONFLICT")
    for key, entry in receipts.items():
        if key != archive_hash and (entry["project_id"] == identity or _normalized(entry["path"]) == _normalized(path)):
            codec.fail("같은 경로에 다른 묶음의 복원 기록이 있습니다.", "E_CONFLICT")
    if (len(state["projects"]) >= MAX_PROJECTS or len(state["snapshots"]) + len(index["snapshots"]) > MAX_SNAPSHOTS
            or len(state["commands"]) + len(index["commands"]) > model.COMMAND_LIMIT):
        codec.fail("새 작업 영역의 프로젝트 또는 스냅샷 보존 상한입니다.", "E_RESOURCE")
    if (state["commands"].keys() & index["commands"].keys() or state["snapshots"].keys() & index["snapshots"].keys()):
        codec.fail("다른 프로젝트가 사용 중인 명령 또는 스냅샷 식별자가 있습니다.", "E_CONFLICT")
    folder = service.journal._safe_path(path)
    if previous is None and folder.parent.exists() and any(_normalized(item.name) == _normalized(folder.name)
                                                            for item in folder.parent.iterdir()):
        codec.fail("이미 있는 비등록 경로를 복원 대상으로 사용하지 않습니다.", "E_CONFLICT")
    if previous is None and len(receipts) >= MAX_RECEIPTS:
        codec.fail("복원 기록 보존 상한에 도달했습니다.", "E_RESOURCE")
    return previous


def preview_restore(service, raw):
    """! @brief 새 workspace를 변경하지 않고 원본과 복원 위치를 검토한다."""
    with read_verified(raw) as (_, plan, index):
        details = _details(service, raw, plan, index)
        _destination(service, service.journal.read(), details, index)
        return {**details, "omitted": deepcopy(index["omitted"])}


def reserve_state(service, state, details, index):
    """! @brief 복원 중단 뒤 같은 원본만 새 경로의 미게시 파일에 접근할 수 있게 한다."""
    previous = _destination(service, state, details, index)
    if previous is not None:
        return deepcopy(previous)
    archive_hash, identity, path = (details[key] for key in ("archive_sha256", "project_id", "path"))
    intent = {**details, "status": "reserved"}
    state.setdefault("archive_restores", {})[archive_hash] = intent
    staged = _merged(state, identity, path, index)
    if len(canonical_bytes(staged)) > MAX_STATE_BYTES:
        codec.fail("복원을 등록할 journal의 여유 공간이 부족합니다.", "E_RESOURCE")
    return intent


def publish_state(service, state, raw, archive, plan, index, details):
    """! @brief 모든 실제 파일이 일치한 뒤 단일 journal commit으로 활성화한다."""
    intent = _destination(service, state, details, index)
    if intent is None:
        codec.fail("복원 대상으로 확정한 검토부터 접수해야 합니다.", "E_CONFLICT")
    if intent["status"] == "restored":
        return deepcopy(intent)
    archive_hash, identity, path = (details[key] for key in ("archive_sha256", "project_id", "path"))
    staged = _merged(state, identity, path, index)
    result = {**details, "status": "restored", "omitted": deepcopy(index["omitted"])}
    staged["archive_restores"][archive_hash] = result
    state_bytes = len(canonical_bytes(staged))
    if state_bytes > MAX_STATE_BYTES:
        codec.fail("현재 상태에 복원 기록을 추가할 공간이 부족합니다.", "E_RESOURCE")
    service.journal._check_space(len(raw) + state_bytes)
    with TemporaryDirectory(prefix=".tracewave-restore-", dir=service.workspace) as folder:
        temp = Path(folder) / "blob"
        for row in plan["files"]:
            if row["uri"] == model.INDEX_FILE:
                continue
            item = {**row, "uri": row["uri"].removeprefix("workspace/")}
            target = service.journal._safe_path(item["uri"])
            if target.exists():
                service.journal.verify_file(item)
            elif item["bytes"] == 0:
                service.journal.put_immutable(item["uri"], b"")
            else:
                temp.write_bytes(archive.read(row["uri"]))
                sealed = service.journal.seal_file(item["uri"], temp, expected_sha256=item["sha256"],
                                                   expected_bytes=item["bytes"])
                if sealed != item:
                    codec.fail("복원한 원문의 소유 경로 또는 해시가 달라졌습니다.", "E_HASH")
    state.update(staged)
    return deepcopy(result)


@contextmanager
def verified_review(service, raw, review_hash):
    """! @brief 검토한 묶음과 받는 작업 영역이 그대로인지 대조한다."""
    digest(review_hash, "review_hash")
    with read_verified(raw) as (archive, plan, index):
        details = _details(service, raw, plan, index)
        if details["review_hash"] != review_hash:
            codec.fail("검토한 복원 묶음과 실제 바이트가 다릅니다.", "E_CONFLICT")
        yield archive, plan, index, details


def restore(service, raw, review_hash):
    """! @brief 명시 적용과 같은 묶음의 재시도만 허용하며 worker 작업을 접수하지 않는다."""
    with verified_review(service, raw, review_hash) as (archive, plan, index, details):
        previous = service.journal.transaction(lambda state: reserve_state(service, state, details, index))
        if previous["status"] == "restored":
            return previous
        return service.journal.transaction(lambda state: publish_state(service, state, raw, archive, plan, index, details))


def _merged(state, identity, path, index):
    """! @brief 활성화할 사용자의 데이터만 추가하고 이전 작업 요청과 환경은 가져오지 않는다."""
    staged = state.copy()
    for collection, values in (("projects", {identity: index["project"]}), ("paths", {path: identity}),
                               ("commands", index["commands"]), ("snapshots", index["snapshots"]),
                               ("archive_restores", {})):
        staged[collection] = {**state[collection], **deepcopy(values)}
    return staged
