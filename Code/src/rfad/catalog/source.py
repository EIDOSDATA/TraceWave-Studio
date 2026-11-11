"""! @brief 원문 패키지를 변경하지 않고 경로, 해시와 JSON 타입을 검증한다."""

import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterator

from rfad.catalog.models import CatalogError


MAX_JSON_BYTES = 128 * 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024 * 1024
POSITIVE_FIELDS = {"dk", "frequency_ghz", "df_frequency_ghz", "thickness_mm"}
NONNEGATIVE_FIELDS = {
    "dk_min", "dk_max", "dk_tolerance", "df", "df_min", "df_max", "df_tolerance",
    "frequency_min_ghz", "frequency_max_ghz", "thickness_min_mm", "thickness_max_mm",
    "thickness_tolerance_mm", "resin_content_pct",
}
RANGE_FIELDS = (
    ("dk_min", "dk_max"), ("df_min", "df_max"),
    ("frequency_min_ghz", "frequency_max_ghz"), ("thickness_min_mm", "thickness_max_mm"),
)


def _pairs(items: list[tuple[str, Any]]) -> dict:
    """! @brief 중복 JSON 키를 뒤의 값으로 조용히 덮어쓰지 않는다."""
    result = {}
    for key, value in items:
        if key in result:
            raise CatalogError("E_SCHEMA", "JSON 객체에 중복 키가 있습니다.", details={"key": key})
        result[key] = value
    return result


def _constant(value: str) -> None:
    """! @brief JSON 표준 밖의 NaN과 Infinity를 거부한다."""
    raise CatalogError("E_SCHEMA", "비유한 JSON 수치는 지원하지 않습니다.", details={"value": value})


def finite_json(value: Any) -> None:
    """! @brief 중첩 원문을 포함하여 비유한 부동소수 값을 거부한다."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CatalogError("E_SCHEMA", "원문에 비유한 수치가 있습니다.")
    elif isinstance(value, dict):
        for child in value.values():
            finite_json(child)
    elif isinstance(value, list):
        for child in value:
            finite_json(child)


def decode_json(raw: bytes | str, label: str = "JSON") -> Any:
    """! @brief 타입과 미제공 키를 유지하면서 UTF-8 JSON을 읽는다."""
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        finite_json(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CatalogError("E_SCHEMA", "원문 JSON을 읽을 수 없습니다.", details={"path": label}) from error


def file_digest(path: Path) -> str:
    """! @brief PDF와 HTML도 실행하거나 적재하지 않고 바이트 해시만 계산한다."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_observation(record: dict, definitions: dict, package: "PackageSource") -> None:
    """! @brief 선언된 타입과 범위를 검사하되 누락값이나 원시 음수 근거는 보정하지 않는다."""
    required = ("record_id", "source_id", "manufacturer", "product", "dataset_role")
    for field in required:
        if not isinstance(record.get(field), str) or not record[field]:
            raise CatalogError("E_SCHEMA", "관측의 필수 식별자가 없습니다.", details={"field": field})
    if record["dataset_role"] not in ("material_published_parameter", "fabricator_published_parameter"):
        raise CatalogError("E_SCHEMA", "지원하지 않는 공개 자료 역할입니다.")
    for field, value in record.items():
        if field not in definitions:
            raise CatalogError("E_SCHEMA", "관측에 선언되지 않은 필드가 있습니다.", details={"field": field})
        types = definitions[field]["observed_types"].split(",")
        if value is not None and type(value).__name__ not in types:
            raise CatalogError("E_SCHEMA", "관측의 원래 타입이 스키마와 다릅니다.", details={"field": field})
    for field in POSITIVE_FIELDS | NONNEGATIVE_FIELDS:
        value = record.get(field)
        if value is None:
            continue
        if type(value) not in (int, float):
            raise CatalogError("E_SCHEMA", "물성 수치는 명시적 숫자여야 합니다.", details={"field": field})
        if value < 0 or (field in POSITIVE_FIELDS and value == 0):
            raise CatalogError("E_RANGE", "정규 물성 수치가 허용 범위를 벗어났습니다.", details={"field": field})
    for field, upper in (("df", 1), ("df_min", 1), ("df_max", 1), ("resin_content_pct", 100)):
        if record.get(field) is not None and record[field] > upper:
            raise CatalogError("E_RANGE", "정규 물성 수치가 상한을 초과했습니다.", details={"field": field})
    for low, high in RANGE_FIELDS:
        if record.get(low) is not None and record.get(high) is not None and record[low] > record[high]:
            raise CatalogError("E_RANGE", "원문 수치 범위의 순서가 반대입니다.", details={"field": low})
    for field in ("source_file", "source_manifest_file"):
        if record.get(field):
            package.verify_file(record[field])


