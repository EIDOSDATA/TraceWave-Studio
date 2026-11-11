"""! @brief 카탈로그 설치 없이 프로젝트 소유 출처 사본의 구조와 해시를 검증한다."""

import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath
import re

from rfad.domain.errors import ProjectError


EVIDENCE_ENTITIES = frozenset({"observations", "sources", "native_templates", "native_components"})
MAX_EVIDENCE_BYTES = 12 * 1024


def fail(code: str, message: str, field: str) -> None:
    """! @brief 저장된 선택 자료의 오류 위치를 보존한다."""
    raise ProjectError(code, message, details={"field_path": field})


def fields(value: object, expected: set[str], field: str) -> None:
    """! @brief 알려진 계약의 누락과 추가 필드를 모두 거부한다."""
    if type(value) is not dict or set(value) != expected:
        fail("E_SCHEMA", "PCB 선택의 필수 필드 또는 지원 필드를 확인하십시오.", field)


def text(value: object, field: str, *, empty: bool = False, characters: int = 1024, byte_limit: int = 4096) -> str:
    """! @brief 원문을 자르지 않고 문자열 길이와 UTF-8을 검사한다."""
    if type(value) is not str or (not empty and not value.strip()) or "\x00" in value:
        fail("E_SCHEMA", "PCB 선택 문자열이 올바르지 않습니다.", field)
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        fail("E_SCHEMA", "PCB 선택 문자열을 UTF-8로 표현할 수 없습니다.", field)
    if len(value) > characters or size > byte_limit:
        fail("E_RESOURCE", "PCB 선택 문자열 예산을 초과했습니다. 출처를 축약하지 않습니다.", field)
    return value


def sha256(value: object, field: str) -> str:
    """! @brief 해시는 소문자 64자리 문자열로만 보존한다."""
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        fail("E_SCHEMA", "PCB 선택 SHA-256이 올바르지 않습니다.", field)
    return value


def encoded(value: object) -> str:
    """! @brief 출처 JSON은 큰 정수도 문자열 내부에서 정확하게 직렬화한다."""
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        result.encode("utf-8")
        return result
    except (ValueError, TypeError, RecursionError) as error:
        raise ProjectError("E_SCHEMA", "PCB 선택에 유한 JSON으로 표현할 수 없는 값이 있습니다.") from error


def _unique(pairs: list) -> dict:
    """! @brief 중복 JSON 키를 뒤의 값으로 덮어쓰지 않는다."""
    result = {}
    for key, value in pairs:
        if key in result:
            fail("E_SCHEMA", "출처 JSON에 중복 키가 있습니다.", "selection.evidence.raw_json")
        result[key] = value
    return result


def decode(raw: object, field: str) -> object:
    """! @brief 작은 완전 JSON 사본의 정규 표현과 깊이를 확인한다."""
    text(raw, field, characters=4096, byte_limit=8192)
    try:
        value = json.loads(raw, object_pairs_hook=_unique)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 32:
                fail("E_RESOURCE", "출처 JSON의 최대 깊이를 초과했습니다.", field)
            if type(item) is dict:
                pending.extend((child, depth + 1) for child in item.values())
            elif type(item) is list:
                pending.extend((child, depth + 1) for child in item)
        if encoded(value) != raw:
            fail("E_SCHEMA", "PCB 선택 JSON은 원문 타입을 보존한 정규 문자열이어야 합니다.", field)
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProjectError("E_SCHEMA", "PCB 선택 JSON을 읽을 수 없습니다.", details={"field_path": field}) from error


def pointer(value: object, field: str) -> str:
    """! @brief RFC 6901 포인터의 구분자와 escape만 허용한다."""
    text(value, field, empty=True, characters=1024)
    if (value and not value.startswith("/")) or re.search(r"~(?![01])", value):
        fail("E_SCHEMA", "출처의 JSON 포인터가 올바르지 않습니다.", field)
    return value


def read_pointer(value: object, location: str) -> tuple[bool, object]:
    """! @brief JSON의 미제공과 명시적인 null을 구분하여 읽는다."""
    current = value
    for raw_token in location.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if type(current) is dict and token in current:
            current = current[token]
        elif type(current) is list and re.fullmatch(r"0|[1-9][0-9]*", token) and len(token) <= 10:
            index = int(token)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _origin(value: object, entity: str, field: str) -> None:
    """! @brief 원시 적층의 파일/포인터/파일 해시를 실행 없는 위치 근거로 보존한다."""
    if entity in ("observations", "sources"):
        if value is not None:
            fail("E_SCHEMA", "정규 관측과 출처의 origin은 null이어야 합니다.", field)
        return
    fields(value, {"source_id", "path", "pointer", "sha256"}, field)
    text(value["source_id"], field + ".source_id")
    path = text(value["path"], field + ".path")
    if ("\\" in path or PurePosixPath(path).is_absolute() or PureWindowsPath(path).drive
            or any(part in ("", ".", "..") for part in path.split("/"))):
        fail("E_SCHEMA", "원시 출처 경로는 명시적인 패키지 상대 경로여야 합니다.", field + ".path")
    pointer(value["pointer"], field + ".pointer")
    sha256(value["sha256"], field + ".sha256")


