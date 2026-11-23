"""! @brief Windows 제품 서비스와 worker의 실행 환경을 WMI 세션 없이 식별한다."""

import ctypes
from functools import cache
import platform
import sys


def _machine_name(code):
    """! @brief PE 시스템 종류를 기존 CPU 식별 및 고정 설치 명세와 같은 이름으로 바꾼다."""
    machines = {0x014C: "x86", 0x8664: "AMD64", 0xAA64: "ARM64", 0x01C4: "ARM", 0x0200: "ia64"}
    if code not in machines:
        raise OSError(f"지원하는 Windows CPU 종류를 확인할 수 없습니다 (0x{code:04X}).")
    return machines[code]


@cache
def _windows_machines():
    """! @brief 현재 프로세스와 호스트의 PE 종류를 NT 커널에서 읽는다."""
    from ctypes import wintypes

    query = ctypes.WinDLL("kernel32", use_last_error=True).IsWow64Process2
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.USHORT), ctypes.POINTER(wintypes.USHORT)]
    query.restype = wintypes.BOOL
    process = wintypes.USHORT()
    native = wintypes.USHORT()
    if not query(wintypes.HANDLE(-1), ctypes.byref(process), ctypes.byref(native)):
        raise ctypes.WinError(ctypes.get_last_error())
    return _machine_name(native.value), _machine_name(process.value or native.value)


def system_name():
    """! @brief 호스트 계산 식별에 사용하는 운영체제 이름을 반환한다."""
    return "Windows" if sys.platform == "win32" else platform.system()


def machine_name(*, process=False):
    """! @brief 기본은 호스트 CPU이며 네이티브 worker 명세 검사는 프로세스 CPU를 사용한다."""
    if sys.platform == "win32":
        native_machine, process_machine = _windows_machines()
        return process_machine if process else native_machine
    return platform.machine()


def os_version():
    """! @brief 진단과 CAD 원문 기록에 필요한 운영체제 릴리스 및 커널 버전을 조회한다."""
    if sys.platform != "win32":
        return platform.release(), platform.version()
    windows = sys.getwindowsversion()
    major, minor, build = windows.platform_version
    version = f"{major}.{minor}.{build}"
    if (major, minor) == (10, 0) and windows.product_type == 1:
        release = "11" if build >= 22000 else "10"
    elif (major, minor) == (10, 0):
        release = next((name for threshold, name in ((26100, "2025Server"), (20348, "2022Server"),
                       (17763, "2019Server"), (14393, "2016Server")) if build >= threshold), "Server-10.0")
    else:
        release = f"NT-{major}.{minor}"
    return release, version


def platform_label():
    """! @brief 내보낸 CAD 산출물에 실제 Windows 빌드와 서비스 팩을 기록한다."""
    if sys.platform != "win32":
        return platform.platform()
    release, version = os_version()
    windows = sys.getwindowsversion()
    pack = str(windows.service_pack_major)
    if windows.service_pack_minor:
        pack += f".{windows.service_pack_minor}"
    return f"Windows-{release}-{version}-SP{pack}"
