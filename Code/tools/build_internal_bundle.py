"""! @brief 고정 Git 소스와 Windows 실행 파일을 재현 가능한 내부 검증 ZIP으로 묶는다."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile
import zlib

if __package__:
    from .internal_bundle_inputs import BIN, FILE_LIMIT, NOTICE, PROFILE, TOTAL_LIMIT, git_sources, native_files, notices
else:
    from internal_bundle_inputs import BIN, FILE_LIMIT, NOTICE, PROFILE, TOTAL_LIMIT, git_sources, native_files, notices


SCHEMA = "rfad.internal-bundle/0.2"
MANIFEST = "bundle-manifest.json"
COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
DOS_BASE = (1980, 1, 1, 0, 0, 0)


def _safe_name(name):
    """! @brief 상대 경로와 Windows에서 동일 이름으로 해석될 수 있는 요소를 제한한다."""
    if (type(name) is not str or len(name) > 260 or re.search(r'[\x00-\x1f\\:*?"<>|]', name) or
            any(not part or part in (".", "..") or part.endswith((".", " ")) or
                part.split(".", 1)[0].casefold() in RESERVED for part in name.split("/"))):
        raise ValueError(f"묶음의 경로가 유효하지 않습니다. {name!r}")
    return name


def _json(value):
    """! @brief 입력 내용만 반영하는 고정 JSON 바이트를 작성한다."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write(archive, name, data):
    """! @brief 빌드 시각, 파일시각, 소유자와 작업 위치를 ZIP에 기록하지 않는다."""
    entry = zipfile.ZipInfo(_safe_name(name), DOS_BASE)
    entry.create_system = 3
    entry.external_attr = (stat.S_IFREG | 0o644) << 16
    archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def verify(archive_path):
    """! @brief 중복/상한/멤버 집합, manifest, 스트리밍 SHA256을 새 출력 없이 검증한다."""
    archive_path = Path(archive_path)
    if not 0 < archive_path.stat().st_size <= TOTAL_LIMIT:
        raise ValueError("묶음 파일 크기가 허용 범위를 벗어났습니다.")
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if not 2 <= len(members) <= 5016 or sum(item.file_size for item in members) > TOTAL_LIMIT:
            raise ValueError("묶음의 멤버 수 또는 총 용량 상한을 초과했습니다.")
        paths = {}
        for item in members:
            name = _safe_name(item.filename)
            key = name.casefold()
            if (key in paths or item.is_dir() or not stat.S_ISREG(item.external_attr >> 16) or
                    item.file_size > FILE_LIMIT or item.date_time != DOS_BASE):
                raise ValueError(f"지원하지 않는 ZIP 멤버입니다. {name}")
            paths[key] = item
        manifest_info = paths.pop(MANIFEST, None)
        if manifest_info is None or manifest_info.filename != MANIFEST or manifest_info.file_size > 2 * 1024 * 1024:
            raise ValueError("유한한 내부 묶음 manifest가 필요합니다.")
        manifest = json.loads(archive.read(manifest_info))
        if (type(manifest) is not dict or manifest.get("schema") != SCHEMA or
                manifest.get("distribution") != "internal_validation_only" or
                type(manifest.get("source_revision")) is not str or not COMMIT.fullmatch(manifest["source_revision"]) or
                type(manifest.get("files")) is not list):
            raise ValueError("내부 묶음 manifest의 schema, 배포 또는 소스 식별이 다릅니다.")
        for row in manifest["files"]:
            if type(row) is not dict or set(row) != {"path", "bytes", "sha256"}:
                raise ValueError("명시된 manifest 멤버 형식이 필요합니다.")
            name = _safe_name(row["path"])
            item = paths.pop(name.casefold(), None)
            if (item is None or item.filename != name or type(row["bytes"]) is not int or row["bytes"] != item.file_size or
                    type(row["sha256"]) is not str or not SHA256.fullmatch(row["sha256"])):
                raise ValueError(f"manifest의 멤버 참조가 다릅니다. {name}")
            with archive.open(item) as incoming:
                digest = hashlib.file_digest(incoming, "sha256").hexdigest()
            if digest != row["sha256"]:
                raise ValueError(f"묶음 파일의 SHA256이 다릅니다. {name}")
        if paths:
            raise ValueError("manifest에 없는 파일이 묶음에 있습니다.")
    with archive_path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(archive_path), "files": len(members) - 1, "bytes": archive_path.stat().st_size,
            "source_revision": manifest["source_revision"], "sha256": digest, "status": "contents_verified"}


