"""! @brief 프로젝트 요청 형식과 저장 예산의 공통 계약을 정의한다."""

from pathlib import PurePosixPath
from uuid import UUID

from rfad.domain.errors import ProjectError
from rfad.domain.project import new_project

RETENTION_SECONDS = 7 * 24 * 60 * 60
from rfad.domain.resource_limits import MAX_DOCUMENT_BYTES
MAX_RECEIPTS = 2048
MAX_JOBS = 512
MAX_PROJECTS = 32
MAX_SNAPSHOTS = 1024
MAX_HISTORY = 128
COMMAND_FIELDS = {
    "project.apply_command": {"type", "payload"},
    "editor.apply": {"selection", "values"},
    "canvas.apply": {"operation", "values"},
    "project.undo": set(),
    "project.redo": set(),
}
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _uuid(value: object) -> str:
    """! @brief 정규 UUID 문자열을 검증한다."""
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise ProjectError("E_SCHEMA", "정규 UUID 문자열이 필요합니다.") from error
    return value


def _fields(value: object, required: set, optional: set | None = None) -> dict:
    """! @brief 필수키와 지원하지 않는 필드를 검사한다."""
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise ProjectError("E_SCHEMA", "필수 필드가 없거나 지원하지 않는 필드가 있습니다.")
    return value


def _path(value: object) -> str:
    """! @brief 서비스 작업 영역의 프로젝트 하위 경로만 허용한다."""
    if type(value) is not str or len(value) > 256 or "\\" in value or ":" in value:
        raise ProjectError("E_SCHEMA", "projects/ 아래의 상대 경로를 사용하십시오.")
    parts = value.split("/")
    if len(parts) != 2 or parts[0] != "projects" or parts[1] in ("", ".", ".."):
        raise ProjectError("E_SCHEMA", "프로젝트 경로는 projects/이름 형식이어야 합니다.")
    name = parts[1]
    if name.endswith((".", " ")) or any(ord(c) < 32 or c in '<>"|?*' for c in name):
        raise ProjectError("E_SCHEMA", "지원하지 않는 프로젝트 경로 문자입니다.")
    if name.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        raise ProjectError("E_SCHEMA", "예약된 경로 이름입니다.")
    return str(PurePosixPath(value))


def validate_project_request(method: str, context: dict, data: dict) -> None:
    """! @brief 접수 전에 지원 필드와 선택지를 검사한다."""
    if method == "project.open":
        _fields(context, set())
        _fields(data, {"path", "open_mode"}, {"name"})
        _path(data["path"])
        if data["open_mode"] not in {"create", "open", "recover"}:
            raise ProjectError("E_UNSUPPORTED", "현재 open/create/recover만 지원합니다.")
        if data["open_mode"] == "create":
            if "name" not in data:
                raise ProjectError("E_SCHEMA", "새 프로젝트 이름이 필요합니다.")
            new_project(data["name"])
        elif "name" in data:
            raise ProjectError("E_SCHEMA", "name은 create에서만 지정합니다.")
    elif method in COMMAND_FIELDS:
        _fields(context, {"project_id"})
        _uuid(context["project_id"])
        _fields(data, {"expected_revision", "command_id", *COMMAND_FIELDS[method]})
        _uuid(data["expected_revision"])
        _uuid(data["command_id"])
    elif method == "design.validate":
        _fields(context, {"project_id"})
        _uuid(context["project_id"])
        _fields(data, {"expected_revision", "purpose", "profile"})
        _uuid(data["expected_revision"])
        if data["purpose"] not in ("geometry", "step", "em") or data["profile"] != "rfad.design/0.1":
            raise ProjectError("E_UNSUPPORTED", "초기 설계 검증은 rfad.design/0.1의 geometry/step/em 목적을 지원합니다.")
    elif method in {"project.save", "snapshot.create"}:
        _fields(context, {"project_id"})
        _uuid(context["project_id"])
        _fields(data, {"expected_revision"}, {"target"} if method == "project.save" else {"description"})
        _uuid(data["expected_revision"])
        if "target" in data:
            _path(data["target"])
        if "description" in data and (
            type(data["description"]) is not str or len(data["description"].encode("utf-8")) > 4096
        ):
            raise ProjectError("E_SCHEMA", "스냅샷 설명은 UTF-8 4096 bytes 이내여야 합니다.")
    elif method == "job.cancel":
        _fields(context, set())
        _fields(data, {"job_id"}, {"reason"})
        _uuid(data["job_id"])
        if "reason" in data and (type(data["reason"]) is not str or len(data["reason"]) > 1024):
            raise ProjectError("E_SCHEMA", "취소 사유가 유효하지 않습니다.")
    else:
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 프로젝트 명령입니다.")
