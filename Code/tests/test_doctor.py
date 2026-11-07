"""! @brief 환경 진단의 읽기 전용 질의, 오류 처리 및 인코딩 계약을 검증한다."""

import builtins
from contextlib import redirect_stdout
import hashlib
import importlib
from importlib import metadata
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rfad.cli import doctor


class DoctorTests(unittest.TestCase):
    """! @brief 실제 도구 설치나 배포판 시작 없이 환경 진단 동작을 검증한다."""

    def test_utf16_korean_output(self):
        """! @brief WSL의 BOM 유무와 한국어 문자를 원문으로 복원한다."""
        text = "  NAME       상태        VERSION\r\n* Ubuntu     중지됨      2\r\n"
        for encoding in ("utf-16", "utf-16-le", "utf-8"):
            with self.subTest(encoding=encoding):
                self.assertEqual(doctor.decode_output(text.encode(encoding), True), text)

    def test_query_uses_argument_array_and_no_shell(self):
        """! @brief 공백과 한국어가 있는 실행 경로를 셸 문자열로 결합하지 않는다."""
        path = "C:\\개발 도구\\cmake.exe"
        completed = subprocess.CompletedProcess([path], 0, b"cmake version 4.3.2\n", b"")
        with patch.object(doctor.subprocess, "run", return_value=completed) as run:
            result = doctor.run_query(path, ("--version",), 2.0)
        self.assertEqual(result["status"], "available")
        self.assertEqual(run.call_args.args[0], [path, "--version"])
        self.assertIs(run.call_args.kwargs["shell"], False)
        self.assertEqual(run.call_args.kwargs["timeout"], 2.0)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_timeout_retains_partial_output(self):
        """! @brief 시간 초과를 일반 누락과 구별하고 이미 받은 출력을 보존한다."""
        error = subprocess.TimeoutExpired(["wsl.exe", "--status"], 1, output="조회 중".encode("utf-16"))
        with patch.object(doctor.subprocess, "run", side_effect=error):
            result = doctor.run_query("wsl.exe", ("--status",), 1, prefer_utf16=True)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["stdout"], "조회 중")
        self.assertIsNone(result["exit_code"])

    def test_nonzero_exit_is_failed(self):
        """! @brief 경로 발견과 버전 질의 성공을 구별한다."""
        completed = subprocess.CompletedProcess(["tool"], 7, b"", b"cannot start")
        with patch.object(doctor.subprocess, "run", return_value=completed):
            result = doctor.run_query("tool", ("--version",), 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 7)

    def test_missing_tool_is_not_executed(self):
        """! @brief PATH에 없는 도구는 다른 경로 탐색이나 실행 없이 누락으로 기록한다."""
        with patch.object(doctor.shutil, "which", return_value=None), patch.object(doctor.subprocess, "run") as run:
            result = doctor.probe_tool("cmake", ("--version",), 1)
        self.assertEqual(result["status"], "missing")
        self.assertFalse(result["executable_found"])
        run.assert_not_called()

    def test_binary_hash_and_permission_error(self):
        """! @brief 단일 파일의 해시를 확인하고 읽기 권한 오류를 보고서로 반환한다."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "실행 도구.bin"
            path.write_bytes(b"known executable bytes")
            identity = doctor.binary_identity(str(path))
            self.assertEqual(identity["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            with patch.object(Path, "open", side_effect=PermissionError("읽기 거부")):
                failed = doctor.binary_identity(str(path))
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["sha256"])

    def test_packages_use_metadata_without_heavy_imports(self):
        """! @brief 설치 메타데이터 조회가 수치 계산 및 CAD 모듈을 import하지 않음을 확인한다."""
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            """! @brief 무거운 모듈 import를 발견하면 시험을 실패시킨다."""
            if name.split(".")[0].lower() in {"numpy", "cadquery", "openems", "skrf", "vtk"}:
                raise AssertionError(f"금지된 import: {name}")
            return original_import(name, *args, **kwargs)

        def package_version(name):
            """! @brief 한 패키지의 메타데이터와 나머지 패키지의 누락을 재현한다."""
            if name == "numpy":
                return "2.0.0"
            raise metadata.PackageNotFoundError(name)

        with patch.object(builtins, "__import__", side_effect=guarded_import), patch.object(doctor.metadata, "version", side_effect=package_version):
            importlib.reload(doctor)
            result = doctor.probe_packages()
        self.assertEqual(result["numpy"]["status"], "available")
        self.assertEqual(result["numpy"]["import_test"], "not_run")
        self.assertEqual(result["cadquery"]["status"], "missing")

    def test_wsl_queries_do_not_start_distributions(self):
        """! @brief WSL 목록과 상태만 조회하고 등록된 배포판의 버전을 해석한다."""
        def query(executable, arguments, timeout, **kwargs):
            """! @brief 읽기 전용 WSL 질의만 허용하는 응답을 제공한다."""
            outputs = {
                ("--list", "--quiet"): "Ubuntu 개발\r\n",
                ("--list", "--verbose"): "  NAME           STATE       VERSION\r\n* Ubuntu 개발    중지됨      2\r\n",
                ("--status",): "기본 버전: 2\r\n",
            }
            return {"status": "available", "stdout": outputs[tuple(arguments)], "output_truncated": False}

        with patch.object(doctor, "run_query", side_effect=query) as run:
            result = doctor.probe_wsl("C:\\Windows\\System32\\wsl.exe", 1)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(result["registration_status"], "registered")
        self.assertEqual(result["distributions"], [{"name": "Ubuntu 개발", "wsl_version": 2, "state_text": "중지됨", "default": True}])
        self.assertEqual(result["guest_probe"], "not_run")

    def test_empty_wsl_registration_and_failed_query_are_distinct(self):
        """! @brief 배포판 없음과 목록 조회 실패를 혼동하지 않는다."""
        for status, expected in (("available", "none"), ("failed", "unknown")):
            with self.subTest(status=status), patch.object(doctor, "run_query", return_value={"status": status, "stdout": "", "output_truncated": False}):
                result = doctor.probe_wsl("wsl.exe", 1)
            self.assertEqual(result["registration_status"], expected)

    def test_report_does_not_claim_runtime_validation(self):
        """! @brief 환경 관찰 결과를 의존성 잠금이나 제품 검증 합격으로 표시하지 않는다."""
        with patch.object(doctor.shutil, "which", return_value=None), patch.object(doctor, "binary_identity", return_value={"status": "available"}), patch.object(doctor.metadata, "version", side_effect=metadata.PackageNotFoundError):
            result = doctor.build_report()
        self.assertEqual(result["scope"], "actual_environment")
        self.assertFalse(result["dependency_lock"])
        self.assertEqual(set(result["verification"].values()), {"not_run"})
        self.assertEqual(result["wsl"]["status"], "missing")

    def test_main_writes_utf8_report(self):
        """! @brief 한글과 공백이 있는 출력 경로에 JSON을 저장하고 같은 내용을 출력한다."""
        report = {"scope": "actual_environment", "note": "환경 조회"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "진단 자료" / "환경.json"
            output = io.StringIO()
            with patch.object(doctor, "build_report", return_value=report), redirect_stdout(output):
                exit_code = doctor.main(["--output", str(path)])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), report)


if __name__ == "__main__":
    unittest.main()
