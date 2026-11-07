"""! @brief 설치나 실행 환경 변경 없이 현재 개발 환경을 진단한다.

@details 패키지 메타데이터만 읽고 CAD, 수치 계산 및 해석기 모듈을 로드하지 않는다.
진단 결과는 실제 환경의 관찰 기록이며 의존성 잠금이나 물리 검증 증거가 아니다.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import locale
import math
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
from typing import Any, Sequence


DEFAULT_TIMEOUT_SECONDS = 5.0
REPORT_OUTPUT_LIMIT = 16_384
PACKAGE_NAMES = ("numpy", "cadquery", "openEMS", "scikit-rf")
TOOL_QUERIES = {
    "cmake": ("--version",),
    "ninja": ("--version",),
    "g++": ("--version",),
    "cl": (),
    "wsl": ("--version",),
}


def decode_output(data: bytes | str | None, prefer_utf16: bool = False) -> str:
    """! @brief 일반 도구의 UTF-8 출력과 Windows WSL의 UTF-16 출력을 해석한다."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    if len(data) % 2 == 0 and b"\x00" in data:
        return data.decode("utf-16-le", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        if prefer_utf16 and len(data) % 2 == 0:
            return data.decode("utf-16-le", errors="replace")
        return data.decode(locale.getpreferredencoding(False), errors="replace")


def binary_identity(executable: str) -> dict[str, Any]:
    """! @brief 확인한 실행 파일 하나의 크기와 SHA256을 읽고 접근 오류를 기록한다."""
    result: dict[str, Any] = {"path": executable, "status": "failed", "sha256": None}
    try:
        path = Path(executable)
        if not path.is_file():
            result["reason"] = "실행 파일을 일반 파일로 읽을 수 없습니다."
            return result
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        result.update(status="available", sha256=digest.hexdigest(), bytes=size)
    except OSError as error:
        result["reason"] = str(error)
    return result


def run_query(
    executable: str,
    arguments: Sequence[str],
    timeout: float,
    *,
    prefer_utf16: bool = False,
    accepted_exit_codes: tuple[int, ...] = (0,),
) -> dict[str, Any]:
    """! @brief 셸 없이 제한 시간 안에서 읽기 전용 도구 질의를 실행한다."""
    command = [executable, *arguments]
    result: dict[str, Any] = {
        "command": command,
        "status": "failed",
        "exit_code": None,
        "timeout_seconds": timeout,
    }
    stdout: bytes | str | None = b""
    stderr: bytes | str | None = b""
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            shell=False,
            timeout=timeout,
            check=False,
        )
        stdout, stderr = completed.stdout, completed.stderr
        result["exit_code"] = completed.returncode
        result["status"] = "available" if completed.returncode in accepted_exit_codes else "failed"
    except subprocess.TimeoutExpired as error:
        result["status"] = "timeout"
        stdout, stderr = error.stdout, error.stderr
    except OSError as error:
        result["reason"] = str(error)
    decoded_stdout = decode_output(stdout, prefer_utf16)
    decoded_stderr = decode_output(stderr, prefer_utf16)
    result["stdout"] = decoded_stdout[:REPORT_OUTPUT_LIMIT]
    result["stderr"] = decoded_stderr[:REPORT_OUTPUT_LIMIT]
    result["output_truncated"] = (
        len(decoded_stdout) > REPORT_OUTPUT_LIMIT or len(decoded_stderr) > REPORT_OUTPUT_LIMIT
    )
    return result


def probe_tool(name: str, arguments: Sequence[str], timeout: float) -> dict[str, Any]:
    """! @brief PATH에서 지정 도구를 찾고 버전 질의와 파일 식별 정보를 수집한다."""
    executable = shutil.which(name)
    if executable is None:
        return {"status": "missing", "executable_found": False, "path": None, "version": None}
    query = run_query(
        executable,
        arguments,
        timeout,
        prefer_utf16=name == "wsl",
        accepted_exit_codes=(0, 2) if name == "cl" else (0,),
    )
    lines = [line.strip() for line in (query["stdout"] + "\n" + query["stderr"]).splitlines() if line.strip()]
    return {
        "status": query["status"],
        "executable_found": True,
        "path": executable,
        "version": lines[0] if query["status"] == "available" and lines else None,
        "version_query": query,
        "binary": binary_identity(executable),
    }


