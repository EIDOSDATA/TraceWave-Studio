"""! @brief 인계 ZIP의 목록, 소유 범위와 실제 바이트를 작은 버퍼로 검증한다."""

from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import PurePosixPath
import stat
import unicodedata
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo

from rfad.application import handoff_plot
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import _fields, _path, _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.network_library import digest
from rfad.storage.sealed_files import CHUNK_BYTES, MAX_FILE_BYTES, validate_reference


PROFILE = "rfad.project-handoff/0.1"
MAX_FILES = 512
MAX_PACKAGE_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ZIP_BYTES = MAX_PACKAGE_BYTES + MAX_MANIFEST_BYTES + 1024 * 1024
MANIFEST_NAME = "manifest.json"
META_FILES = {"project-index.json", "report.json", "report.md"}


def fail(message, code="E_SCHEMA"):
    """! @brief 인계 원문, 계약, 상한 위반을 구조화된 오류로 반환한다."""
    raise ProjectError(code, message)


def entry_path(name):
    """! @brief 경로를 고쳐 쓰지 않으며 Windows와 POSIX에서 같은 상대경로만 받는다."""
    if type(name) is not str or not 1 <= len(name) <= 640 or any(ord(char) < 32 or char in '\\:<>"|?*' for char in name):
        fail("인계 파일 이름에는 안전한 상대경로만 사용할 수 있습니다.")
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or path.as_posix() != name or any(part in (".", "..") for part in path.parts):
        fail("인계 파일의 절대경로, 부모 이동 또는 비정규 경로를 사용할 수 없습니다.")
    reserved = {"con", "prn", "aux", "nul", "conin$", "conout$", *(f"com{n}" for n in "123456789¹²³"), *(f"lpt{n}" for n in "123456789¹²³")}
    if any(len(part) > 255 or part.endswith((".", " ")) or part.split(".", 1)[0].rstrip(" ").casefold() in reserved for part in path.parts):
        fail("인계 파일 경로가 Windows 이름 계약을 벗어났습니다.")
    return path


def validate_paths(names):
    """! @brief 대소문자와 유니코드 정규화가 같은 이름 및 파일/폴더 충돌을 차단한다."""
    keys, directories = set(), set()
    for name in names:
        parts = tuple(unicodedata.normalize("NFC", part).casefold() for part in entry_path(name).parts)
        parents = {parts[:index] for index in range(1, len(parts))}
        if parts in keys or parts in directories or parents & keys:
            fail("인계 파일 목록에 중복 이름 또는 파일과 폴더 충돌이 있습니다.", "E_CONFLICT")
        keys.add(parts)
        directories.update(parents)


def manifest(value):
    """! @brief 선택 프로젝트의 상대 원본, manifest 상한 및 미포함 조건을 확인한다."""
    _fields(value, {"schema", "project_id", "project_path", "revision_id", "snapshot_id", "content_hash", "files", "limitations"})
    if value["schema"] != PROFILE:
        fail("지원하지 않는 인계 파일 버전입니다.", "E_VERSION")
    for key in ("project_id", "revision_id", "snapshot_id"):
        _uuid(value[key])
    digest(value["content_hash"], "content_hash")
    return validate_members(value, META_FILES, optional={handoff_plot.FILE_NAME})


