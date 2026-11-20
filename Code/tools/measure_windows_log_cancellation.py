"""! @brief Windows native 감독기의 초당 1000행과 자식 회수 지연을 계측한다."""

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time

from rfad.application.native_process import run_native


_LINE = b"TraceWave diagnostic log line\n"
_WRITER = '''
import json, os, subprocess, sys, time
from pathlib import Path

if not sys.stdin.buffer.readline():
    raise SystemExit(2)
child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
start = time.perf_counter()
for batch in range(1, 401):
    delay = start + batch / 50 - time.perf_counter()
    if delay > 0:
        time.sleep(delay)
    raw = LINE * 20
    if os.write(1, raw) != len(raw):
        raise SystemExit(3)
    if batch == 100:
        Path("ready.tmp").write_text(json.dumps({
            "child": child.pid, "logged": 2000, "seconds": time.perf_counter() - start
        }), encoding="utf-8")
        os.replace("ready.tmp", "ready.json")
'''


def measure(kernel):
    """! @brief 같은 실행에서 지정 로그량 도달과 소유한 후손의 실제 종료를 연결한다."""
    with TemporaryDirectory(prefix="TraceWave Windows log cancellation ") as temporary:
        directory = Path(temporary)
        ready = directory / "ready.json"
        cancel = threading.Event()
        finished = threading.Event()
        observed = {}

        def request_cancel():
            """! @brief 로그 쓰기 도중에만 취소하며 앞에서 연 후손 핸들로 종료를 대조한다."""
            deadline = time.monotonic() + 12
            while not finished.is_set() and time.monotonic() < deadline:
                try:
                    payload = json.loads(ready.read_bytes())
                except (FileNotFoundError, PermissionError):
                    # @brief 원자 교체 중 잠긴 표식은 실행 상한 안에서 다시 연다.
                    finished.wait(0.002)
                    continue
                observed.update(payload)
                observed["handle"] = kernel.OpenProcess(0x00100000, False, observed["child"])
                observed["cancel_at"] = time.perf_counter()
                cancel.set()
                return
            cancel.set()

        requester = threading.Thread(target=request_cancel)
        requester.start()
        try:
            process = run_native(
                [sys.executable, "-I", "-c", "LINE = " + repr(_LINE) + "\n" + _WRITER],
                directory, b"{}\n", cancel, timeout_seconds=15,
            )
            returned = time.perf_counter()
        finally:
            finished.set()
            requester.join()
            handle = observed.pop("handle", None)
            if handle:
                observed["descendant_signaled"] = kernel.WaitForSingleObject(handle, 1000) == 0
                kernel.CloseHandle(handle)
        if (process["termination"] != "cancelled" or not observed.get("descendant_signaled")
                or process["stdout_bytes"] < len(_LINE) * observed["logged"]
                or process["stdout_bytes"] % len(_LINE)):
            raise RuntimeError("로그 중 취소, 배출한 로그량과 후손 종료의 확인이 일치하지 않습니다.")
        return {
            "target_lines_per_second": 1000, "before_request_lines": observed["logged"],
            "before_request_seconds": observed["seconds"],
            "before_request_lines_per_second": observed["logged"] / observed["seconds"],
            "drained_stdout_lines": process["stdout_bytes"] // len(_LINE), "stderr_bytes": process["stderr_bytes"],
            "cancel_to_native_return_ms": (returned - observed["cancel_at"]) * 1000,
            "descendant_signaled": True, "termination": process["termination"],
        }


def main():
    """! @brief 전용 Windows 작업 영역에서 동일 로그 부하를 세 번 반복한다."""
    if sys.platform != "win32":
        raise SystemExit("Windows native Job Object 실행 환경이 필요합니다.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    runs = [measure(kernel) for _ in range(3)]
    print(json.dumps({"schema": "rfad.native-log-cancel-measurement/0.1",
                      "scope": "windows-native-job-object", "wsl_and_gui_load": False, "runs": runs},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
