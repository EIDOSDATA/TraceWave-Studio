"""! @brief 하나의 current pointer로 상태와 receipt의 원자적 commit을 게시한다.

@details journal은 workspace 상태의 authority다. 미게시 commit과 artifact는
orphan으로 남을 수 있으며 자동 삭제하지 않는다. directory fsync는 POSIX에서
수행한다. Windows에서는 파일 fsync와 같은 volume의 os.replace를 사용하지만
전원 장애 durability까지 검증했다고 주장하지 않는다. 외부 actor가 실행 중
workspace 경로를 교체하는 적대적 경쟁 조건은 이 초기 profile의 지원 범위 밖이다.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import threading
from typing import Any, Callable
from uuid import UUID, uuid4

from rfad.application.canonical import CanonicalEncodingError, canonical_bytes
from rfad.domain.errors import ProjectError

MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = MAX_STATE_BYTES
MIN_DISK_RESERVE = 16 * 1024 * 1024
JOURNAL_SCHEMA = "rfad.journal/0.1"
_RESERVED = {"commits", "current.json", ".writer.lock"}
_LOCAL_LOCKS: set[str] = set()
_LOCAL_LOCK_GUARD = threading.Lock()
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _digest(payload: bytes) -> str:
    """! @brief canonical prefix 없이 실제 파일 바이트의 SHA256을 구한다."""
    return hashlib.sha256(payload).hexdigest()


def _check_path_parts(path: Path) -> None:
    """! @brief 존재하는 모든 상위 경로의 symlink와 reparse point를 거부한다."""
    for candidate in (*reversed(path.parents), path):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ProjectError("E_DISK", "저장 경로의 상태를 검사할 수 없습니다.", details={"path": str(candidate)}) from error
        if candidate.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ProjectError("E_SCHEMA", "링크 또는 reparse 경로는 저장소에서 지원하지 않습니다.", details={"path": str(candidate)})


def _strict_json(payload: bytes) -> Any:
    """! @brief journal의 비정상 JSON이나 중복 key를 손상으로 판정한다."""
    def unique(pairs):
        """! @brief 중복 key를 덮어쓰지 않는다."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(value):
        """! @brief 비유한 JSON 상수를 거부한다."""
        raise ValueError(value)

    try:
        result = json.loads(payload.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant)
        if canonical_bytes(result) != payload:
            raise ValueError("noncanonical journal payload")
        return result
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProjectError("E_HASH", "journal JSON의 형식 또는 정규 바이트가 손상되었습니다.") from error