def validate_evidence(values: object, catalog: dict | None) -> dict[str, tuple[dict, object]]:
    """! @brief 전체 사본과 선택 필드 사본을 구분하고 출처 ID와 해시를 대조한다."""
    if type(values) is not list or len(values) > 32:
        fail("E_RESOURCE", "PCB 선택 출처는 최대 32개 목록이어야 합니다.", "selection.evidence")
    if values and catalog is None:
        fail("E_SCHEMA", "카탈로그 개정 없는 출처 사본은 저장할 수 없습니다.", "selection.catalog")
    if len(encoded(values).encode("utf-8")) > MAX_EVIDENCE_BYTES:
        fail("E_RESOURCE", "PCB 선택 출처의 12 KiB 예산을 초과했습니다.", "selection.evidence")
    result = {}
    for number, entry in enumerate(values):
        field = f"selection.evidence[{number}]"
        fields(entry, {"id", "entity", "item_id", "scope", "pointers", "original_sha256", "snapshot_sha256", "raw_json", "origin"}, field)
        if type(entry["entity"]) is not str or entry["entity"] not in EVIDENCE_ENTITIES:
            fail("E_SCHEMA", "지원하지 않는 출처 개체입니다.", field + ".entity")
        text(entry["item_id"], field + ".item_id")
        _origin(entry["origin"], entry["entity"], field + ".origin")
        sha256(entry["original_sha256"], field + ".original_sha256")
        sha256(entry["snapshot_sha256"], field + ".snapshot_sha256")
        locations = entry["pointers"]
        if type(locations) is not list or len(locations) > 64:
            fail("E_RESOURCE", "선택 출처 포인터 목록의 상한을 초과했습니다.", field + ".pointers")
        for location in locations:
            pointer(location, field + ".pointers")
        if locations != sorted(set(locations)):
            fail("E_SCHEMA", "출처 포인터는 중복 없는 정렬 목록이어야 합니다.", field + ".pointers")
        value = decode(entry["raw_json"], field + ".raw_json")
        actual = hashlib.sha256(entry["raw_json"].encode("utf-8")).hexdigest()
        if actual != entry["snapshot_sha256"]:
            fail("E_HASH", "선택 출처 사본의 해시가 다릅니다.", field + ".snapshot_sha256")
        if entry["scope"] == "complete":
            if locations or actual != entry["original_sha256"]:
                fail("E_HASH", "전체 출처 사본의 범위 또는 원문 해시가 다릅니다.", field)
            source_key = {"observations": "record_id", "sources": "source_id"}.get(entry["entity"])
            if source_key is not None and (type(value) is not dict or value.get(source_key) != entry["item_id"]):
                fail("E_HASH", "전체 출처 사본의 원래 ID가 선택한 개체와 다릅니다.", field + ".item_id")
        elif entry["scope"] == "projection":
            fields(value, {"values", "missing"}, field + ".raw_json")
            if type(value["values"]) is not dict or type(value["missing"]) is not list:
                fail("E_SCHEMA", "선택 필드 사본의 구조가 올바르지 않습니다.", field)
            if any(type(item) is not str for item in value["missing"]):
                fail("E_SCHEMA", "미제공 필드 목록은 JSON 포인터 문자열이어야 합니다.", field)
            if (value["missing"] != sorted(set(value["missing"])) or set(value["values"]) & set(value["missing"])
                    or set(value["values"]) | set(value["missing"]) != set(locations)):
                fail("E_SCHEMA", "선택 필드 사본의 값과 미제공 목록이 포인터와 다릅니다.", field)
        else:
            fail("E_SCHEMA", "출처 사본의 범위는 complete 또는 projection이어야 합니다.", field + ".scope")
        identity_data = ["evidence", catalog["catalog_id"], entry["entity"], entry["item_id"], entry["scope"], locations, actual, entry["origin"]]
        expected = "evidence:" + hashlib.sha256(encoded(identity_data).encode("utf-8")).hexdigest()
        if entry["id"] != expected or entry["id"] in result:
            fail("E_HASH", "선택 출처의 안정 ID가 다르거나 중복됩니다.", field + ".id")
        result[entry["id"]] = (entry, value)
    return result
