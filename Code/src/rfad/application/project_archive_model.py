"""! @brief 편집 가능한 보존 묶음의 명령, 개정, 스냅샷과 원문 참조를 검증한다."""

from copy import deepcopy
import json
import math

from rfad.application import handoff_archive as codec
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import MAX_DOCUMENT_BYTES, MAX_HISTORY, MAX_SNAPSHOTS, _fields, _path, _uuid
from rfad.domain.measurement import registry as measurement_registry
from rfad.domain.network_library import digest, library
from rfad.domain.project import validate_project
from rfad.storage.sealed_files import validate_reference


PROFILE = "rfad.project-archive/0.1"
INDEX_FILE = "restore-index.json"
INDEX_LIMIT = 4 * 1024 * 1024
COMMAND_LIMIT = 2048
SCOPE = {"project_revisions": "preserved", "active_workspace_identity": "original",
         "sessions_and_jobs": "omitted", "external_worker_results": "omitted",
         "execution_on_restore": False, "fabrication_and_measurement_acceptance": "not_established"}
LIMITATIONS = [
    "현재 개정과 저장 기준점, 명령 이력, 고정 스냅샷 및 등록 원문을 보존합니다.",
    "작업/전송/요청 영수증, 실행 환경과 해석/출력 작업 기록은 묶음 범위 밖입니다.",
    "미확보 파일과 다른 저장 영역의 등록 원문은 누락 상태를 보존합니다. 복원만으로 계산하지 않습니다.",
]
ARTIFACT_FIELDS = {"uri", "bytes", "sha256"}


def manifest(value):
    """! @brief 활성 복원 프로파일을 읽기 전용 보고서 묶음과 구분한다."""
    if type(value) is not dict or value.get("schema") != PROFILE:
        codec.fail("편집 복원용 TraceWave 묶음을 선택하십시오.", "E_VERSION")
    _fields(value, {"schema", "project_id", "project_path", "revision_id", "content_hash", "files", "limitations"})
    _uuid(value["project_id"])
    _uuid(value["revision_id"])
    digest(value["content_hash"], "content_hash")
    if value["limitations"] != LIMITATIONS:
        codec.fail("복원 묶음의 범위 표기가 다릅니다.")
    return codec.validate_members(value, {INDEX_FILE})


def document_from(raw):
    """! @brief 자산을 읽기 전에 문서 검증과 정규 바이트를 검사한다."""
    if not 0 < len(raw) <= MAX_DOCUMENT_BYTES:
        codec.fail(f"복원할 설계 개정이 {MAX_DOCUMENT_BYTES} bytes 한도를 초과했습니다.", "E_RESOURCE")
    result = json.loads(raw)
    validate_project(result)
    if canonical_bytes(result) != raw:
        codec.fail("복원 개정의 정규 바이트가 다릅니다.", "E_HASH")
    return result


def reference(value):
    """! @brief 묶음은 원래 참조에서 파일 게시에 필요한 세 항목만 사용한다."""
    validate_reference(value)
    codec.entry_path(value["uri"])
    return {key: value[key] for key in ARTIFACT_FIELDS}


def archived(value):
    """! @brief workspace 상대경로를 ZIP 네임스페이스로 옮긴다."""
    return {**value, "uri": "workspace/" + value["uri"]}


def _revision_path(path, identity):
    return f"{path}/revisions/{identity}/project.json"


