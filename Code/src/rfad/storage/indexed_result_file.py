"""! @brief 대용량 결과의 원문과 확인한 바이트 구간을 연결한다."""

from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import io
import os
import stat

from rfad.domain.errors import ProjectError
from rfad.storage.sealed_files import CHUNK_BYTES


@contextmanager
def regular_file(path):
    """! @brief 별칭, junction, 유형이나 inode가 바뀐 원문을 거절한다."""
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or getattr(before, "st_file_attributes", 0) & 0x400):
        raise ProjectError("E_HASH", "대용량 결과는 링크가 없는 일반 파일이어야 합니다.")
    with path.open("rb") as stream:
        current = os.fstat(stream.fileno())
        if not os.path.samestat(before, current) or current.st_nlink != 1:
            raise ProjectError("E_HASH", "대용량 결과 파일이 열린 경로와 다릅니다.")
        yield stream, current.st_size


def index_file(path, limit):
    """! @brief 메모리에 한 블록만 유지하며 전체와 각 블록의 SHA256을 계산한다."""
    with regular_file(path) as (stream, size):
        if not 8 <= size <= limit:
            raise ProjectError("E_RESOURCE", "선택한 대용량 결과가 파일 크기 예산을 벗어났습니다.")
        whole = hashlib.sha256()
        blocks = []
        count = 0
        while block := stream.read(CHUNK_BYTES):
            count += len(block)
            if count > size:
                raise ProjectError("E_HASH", "가져오는 동안 파일 길이가 바뀌었습니다.")
            whole.update(block)
            blocks.append(hashlib.sha256(block).hexdigest())
        if count != size:
            raise ProjectError("E_HASH", "가져오는 동안 파일 길이가 바뀌었습니다.")
        return {"bytes": size, "sha256": whole.hexdigest(), "blocks": blocks}


class IndexedReader(io.RawIOBase):
    """! @brief HDF5가 실제로 요청한 블록만 검증하고 고정된 8 MiB 캐시를 사용한다."""

    def __init__(self, stream, size, index):
        super().__init__()
        if index["bytes"] != size or len(index["blocks"]) != (size + CHUNK_BYTES - 1) // CHUNK_BYTES:
            raise ProjectError("E_HASH", "대용량 결과의 길이와 봉인 블록 목록이 다릅니다.")
        self._stream = stream
        self._size = size
        self._blocks = index["blocks"]
        self._offset = 0
        self._cache = OrderedDict()

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._offset

    def seek(self, offset, whence=io.SEEK_SET):
        origin = {io.SEEK_SET: 0, io.SEEK_CUR: self._offset, io.SEEK_END: self._size}[whence]
        if origin + offset < 0:
            raise ValueError("negative offset")
        self._offset = origin + offset
        return self._offset

    def _block(self, index):
        """! @brief 반환 전에 원문과 블록 봉인을 대조한다."""
        if index not in self._cache:
            start = index * CHUNK_BYTES
            size = min(CHUNK_BYTES, self._size - start)
            self._stream.seek(start)
            raw = self._stream.read(size)
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != self._blocks[index]:
                raise ProjectError("E_HASH", "대용량 결과의 읽기 블록이 원본 해시와 다릅니다.")
            if len(self._cache) == 8:
                self._cache.popitem(last=False)
            self._cache[index] = raw
        self._cache.move_to_end(index)
        return self._cache[index]

    def readinto(self, buffer):
        """! @brief 임의 오프셋의 제한된 HDF5 요청을 바이트 단위로 채운다."""
        view = memoryview(buffer).cast("B")
        length = min(len(view), max(0, self._size - self._offset))
        if length > 16 * CHUNK_BYTES:
            raise ProjectError("E_RESOURCE", "HDF5 단일 읽기 요청이 16 MiB를 초과했습니다.")
        done = 0
        while done < length:
            index, within = divmod(self._offset, CHUNK_BYTES)
            raw = self._block(index)
            count = min(length - done, len(raw) - within)
            view[done:done+count] = raw[within:within+count]
            done += count
            self._offset += count
        return done

    def read(self, size=-1):
        """! @brief 크기 없는 전체 파일 읽기도 동일한 유한 경계를 적용한다."""
        remaining = max(0, self._size - self._offset)
        size = min(remaining, size) if size >= 0 else remaining
        if size > 16 * CHUNK_BYTES:
            raise ProjectError("E_RESOURCE", "HDF5 단일 읽기 요청이 16 MiB를 초과했습니다.")
        buffer = bytearray(size)
        return bytes(memoryview(buffer)[:self.readinto(buffer)])
