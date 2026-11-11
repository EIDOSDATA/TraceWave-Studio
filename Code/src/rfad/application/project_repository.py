"""! @brief 불변 프로젝트 문서의 검증과 저장 참조 접근을 담당한다."""

import json
from pathlib import Path

from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import MAX_DOCUMENT_BYTES, _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project
from rfad.storage.journal import Journal


class ProjectRepository:
    """! @brief journal이 소유한 원본 바이트를 검증하고 revision 파일을 봉인한다."""

    def __init__(self, workspace: Path, journal: Journal, *, max_document_bytes: int = MAX_DOCUMENT_BYTES):
        """! @brief 저장 경로와 예산만 주입하며 작업/화면 상태를 소유하지 않는다."""
        self.workspace = workspace
        self.journal = journal
        self.max_document_bytes = max_document_bytes

    def read(self, reference: dict) -> tuple[bytes, dict]:
        """! @brief 실제 소비할 바이트와 정규 문서를 함께 반환한다."""
        raw = self.journal.read_artifact(reference)
        try:
            document = json.loads(raw.decode("utf-8"))
            validate_project(document)
            if canonical_bytes(document) != raw:
                raise ProjectError("E_HASH", "저장된 문서의 정규 바이트가 다릅니다.")
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ProjectError("E_HASH", "저장된 프로젝트를 해석할 수 없습니다.") from error
        return raw, document

    def load(self, project: dict) -> dict:
        """! @brief 현재 revision을 같은 정규 바이트 검사로 읽는다."""
        return self.read(project["current"])[1]

    def store(self, path: str, document: dict) -> dict:
        """! @brief 새 revision을 독립 파일로 기록하고 게시할 참조를 돌려준다."""
        validate_project(document)
        payload = canonical_bytes(document)
        if len(payload) > self.max_document_bytes:
            raise ProjectError("E_RESOURCE", "초기 profile의 프로젝트 크기 32 KiB를 초과했습니다.")
        return self.journal.put_immutable(f"{path}/revisions/{document['revision_id']}/project.json", payload)

    @staticmethod
    def project(state: dict, context: dict) -> dict:
        """! @brief 명시한 프로젝트의 영속 상태를 조회한다."""
        _fields(context, {"project_id"})
        project_id = _uuid(context["project_id"])
        if project_id not in state["projects"]:
            raise ProjectError("E_SCHEMA", "등록되지 않은 프로젝트입니다.")
        return state["projects"][project_id]

    def saved_revision(self, project: dict) -> str:
        """! @brief 저장 기준점 파일의 무결성을 확인한다."""
        return self.load({"current": project["saved"]})["revision_id"]