class Journal:
    """! @brief workspace의 유일한 writer를 소유하며 불변 commit을 게시한다.

    @param root 사용자에게 지정된 workspace 폴더.
    @param initial_state 새로운 저장소의 초기 primitive JSON 상태.
    @param fault_hook 시험용 단계 콜백. after_payload/before_publish/after_publish.
    @details current.json이 없는데 commits에 파일이 있으면 pointer 분실과
    최초 미게시 commit을 구분할 수 없으므로 E_HASH로 보존한다. 초기화는
    commit이 전혀 없는 저장소에만 허용한다. close 또는 context manager로
    잠금을 해제하며 프로세스 종료 시 OS 잠금은 자동 해제된다.
    """

    def __init__(self, root: Path, initial_state: dict, fault_hook: Callable[[str], None] | None = None):
        self.root = Path(os.path.abspath(os.fspath(root)))
        self.fault_hook = fault_hook
        self._mutex = threading.RLock()
        self._closed = True
        self._in_transaction = False
        self._lock_stream = None
        self._lock_key = os.path.normcase(str(self.root))
        try:
            _check_path_parts(self.root)
            self.root.mkdir(parents=True, exist_ok=True)
            self._acquire_lock()
            self._closed = False
            if self._safe_path("current.json", internal=True).exists():
                self.read()
            else:
                commits = self._safe_path("commits", internal=True)
                if commits.exists() and any(commits.iterdir()):
                    raise ProjectError("E_HASH", "commit 자료는 있지만 current pointer가 없습니다. 원본을 보존하고 복구해야 합니다.")
                if type(initial_state) is not dict:
                    raise ProjectError("E_SCHEMA", "초기 journal 상태는 object여야 합니다.")
                self._commit(copy.deepcopy(initial_state))
        except BaseException:
            self.close()
            raise

    def _acquire_lock(self) -> None:
        """! @brief 같은 프로세스와 다른 프로세스의 중복 writer를 즉시 거부한다."""
        with _LOCAL_LOCK_GUARD:
            if self._lock_key in _LOCAL_LOCKS:
                raise ProjectError("E_CONFLICT", "이 workspace는 이미 다른 writer가 사용 중입니다.")
            _LOCAL_LOCKS.add(self._lock_key)
        try:
            lock_path = self._safe_path(".writer.lock", internal=True)
            self._lock_stream = lock_path.open("a+b")
            self._lock_stream.seek(0, os.SEEK_END)
            if self._lock_stream.tell() == 0:
                self._lock_stream.write(b"\0")
                self._lock_stream.flush()
            self._lock_stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._lock_stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if self._lock_stream is not None:
                self._lock_stream.close()
                self._lock_stream = None
            with _LOCAL_LOCK_GUARD:
                _LOCAL_LOCKS.discard(self._lock_key)
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise ProjectError("E_CONFLICT", "이 workspace는 이미 다른 writer가 잠갔습니다.") from error
            raise ProjectError("E_DISK", "workspace writer 잠금 파일을 열 수 없습니다.") from error
        except BaseException:
            if self._lock_stream is not None:
                self._lock_stream.close()
                self._lock_stream = None
            with _LOCAL_LOCK_GUARD:
                _LOCAL_LOCKS.discard(self._lock_key)
            raise

    def _ensure_open(self) -> None:
        """! @brief 닫힌 writer의 상태 접근을 거부한다."""
        if self._closed:
            raise ProjectError("E_CONFLICT", "이미 닫힌 journal입니다.")

    def _safe_path(self, relative: str, *, internal: bool = False) -> Path:
        """! @brief canonical 상대 URI와 실제 기존 경로를 함께 검사한다."""
        if type(relative) is not str or not relative or "\\" in relative or ":" in relative or "\0" in relative:
            raise ProjectError("E_SCHEMA", "저장 URI는 안전한 POSIX 상대경로여야 합니다.")
        pure = PurePosixPath(relative)
        if not pure.parts or pure.is_absolute() or pure.as_posix() != relative or any(part in (".", "..") for part in pure.parts):
            raise ProjectError("E_SCHEMA", "절대경로, 상위 이동 또는 비정규 URI를 사용할 수 없습니다.")
        if not internal and pure.parts[0] in _RESERVED:
            raise ProjectError("E_SCHEMA", "journal 내부 경로는 artifact URI로 사용할 수 없습니다.")
        for part in pure.parts:
            stem = part.split(".", 1)[0].upper()
            if part.endswith((" ", ".")) or stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
                raise ProjectError("E_SCHEMA", "이름이 플랫폼 간 안전한 파일명 규칙을 만족하지 않습니다.")
        path = self.root.joinpath(*pure.parts)
        _check_path_parts(path)
        return path

    def _check_space(self, payload_size: int) -> None:
        """! @brief 게시 전에 임시/최종 파일과 최소 여유 공간을 확인한다."""
        needed = max(MIN_DISK_RESERVE, 2 * payload_size + 65536)
        try:
            free = shutil.disk_usage(self.root).free
        except OSError as error:
            raise ProjectError("E_DISK", "workspace의 남은 공간을 조회할 수 없습니다.") from error
        if free < needed:
            raise ProjectError("E_RESOURCE", "journal commit에 필요한 디스크 여유가 부족합니다.", details={"required_free_bytes": needed, "free_bytes": free})

    def _read_bytes(self, path: Path, limit: int) -> bytes:
        """! @brief 최대 길이 안에서 실제 파일 바이트를 읽는다."""
        _check_path_parts(path)
        try:
            with path.open("rb") as stream:
                result = stream.read(limit + 1)
        except OSError as error:
            raise ProjectError("E_HASH", "참조한 저장 파일을 읽을 수 없습니다.", details={"path": str(path)}) from error
        if len(result) > limit:
            raise ProjectError("E_HASH", "저장 파일이 허용된 크기를 초과합니다.", details={"path": str(path)})
        return result

    def _write_new(self, path: Path, payload: bytes) -> None:
        """! @brief 새 파일만 생성하고 flush/fsync 및 read-back 검증을 수행한다."""
        _check_path_parts(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _check_path_parts(path)
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        actual = self._read_bytes(path, len(payload))
        if actual != payload:
            raise ProjectError("E_HASH", "기록한 파일을 다시 읽은 결과가 일치하지 않습니다.")

    def _flush_directory(self, directory: Path) -> None:
        """! @brief 지원하는 POSIX 환경에서 디렉터리 항목을 동기화한다."""
        if os.name != "nt":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _fault(self, stage: str) -> None:
        """! @brief 명시적으로 주입한 시험 콜백만 호출한다."""
        if self.fault_hook is not None:
            self.fault_hook(stage)

    def _commit(self, state: dict) -> str:
        """! @brief 모든 payload 검증 뒤 current pointer 하나만 교체한다."""
        try:
            payload = canonical_bytes(state)
        except CanonicalEncodingError as error:
            raise ProjectError("E_SCHEMA", "journal 상태가 정규 JSON 계약을 위반합니다.") from error
        if len(payload) > MAX_STATE_BYTES:
            raise ProjectError("E_RESOURCE", "journal 상태가 8 MiB 한도를 초과합니다.")
        self._check_space(len(payload))
        commit_id = str(uuid4())
        base = f"commits/{commit_id}"
        manifest = {"schema_version": JOURNAL_SCHEMA, "commit_id": commit_id, "state": {"uri": f"{base}/state.json", "sha256": _digest(payload), "bytes": len(payload)}}
        manifest_bytes = canonical_bytes(manifest)
        pointer_bytes = canonical_bytes({"schema_version": JOURNAL_SCHEMA, "commit_id": commit_id, "manifest_sha256": _digest(manifest_bytes)})
        pointer_temp = self._safe_path(f".current-{commit_id}.tmp", internal=True)
        published = False
        try:
            self._write_new(self._safe_path(f"{base}/state.json", internal=True), payload)
            self._write_new(self._safe_path(f"{base}/manifest.json", internal=True), manifest_bytes)
            self._flush_directory(self.root / "commits" / commit_id)
            self._flush_directory(self.root / "commits")
            self._flush_directory(self.root)
            self._fault("after_payload")
            self._write_new(pointer_temp, pointer_bytes)
            self._fault("before_publish")
            os.replace(pointer_temp, self._safe_path("current.json", internal=True))
            published = True
            self._flush_directory(self.root)
            self._fault("after_publish")
            return commit_id
        except Exception as error:
            if published:
                raise ProjectError("E_DISK", "commit은 이미 게시되었습니다. 동일 request key로 결과를 조회해야 합니다.", details={"committed": True, "commit_id": commit_id, "cause": type(error).__name__}) from error
            if isinstance(error, ProjectError):
                raise
            if isinstance(error, OSError):
                raise ProjectError("E_DISK", "commit 게시 전에 저장에 실패했습니다. 마지막 정상 상태를 유지합니다.", details={"committed": False}) from error
            raise

    def read(self) -> dict:
        """! @brief pointer/manifest/payload hash를 매번 확인한 새 상태 사본을 읽는다."""
        with self._mutex:
            self._ensure_open()
            pointer = _strict_json(self._read_bytes(self._safe_path("current.json", internal=True), 16384))
            if type(pointer) is not dict or set(pointer) != {"schema_version", "commit_id", "manifest_sha256"} or pointer["schema_version"] != JOURNAL_SCHEMA:
                raise ProjectError("E_HASH", "current pointer 구조가 손상되었거나 지원하지 않습니다.")
            commit_id = pointer["commit_id"]
            try:
                if type(commit_id) is not str or str(UUID(commit_id)) != commit_id:
                    raise ValueError("invalid UUID")
            except ValueError as error:
                raise ProjectError("E_HASH", "current commit ID가 잘못되었습니다.") from error
            manifest_bytes = self._read_bytes(self._safe_path(f"commits/{commit_id}/manifest.json", internal=True), 16384)
            if _digest(manifest_bytes) != pointer["manifest_sha256"]:
                raise ProjectError("E_HASH", "commit manifest의 SHA256이 일치하지 않습니다.")
            manifest = _strict_json(manifest_bytes)
            if type(manifest) is not dict or set(manifest) != {"schema_version", "commit_id", "state"} or manifest["schema_version"] != JOURNAL_SCHEMA or manifest["commit_id"] != commit_id:
                raise ProjectError("E_HASH", "commit manifest 구조가 손상되었습니다.")
            reference = manifest["state"]
            if type(reference) is not dict or reference.get("uri") != f"commits/{commit_id}/state.json":
                raise ProjectError("E_HASH", "commit의 상태 파일 참조가 일치하지 않습니다.")
            payload = self._read_artifact(reference, internal=True)
            state = _strict_json(payload)
            if type(state) is not dict:
                raise ProjectError("E_HASH", "journal 최상위 상태는 object여야 합니다.")
            return copy.deepcopy(state)

    def transaction(self, mutator: Callable[[dict], Any]) -> Any:
        """! @brief 상태 사본 변경과 같은 commit의 receipt를 한 번에 게시한다.

        @param mutator 새 상태 사본을 수정하고 호출 결과를 반환하는 함수.
        @return commit 완료 후 mutator의 결과 사본.
        @details mutator 예외나 게시 전 실패는 current를 변경하지 않는다.
        mutator 안에서 put_immutable을 호출할 수 있으나 미게시 파일은 orphan이다.
        """
        with self._mutex:
            self._ensure_open()
            if self._in_transaction:
                raise ProjectError("E_CONFLICT", "중첩 journal transaction은 지원하지 않습니다.")
            state = self.read()
            previous_bytes = canonical_bytes(state)
            self._in_transaction = True
            try:
                result = mutator(state)
                result_copy = copy.deepcopy(result)
                try:
                    unchanged = canonical_bytes(state) == previous_bytes
                except CanonicalEncodingError as error:
                    raise ProjectError("E_SCHEMA", "journal 상태가 정규 JSON 계약을 위반합니다.") from error
                if unchanged:
                    return result_copy
                self._commit(state)
                return result_copy
            finally:
                self._in_transaction = False

    def put_immutable(self, relative_path: str, payload: bytes) -> dict:
        """! @brief 새 불변 artifact를 기록하고 실제 파일 hash 참조를 반환한다."""
        with self._mutex:
            self._ensure_open()
            if type(payload) is not bytes or len(payload) > MAX_ARTIFACT_BYTES:
                raise ProjectError("E_RESOURCE", "불변 파일은 최대 8 MiB의 bytes여야 합니다.")
            path = self._safe_path(relative_path)
            if path.exists():
                if self._read_bytes(path, MAX_ARTIFACT_BYTES) != payload:
                    raise ProjectError("E_HASH", "기존 불변 파일에 다른 내용을 기록할 수 없습니다.")
                try:
                    with path.open("r+b") as stream:
                        os.fsync(stream.fileno())
                except OSError as error:
                    raise ProjectError("E_DISK", "기존 불변 파일의 동기화를 확인할 수 없습니다.") from error
            else:
                self._check_space(len(payload))
                try:
                    self._write_new(path, payload)
                    directory = path.parent
                    while directory.is_relative_to(self.root):
                        self._flush_directory(directory)
                        if directory == self.root:
                            break
                        directory = directory.parent
                except OSError as error:
                    raise ProjectError("E_DISK", "불변 파일을 기록하지 못했습니다.") from error
            return {"uri": relative_path, "sha256": _digest(payload), "bytes": len(payload)}

    def _read_artifact(self, reference: dict, *, internal: bool = False) -> bytes:
        """! @brief 참조의 URI/크기/hash와 실제 바이트를 대조한다."""
        if type(reference) is not dict or not {"uri", "sha256", "bytes"}.issubset(reference):
            raise ProjectError("E_HASH", "불변 파일 참조에 필수 필드가 없습니다.")
        size = reference["bytes"]
        digest = reference["sha256"]
        if type(size) is not int or not 0 <= size <= MAX_ARTIFACT_BYTES or type(digest) is not str or _HASH.fullmatch(digest) is None:
            raise ProjectError("E_HASH", "불변 파일 참조의 크기 또는 hash가 유효하지 않습니다.")
        payload = self._read_bytes(self._safe_path(reference["uri"], internal=internal), size)
        if len(payload) != size or _digest(payload) != digest:
            raise ProjectError("E_HASH", "불변 파일의 크기 또는 SHA256이 일치하지 않습니다.")
        return payload

    def seal_file(self, relative_path: str, source: Path, *, expected_sha256: str, expected_bytes: int, limit: int = 64 * 1024 * 1024) -> dict:
        """! @brief 종료된 worker 파일을 스트리밍 검증하여 새 불변 경로로 봉인한다.

        @details 큰 복사 중 journal 잠금을 잡지 않는다. 호출자는 worker가 종료하고
        파일을 닫았음을 확인하고 이 호출이 끝날 때까지 journal 수명을 소유한다.
        참조는 반환 후 별도 transaction으로 게시해야 하며 실패한 파일은 미게시다.
        """
        if type(expected_bytes) is not int or not 0 < expected_bytes <= limit or type(expected_sha256) is not str or _HASH.fullmatch(expected_sha256) is None:
            raise ProjectError("E_RESOURCE", "봉인할 파일의 크기 또는 SHA256이 유효하지 않습니다.")
        source = Path(source)
        _check_path_parts(source)
        with self._mutex:
            self._ensure_open()
            path = self._safe_path(relative_path)
            self._check_space(expected_bytes)
            path.parent.mkdir(parents=True, exist_ok=True)
            _check_path_parts(path)
        temporary = path.with_name(path.name + "." + str(uuid4()) + ".partial")
        try:
            digest = hashlib.sha256()
            count = 0
            with source.open("rb") as incoming, temporary.open("xb") as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    count += len(chunk)
                    if count > expected_bytes:
                        raise ProjectError("E_HASH", "worker 파일이 선언한 크기를 초과했습니다.")
                    digest.update(chunk)
                    outgoing.write(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if count != expected_bytes or digest.hexdigest() != expected_sha256:
                raise ProjectError("E_HASH", "worker 파일의 크기 또는 SHA256이 일치하지 않습니다.")
            _check_path_parts(path)
            # @brief 배타적 hard link로 기존 정상 artifact를 덮어쓰지 않는다.
            os.link(temporary, path)
            self._flush_directory(path.parent)
            actual = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    actual.update(chunk)
            if actual.hexdigest() != expected_sha256:
                raise ProjectError("E_HASH", "봉인한 파일의 재읽기 검증이 실패했습니다.")
            return {"uri": relative_path, "sha256": expected_sha256, "bytes": expected_bytes}
        except OSError as error:
            raise ProjectError("E_DISK", "worker 파일을 불변 경로에 봉인하지 못했습니다.") from error
        finally:
            if temporary.exists():
                temporary.unlink()

    def read_artifact(self, reference: dict) -> bytes:
        """! @brief 외부 artifact 참조를 검증해 읽고 journal 내부 URI는 거부한다."""
        with self._mutex:
            self._ensure_open()
            return self._read_artifact(reference)

    def verify_file(self, reference: dict) -> None:
        """! @brief 메타데이터 읽기 상한은 유지하며 큰 봉인 파일의 전체 바이트를 스트리밍 확인한다."""
        from rfad.storage.sealed_files import verify, validate_reference

        validate_reference(reference)
        with self._mutex:
            self._ensure_open()
            path = self._safe_path(reference["uri"])
        verify(path, reference)

    def copy_artifact(self, reference: dict, relative_path: str) -> None:
        """! @brief 같은 workspace의 새 staging 경로에 64 MiB 이하 원시 입력을 유한 버퍼로 복제한다.

        @details 호출자는 복사 완료까지 journal 수명을 소유한다. 큰 IO 동안 상태 mutex는 잡지 않는다.
        """
        from rfad.storage.sealed_files import copy as copy_file, validate_reference

        validate_reference(reference)
        with self._mutex:
            self._ensure_open()
            source = self._safe_path(reference["uri"])
            destination = self._safe_path(relative_path)
            self._check_space(reference["bytes"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            _check_path_parts(destination)
        copy_file(source, destination, reference)
        self._flush_directory(destination.parent)

    def close(self) -> None:
        """! @brief writer 잠금을 해제한다. 파일을 삭제하거나 commit을 되돌리지 않는다."""
        with self._mutex:
            if self._in_transaction:
                raise ProjectError("E_CONFLICT", "transaction 처리 중 journal을 닫을 수 없습니다.")
            stream = self._lock_stream
            self._lock_stream = None
            self._closed = True
            if stream is not None:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                finally:
                    stream.close()
                    with _LOCAL_LOCK_GUARD:
                        _LOCAL_LOCKS.discard(self._lock_key)

    def __enter__(self) -> "Journal":
        """! @brief context manager에서 writer를 반환한다."""
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """! @brief context manager 종료 시 writer 잠금을 해제한다."""
        self.close()
