"""! @brief 작은 프로젝트 파일 작업의 실행을 문서 저장소와 결합한다."""

from copy import deepcopy
from typing import Callable
from uuid import uuid4

from rfad.application.canonical import canonical_hash
from rfad.application.project_contract import MAX_PROJECTS, MAX_SNAPSHOTS, _path
from rfad.application.project_repository import ProjectRepository
from rfad.domain.design import preflight_design
from rfad.domain.errors import ProjectError
from rfad.domain.project import new_project


class ProjectOperations:
    """! @brief 불변 입력을 소비하고 현재 journal transaction에 결과 참조만 게시한다."""

    def __init__(self, repository: ProjectRepository, now: Callable[[], float]):
        """! @brief 저장소와 시각을 주입하며 worker thread를 소유하지 않는다."""
        self.repository = repository
        self.now = now

    def execute(self, state: dict, job: dict) -> dict:
        """! @brief 지원하는 파일 작업을 명시적인 실행 경로로 분배한다."""
        method, data = job["operation_method"], job["input"]
        if method == "project.open":
            return self.open(state, data)
        project = self.repository.project(state, job["context"])
        raw, document = self.repository.read(job["captured"])
        if method == "export.preview":
            return deepcopy(job["preview_result"])
        if method == "design.validate":
            return self.validate(document, data)
        if method == "project.save":
            return self.save(project, document, job["captured"])
        if method == "snapshot.create":
            return self.snapshot(state, project, document, raw, data)
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 자료 처리 작업입니다.")

    def open(self, state: dict, data: dict) -> dict:
        """! @brief 경로 중복을 거절하고 새 프로젝트 또는 등록된 문서만 연다."""
        path = _path(data["path"])
        registered = next((existing for existing in state["paths"] if existing.casefold() == path.casefold()), None)
        if data["open_mode"] == "create":
            if registered is not None or (self.repository.workspace / path).exists():
                raise ProjectError("E_CONFLICT", "기존 프로젝트 경로를 덮어쓸 수 없습니다.")
            if len(state["projects"]) >= MAX_PROJECTS:
                raise ProjectError("E_RESOURCE", "초기 프로젝트 수 상한에 도달했습니다.")
            document = new_project(data["name"])
            reference = self.repository.store(path, document)
            project = {
                "path": path,
                "current": reference,
                "saved": deepcopy(reference),
                "revisions": {document["revision_id"]: reference},
                "history": {"undo": [], "redo": [], "head_revision": document["revision_id"]},
            }
            state["projects"][document["project_id"]] = project
            state["paths"][path] = document["project_id"]
        else:
            if registered is None or registered != path:
                raise ProjectError("E_SCHEMA", "등록된 정확한 프로젝트 경로가 필요합니다.")
            project = state["projects"][state["paths"][path]]
            document = self.repository.load(project)
        return {
            "project_id": document["project_id"],
            "revision_id": document["revision_id"],
            "revision_hash": canonical_hash(document),
            "document": document,
            "saved_revision": self.repository.saved_revision(project),
            "diagnostics": [],
        }

    @staticmethod
    def validate(document: dict, data: dict) -> dict:
        """! @brief 입력 검증 결과를 물리 검증 완료와 구분하여 반환한다."""
        diagnostics = preflight_design(document, data["purpose"])
        return {
            "revision_id": document["revision_id"], "revision_hash": canonical_hash(document),
            "purpose": data["purpose"], "profile": data["profile"],
            "input_status": "blocked" if diagnostics else "valid",
            "diagnostics": diagnostics[:64], "diagnostic_count": len(diagnostics),
            "diagnostics_truncated": len(diagnostics) > 64,
            "solver_ready": False,
            "validation_scope": "input_only",
            "next_validation": {
                "em": "solver.plan", "geometry": "geometry.build", "step": "export.preview",
            }[data["purpose"]],
        }

    def save(self, project: dict, document: dict, captured: dict) -> dict:
        """! @brief 접수 이후 편집이 없을 때만 저장 기준점을 갱신한다."""
        current = self.repository.load(project)
        if current["revision_id"] != document["revision_id"]:
            raise ProjectError("E_CONFLICT", "접수 후 설계가 바뀌어 저장 기준점을 변경하지 않았습니다.")
        project["saved"] = deepcopy(captured)
        return {
            "saved_revision": document["revision_id"],
            "checksum": captured["sha256"],
            "artifact": deepcopy(captured),
        }

    def snapshot(self, state: dict, project: dict, document: dict, raw: bytes, data: dict) -> dict:
        """! @brief 접수 시점의 바이트로 독립 snapshot을 봉인한다."""
        if len(state["snapshots"]) >= MAX_SNAPSHOTS:
            raise ProjectError("E_RESOURCE", "스냅샷 보존 상한에 도달했습니다.")
        snapshot_id = str(uuid4())
        reference = self.repository.journal.put_immutable(
            f"{project['path']}/snapshots/{document['revision_id']}/{snapshot_id}/project.json", raw,
        )
        snapshot = {
            "snapshot_id": snapshot_id,
            "project_id": document["project_id"],
            "revision_id": document["revision_id"],
            "schema_version": document["schema_version"],
            "canonical_version": "rfad.canonical/1.0",
            "content_hash": canonical_hash(document),
            "sealed_at": self.now(),
            "description": data.get("description", ""),
            "artifact": reference,
            "validation_state": "not_evaluated",
        }
        state["snapshots"][snapshot_id] = snapshot
        return deepcopy(snapshot)