def validate_index(index, plan, read):
    """! @brief 원래 workspace ID, 경로, 현재/저장 개정과 실제 봉인 파일을 대조한다."""
    _fields(index, {"schema", "project", "commands", "snapshots", "omitted", "unavailable_parents", "scope"})
    if index["schema"] != PROFILE or canonical_bytes(index["scope"]) != canonical_bytes(SCOPE):
        codec.fail("복원 대상의 이력이나 실행 범위가 다릅니다.", "E_VERSION")
    project_id, path = plan["project_id"], plan["project_path"]
    project = _fields(index["project"], {"path", "current", "saved", "revisions", "history"})
    if _path(project["path"]) != path:
        codec.fail("복원 프로젝트의 소유 경로가 다릅니다.", "E_CONFLICT")
    revisions = project["revisions"]
    if type(revisions) is not dict or not 1 <= len(revisions) <= codec.MAX_FILES - 1:
        codec.fail("복원할 개정 수의 지원 범위를 초과했습니다.", "E_RESOURCE")
    documents, required = {}, {}

    def require(value, uri):
        """! @brief 승인한 소유 경로의 정확한 봉인 참조만 필수 원문으로 등록한다."""
        item = reference(value)
        if item["uri"] != uri or uri in required:
            codec.fail("복원 색인의 필수 원문 경로가 중복되거나 다릅니다.", "E_HASH")
        required[uri] = item
        raw = read(item)
        if raw is None:
            codec.fail("복원에 필요한 설계 또는 스냅샷 원문이 없습니다.", "E_MISSING_ARTIFACT")
        return document_from(raw)

    for identity, value in revisions.items():
        _uuid(identity)
        doc = require(value, _revision_path(path, identity))
        if doc["project_id"] != project_id or doc["revision_id"] != identity:
            codec.fail("봉인 개정의 프로젝트 또는 개정 식별자가 다릅니다.", "E_HASH")
        documents[identity] = doc
    head = plan["revision_id"]
    if (head not in documents or revisions[head] != project["current"] or project["saved"] not in revisions.values()
            or canonical_hash(documents[head]) != plan["content_hash"]):
        codec.fail("복원 대상의 현재/저장 개정이 봉인 원본과 다릅니다.", "E_HASH")

    commands = index["commands"]
    if type(commands) is not dict or len(commands) > COMMAND_LIMIT:
        codec.fail("복원 명령 수의 지원 범위를 초과했습니다.", "E_RESOURCE")
    history = _fields(project["history"], {"undo", "redo", "head_revision"})
    linked = set()
    for kind in ("undo", "redo"):
        values = history[kind]
        if type(values) is not list or len(values) > MAX_HISTORY:
            codec.fail("실행 취소/다시 실행의 보존 수를 초과했습니다.", "E_RESOURCE")
        for identity in values:
            _uuid(identity)
            if identity not in commands or identity in linked:
                codec.fail("실행 취소/다시 실행에서 중복되거나 빠진 명령이 있습니다.", "E_HASH")
            linked.add(identity)
    if history["head_revision"] != head:
        codec.fail("실행 취소 이력 head와 현재 개정이 다릅니다.", "E_HASH")
    for identity, command in commands.items():
        _uuid(identity)
        _fields(command, {"project_id", "old_revision", "new_revision", "previous_artifact", "command", "inverse_command"},
                set(command) if type(command) is dict else None)
        _uuid(command["old_revision"])
        _uuid(command["new_revision"])
        if (command.get("project_id") != project_id or command.get("old_revision") not in revisions
                or command.get("new_revision") not in revisions
                or command.get("previous_artifact") != revisions[command["old_revision"]]):
            codec.fail("복원 명령의 소유자 또는 개정 근거가 다릅니다.", "E_HASH")
        for key in ("command", "inverse_command"):
            payload = _fields(command[key], {"type", "payload"}, {"command_id"})
            if type(payload["type"]) is not str or type(payload["payload"]) is not dict:
                codec.fail("복원 명령의 일반 데이터 형식이 다릅니다.")
    snapshots = index["snapshots"]
    if type(snapshots) is not dict or len(snapshots) > MAX_SNAPSHOTS:
        codec.fail("복원 스냅샷 수의 지원 범위를 초과했습니다.", "E_RESOURCE")
    for identity, row in snapshots.items():
        _uuid(identity)
        _fields(row, {"snapshot_id", "project_id", "revision_id", "schema_version", "canonical_version", "content_hash",
                      "sealed_at", "description", "artifact", "validation_state"})
        revision = row["revision_id"]
        if (row["snapshot_id"] != identity or row["project_id"] != project_id or revision not in documents
                or row["canonical_version"] != "rfad.canonical/1.0" or row["schema_version"] != documents[revision]["schema_version"]
                or type(row["sealed_at"]) not in (int, float) or not math.isfinite(row["sealed_at"]) or row["sealed_at"] < 0
                or type(row["description"]) is not str or len(row["description"]) > 1024):
            codec.fail("복원 스냅샷의 소유자/개정 또는 정규화 계약이 다릅니다.", "E_HASH")
        doc = require(row["artifact"], f"{path}/snapshots/{revision}/{identity}/project.json")
        if doc != documents[revision] or canonical_hash(doc) != row["content_hash"]:
            codec.fail("복원 스냅샷의 실제 설계가 봉인 개정과 다릅니다.", "E_HASH")
    return documents, required


def unavailable_parents(documents):
    """! @brief 과거 원본에 이미 없던 상위 개정을 새 원본으로 채우지 않고 기록한다."""
    return [{"revision_id": identity, "parent_revision_id": parent}
            for identity in sorted(documents) for parent in documents[identity]["parent_revision_ids"]
            if parent not in documents]


def iter_references(value):
    """! @brief 등록 원문 블록 안의 형식화된 파일 참조만 찾는다."""
    if type(value) is dict:
        if ARTIFACT_FIELDS <= value.keys():
            yield reference(value)
        else:
            for child in value.values():
                yield from iter_references(child)
    elif type(value) is list:
        for child in value:
            yield from iter_references(child)


def assets(documents, commands, retain):
    """! @brief 라이브러리, PCB 수입, 측정 원문과 등록 계산 출처의 파일 폐쇄를 구한다."""
    visited = set()
    for doc in documents.values():
        known = library(doc)
        pcb = doc.get("pcb", {}).get("imports", [])
        measured = measurement_registry(doc)
        for value in (known, pcb, measured):
            for item in iter_references(value):
                retain(item)
        for family in ("records", "alignments", "comparisons"):
            for row in measured[family]:
                key = row["artifact"]["uri"]
                if key in visited:
                    continue
                visited.add(key)
                raw = retain(reference(row["artifact"]), read=True)
                if raw is not None:
                    for item in iter_references(json.loads(raw)):
                        retain(item)
    # @brief 명령 DTO 전체와 독립된 등록 계산 원문 및 사본 매핑만 따라간다.
    for row in commands.values():
        for key in ("host_calculation", "source_artifact_copies"):
            for item in iter_references(row.get(key)):
                retain(item)


def make_index(state, project_id):
    """! @brief 단일 프로젝트가 소유한 durable 상태를 현재 transaction에서 고정한다."""
    return {"schema": PROFILE, "project": deepcopy(state["projects"][project_id]),
            "commands": {identity: deepcopy(row) for identity, row in state["commands"].items()
                         if row["project_id"] == project_id},
            "snapshots": {identity: deepcopy(row) for identity, row in state["snapshots"].items()
                          if row["project_id"] == project_id},
            "omitted": [], "unavailable_parents": [], "scope": deepcopy(SCOPE)}
