"""! @brief 내부 bundle의 Git 원본 선택, 해시 검증과 Windows 경로 경계를 검사한다."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from tools import build_internal_bundle as bundle
from tools.internal_bundle_inputs import _imports, git_sources


class InternalBundleTests(unittest.TestCase):
    def test_extracts_only_explicit_committed_inputs(self):
        """! @brief 사용자 작업 트리 재저장과 참고자료/무시 파일을 묶음의 소스로 사용하지 않는다."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            code = root / "Code"
            (code / "src").mkdir(parents=True)
            (root / "00_참고자료").mkdir()
            source = code / "src/a.py"
            source.write_bytes(b"original")
            (code / "CMakeLists.txt").write_bytes(b"build")
            (root / "00_참고자료/source.txt").write_bytes(b"restricted")
            (code / "untracked-project.json").write_bytes(b"working")
            command = ["git", "-C", str(root)]
            subprocess.run([*command, "init", "-q"], check=True)
            subprocess.run([*command, "add", "--", "Code/src/a.py", "Code/CMakeLists.txt", "00_참고자료"], check=True)
            subprocess.run([*command, "-c", "user.name=TraceWave", "-c", "user.email=test@local.invalid",
                            "commit", "-qm", "fixture"], check=True)
            source.write_bytes(b"unsaved changes")
            (code / "src/local.py").write_bytes(b"untracked")
            commit, selected = git_sources(root, "HEAD")
            self.assertEqual(subprocess.check_output([*command, "rev-parse", "HEAD"], text=True).strip(), commit)
            self.assertEqual(selected, {"Code/src/a.py": b"original", "Code/CMakeLists.txt": b"build"})

    def test_zip_is_deterministic_and_checks_hash_and_path(self):
        """! @brief 동일 바이트를 같은 ZIP으로 작성하며 변조, 중복 및 NTFS 특수 이름을 거절한다."""
        data = b"known source"
        manifest = {"schema": bundle.SCHEMA, "distribution": "internal_validation_only", "source_revision": "a" * 40,
                    "files": [{"path": "Code/src/a.py", "bytes": len(data),
                               "sha256": hashlib.sha256(data).hexdigest()}]}
        with TemporaryDirectory() as folder:
            root = Path(folder)

            def write(name, payload, metadata, duplicate=False):
                path = root / name
                with zipfile.ZipFile(path, "x") as archive:
                    bundle._write(archive, "Code/src/a.py", payload)
                    if duplicate:
                        bundle._write(archive, "code/src/A.py", payload)
                    bundle._write(archive, bundle.MANIFEST, bundle._json(metadata))
                return path

            first = write("one.zip", data, manifest)
            second = write("two.zip", data, manifest)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(bundle.verify(first)["files"], 1)
            with self.assertRaisesRegex(ValueError, "SHA256"):
                bundle.verify(write("changed.zip", b"x" * len(data), manifest))
            with self.assertRaisesRegex(ValueError, "멤버"):
                bundle.verify(write("duplicate.zip", data, manifest, True))
            unsafe = deepcopy(manifest)
            unsafe["files"][0]["path"] = "../a.py"
            with self.assertRaisesRegex(ValueError, "경로"):
                bundle.verify(write("unsafe.zip", data, unsafe))
            for name in ("Code/src/AUX.txt", "A//b", "C:/paths", "relative\\b"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    bundle._safe_name(name)

    def test_pe_imports_include_cpp_runtime_name(self):
        """! @brief GNU PE import에서 C++ 이름의 + 문자를 제외하지 않는다."""
        output = b"tracewave_gui.exe: file format pei-x86-64\r\n\tDLL Name: libstdc++-6.dll\r\n\tDLL Name: KERNEL32.dll\r\n"
        with patch("tools.internal_bundle_inputs.subprocess.check_output", return_value=output):
            self.assertEqual(_imports(Path("tracewave_gui.exe"), "objdump"), {"libstdc++-6.dll", "kernel32.dll"})
