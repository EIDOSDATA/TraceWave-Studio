"""! @brief 메타데이터 상한과 분리하여 봉인한 큰 worker 파일을 유한 버퍼로 검증/복제한다."""

import hashlib
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from rfad.domain.errors import ProjectError


MAX_FILE_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


def validate_reference(reference):
    """! @brief 원시 파일도 크기/hash를 명시하며 기존 64 MiB 파일 상한을 유지한다."""
    if (type(reference) is not dict or not {"uri", "bytes", "sha256"} <= reference.keys()
            or type(reference["bytes"]) is not int or not 0 <= reference["bytes"] <= MAX_FILE_BYTES
            or type(reference["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None):
        raise ProjectError("E_HASH", "봉인 파일의 참조/크기/hash가 유효하지 않습니다.")


def _transfer(source, reference, outgoing=None):
    """! @brief 동일하게 연 파일의 유형/길이/SHA256을 검사하고 한 번에 1 MiB만 소비한다."""
    digest, count = hashlib.sha256(), 0
    try:
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ProjectError("E_HASH", "봉인 파일은 링크가 아닌 일반 파일이어야 합니다.")
        with source.open("rb") as incoming:
            info = os.fstat(incoming.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != reference["bytes"]:
                raise ProjectError("E_HASH", "봉인 파일의 유형 또는 실제 길이가 다릅니다.")
            while block := incoming.read(CHUNK_BYTES):
                count += len(block)
                if count > reference["bytes"]:
                    raise ProjectError("E_HASH", "봉인 파일이 선언한 길이를 초과했습니다.")
                digest.update(block)
                if outgoing is not None:
                    outgoing.write(block)
    except OSError as error:
        raise ProjectError("E_HASH", "봉인 파일을 스트리밍 검증할 수 없습니다.") from error
    if count != reference["bytes"] or digest.hexdigest() != reference["sha256"]:
        raise ProjectError("E_HASH", "봉인 파일의 실제 길이 또는 SHA256이 다릅니다.")


def verify(source, reference):
    """! @brief 파일을 메모리에 반환하지 않고 봉인 전체를 검증한다."""
    validate_reference(reference)
    _transfer(Path(source), reference)


def copy(source, destination, reference):
    """! @brief 검증이 끝난 새 복사본만 게시하며 기존 대상과 원본을 덮어쓰지 않는다."""
    validate_reference(reference)
    destination = Path(destination)
    temporary = destination.with_name(destination.name + "." + str(uuid4()) + ".partial")
    try:
        with temporary.open("xb") as outgoing:
            _transfer(Path(source), reference, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        os.link(temporary, destination)
    except OSError as error:
        raise ProjectError("E_DISK", "봉인 파일을 새 staging에 복제하지 못했습니다.") from error
    finally:
        if temporary.exists():
            temporary.unlink()
