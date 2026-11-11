"""! @brief 명령 실행과 영속 undo/redo의 개정 연결을 관리한다."""

from copy import deepcopy

from rfad.application.canonical import canonical_hash
from rfad.application.project_repository import ProjectRepository
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command


class ProjectHistory:
    """! @brief 현재 journal transaction 안에서 명령과 역명령을 하나의 변경으로 구성한다."""

    def __init__(self, repository: ProjectRepository):
        """! @brief 검증된 문서 접근을 주입하며 별도 transaction을 열지 않는다."""
        self.repository = repository

    def restore(self, state: dict, *, limit: int) -> None:
        """! @brief 과거 이력이 없을 때 프로젝트별 명령 색인으로 현재 개정의 이력만 복원한다."""
        links_by_project = {}
        missing = {key for key, project in state["projects"].items() if "history" not in project}
        if missing:
            for key, record in state["commands"].items():
                if record["project_id"] in missing:
                    links_by_project.setdefault(record["project_id"], {})[record["new_revision"]] = (key, record)
        for project_id, project in state["projects"].items():
            revision = self.repository.load(project)["revision_id"]
            if "history" in project:
                self.check_head(project, revision)
                continue
            links = links_by_project.get(project_id, {})
            current_revision = revision
            undo = []
            while revision in links and len(undo) < limit:
                key, record = links[revision]
                undo.append(key)
                revision = record["old_revision"]
            project["history"] = {"undo": list(reversed(undo)), "redo": [], "head_revision": current_revision}

    def apply(self, state: dict, context: dict, data: dict, *, limit: int, record_history: bool = True) -> dict:
        """! @brief revision, undo 근거와 영향 목록을 같은 상태 변경에 포함한다."""
        project = self.repository.project(state, context)
        command_id = data["command_id"]
        if command_id in state["commands"]:
            raise ProjectError("E_CONFLICT", "이미 사용한 command_id입니다. 원 request_key로 조회하십시오.")
        if len(state["commands"]) >= 2048:
            raise ProjectError("E_RESOURCE", "초기 명령 이력 상한에 도달했습니다.")
        old = self.repository.load(project)
        self.check_head(project, old["revision_id"])
        command = {key: data[key] for key in ("command_id", "type", "payload")}
        document, changed, invalidation, inverse = apply_command(old, command, data["expected_revision"])
        reference = self.repository.store(project["path"], document)
        project["current"] = reference
        state["commands"][command_id] = {
            "project_id": document["project_id"], "old_revision": old["revision_id"],
            "new_revision": document["revision_id"], "inverse_command": inverse,
            "command": command, "previous_artifact": deepcopy(project["revisions"][old["revision_id"]]),
        }
        migration = None
        if old["schema_version"] != document["schema_version"]:
            migration = {"from": old["schema_version"], "to": document["schema_version"], "original_revision": old["revision_id"]}
            state["commands"][command_id]["schema_migration"] = migration
        project["revisions"][document["revision_id"]] = reference
        project["history"]["head_revision"] = document["revision_id"]
        if record_history:
            history = project["history"]
            history["undo"] = [*history["undo"], command_id][-limit:]
            history["redo"] = []
        response = {
            "project_id": document["project_id"],
            "new_revision": document["revision_id"],
            "revision_hash": canonical_hash(document),
            "changed_ids": changed,
            "invalidation_set": invalidation,
            "history": self.status(project, limit=limit),
        }
        if migration is not None:
            response["schema_migration"] = deepcopy(migration)
        return response

    @staticmethod
    def check_head(project: dict, revision: str) -> None:
        """! @brief 구버전 앱 등으로 현재 개정과 이력이 어긋났으면 역명령 적용을 차단한다."""
        history = project["history"]
        if "head_revision" not in history:
            raise ProjectError(
                "E_VERSION", "이력 head가 없는 미출시 편집기 workspace입니다. 원본을 보존하고 명시적으로 이관해야 합니다.",
                details={"field_path": "history.head_revision"},
            )
        if history["head_revision"] != revision:
            raise ProjectError(
                "E_CONFLICT", "현재 개정과 명령 이력의 head가 다릅니다. 구버전 앱의 수정 여부를 확인하십시오.",
                details={"field_path": "history.head_revision"},
            )

    @staticmethod
    def status(project: dict, *, limit: int) -> dict:
        """! @brief 원본 역명령을 노출하지 않고 UI 버튼에 필요한 상태만 제공한다."""
        history = project["history"]
        return {
            "can_undo": bool(history["undo"]),
            "can_redo": bool(history["redo"]),
            "undo_count": len(history["undo"]),
            "redo_count": len(history["redo"]),
            "limit": limit,
        }

    def move(self, state: dict, context: dict, data: dict, *, limit: int, undo: bool) -> dict:
        """! @brief 과거 포인터를 복원하지 않고 검증된 역명령/원명령을 새 개정으로 게시한다."""
        project = self.repository.project(state, context)
        document = self.repository.load(project)
        self.check_head(project, document["revision_id"])
        if document["revision_id"] != data["expected_revision"]:
            raise ProjectError("E_CONFLICT", "실행 취소의 기준 개정이 현재 개정과 다릅니다.", details={"field_path": "expected_revision"})
        source, destination = ("undo", "redo") if undo else ("redo", "undo")
        history = project["history"]
        if not history[source]:
            raise ProjectError("E_CONFLICT", "실행 취소 또는 다시 실행할 명령이 없습니다.", details={"field_path": "history." + source})
        target = history[source][-1]
        record = state["commands"][target]
        if record["project_id"] != context["project_id"]:
            raise ProjectError("E_HASH", "명령 이력의 프로젝트가 다릅니다.")
        command = record["inverse_command"] if undo else record["command"]
        result = self.apply(state, context, {
            "expected_revision": data["expected_revision"],
            "command_id": data["command_id"],
            "type": command["type"],
            "payload": command["payload"],
        }, limit=limit, record_history=False)
        history[source].pop()
        history[destination].append(target)
        state["commands"][data["command_id"]]["history_action"] = {"direction": source, "target_command_id": target}
        result["history"] = self.status(project, limit=limit)
        return result