class PackageSource:
    """! @brief 패키지 안의 검증된 파일을 읽고 동일 경로의 해시 검사를 재사용한다."""

    def __init__(self, root: Path):
        """! @brief 루트와 파일 명세를 읽되 소비하지 않는 원문은 파싱하지 않는다."""
        self.root = Path(root).resolve()
        self.source_root = self.root
        self._verified = {}
        self._verified_paths = {}
        manifest_path = self.path("catalog/file_manifest.json")
        raw = self._bounded_bytes(manifest_path)
        manifest = decode_json(raw, "catalog/file_manifest.json")
        if not isinstance(manifest, dict) or manifest.get("schema") != "rfad.reference.file-manifest/1":
            raise CatalogError("E_VERSION", "지원하지 않는 원문 파일 명세입니다.")
        self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        self.files = {}
        entries = manifest.get("files")
        if not isinstance(entries, list):
            raise CatalogError("E_SCHEMA", "파일 명세에는 파일 배열이 필요합니다.")
        for item in entries:
            if not isinstance(item, dict):
                raise CatalogError("E_SCHEMA", "파일 명세 행은 객체여야 합니다.")
            relative = item.get("path")
            self.path(relative, must_exist=False)
            if relative in self.files:
                raise CatalogError("E_SCHEMA", "파일 명세 경로가 중복됩니다.", details={"path": relative})
            if type(item.get("bytes")) is not int or item["bytes"] < 0 or not self._hash(item.get("sha256")):
                raise CatalogError("E_SCHEMA", "파일 명세의 크기 또는 해시가 잘못되었습니다.")
            self.files[relative] = item
        if not self.files:
            raise CatalogError("E_SCHEMA", "파일 명세가 비어 있습니다.")

    @staticmethod
    def _hash(value: Any) -> bool:
        """! @brief SHA-256의 명시적인 소문자 16진 표현을 확인한다."""
        return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)

    @staticmethod
    def _bounded_bytes(path: Path) -> bytes:
        """! @brief 메타데이터 JSON의 한 번 읽기 크기를 제한한다."""
        with path.open("rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise CatalogError("E_RESOURCE", "JSON 메타데이터 크기 상한을 초과했습니다.", details={"path": str(path)})
        return raw

    def path(self, relative: str, *, must_exist: bool = True) -> Path:
        """! @brief 절대 경로, 상위 이동과 심볼릭 링크를 통한 패키지 이탈을 거부한다."""
        if not isinstance(relative, str) or not relative or "\x00" in relative:
            raise CatalogError("E_PATH", "원문 상대 경로가 필요합니다.")
        normalized = relative.replace("\\", "/")
        parts = normalized.split("/")
        if PureWindowsPath(relative).drive or PurePosixPath(normalized).is_absolute() or any(part in ("", ".", "..") for part in parts):
            raise CatalogError("E_PATH", "원문 경로는 패키지 내부의 상대 경로여야 합니다.", details={"path": relative})
        path = (self.root / normalized).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise CatalogError("E_PATH", "원문 경로가 패키지 밖을 가리킵니다.", details={"path": relative})
        if must_exist and not path.is_file():
            raise CatalogError("E_PATH", "보관된 원문 파일을 찾을 수 없습니다.", details={"path": relative})
        return path

    def verify_file(self, relative: str) -> Path:
        """! @brief 명세의 실제 바이트 수와 해시를 확인하고 수정되지 않은 파일만 캐시한다."""
        if isinstance(relative, str) and relative in self._verified:
            return self._verified_paths[relative]
        path = self.path(relative)
        entry = self.files.get(relative)
        if entry is None:
            raise CatalogError("E_HASH", "파일이 패키지 명세에 없습니다.", details={"path": relative})
        state = path.stat()
        signature = (state.st_size, state.st_mtime_ns, state.st_ino)
        if state.st_size != entry["bytes"] or file_digest(path) != entry["sha256"]:
            raise CatalogError("E_HASH", "원문 파일의 크기 또는 SHA-256이 일치하지 않습니다.", details={"path": relative})
        after = path.stat()
        if signature != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise CatalogError("E_CONFLICT", "검증 중 원문 파일이 변경되었습니다.", details={"path": relative})
        self._verified[relative] = signature
        self._verified_paths[relative] = path
        return path

    def file_sha256(self, relative: str) -> str:
        """! @brief 실제 바이트를 확인한 파일의 원문 해시를 반환한다."""
        self.verify_file(relative)
        return self.files[relative]["sha256"]

    def read_json(self, relative: str) -> Any:
        """! @brief 검증한 바이트 자체를 파싱하여 원문 변경 경쟁도 검출한다."""
        path = self.verify_file(relative)
        raw = self._bounded_bytes(path)
        if hashlib.sha256(raw).hexdigest() != self.files[relative]["sha256"]:
            raise CatalogError("E_HASH", "읽는 중 원문 JSON이 변경되었습니다.", details={"path": relative})
        return decode_json(raw, relative)

    def records(self, partition: dict) -> Iterator[dict]:
        """! @brief 한 관측씩 읽으면서 명세와 분할의 해시 및 행수를 함께 검증한다."""
        relative = partition.get("path")
        path = self.verify_file(relative)
        entry = self.files[relative]
        if partition.get("sha256") != entry["sha256"] or partition.get("bytes") != entry["bytes"]:
            raise CatalogError("E_HASH", "관측 분할과 파일 명세가 서로 다릅니다.", details={"path": relative})
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as handle:
            while True:
                raw = handle.readline(MAX_RECORD_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_RECORD_BYTES:
                    raise CatalogError("E_RESOURCE", "관측 한 행의 크기 상한을 초과했습니다.")
                digest.update(raw)
                record = decode_json(raw, relative)
                if not isinstance(record, dict) or record.get("manufacturer") != partition.get("publisher"):
                    raise CatalogError("E_SCHEMA", "관측의 공개 업체와 분할이 일치하지 않습니다.")
                count += 1
                yield record
        if digest.hexdigest() != entry["sha256"] or count != partition.get("records"):
            raise CatalogError("E_HASH", "관측 분할의 실제 해시 또는 행수가 일치하지 않습니다.")

    def verify_unchanged(self) -> None:
        """! @brief DB 발행 직전에 이미 소비한 원문 파일의 변경 여부를 확인한다."""
        if file_digest(self.path("catalog/file_manifest.json")) != self.manifest_sha256:
            raise CatalogError("E_CONFLICT", "구축 중 원문 파일 명세가 변경되었습니다.")
        for relative in tuple(self._verified):
            path = self.path(relative)
            state = path.stat()
            signature = (state.st_size, state.st_mtime_ns, state.st_ino)
            if path != self._verified_paths[relative] or signature != self._verified[relative]:
                raise CatalogError("E_CONFLICT", "구축 중 소비한 원문 파일이 변경되었습니다.", details={"path": relative})
