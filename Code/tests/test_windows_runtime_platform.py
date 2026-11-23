"""! @brief WMI를 사용할 수 없는 Windows 작업 스레드의 식별과 기존 원문 키를 검증한다."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import platform
import struct
import sys
import unittest
from unittest.mock import patch

from rfad import runtime_platform
from rfad.application.host_calculation_runtime import python_identity


class RuntimePlatformTests(unittest.TestCase):
    """! @brief Windows CPU 코드 및 운영체제 원문을 CPU 이름 추측 없이 대조한다."""

    def test_pe_machine_codes_and_unknown(self):
        """! @brief 실제 Win32 PE 상수와 알 수 없는 코드 처리를 검사한다."""
        for code, name in ((0x014C, "x86"), (0x8664, "AMD64"), (0xAA64, "ARM64")):
            self.assertEqual(runtime_platform._machine_name(code), name)
        with self.assertRaises(OSError):
            runtime_platform._machine_name(0xFFFF)

    def test_emulated_workers_use_process_abi(self):
        """! @brief x86 및 AMD64 에뮬레이션에서 호스트와 프로세스 명세를 구분한다."""
        with patch.object(sys, "platform", "win32"):
            for native, process in (("AMD64", "x86"), ("ARM64", "AMD64"), ("ARM64", "ARM64")):
                with patch.object(runtime_platform, "_windows_machines", return_value=(native, process)):
                    self.assertEqual(runtime_platform.machine_name(), native)
                    self.assertEqual(runtime_platform.machine_name(process=True), process)

    @unittest.skipUnless(sys.platform == "win32", "실제 Windows API 및 프로세스 파일 필요")
    def test_worker_threads_skip_wmi_and_keep_identity(self):
        """! @brief 실제 PE 실행 파일과 커널을 대조하고 복수 작업 스레드의 기존 identity를 확인한다."""
        raw = Path(sys.executable).read_bytes()
        pe = int.from_bytes(raw[0x3C:0x40], "little")
        self.assertEqual(raw[pe:pe + 4], b"PE\x00\x00")
        executable_machine = runtime_platform._machine_name(int.from_bytes(raw[pe + 4:pe + 6], "little"))
        with patch.object(platform, "_wmi_query", side_effect=AssertionError("WMI 호출"), create=True):
            runtime_platform._windows_machines.cache_clear()
            self.assertEqual(runtime_platform.machine_name(process=True), executable_machine)
            native = runtime_platform.machine_name()
            expected = {"implementation": sys.implementation.name, "version": platform.python_version(),
                        "system": "Windows", "machine": native, "pointer_bits": 8 * struct.calcsize("P"),
                        "byteorder": sys.byteorder, "sha256": hashlib.sha256(raw).hexdigest()}
            with ThreadPoolExecutor(max_workers=4) as workers:
                self.assertEqual(list(workers.map(lambda _: python_identity(), range(12))), [expected] * 12)
            self.assertEqual(runtime_platform.os_version()[1], ".".join(map(str, sys.getwindowsversion().platform_version)))
            self.assertIn(runtime_platform.os_version()[1], runtime_platform.platform_label())
