"""! @brief 고정 B0 보존 묶음을 검증하고 별도의 작업 사본을 두 개 만든다."""

import argparse
from hashlib import file_digest, sha256
from io import BytesIO
import json
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import tempfile
import zipfile


WORKSPACE = "workspace/B0-workspace.zip"
WORKSPACE_HASHES = "workspace/B0-workspace-sha256.json"
PROTOCOL = ("protocol/B0-public-api.json", "protocol/B0-mcp.json")


def check_bytes(raw, pin, name):
    """! @brief 고정된 크기 및 SHA256을 모두 검증한다."""
    if len(raw) != pin["bytes"] or sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError(f"B0 고정값이 다릅니다. {name}")


def member_index(archive):
    """! @brief Windows의 정규 상대 경로로만 ZIP 멤버를 인덱싱한다."""
    indexed = {}
    folded = set()
    for member in archive.infolist():
        raw_name = member.orig_filename.replace("\\", "/")
        if raw_name == "./":
            continue
        raw_name = raw_name.removeprefix("./")
        name = raw_name.removesuffix("/")
        parts = name.split("/")
        if (not name or re.search(r'[\x00-\x1f:*?"<>|]', name)
                or any(part in ("", ".", "..") or part.endswith((" ", ".")) or PureWindowsPath(part).is_reserved()
                       for part in parts)
                or stat.S_ISLNK(member.external_attr >> 16)):
            raise ValueError(f"B0 ZIP 경로가 유효하지 않습니다. {raw_name!r}")
        key = name.casefold()
        if key in folded:
            raise ValueError(f"B0 ZIP 경로가 중복됩니다. {name}")
        folded.add(key)
        indexed[name] = (member, raw_name.endswith("/"))
    return indexed


def unpack_workspace(data, expected_files, target):
    """! @brief 파일 수를 검증한 뒤 새 경로에서만 작업 영역을 복원한다."""
    with zipfile.ZipFile(BytesIO(data)) as workspace:
        entries = member_index(workspace)
        count = sum(not directory for _, directory in entries.values())
        if count != expected_files:
            raise ValueError(f"B0 작업 영역 파일 수가 다릅니다. {count}개")
        target.mkdir()
        for name, (member, directory) in entries.items():
            path = target.joinpath(*name.split("/"))
            if directory:
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with workspace.open(member) as source, path.open("xb") as destination:
                    shutil.copyfileobj(source, destination)


def tree_hash(root):
    """! @brief 복원한 파일을 상대 경로별로 해시해 두 사본을 대조한다."""
    hashes = {}
    for file in sorted(root.rglob("*")):
        if file.is_file():
            with file.open("rb") as stream:
                hashes[file.relative_to(root).as_posix()] = file_digest(stream, "sha256").hexdigest()
    return hashes


def restore(manifest, source, output):
    """! @brief 모든 고정 멤버 검증에 성공한 뒤 새 출력에 복원 결과를 게시한다."""
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    with source.open("rb") as stream:
        raw = stream.read(manifest["proof_archive"]["bytes"] + 1)
    check_bytes(raw, manifest["proof_archive"], source.name)
    with zipfile.ZipFile(BytesIO(raw)) as proof:
        members = member_index(proof)
        payload = {}
        wanted = {WORKSPACE, WORKSPACE_HASHES, *PROTOCOL}
        for key, pin in manifest["archive_members"].items():
            member, directory = members.get(key, (None, True))
            if member is None or directory or member.file_size != pin["bytes"]:
                raise ValueError(f"B0 고정 멤버가 없습니다. {key}")
            data = proof.read(member)
            check_bytes(data, pin, key)
            if key in wanted:
                payload[key] = data

    with tempfile.TemporaryDirectory(prefix=".tracewave-b0-", dir=output.parent) as staging:
        published = Path(staging) / "prepared"
        published.mkdir()
        original = published / "B0"
        unpack_workspace(payload[WORKSPACE], manifest["workspace_file_count"], original)
        hashes = tree_hash(original)
        shutil.copytree(original, published / "main")
        if tree_hash(published / "main") != hashes:
            raise ValueError("두 B0 작업 사본의 파일 해시가 다릅니다.")
        for key in (WORKSPACE_HASHES, *PROTOCOL):
            target = published / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload[key])
        details = {"archive_sha256": manifest["proof_archive"]["sha256"],
                   "workspace_file_count": len(hashes), "copies": ["B0", "main"], "workspace_sha256": hashes}
        (published / "restore-verification.json").write_text(
            json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise FileExistsError(output)
        published.rename(output)


def main():
    """! @brief 431 목록, 실제 보존 ZIP 및 존재하지 않는 출력 경로를 받는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    output = args.output.parent.resolve(strict=True) / args.output.name
    restore(manifest, args.archive.resolve(strict=True), output)
    print(f"검증한 작업 파일 {manifest['workspace_file_count']}개를 B0와 main 작업 사본에 복원했습니다.")


if __name__ == "__main__":
    main()
