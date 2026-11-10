"""! @brief 환경 구성에서 Qt 유입과 기존 계정/소스 변경을 설치 전에 차단한다."""

import importlib.util
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


_PATH = Path(__file__).resolve().parents[1] / "tools/setup_openems_wsl.py"
_SPEC = importlib.util.spec_from_file_location("rfad_wsl_setup_test", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class BuildGuardTests(unittest.TestCase):
    """! @brief 실패 경로가 패키지 설치나 소스 checkout 변경을 수행하지 않는지 확인한다."""

    def builder(self):
        """! @brief 외부 프로세스 없이 실제 고정 profile을 검사할 구성을 만든다."""
        builder = _MODULE.Builder.__new__(_MODULE.Builder)
        builder.profile = json.loads(_MODULE.PROFILE.read_text(encoding="utf-8"))
        builder.root = builder.profile["root"]
        builder.source = builder.root + "/openEMS-Project"
        return builder

    def test_qt_transitive_dependency_blocks_apt_install(self):
        """! @brief 직접 요청하지 않은 Qt 전이 패키지도 실제 설치 전에 거부한다."""
        builder = self.builder()
        calls = []
        def run(arguments, **options):
            calls.append(arguments)
            return "Inst libvtk9-dev (9.1 Ubuntu)\nInst libqt5core5t64 (5.15 Ubuntu)\n" if "--simulate" in arguments else ""
        builder.run = run
        with self.assertRaisesRegex(RuntimeError, "Qt found"):
            builder.dependencies(True)
        self.assertFalse(any("-y" in call for call in calls))

    def test_missing_packages_are_not_installed_without_explicit_option(self):
        """! @brief 준비 확인 모드에서는 누락 패키지를 자동으로 추가하지 않는다."""
        builder = self.builder()
        calls = []
        def run(arguments, **options):
            calls.append(arguments)
            return "Inst cmake (3.28 Ubuntu)\n"
        builder.run = run
        with self.assertRaisesRegex(RuntimeError, "Missing native dependencies"):
            builder.dependencies(False)
        self.assertEqual(len(calls), 1)
        self.assertIn("--simulate", calls[0])

    def test_modified_source_is_not_reset_by_submodule_update(self):
        """! @brief 이미 수정된 원본을 고정 commit 복구 명목으로 덮어쓰지 않는다."""
        builder = self.builder()
        calls = []
        def run(arguments, **options):
            calls.append(arguments)
            if arguments[0] == "python3":
                return "1\n"
            if "rev-parse" in arguments:
                return builder.profile["commit"] + "\n"
            if "status" in arguments:
                return " M CMakeLists.txt\n"
            return ""
        builder.run = run
        with self.assertRaisesRegex(RuntimeError, "Tracked meta source was modified"):
            builder.checkout()
        self.assertFalse(any("update" in call or "checkout" in call for call in calls))

    def test_existing_privileged_or_wrong_home_user_is_not_repurposed(self):
        """! @brief 이름만 같은 다른 계정을 개발용 계정으로 사용하거나 바꾸지 않는다."""
        profile = self.builder().profile
        for entry in ("tracewave:x:0:0::/home/tracewave:/bin/bash\n", "tracewave:x:1000:1000::/srv/shared:/bin/bash\n"):
            with self.subTest(entry=entry):
                result = subprocess.CompletedProcess([], 0, entry.encode(), b"")
                with patch.object(_MODULE.subprocess, "run", return_value=result) as run:
                    with self.assertRaisesRegex(RuntimeError, "Existing user differs"):
                        _MODULE.ensure_user(profile)
                    self.assertEqual(run.call_count, 1)

    def test_untracked_cmake_override_is_rejected_before_submodule_update(self):
        """! @brief Git 미추적 localConfig의 자동 포함으로 고정 빌드가 달라지는 것을 차단한다."""
        builder = self.builder()
        calls = []
        override = builder.source + "/CSXCAD/localConfig.cmake"
        def run(arguments, **options):
            calls.append(arguments)
            if arguments[0] == "python3":
                if "lexists" in arguments[2]:
                    self.assertIn(override, arguments)
                    self.assertIn(builder.source + "/openEMS/localConfig.cmake", arguments)
                    return json.dumps([override])
                return "1\n"
            if "rev-parse" in arguments:
                return builder.profile["commit"] + "\n"
            return ""
        builder.run = run
        with self.assertRaisesRegex(RuntimeError, "Unpinned localConfig.cmake"):
            builder.checkout()
        self.assertFalse(any("update" in call or "checkout" in call for call in calls))

    def vtk_report(self):
        """! @brief 원본과 설치 위치에 결합된 작은 VTK 근거를 생성한다."""
        profile = json.loads((_MODULE.CODE / "runtime_profiles/vtk-headless.json").read_text(encoding="utf-8"))
        prefix = self.builder().profile["vtk_prefix"]
        report = {
            "schema": "rfad.runtime.vtk-build/0.1", "status": "passed",
            "version": profile["version"], "commit": profile["commit"],
            "source_archive_sha256": profile["source_archive_sha256"], "prefix": prefix,
            "library_count": 1, "qt_dynamic_dependencies": [],
            "libraries": [{"name": "libvtkIOXML-9.3.so.9.3", "sha256": "a" * 64}],
        }
        return report, profile, prefix

    def test_vtk_reuse_checks_source_identity_and_prefix(self):
        """! @brief 다른 소스나 다른 설치의 과거 성공 보고서를 재사용하지 않는다."""
        report, profile, prefix = self.vtk_report()
        _MODULE.validate_vtk_report(report, profile, prefix)
        for field, value in (("status", "failed"), ("commit", "0" * 40), ("source_archive_sha256", "0" * 64), ("version", "9.9.9"), ("prefix", "/another/runtime")):
            changed = deepcopy(report)
            changed[field] = value
            with self.subTest(field=field):
                with self.assertRaises(RuntimeError):
                    _MODULE.validate_vtk_report(changed, profile, prefix)

    def test_vtk_inventory_must_be_complete_and_qt_free(self):
        """! @brief 빈 목록, 중복, Qt, 잘못된 파일 해시를 성공 근거로 받지 않는다."""
        report, profile, prefix = self.vtk_report()
        changes = [
            {"libraries": [], "library_count": 0},
            {"libraries": report["libraries"] * 2, "library_count": 2},
            {"libraries": [{"name": "libvtkGUISupportQt.so", "sha256": "a" * 64}]},
            {"libraries": [{"name": "libvtkIOXML.so", "sha256": "not-a-hash"}]},
            {"qt_dynamic_dependencies": ["libQt5Core.so"]},
            {"library_count": 99},
        ]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(RuntimeError):
                    _MODULE.validate_vtk_report({**report, **change}, profile, prefix)
        with self.assertRaises(RuntimeError):
            _MODULE.validate_vtk_report([], profile, prefix)

    def test_skipped_vtk_build_still_requires_verified_report(self):
        """! @brief 설정 파일만 존재하는 미검증 VTK prefix의 재사용을 거부한다."""
        builder = self.builder()
        report, _, prefix = self.vtk_report()
        builder.vtk = prefix
        expected_path = prefix.rsplit("/", 1)[0] + "/build-report.json"
        def read(arguments, **options):
            self.assertEqual(arguments, ["cat", expected_path])
            return json.dumps(report)
        builder.run = read
        self.assertEqual(builder.verify_vtk(), expected_path)
        report["commit"] = "0" * 40
        with self.assertRaises(RuntimeError):
            builder.verify_vtk()


if __name__ == "__main__":
    unittest.main()
