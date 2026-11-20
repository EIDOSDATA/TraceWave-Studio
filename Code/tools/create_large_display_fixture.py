"""! @brief 100만 삼각형의 표시 전용 F2 비교 fixture를 새 작업 영역에 기록한다."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID

SIZE = 500
COLUMNS = SIZE + 1


def _identity(value):
    """! @brief 실행과 바디 대응을 반복 실행에서 고정한다."""
    return str(UUID(int=value))


def _body(stream, index):
    """! @brief 두 격자 바디를 각 행의 작은 배치만 메모리에 두고 기록한다."""
    identity = {"id": _identity(10 + index), "source_entity_ids": [_identity(20 + index)],
                "layer_id": _identity(30 + index), "role": "dielectric" if index == 0 else "conductor"}
    stream.write(json.dumps(identity, separators=(",", ":"))[:-1] + ',"vertices":[')
    for row in range(COLUMNS):
        if row:
            stream.write(",")
        y = (row + index * SIZE) / 1024
        stream.write(",".join(f"[{column / 1024},{y},{index / 16}]" for column in range(COLUMNS)))
    stream.write('],"triangles":[')
    for row in range(SIZE):
        if row:
            stream.write(",")
        start = row * COLUMNS
        stream.write(",".join(
            f"[{first},{first + 1},{first + COLUMNS}],[{first + 1},{first + COLUMNS + 1},{first + COLUMNS}]"
            for first in range(start, start + SIZE)))
    stream.write("]}")


def write_fixture(directory):
    """! @brief 실제 CAD 전송과 같은 단일 파일, 스냅샷/실행/해시 결합을 제공한다."""
    directory.mkdir()
    snapshot = {"snapshot_id": _identity(1), "revision_id": _identity(2),
                "content_hash": hashlib.sha256(b"TraceWave flat two-body display fixture").hexdigest()}
    run = _identity(3)
    mesh = directory / "mesh.json"
    header = {"schema": "rfad.display-mesh/0.2", "snapshot": snapshot, "run_id": run, "unit": "mm",
              "purpose": "display_only", "linear_deflection_mm": 0.05, "angular_deflection_rad": 0.15}
    with mesh.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(header, separators=(",", ":"))[:-1] + ',"bodies":[')
        _body(stream, 0)
        stream.write(",")
        _body(stream, 1)
        stream.write("]}\n")
    with mesh.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    artifact = {"uri": "mesh.json", "sha256": digest, "bytes": mesh.stat().st_size,
                "snapshot_id": snapshot["snapshot_id"], "run_id": run, "role": "display_mesh"}
    result = {"snapshot": snapshot, "artifact": artifact, "triangles": 4 * SIZE**2,
              "vertices": 2 * COLUMNS**2, "source": "synthetic-display-only"}
    (directory / "fixture.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    """! @brief 기존 작업 영역을 덮지 않고 새 fixture와 원본 SHA256을 생성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(write_fixture(args.directory), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
