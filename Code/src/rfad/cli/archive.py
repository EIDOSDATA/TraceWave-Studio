"""! @brief 단일 writer로 기존 프로젝트를 내보내고 검토한 묶음을 복원한다."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from types import SimpleNamespace

from rfad.application import project_archive
from rfad.application.project_repository import ProjectRepository
from rfad.domain.errors import ProjectError
from rfad.storage.journal import Journal, MAX_ARTIFACT_BYTES, new_workspace_state


def _read(path):
    """! @brief 유한 크기의 사용자가 선택한 원본을 한 번 읽는다."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_ARTIFACT_BYTES + 1)
    if not 0 < len(raw) <= MAX_ARTIFACT_BYTES:
        raise ProjectError("E_RESOURCE", "복원 묶음은 8 MiB 이내의 파일입니다.")
    return raw


def _publish(path, workspace, raw):
    """! @brief 작업 영역 밖의 새 파일에 전송 바이트를 게시한다."""
    if not path.name.lower().endswith(".rfad.zip"):
        raise ProjectError("E_SCHEMA", "목적지 이름 끝에 .rfad.zip을 지정하십시오.")
    parent = path.parent.resolve(strict=True)
    if parent.is_relative_to(workspace.resolve(strict=True)):
        raise ProjectError("E_CONFLICT", "작업 영역 밖의 새 파일을 목적지로 선택하십시오.")
    target = parent / path.name
    temporary = None
    try:
        with NamedTemporaryFile(mode="xb", prefix=".tracewave-archive-", suffix=".tmp", dir=parent, delete=False) as out:
            temporary = Path(out.name)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise ProjectError("E_CONFLICT", "기존 인계 파일을 덮어쓸 수 없습니다.") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"path": str(target), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def _parser():
    """! @brief 내보내기와 복원의 각 검토/적용을 별도 명령으로 정의한다."""
    parser = argparse.ArgumentParser(prog="rfad archive")
    operations = parser.add_subparsers(dest="operation", required=True)
    for name in ("review-export", "export", "review-restore", "restore"):
        action = operations.add_parser(name)
        action.add_argument("--workspace", required=True, type=Path)
        if name in ("review-export", "export"):
            action.add_argument("--project", required=True)
            action.add_argument("--revision", required=True)
            action.add_argument("--include-sources", action="store_true",
                                help="공유 권한을 확인한 작업 영역의 등록 원문을 포함합니다.")
        if name != "review-export":
            action.add_argument("--file", required=True, type=Path)
        if name in ("export", "restore"):
            action.add_argument("--review-hash", required=True)
    return parser


def main(argv=None):
    """! @brief GUI 또는 worker를 시작하지 않고 같은 저장소와 복원 계약만 사용한다."""
    options = _parser().parse_args(argv)
    try:
        workspace = options.workspace.absolute()
        if options.operation in ("review-export", "export") and not (workspace / "current.json").is_file():
            raise ProjectError("E_CONFLICT", "내보낼 기존 작업 영역을 선택하십시오.")
        supplied = _read(options.file) if options.operation in ("review-restore", "restore") else None
        with Journal(workspace, new_workspace_state()) as journal:
            if journal.read().get("schema_version") != "rfad.workspace/0.1":
                raise ProjectError("E_VERSION", "지원하지 않는 작업 영역 버전입니다.")
            service = SimpleNamespace(workspace=workspace, journal=journal, repository=ProjectRepository(workspace, journal))
            if options.operation == "review-export":
                reviewed = project_archive.prepare(service, options.project, options.revision, options.include_sources)
                result = {key: reviewed[key] for key in ("profile", "review_hash", "project_id", "revision_id",
                                                          "zip_bytes", "missing_count", "omitted")}
            elif options.operation == "export":
                raw = project_archive.build(service, options.project, options.revision, options.include_sources, options.review_hash)
                result = _publish(options.file, workspace, raw)
            elif options.operation == "review-restore":
                result = project_archive.preview_restore(service, supplied)
            else:
                result = project_archive.restore(service, supplied, options.review_hash)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ProjectError, OSError, ValueError, RecursionError) as error:
        print(f"{getattr(error, 'code', 'E_SCHEMA')}: {error}", file=sys.stderr)
        return 1
    return 0
