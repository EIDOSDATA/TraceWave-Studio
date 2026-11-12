"""! @brief 제품 외부의 G031 원본 ZIP/member와 카드의 제한된 원문 사본을 대조한다."""

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZipFile

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))

from rfad.templates.g031 import evidence


MAX_SOURCE_BYTES = 64 * 1024 * 1024


def checked_bytes(archive, name, expected):
    """! @brief 압축 해제 크기를 먼저 제한하고 실제 bytes의 SHA256을 대조한다."""
    info = archive.getinfo(name)
    if info.file_size > MAX_SOURCE_BYTES:
        raise ValueError("원문 member의 제한 크기를 초과했습니다: " + name)
    raw = archive.read(info)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("원문 member 해시가 다릅니다: " + name)
    return raw


def verify(repository: Path) -> dict:
    """! @brief 외부 원문을 변경하지 않고 중첩 archive, 좌표 줄과 PDF 식별자를 검사한다."""
    source = evidence()
    path = repository / source["archive_path"]
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("원문 archive의 제한 크기를 초과했습니다.")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source["archive_sha256"]:
        raise ValueError("G031 원문 archive 해시가 다릅니다.")
    with ZipFile(BytesIO(raw)) as outer:
        inner = checked_bytes(outer, source["inner_member"], source["inner_sha256"])
    members = []
    with ZipFile(BytesIO(inner)) as archive:
        for member in source["members"]:
            data = checked_bytes(archive, member["path"], member["sha256"])
            if member["spans"]:
                lines = data.decode("ascii").splitlines()
                for span in member["spans"]:
                    start = span["start"] - 1
                    if lines[start:start + len(span["lines"])] != span["lines"]:
                        raise ValueError("원문 Gerber 줄이 카드 사본과 다릅니다: " + member["path"])
            members.append({"path": member["path"], "sha256": member["sha256"], "bytes": len(data),
                            "gerber_spans_checked": len(member["spans"]), "pdf_pages_referenced": member["pdf_pages"]})
    return {"schema": "rfad.literature-source-review/0.1", "geometry_id": "G031",
            "archive_sha256": source["archive_sha256"], "inner_sha256": source["inner_sha256"],
            "members": members, "source_identity_checked": True, "whole_board_reproduced": False,
            "physics_verified": False, "measurement_verified": False}


def main():
    """! @brief 원문 경로를 명시할 수 있는 읽기 전용 개발 검증 CLI다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=CODE.parent)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(args.repository)
    raw = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(raw, encoding="utf-8")
    print(raw)


if __name__ == "__main__":
    main()
