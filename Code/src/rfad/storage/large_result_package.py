"""! @brief 대용량 결과 한 건과 그 출처를 유한 버퍼로 이관한다."""

import hashlib
import json
import os
import re
from struct import Struct
from uuid import UUID

from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError
from rfad.storage.indexed_result_file import regular_file
from rfad.storage.sealed_files import CHUNK_BYTES


MAGIC = b"RFADRES\x01"
HEADER_LENGTH = Struct(">I")
MAX_HEADER = 4096
HEADER_HASH_BYTES = hashlib.sha256().digest_size
MAX_OVERHEAD = len(MAGIC) + HEADER_LENGTH.size + MAX_HEADER + HEADER_HASH_BYTES


def _uuid(value):
    """! @brief 정규 UUID만 원개정 및 프로젝트 출처로 기록한다."""
    if type(value) is not str or len(value) != 36:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _validate(header, limits):
    """! @brief 가져올 자료의 크기와 최초 연결 출처를 엄격히 확인한다."""
    if type(header) is not dict or set(header) != {"kind", "name", "source_name", "origin", "payload"}:
        raise ProjectError("E_SCHEMA", "이관 파일의 결과 출처 구조가 올바르지 않습니다.")
    kind = header["kind"]
    origin, payload = header["origin"], header["payload"]
    if type(kind) is not str or kind not in limits:
        raise ProjectError("E_SCHEMA", "이관할 수 없는 결과 종류입니다.")
    if (type(origin) is not dict or set(origin) != {"project_id", "revision_id"}
            or not all(_uuid(value) for value in origin.values())):
        raise ProjectError("E_SCHEMA", "이관 파일에 원본 프로젝트와 개정 ID가 필요합니다.")
    try:
        names_ok = all(type(header[key]) is str and header[key].strip() and len(header[key].encode("utf-8")) <= 512
                       for key in ("name", "source_name"))
    except UnicodeEncodeError:
        names_ok = False
    if not names_ok:
        raise ProjectError("E_SCHEMA", "이관 파일의 결과 이름과 원본 파일명이 올바르지 않습니다.")
    if (type(payload) is not dict or set(payload) != {"bytes", "sha256"}
            or type(payload["bytes"]) is not int or not 8 <= payload["bytes"] <= limits[kind]
            or type(payload["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", payload["sha256"]) is None):
        raise ProjectError("E_HASH", "이관 파일 원문의 길이 또는 SHA256 선언이 잘못되었습니다.")


def _transfer(incoming, outgoing, payload, package_digest=None):
    """! @brief 정확한 선언 길이만 복제하며 원문 해시와 부분 해시를 함께 계산한다."""
    actual = hashlib.sha256()
    blocks = []
    remaining = payload["bytes"]
    while remaining:
        size = min(CHUNK_BYTES, remaining)
        block = incoming.read(size)
        if len(block) != size:
            raise ProjectError("E_HASH", "이관 도중 결과 원문이 잘렸습니다.")
        actual.update(block)
        if package_digest is not None:
            package_digest.update(block)
        blocks.append(hashlib.sha256(block).hexdigest())
        outgoing.write(block)
        remaining -= size
    if incoming.read(1) or actual.hexdigest() != payload["sha256"]:
        raise ProjectError("E_HASH", "이관할 결과가 선언한 길이 또는 SHA256과 다릅니다.")
    outgoing.flush()
    os.fsync(outgoing.fileno())
    return {**payload, "blocks": blocks}


def write(source, temporary, header, limits):
    """! @brief 출처가 포함된 고정 헤더와 원문을 전용 임시 파일에 기록한다."""
    _validate(header, limits)
    raw = canonical_bytes(header)
    if len(raw) > MAX_HEADER:
        raise ProjectError("E_RESOURCE", "이관 파일 머리말이 지원 크기를 초과했습니다.")
    prefix = MAGIC + HEADER_LENGTH.pack(len(raw)) + raw + hashlib.sha256(raw).digest()
    digest = hashlib.sha256(prefix)
    with regular_file(source) as (incoming, size):
        if size != header["payload"]["bytes"]:
            raise ProjectError("E_HASH", "이관할 원문의 실제 길이가 다릅니다.")
        with temporary.open("xb") as outgoing:
            outgoing.write(prefix)
            _transfer(incoming, outgoing, header["payload"], digest)
    return {"bytes": len(prefix) + size, "sha256": digest.hexdigest()}


def extract(source, temporary, expected_size, limits):
    """! @brief 전송 크기와 고정 머리말을 확인한 뒤 원문을 원래 바이트로 복원한다."""
    with regular_file(source) as (incoming, size):
        if size != expected_size:
            raise ProjectError("E_HASH", "접수한 이관 파일의 실제 길이가 달라졌습니다.")
        if incoming.read(len(MAGIC)) != MAGIC:
            raise ProjectError("E_VERSION", "지원하는 대용량 결과 이관 형식이 아닙니다.")
        length = incoming.read(HEADER_LENGTH.size)
        if len(length) != HEADER_LENGTH.size:
            raise ProjectError("E_SCHEMA", "이관 파일의 머리말 길이가 없습니다.")
        length = HEADER_LENGTH.unpack(length)[0]
        if not 1 <= length <= MAX_HEADER:
            raise ProjectError("E_RESOURCE", "이관 파일 머리말이 지원 크기를 벗어났습니다.")
        raw = incoming.read(length)
        if len(raw) != length or incoming.read(HEADER_HASH_BYTES) != hashlib.sha256(raw).digest():
            raise ProjectError("E_HASH", "이관 파일 머리말의 SHA256이 다릅니다.")
        try:
            header = json.loads(raw.decode("utf-8"))
            _validate(header, limits)
            if canonical_bytes(header) != raw:
                raise ValueError("noncanonical header")
        except (ValueError, RecursionError) as error:
            raise ProjectError("E_SCHEMA", "이관 파일의 원본 출처를 읽을 수 없습니다.") from error
        if size != MAX_OVERHEAD - MAX_HEADER + length + header["payload"]["bytes"]:
            raise ProjectError("E_HASH", "이관 파일의 길이가 머리말과 다릅니다.")
        with temporary.open("xb") as outgoing:
            index = _transfer(incoming, outgoing, header["payload"])
    return header, index