def validate_members(value, metadata, *, optional=frozenset()):
    """! @brief 두 인계 프로파일의 소유 경로, 파일 목록과 상한을 공통으로 확인한다."""
    project = _path(value["project_path"])
    files = value["files"]
    if type(files) is not list or not len(metadata) <= len(files) <= MAX_FILES:
        fail("인계 파일 개수가 지원 범위를 벗어났습니다.", "E_RESOURCE")
    paths, total = [], 0
    for item in files:
        _fields(item, {"uri", "bytes", "sha256"})
        validate_reference(item)
        name = item["uri"]
        entry_path(name)
        if name not in metadata and name not in optional and not name.startswith("workspace/" + project + "/"):
            fail("선택 프로젝트에 속하지 않는 파일이 인계 목록에 있습니다.", "E_CONFLICT")
        paths.append(name)
        total += item["bytes"]
    validate_paths([MANIFEST_NAME, *paths])
    if sorted(paths) != paths or not metadata <= set(paths) or total > MAX_PACKAGE_BYTES:
        fail("인계 파일 순서, 필수 메타데이터 또는 총 크기가 계약과 다릅니다.", "E_RESOURCE")
    limits = value["limitations"]
    if type(limits) is not list or len(limits) > 32 or any(type(line) is not str or not 1 <= len(line) <= 512 for line in limits):
        fail("인계 자료의 제한은 32개 이내의 명시 문장입니다.")
    if len(canonical_bytes(value)) > MAX_MANIFEST_BYTES:
        fail("인계 manifest의 크기 상한을 초과했습니다.", "E_RESOURCE")
    return value


def _transfer(incoming, reference, outgoing=None):
    """! @brief 선언 크기와 파일 해시를 확인하면서 1 MiB 단위로 복제한다."""
    count = 0
    digest_value = hashlib.sha256()
    while block := incoming.read(CHUNK_BYTES):
        count += len(block)
        if count > reference["bytes"]:
            fail("인계 파일이 선언한 길이를 초과했습니다.", "E_HASH")
        digest_value.update(block)
        if outgoing is not None:
            outgoing.write(block)
    if count != reference["bytes"] or digest_value.hexdigest() != reference["sha256"]:
        fail("인계 파일의 실제 길이 또는 SHA256이 다릅니다.", "E_HASH")


def _entry(name):
    """! @brief 플랫폼 시간과 접근 권한을 포함하지 않은 결정적 일반 파일 항목이다."""
    entry = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = (stat.S_IFREG | 0o644) << 16
    entry.compress_type = ZIP_STORED
    return entry


def write_archive(stream, plan, source, *, validate_plan=manifest):
    """! @brief 호출부가 선택한 봉인 원문을 실제 hash와 대조해 ZIP 스트림을 작성한다."""
    verified = validate_plan(plan)
    with ZipFile(stream, "w", allowZip64=False) as archive:
        archive.writestr(_entry(MANIFEST_NAME), canonical_bytes(verified))
        for reference in verified["files"]:
            with source(reference["uri"]) as original, archive.open(_entry(reference["uri"]), "w") as outgoing:
                _transfer(original, reference, outgoing)


def read_canonical(archive, name, limit):
    """! @brief 메타데이터는 선언 상한 안에서만 읽고 원래 정규 JSON과 일치시킨다."""
    item = archive.getinfo(name)
    if not 0 < item.file_size <= limit:
        fail("인계 메타데이터가 지원 크기를 벗어났습니다.", "E_RESOURCE")
    raw = archive.read(item)
    parsed = json.loads(raw)
    if canonical_bytes(parsed) != raw or type(parsed) is not dict:
        fail("인계 메타데이터의 정규 바이트가 다릅니다.", "E_HASH")
    return parsed


