"""! @brief 실제 Windows Studio와 같은 하위 서비스의 자원 표본을 수집한다."""

import ctypes
from ctypes import wintypes as wt
from time import perf_counter, sleep


class ProcessEntry(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("usage", wt.DWORD), ("pid", wt.DWORD),
                ("heap", ctypes.c_size_t), ("module", wt.DWORD), ("threads", wt.DWORD),
                ("parent", wt.DWORD), ("priority", wt.LONG), ("flags", wt.DWORD),
                ("name", wt.WCHAR * 260)]


class Counters(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("faults", wt.DWORD)] + [
        (key, ctypes.c_size_t) for key in ("peak_working", "working", "peak_paged", "paged",
                                          "peak_nonpaged", "nonpaged", "commit", "peak_commit", "private")]


def sampler():
    """! @brief 64비트 Windows 핸들과 프로세스별 메모리 계측 함수를 구성한다."""
    system = ctypes.windll.kernel32
    snapshot = system.CreateToolhelp32Snapshot
    snapshot.argtypes = [wt.DWORD, wt.DWORD]
    snapshot.restype = wt.HANDLE
    first, next_entry = system.Process32FirstW, system.Process32NextW
    for function in (first, next_entry):
        function.argtypes = [wt.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wt.BOOL
    open_process = system.OpenProcess
    open_process.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    open_process.restype = wt.HANDLE
    close = system.CloseHandle
    close.argtypes = [wt.HANDLE]
    process_times = system.GetProcessTimes
    process_times.argtypes = [wt.HANDLE, *(ctypes.POINTER(wt.FILETIME) for _ in range(4))]
    process_times.restype = wt.BOOL
    memory = ctypes.windll.psapi.GetProcessMemoryInfo
    memory.argtypes = [wt.HANDLE, ctypes.POINTER(Counters), wt.DWORD]
    memory.restype = wt.BOOL

    def creation_time(process):
        """! @brief 프로세스 핸들의 실제 Windows 생성 시각을 읽는다."""
        creation, exit_time, kernel, user = (wt.FILETIME() for _ in range(4))
        if process_times(process, creation, exit_time, kernel, user):
            return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return None

    def created(pid):
        """! @brief PID를 재사용한 부모보다 먼저 생성된 프로세스를 구별한다."""
        process = open_process(0x1000, False, pid)
        if process is None:
            return None
        try:
            return creation_time(process)
        finally:
            close(process)

    def sample(pid):
        """! @brief 소유한 프로세스 트리 밖의 메모리는 샘플에서 제외한다."""
        tree = snapshot(2, 0)
        if tree in (None, wt.HANDLE(-1).value):
            raise ctypes.WinError()
        children = {}
        try:
            entry = ProcessEntry(size=ctypes.sizeof(ProcessEntry))
            ok = first(tree, ctypes.byref(entry))
            while ok:
                children.setdefault(entry.parent, []).append(entry.pid)
                ok = next_entry(tree, ctypes.byref(entry))
        finally:
            close(tree)
        started = created(pid)
        if started is None:
            return []
        pids = {pid: started}
        pending = [pid]
        while pending:
            parent = pending.pop()
            for child in children.get(parent, ()):
                if child in pids:
                    continue
                child_started = created(child)
                if child_started is not None and child_started >= pids[parent]:
                    pids[child] = child_started
                    pending.append(child)
        rows = []
        for current in sorted(pids):
            process = open_process(0x0410, False, current)
            if process is None:
                continue
            try:
                counters = Counters(size=ctypes.sizeof(Counters))
                if creation_time(process) == pids[current] and memory(process, ctypes.byref(counters), counters.size):
                    rows.append({"pid": current, "created_100ns": str(pids[current]),
                                 "gui": current == pid, "private_commit_bytes": counters.private,
                                 "working_set_bytes": counters.working, "peak_commit_bytes": counters.peak_commit})
            finally:
                close(process)
        return rows

    return sample


def observe(process, phases, timeout):
    """! @brief runtime 준비 이후부터 GUI 닫기까지 100 ms 목표 주기로 실제 프로세스를 관찰한다."""
    start = perf_counter()
    collect = sampler()
    rows = []
    last = "startup"
    while process.poll() is None:
        if perf_counter() - start > timeout:
            process.kill()
            process.wait(10)
            raise TimeoutError("Windows 대용량 결과 검증 시간이 초과됐습니다.")
        if phases.exists():
            markers = phases.read_text(encoding="ascii").splitlines()
            if markers:
                last = markers[-1]
        rows.append({"seconds": perf_counter() - start, "phase": last, "processes": collect(process.pid)})
        sleep(0.1)
    return rows
