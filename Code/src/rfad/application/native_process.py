"""! @brief 격리 native worker의 프로세스 트리와 제한된 입출력 수명을 소유한다."""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Callable

from rfad.domain.errors import ProjectError


MAX_REQUEST_BYTES = 64 * 1024
TAIL_BYTES = 16 * 1024
REAP_SECONDS = 5.0
FILE_SCAN_SECONDS = 0.1


def _reparse(metadata) -> bool:
    """! @brief Windows 재분석점과 POSIX 심볼릭 링크를 따라가지 않는다."""
    return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _scan_output(directory: Path, cwd: Path, max_file_bytes: int, max_directory_bytes: int, max_files: int) -> dict:
    """! @brief 고정 출력 하위 경로의 파일 수/크기와 경로 유형을 유한하게 검사한다."""
    result = {"reason": "", "bytes": 0, "files": 0}
    for path in reversed(directory.relative_to(cwd).parents):
        if path == Path("."):
            continue
        try:
            metadata = (cwd / path).lstat()
        except FileNotFoundError:
            continue
        if _reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
            result["reason"] = "unsafe_path"
            return result
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        return result
    if _reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        result["reason"] = "unsafe_path"
        return result
    pending = [directory]
    directories = 0
    while pending:
        current = pending.pop()
        directories += 1
        if directories > max_files:
            result["reason"] = "directory_count"
            return result
        with os.scandir(current) as entries:
            for entry in entries:
                try:
                    # @brief Windows DirEntry의 생략된 link 수 대신 실제 파일 정보를 읽는다.
                    metadata = os.stat(entry.path, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if _reparse(metadata):
                    result["reason"] = "unsafe_path"
                    return result
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(Path(entry.path))
                    if len(pending) + directories > max_files:
                        result["reason"] = "directory_count"
                        return result
                    continue
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink > 1:
                    result["reason"] = "unsafe_path"
                    return result
                result["files"] += 1
                result["bytes"] += metadata.st_size
                if result["files"] > max_files:
                    result["reason"] = "file_count"
                elif metadata.st_size > max_file_bytes:
                    result["reason"] = "file_size"
                elif result["bytes"] > max_directory_bytes:
                    result["reason"] = "directory_size"
                if result["reason"]:
                    return result
    return result


class _WindowsJob:
    """! @brief 이름 없는 Job Object로 시작한 worker와 후손만 회수한다."""

    def __init__(self):
        """! @brief 마지막 핸들이 닫히면 트리를 종료하는 비상 회수 경계를 만든다."""
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self._accounting = Accounting
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._kernel, name)
            function.argtypes = arguments
            function.restype = result
        self._handle = self._kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not self._kernel.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process: subprocess.Popen) -> None:
        """! @brief CPython이 보유한 프로세스 핸들을 할당하고 PID 재탐색을 하지 않는다."""
        if not self._kernel.AssignProcessToJobObject(self._handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self) -> None:
        """! @brief 소유 Job Object의 실행 중인 프로세스만 종료한다."""
        if not self._kernel.TerminateJobObject(self._handle, 2):
            raise ctypes.WinError(ctypes.get_last_error())

    def active(self) -> bool:
        """! @brief 실제 Job Object의 실행 프로세스 수를 확인한다."""
        accounting = self._accounting()
        if not self._kernel.QueryInformationJobObject(self._handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return accounting.ActiveProcesses != 0

    def close(self) -> None:
        """! @brief 핸들을 닫아 비상 트리 회수 정책을 적용한다."""
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def _group_active(process_group: int) -> bool:
    """! @brief Linux의 종료된 zombie를 실행 중인 후손으로 오인하지 않는다."""
    if sys.platform.startswith("linux"):
        try:
            for path in Path("/proc").iterdir():
                if not path.name.isdigit():
                    continue
                try:
                    fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
                    if int(fields[2]) == process_group and fields[0] not in {"Z", "X"}:
                        return True
                except (FileNotFoundError, ProcessLookupError):
                    continue
            return False
        except (OSError, ValueError, IndexError):
            # @brief 확인 실패를 종료 성공으로 추측하지 않고 보수적인 그룹 검사로 되돌린다.
            pass
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False


def _signal_group(process_group: int, number: int) -> None:
    """! @brief 이 실행에서 새로 만든 세션의 그룹에만 종료 신호를 전달한다."""
    try:
        os.killpg(process_group, number)
    except ProcessLookupError:
        pass


def _tail_text(value: bytearray) -> str:
    """! @brief 잘못된 UTF-8의 대체 문자까지 포함해 표시 tail의 byte 상한을 유지한다."""
    encoded = bytes(value).decode("utf-8", errors="replace").encode("utf-8")
    return encoded[-TAIL_BYTES:].decode("utf-8", errors="ignore")


def _reap(process: subprocess.Popen, job: _WindowsJob | None) -> None:
    """! @brief 주 프로세스와 남은 소유 후손을 회수하고 종료 확인 실패를 숨기지 않는다."""
    deadline = time.monotonic() + REAP_SECONDS
    try:
        if job is not None:
            job.terminate()
        else:
            _signal_group(process.pid, signal.SIGTERM)
            grace = time.monotonic() + 0.2
            while time.monotonic() < grace and _group_active(process.pid):
                time.sleep(0.01)
            _signal_group(process.pid, signal.SIGKILL)
        process.wait(timeout=max(0.01, deadline - time.monotonic()))
        while (job.active() if job is not None else _group_active(process.pid)):
            if time.monotonic() >= deadline:
                raise TimeoutError("native process tree is still active")
            time.sleep(0.01)
    except (OSError, subprocess.TimeoutExpired, TimeoutError) as error:
        raise ProjectError("E_RESOURCE", "native 프로세스 트리의 종료를 확인하지 못했습니다.",
                           details={"outcome_unknown": True, "pid": process.pid}) from error


def run_native(
    argv: list[str], cwd: Path, request_bytes: bytes, cancel: threading.Event,
    timeout_seconds: float = 120, max_output_bytes: int = 1024 * 1024,
    on_started: Callable[[dict], None] | None = None,
    *, output_directory: Path | None = None, max_file_bytes: int = 64 * 1024 * 1024,
    max_directory_bytes: int = 128 * 1024 * 1024, max_files: int = 16,
) -> dict:
    """! @brief stdin 접수 전에 소유권을 확정하고 native 실행의 유한 결과를 반환한다.

    @details worker는 stdin의 한 요청을 완전히 받은 뒤에만 native import나 후손 생성을
    시작해야 한다. EOF이면 종료해야 하며 부모의 할당 전 crash가 작업을 시작하지 않게 한다.
    stdout/stderr는 protocol이 아닌 제한된 로그이며 각 tail은 최대 16 KiB다.
    @param argv 절대 실행 파일 경로와 셸을 거치지 않는 고정 인수 목록.
    @param cwd 이미 존재하는 이 실행 전용 디렉터리.
    @param request_bytes 최대 64 KiB의 개행 종료 UTF-8 요청.
    @param cancel 실행 중 취소 요청. 실제 트리 종료 후 cancelled로 반환한다.
    @param timeout_seconds 프로세스 시작부터 적용할 벽시계 상한.
    @param max_output_bytes stdout와 stderr를 합한 byte 상한.
    @param on_started 소유권 확립 후, stdin 전달 전에 실행할 영속 접수 callback.
    @param output_directory 감시할 cwd 하위 출력 디렉터리. None이면 파일 감시는 하지 않는다.
    @param max_file_bytes 출력 파일 하나의 최대 크기.
    @param max_directory_bytes 모든 출력 파일 크기의 합계 상한.
    @param max_files 출력 파일 수와 별도 디렉터리 수의 상한.
    @return 종료 코드, bounded tail, 읽은 byte 수, pid와 종료 원인.
    @warning 파일 상한은 0.1초 간격 관측이며 OS 디스크 quota가 아니므로 사이에 초과할 수 있다.
    """
    if (type(argv) is not list or not argv or any(type(value) is not str or "\0" in value for value in argv)
            or not Path(argv[0]).is_absolute()):
        raise ProjectError("E_SCHEMA", "native 실행 파일의 절대 경로와 명시적 인수가 필요합니다.")
    if (type(request_bytes) is not bytes or not request_bytes.endswith(b"\n")
            or len(request_bytes) > MAX_REQUEST_BYTES):
        raise ProjectError("E_RESOURCE", "native 요청은 개행으로 끝나는 64 KiB 이하 bytes여야 합니다.")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
            or any(type(value) is not int or value <= 0 for value in (max_output_bytes, max_file_bytes, max_directory_bytes, max_files))):
        raise ProjectError("E_SCHEMA", "native 시간과 출력 상한은 유한 양수여야 합니다.")
    cwd = Path(cwd).resolve(strict=True)
    if output_directory is not None:
        output_directory = Path(output_directory)
        if not output_directory.is_absolute():
            output_directory = cwd / output_directory
        output_directory = Path(os.path.abspath(output_directory))
        if output_directory == cwd or not output_directory.is_relative_to(cwd):
            raise ProjectError("E_SCHEMA", "출력 감시 경로는 실행 디렉터리의 하위 경로여야 합니다.")
    started = time.monotonic()
    job = None
    process = None
    threads = []
    owned = False
    reaped = False
    lock = threading.Lock()
    output_limit = threading.Event()
    counts = {"stdout": 0, "stderr": 0}
    tails = {"stdout": bytearray(), "stderr": bytearray()}
    io_errors = []
    file_observation = {"reason": "", "bytes": 0, "files": 0}
    file_peak_bytes = 0
    file_peak_count = 0
    file_violation_reason = ""

    def inspect_files():
        """! @brief 관측한 파일 상한 초과와 최대값을 결과에 보존한다."""
        nonlocal file_observation, file_peak_bytes, file_peak_count, file_violation_reason
        if output_directory is not None:
            file_observation = _scan_output(output_directory, cwd, max_file_bytes, max_directory_bytes, max_files)
            file_peak_bytes = max(file_peak_bytes, file_observation["bytes"])
            file_peak_count = max(file_peak_count, file_observation["files"])
            if file_observation["reason"] and not file_violation_reason:
                file_violation_reason = file_observation["reason"]
        return bool(file_violation_reason)

    def drain(stream, name):
        """! @brief 두 출력 스트림을 동시에 비우며 tail과 전체 byte 수만 보존한다."""
        try:
            while True:
                block = stream.read(8192)
                if not block:
                    break
                with lock:
                    counts[name] += len(block)
                    tails[name].extend(block)
                    if len(tails[name]) > TAIL_BYTES:
                        del tails[name][:-TAIL_BYTES]
                    if sum(counts.values()) > max_output_bytes:
                        output_limit.set()
        except OSError as error:
            io_errors.append(error)

    def send():
        """! @brief worker가 읽지 않아도 감독 루프가 막히지 않도록 요청을 별도로 쓴다."""
        try:
            remaining = memoryview(request_bytes)
            while remaining:
                count = process.stdin.write(remaining)
                if not count:
                    raise BrokenPipeError("native stdin closed")
                remaining = remaining[count:]
        except (BrokenPipeError, OSError):
            # @brief worker 조기 종료는 returncode와 출력으로 판정한다.
            pass
        finally:
            process.stdin.close()

    try:
        if os.name == "nt":
            job = _WindowsJob()
        process = subprocess.Popen(
            argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, bufsize=0, close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        if job is not None:
            job.assign(process)
        owned = True
        for name in ("stdout", "stderr"):
            thread = threading.Thread(target=drain, args=(getattr(process, name), name), daemon=True,
                                      name="rfad-native-" + name)
            thread.start()
            threads.append(thread)
        if on_started is not None:
            on_started({"pid": process.pid, "platform": sys.platform})
        if not cancel.is_set():
            writer = threading.Thread(target=send, daemon=True, name="rfad-native-stdin")
            writer.start()
            threads.append(writer)
        else:
            process.stdin.close()
        termination = "completed"
        next_file_scan = started
        while True:
            if cancel.is_set():
                termination = "cancelled"
                break
            if output_limit.is_set():
                termination = "output_limit"
                break
            if time.monotonic() >= next_file_scan:
                if inspect_files():
                    termination = "output_limit"
                    break
                next_file_scan = time.monotonic() + FILE_SCAN_SECONDS
            if time.monotonic() - started >= timeout_seconds:
                termination = "timeout"
                break
            if process.poll() is not None:
                break
            time.sleep(0.01)
        _reap(process, job)
        reaped = True
        for thread in threads:
            thread.join(timeout=1.0)
        if any(thread.is_alive() for thread in threads):
            raise ProjectError("E_RESOURCE", "native 입출력 회수를 확인하지 못했습니다.",
                               details={"outcome_unknown": True, "pid": process.pid})
        if io_errors:
            raise ProjectError("E_RESOURCE", "native 출력 스트림을 읽지 못했습니다.") from io_errors[0]
        if termination == "completed" and output_limit.is_set():
            termination = "output_limit"
        if inspect_files() and termination == "completed":
            termination = "output_limit"
        return {
            "returncode": process.returncode, "pid": process.pid, "termination": termination,
            "output_limit_reason": file_violation_reason or ("stream_bytes" if output_limit.is_set() else ""),
            "file_monitor": {
                "enabled": output_directory is not None, "poll_interval_seconds": FILE_SCAN_SECONDS,
                "max_file_bytes": max_file_bytes, "max_directory_bytes": max_directory_bytes, "max_files": max_files,
                "observed_peak_bytes": file_peak_bytes, "observed_peak_file_count": file_peak_count,
                "overshoot_between_polls_possible": True,
            },
            **{name + "_bytes": value for name, value in counts.items()},
            **{name + "_tail": _tail_text(value) for name, value in tails.items()},
        }
    finally:
        try:
            if process is not None and not reaped:
                if owned:
                    _reap(process, job)
                else:
                    # @brief 할당 전 worker는 stdin을 받지 않았으므로 native 후손이 없어야 한다.
                    try:
                        process.kill()
                        process.wait(timeout=REAP_SECONDS)
                    except (OSError, subprocess.TimeoutExpired) as error:
                        raise ProjectError("E_RESOURCE", "native 할당 전 프로세스의 종료를 확인하지 못했습니다.",
                                           details={"outcome_unknown": True, "pid": process.pid}) from error
                for thread in threads:
                    thread.join(timeout=1.0)
        finally:
            if job is not None:
                job.close()
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