def build(repository, output, reference, executable, runtime, wx_archive, notice_dir, objdump):
    """! @brief 검증된 임시 묶음만 새 이름에 게시하며 기존 ZIP은 덮지 않는다."""
    repository, output = Path(repository), Path(output)
    if output.exists():
        raise FileExistsError("새 묶음 출력 경로가 필요합니다.")
    revision, sources = git_sources(repository, reference)
    profile_data = sources.get(PROFILE)
    if profile_data is None or len(profile_data) > 64 * 1024:
        raise ValueError("선택한 Git 개정에 고정 Windows 내부 묶음 profile이 필요합니다.")
    profile = json.loads(profile_data)
    if profile.get("schema") != "rfad.runtime.windows-internal-bundle/0.1":
        raise ValueError("Windows 내부 묶음 의존 profile이 다릅니다.")
    native, imports = native_files(Path(executable), Path(runtime), profile, objdump)
    files = {**sources, **native, **notices(Path(wx_archive), Path(notice_dir), profile)}
    casefolded = {name.casefold() for name in files}
    if (len(casefolded) != len(files) or MANIFEST in casefolded or
            sum(len(data) for data in files.values()) > TOTAL_LIMIT):
        raise ValueError("내부 묶음 전체 용량 또는 Windows 이름 조건이 다릅니다.")
    entries = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
               for name, data in sorted(files.items())]
    manifest = {"schema": SCHEMA, "distribution": "internal_validation_only",
                "design_baseline": "RFAD-D0-3.4", "source_revision": revision, "platform": profile["platform"],
                "release_runtime_profile": PROFILE, "native_imports": imports, "files": entries,
                "compression": {"method": "deflate", "level": 9, "zlib": zlib.ZLIB_RUNTIME_VERSION},
                "installed_application": BIN + "tracewave_gui.exe", "third_party_notices": NOTICE,
                "external_prerequisites": ["Windows 11 x64", "CPython 3.12 x64"],
                "optional_external_prerequisites": ["OCCT Python runtime", "engineering export runtime",
                    "WSL2 openEMS", "material catalog import", "pinned Python wheels by feature"],
                "turnkey_installation": False, "r1_acceptance_established": False, "physics_validated": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".tracewave-bundle-", dir=output.parent) as temp:
        pending = Path(temp) / "bundle.zip"
        with zipfile.ZipFile(pending, "x") as archive:
            for entry in entries:
                name = entry["path"]
                _write(archive, name, files[name])
            _write(archive, MANIFEST, _json(manifest))
        result = verify(pending)
        os.link(pending, output)
    return {**result, "path": str(output)}


def main():
    """! @brief Windows 개발 환경의 명시 입력을 묶거나 기존 내부 ZIP을 검사한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-ref", default="HEAD")
    parser.add_argument("--gui", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--wx-archive", type=Path)
    parser.add_argument("--notice-dir", type=Path)
    parser.add_argument("--objdump", default="objdump")
    args = parser.parse_args()
    if args.verify is not None:
        if args.output is not None:
            parser.error("--verify와 --output을 함께 사용할 수 없습니다.")
        result = verify(args.verify)
    else:
        if args.output is None or args.notice_dir is None:
            parser.error("--output과 --notice-dir이 필요합니다.")
        repository = Path(__file__).resolve().parents[2]
        executable = args.gui or repository / BIN / "tracewave_gui.exe"
        runtime = args.runtime_dir or executable.parent
        wx_archive = args.wx_archive or repository / "Code/.local/deps/wxWidgets-3.2.12.tar.bz2"
        result = build(repository, args.output, args.source_ref, executable, runtime, wx_archive, args.notice_dir, args.objdump)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
