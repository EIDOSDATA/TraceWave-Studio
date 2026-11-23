"""! @brief Windows 앱 제거의 등록, 경로 격리 및 데이터 보존을 검증한다."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

if sys.platform == "win32":
    import winreg


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


@unittest.skipUnless(sys.platform == "win32", "Windows 앱 등록과 제거 시험")
class WindowsRemovalTests(unittest.TestCase):
    """! @brief 실제 Windows PowerShell에서 제거 명령과 보호 경로를 대조한다."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="TraceWave 제거 검증 ")))
        self.script = self.root / "TraceWaveUninstall.ps1"
        self.script.write_text((ROOT / "tools/windows_setup/uninstall.ps1").read_text(encoding="utf-8-sig"),
                               encoding="utf-8-sig")
        identifier = hashlib.sha256((str(self.root).upper() + "\\").encode("utf-8")).hexdigest().upper()
        self.key = REGISTRY + "\\TraceWaveStudio." + identifier
        self.addCleanup(self.clear_registration)
        self.powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        self.gui = self.root / "Versions" / "Code with spaces" / "tracewave_gui.exe"
        self.gui.parent.mkdir(parents=True)
        self.gui.write_bytes(b"studio")
        self.output = self.root / "Workspace" / "old-result.json"
        self.output.parent.mkdir()
        self.output.write_bytes(b"original")
        self.run_removal("-DisplayVersion", "R1 RC5", "-StudioExe", str(self.gui))

    def clear_registration(self):
        """! @brief 고유 임시 경로의 시험 등록만 정리한다."""
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key)
        except FileNotFoundError:
            pass

    def registration(self, name):
        """! @brief Windows가 읽는 사용자 등록에서 값을 가져온다."""
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key) as key:
            return winreg.QueryValueEx(key, name)[0]

    def run_command(self, arguments, *, check=True):
        """! @brief 현재 사용자에게 창을 띄우지 않고 Windows 명령을 실행한다."""
        result = subprocess.run(arguments, cwd=self.root.parent, check=False, capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode("utf-8", errors="replace"))
        return result

    def run_removal(self, *arguments, check=True):
        """! @brief 별도의 실제 Windows PowerShell에서 설치된 제거기를 실행한다."""
        return self.run_command([str(self.powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-File", str(self.script), *arguments], check=check)

    def test_registration_updates_in_place_and_removes_only_installed_files(self):
        """! @brief 등록을 갱신하고 실제 제거 명령이 프로젝트와 WSL을 보존하는지 확인한다."""
        self.run_removal("-DisplayVersion", "R1 RC6", "-StudioExe", str(self.gui), "-KeepExisting")
        self.assertEqual(self.registration("DisplayVersion"), "R1 RC5")
        self.run_removal("-DisplayVersion", "R1 RC6", "-StudioExe", str(self.gui))
        self.assertEqual(self.registration("DisplayVersion"), "R1 RC6")
        self.assertEqual(self.registration("InstallLocation"), str(self.root))
        self.assertEqual(self.registration("DisplayIcon"), str(self.gui) + ",0")
        self.assertIn("-WindowStyle Hidden", self.registration("UninstallString"))
        for name in ("Cache", "Python31210", "WSL"):
            (self.root / name).mkdir()
        (self.root / "Setup.log").write_bytes(b"log")
        link = self.gui.parent / "WorkspaceLink"
        self.run_command([str(self.powershell), "-NoProfile", "-Command",
                          f"New-Item -ItemType Junction -Path '{link}' -Target '{self.output.parent}'"])
        self.run_command(self.registration("QuietUninstallString"))
        self.assertEqual({path.name for path in self.root.iterdir()}, {"Workspace", "WSL"})
        self.assertEqual(self.output.read_bytes(), b"original")
        with self.assertRaises(FileNotFoundError):
            self.registration("UninstallString")

    def test_top_level_junction_blocks_removal_before_any_file_is_removed(self):
        """! @brief 설치 폴더의 직접 연결은 보호하고 등록을 남겨 재시도를 허용한다."""
        junction = self.root / "Cache"
        self.run_command([str(self.powershell), "-NoProfile", "-Command",
                          f"New-Item -ItemType Junction -Path '{junction}' -Target '{self.output.parent}'"])
        result = self.run_removal("-Quiet", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("연결된 경로", result.stderr.decode("utf-8"))
        self.assertTrue(self.gui.is_file())
        self.assertEqual(self.output.read_bytes(), b"original")
        self.assertEqual(self.registration("DisplayVersion"), "R1 RC5")
