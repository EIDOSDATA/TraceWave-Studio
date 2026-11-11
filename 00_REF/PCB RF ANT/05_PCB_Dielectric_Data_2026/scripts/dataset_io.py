"""! @brief 정규 관측 분할 자료를 수정하지 않고 읽고 식별자를 검증한다."""

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator


BASE = Path(__file__).resolve().parents[1]
INDEX = BASE / "data/observations/index.json"


def reject_constant(value: str) -> None:
    """! @brief JSON 표준에 없는 NaN과 무한대 토큰을 거부한다."""
    raise ValueError(f"Non-finite JSON constant: {value}")


def load_json(path: Path) -> Any:
    """! @brief JSON의 원래 타입과 null을 보존하여 읽는다."""
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream, parse_constant=reject_constant)


def package_path(relative: str, base: Path = BASE) -> Path:
    """! @brief 패키지 상대 경로가 실제 자료 폴더 밖으로 나가지 않도록 검사한다."""
    base = base.resolve()
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive:
        raise ValueError(f"Absolute package path is not allowed: {relative}")
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as error:
        raise ValueError(f"Path escapes the package: {relative}") from error
    return resolved


def sha256(path: Path) -> str:
    """! @brief 대용량 원문을 한 번에 올리지 않고 바이트 해시를 계산한다."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(records: Iterable[dict[str, Any]]) -> str:
    """! @brief 원 관측 ID 순서와 원 JSON 타입을 보존한 정규 해시를 계산한다."""
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["record_id"]):
        encoded = json.dumps(
            record, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        digest.update((encoded + "\n").encode("utf-8"))
    return digest.hexdigest()


def iter_records(publisher: str | None = None, base: Path = BASE) -> Iterator[dict[str, Any]]:
    """! @brief 공개 주체가 일치하는 분할만 읽고 해시와 중복 및 건수를 검증한다.

    @param publisher 대소문자를 구분하지 않는 공개 주체 부분 문자열이다.
    @param base 패키지 루트다. 기본값은 이 도구가 포함된 패키지다.
    @return 원래 필드와 타입을 가진 관측을 반환한다. 끝까지 소비해야 해시 검증이 완료된다.
    """
    base = base.resolve()
    index = load_json(base / "data/observations/index.json")
    if index.get("schema") != "rfad.reference.observations/1":
        raise ValueError("Unsupported observation index schema")
    selected = publisher.casefold() if publisher else None
    seen_ids = set()
    seen_paths = set()
    total = 0
    for partition in index["partitions"]:
        if selected and selected not in partition["publisher"].casefold():
            continue
        path = package_path(partition["path"], base)
        if path in seen_paths:
            raise ValueError(f"Duplicate partition: {partition['path']}")
        seen_paths.add(path)
        digest = hashlib.sha256()
        byte_count = 0
        row_count = 0
        with path.open("rb") as stream:
            for line_number, line in enumerate(stream, start=1):
                digest.update(line)
                byte_count += len(line)
                record = json.loads(line.decode("utf-8-sig"), parse_constant=reject_constant)
                if not isinstance(record, dict):
                    raise ValueError(f"Observation is not an object: {path}:{line_number}")
                record_id = record.get("record_id")
                if not isinstance(record_id, str) or not record_id:
                    raise ValueError(f"Missing record_id: {path}:{line_number}")
                if record_id in seen_ids:
                    raise ValueError(f"Duplicate record_id: {record_id}")
                if record.get("manufacturer") != partition["publisher"]:
                    raise ValueError(f"Publisher does not match its partition: {record_id}")
                seen_ids.add(record_id)
                row_count += 1
                total += 1
                yield record
        if row_count != partition["records"]:
            raise ValueError(f"Partition row count mismatch: {partition['path']}")
        if byte_count != partition["bytes"] or digest.hexdigest() != partition["sha256"]:
            raise ValueError(f"Partition bytes or SHA-256 mismatch: {partition['path']}")
    if selected is None and total != index["record_count"]:
        raise ValueError("Total observation count mismatch")
