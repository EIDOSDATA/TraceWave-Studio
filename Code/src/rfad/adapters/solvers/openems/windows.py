"""! @brief Windows solver가 실제로 로딩한 모듈과 최대 working set을 읽는다."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path


def mapped_files(pid):
    """! @brief Windows가 실제 매핑한 DLL 및 Python 확장 경로만 반환한다."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    api = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    api.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    api.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    handle = kernel.OpenProcess(0x0410, False, os.getpid() if pid == "self" else pid)
    if not handle:
        return []
    try:
        modules = (wintypes.HMODULE * 1024)()
        length = wintypes.DWORD()
        if not api.EnumProcessModulesEx(handle, modules, ctypes.sizeof(modules), ctypes.byref(length), 3):
            return []
        if length.value > ctypes.sizeof(modules):
            raise OSError("Windows native module observation exceeded its bound")
        result = set()
        buffer = ctypes.create_unicode_buffer(32768)
        for index in range(length.value // ctypes.sizeof(wintypes.HMODULE)):
            count = api.GetModuleFileNameExW(handle, modules[index], buffer, len(buffer))
            if 0 < count < len(buffer):
                result.add(Path(buffer.value).resolve())
        return sorted(result)
    finally:
        kernel.CloseHandle(handle)


class _Memory(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("page_faults", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ("peak_working", "working", "peak_paged", "paged",
                                            "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]


def peak_rss(process):
    """! @brief 이 실행의 프로세스 핸들로만 최대 working set을 조회한다."""
    api = ctypes.WinDLL("psapi", use_last_error=True)
    api.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    data = _Memory()
    data.size = ctypes.sizeof(data)
    if api.GetProcessMemoryInfo(int(process._handle), ctypes.byref(data), data.size):
        return int(data.peak_working)
    return 0