def probe_packages() -> dict[str, dict[str, Any]]:
    """! @brief 현재 Python 환경의 배포 메타데이터만 읽어 패키지 설치 정보를 구한다."""
    result: dict[str, dict[str, Any]] = {}
    for name in PACKAGE_NAMES:
        item: dict[str, Any] = {"status": "missing", "version": None, "import_test": "not_run"}
        try:
            item["version"] = metadata.version(name)
            item["status"] = "available"
        except metadata.PackageNotFoundError:
            pass
        except (OSError, ValueError) as error:
            item.update(status="failed", reason=str(error))
        result[name] = item
    return result


def probe_wsl(executable: str | None, timeout: float) -> dict[str, Any]:
    """! @brief WSL의 등록 목록과 상태만 조회하며 배포판을 시작하거나 변경하지 않는다."""
    if executable is None:
        return {"status": "missing", "registration_status": "unknown", "distributions": [], "guest_probe": "not_run"}
    quiet = run_query(executable, ("--list", "--quiet"), timeout, prefer_utf16=True)
    verbose = run_query(executable, ("--list", "--verbose"), timeout, prefer_utf16=True)
    status = run_query(executable, ("--status",), timeout, prefer_utf16=True)
    distributions: list[dict[str, Any]] = []
    registration_status = "unknown"
    if quiet["status"] == "available" and not quiet["output_truncated"]:
        names = [line.strip() for line in quiet["stdout"].splitlines() if line.strip()]
        registration_status = "registered" if names else "none"
        for name in names:
            item: dict[str, Any] = {"name": name, "wsl_version": None, "state_text": None, "default": None}
            if verbose["status"] == "available":
                for line in verbose["stdout"].splitlines():
                    match = re.fullmatch(r"\s*(\*)?\s*" + re.escape(name) + r"\s+(.+?)\s+([12])\s*", line)
                    if match is not None:
                        item.update(wsl_version=int(match.group(3)), state_text=match.group(2), default=bool(match.group(1)))
                        break
            distributions.append(item)
    return {
        "status": quiet["status"],
        "registration_status": registration_status,
        "distributions": distributions,
        "queries": {"list_quiet": quiet, "list_verbose": verbose, "status": status},
        "guest_probe": "not_run",
        "note": "등록 상태만 조회했습니다. guest 시작, 설치, 실행 가능성 및 solver 검증은 수행하지 않았습니다.",
    }


def build_report(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """! @brief 현재 환경의 관찰 정보를 수집하며 준비 완료나 물리 검증 합격을 선언하지 않는다.

    @param timeout 각 외부 질의의 최대 대기 시간(초).
    @return 의존성 잠금과 구별된 JSON 직렬화 가능 진단 기록.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("질의 제한 시간은 유한한 양수여야 합니다.")
    tools = {name: probe_tool(name, arguments, timeout) for name, arguments in TOOL_QUERIES.items()}
    return {
        "report_schema": "rfad.doctor/0.1",
        "scope": "actual_environment",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dependency_lock": False,
        "note": "현재 환경의 조회 기록입니다. 호환성 보장, 의존성 잠금 또는 제품 검증 합격 기록이 아닙니다.",
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "process_bits": struct.calcsize("P") * 8,
            "executable": binary_identity(sys.executable),
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "platform": sys.platform,
        },
        "tools": tools,
        "python_package_scope": "current_interpreter_distribution_metadata_only",
        "python_packages": probe_packages(),
        "wsl": probe_wsl(tools["wsl"]["path"], timeout),
        "verification": {
            "worker_smoke": "not_run",
            "cad": "not_run",
            "physics": "not_run",
            "gui_performance": "not_run",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """! @brief JSON 진단 보고서를 출력하고 요청한 경우 UTF-8 파일로 저장한다.

    @param argv 프로그램 이름을 제외한 명령행 인수. 생략하면 현재 프로세스 인수를 사용한다.
    @return 보고서 생성 성공은 0, 출력 파일 저장 실패는 1이다. 누락 도구는 보고서 상태로 구분한다.
    """
    parser = argparse.ArgumentParser(description="설치나 환경 변경 없이 현재 개발 환경을 JSON으로 진단합니다.")
    parser.add_argument("--output", type=Path, help="UTF-8 보고서를 저장할 경로")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="외부 질의별 제한 시간(초)")
    options = parser.parse_args(argv)
    if not math.isfinite(options.timeout) or options.timeout <= 0:
        parser.error("--timeout은 유한한 양수여야 합니다.")
    report = build_report(options.timeout)
    serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    exit_code = 0
    if options.output is not None:
        try:
            options.output.parent.mkdir(parents=True, exist_ok=True)
            options.output.write_text(serialized, encoding="utf-8", newline="\n")
        except OSError as error:
            print(f"진단 보고서 저장 실패: {error}", file=sys.stderr)
            exit_code = 1
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(serialized.encode("utf-8"))
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write(serialized)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