def _verify_design(archive, plan):
    """! @brief 목록 자체가 일치해도 다른 스냅샷이나 보고서를 같은 원본으로 해석하지 않는다."""
    index = read_canonical(archive, "project-index.json", MAX_MANIFEST_BYTES)
    _fields(index, {"schema", "snapshot", "project_path", "view_only", "active_restore_supported"})
    if (index["schema"] != "rfad.handoff-index/0.1" or index["project_path"] != plan["project_path"]
            or index["view_only"] is not True or index["active_restore_supported"] is not False):
        fail("인계 고정 입력과 읽기 전용 범위가 다릅니다.", "E_CONFLICT")
    snapshot = index["snapshot"]
    report = read_canonical(archive, "report.json", 8 * 1024 * 1024)
    if handoff_plot.FILE_NAME in archive.namelist():
        graph = handoff_plot.render(report)
        entry = archive.getinfo(handoff_plot.FILE_NAME)
        if graph is None or entry.file_size != len(graph) or archive.read(entry) != graph:
            fail("인계 그래프가 보고서의 고정 S11 표본과 다릅니다.", "E_HASH")
    for key in ("project_id", "revision_id", "snapshot_id", "content_hash"):
        if snapshot[key] != plan[key] or report[key] != plan[key]:
            fail("인계 스냅샷과 보고서가 같은 고정 입력을 가리키지 않습니다.", "E_HASH")
    original = snapshot["artifact"]
    validate_reference(original)
    name = "workspace/" + original["uri"]
    expected = {**original, "uri": name}
    if expected not in plan["files"]:
        fail("인계 스냅샷의 봉인 파일이 파일 목록 또는 원본 해시와 다릅니다.", "E_HASH")
    design = read_canonical(archive, name, 512 * 1024)
    if (design["project_id"] != plan["project_id"] or design["revision_id"] != plan["revision_id"]
            or canonical_hash(design) != plan["content_hash"]):
        fail("인계 설계 원문이 해당 프로젝트 개정과 다릅니다.", "E_HASH")


@contextmanager
def read_archive(stream, *, validate_plan=manifest, verify_metadata=_verify_design):
    """! @brief 모든 항목을 검증한 뒤만 읽기 전용 ZIP/manifest를 호출부에 노출한다."""
    stream.seek(0, 2)
    if not 0 < stream.tell() <= MAX_ZIP_BYTES:
        fail("인계 ZIP의 전체 크기가 지원 범위를 벗어났습니다.", "E_RESOURCE")
    with ExitStack() as stack:
        try:
            archive = stack.enter_context(ZipFile(stream, "r", allowZip64=False))
            entries = archive.infolist()
            if not 1 <= len(entries) <= MAX_FILES + 1:
                fail("인계 ZIP 항목 수 상한을 초과했습니다.", "E_RESOURCE")
            validate_paths([item.orig_filename for item in entries])
            for item in entries:
                mode = (item.external_attr >> 16) & 0xffff
                file_type = stat.S_IFMT(mode)
                if (item.filename != item.orig_filename or item.is_dir() or item.flag_bits & 1
                        or item.compress_type != ZIP_STORED or item.compress_size != item.file_size
                        or file_type not in (0, stat.S_IFREG) or item.external_attr & 0x410
                        or not 0 <= item.file_size <= MAX_FILE_BYTES):
                    fail("인계 ZIP에는 지원하는 일반 파일 항목만 사용할 수 있습니다.")
            entry = archive.getinfo(MANIFEST_NAME)
            if not 0 < entry.file_size <= MAX_MANIFEST_BYTES:
                fail("인계 manifest의 크기가 지원 범위를 벗어났습니다.", "E_RESOURCE")
            raw = archive.read(entry)
            plan = validate_plan(json.loads(raw))
            if canonical_bytes(plan) != raw:
                fail("인계 manifest의 실제 정규 바이트가 다릅니다.", "E_HASH")
            if set(archive.namelist()) != {MANIFEST_NAME, *(row["uri"] for row in plan["files"])}:
                fail("ZIP 항목과 인계 manifest의 파일 목록이 다릅니다.", "E_HASH")
            for reference in plan["files"]:
                item = archive.getinfo(reference["uri"])
                if item.file_size != reference["bytes"]:
                    fail("인계 manifest와 ZIP 항목의 길이가 다릅니다.", "E_HASH")
                with archive.open(item) as incoming:
                    _transfer(incoming, reference)
            verify_metadata(archive, plan)
        except (BadZipFile, EOFError, KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError, NotImplementedError) as error:
            raise ProjectError("E_HASH", "인계 ZIP의 파일 구조 또는 manifest를 확인할 수 없습니다.") from error
        yield archive, plan
