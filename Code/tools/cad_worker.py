"""! @brief 소유권 설정 후 받은 불변 입력으로만 CAD를 계산하는 격리 진입점이다."""

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys


def main() -> int:
    """! @brief stdin 시작 메시지 이전에는 native 라이브러리를 import하지 않는다."""
    raw_request = sys.stdin.buffer.readline(65537)
    if not raw_request.endswith(b"\n") or len(raw_request) > 65536:
        return 2
    request = json.loads(raw_request)
    if request.get("schema") != "rfad.cad-worker/0.1":
        return 2
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "src"))
    from rfad.application.canonical import canonical_bytes
    from rfad.application.cad_jobs import CadRuntime, file_hash
    from rfad.domain.errors import ProjectError

    result = {"schema": "rfad.cad-worker-result/0.1", "run_id": request["run_id"],
              "nonce": request["nonce"], "input_sha256": request["input_sha256"]}
    exit_code = 0
    try:
        expected = request["runtime"]
        if file_hash(Path(__file__)) != expected["entry_sha256"] or file_hash(Path(sys.executable)) != expected["python_sha256"] or CadRuntime.source_hash() != expected["source_sha256"]:
            raise ProjectError("E_VERSION", "worker의 실제 Python 또는 구현 hash가 실행 계획과 다릅니다.")
        runtime_raw = Path("runtime.json").read_bytes()
        if len(runtime_raw) > 128 * 1024 or hashlib.sha256(runtime_raw).hexdigest() != expected["manifest_sha256"]:
            raise ProjectError("E_HASH", "CAD 런타임 명세의 바이트가 다릅니다.")
        runtime = json.loads(runtime_raw)
        expected_python = runtime["python"]
        if (platform.python_implementation() != expected_python["implementation"]
                or ".".join(str(part) for part in sys.version_info[:2]) != expected_python["version_series"]
                or sys.platform != expected_python["platform"] or platform.machine().upper() != expected_python["architecture"].upper()):
            raise ProjectError("E_VERSION", "CAD worker의 Python/운영체제/CPU가 고정 명세와 다릅니다.")
        installed = {re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower(): distribution.version for distribution in importlib.metadata.distributions()}
        if any(re.match(r"^(pyqt|pyside|shiboken|qt|cq-editor)", name) for name in installed):
            raise ProjectError("E_UNSUPPORTED", "CAD worker 환경에 금지된 Qt 배포가 있습니다.")
        for package in runtime["packages"]:
            if installed.get(package["name"]) != package["version"]:
                raise ProjectError("E_VERSION", "CAD worker 패키지 버전이 고정 명세와 다릅니다: " + package["name"])
        if set(installed) - {package["name"] for package in runtime["packages"]} - {"pip", "setuptools", "wheel"}:
            raise ProjectError("E_VERSION", "CAD worker에 고정 명세 밖의 패키지가 설치되어 있습니다.")
        with Path("input.json").open("rb") as stream:
            payload = stream.read(128 * 1024 + 1)
        if len(payload) > 128 * 1024 or hashlib.sha256(payload).hexdigest() != request["input_sha256"]:
            raise ProjectError("E_HASH", "CAD worker 입력 파일 hash 또는 크기가 다릅니다.")
        projection = json.loads(payload)
        if canonical_bytes(projection) != payload or projection.get("run_id") != request["run_id"]:
            raise ProjectError("E_HASH", "CAD 입력의 정규 바이트 또는 실행 식별자가 다릅니다.")
        from rfad.adapters.cad.native import build_package

        result["package"] = build_package(projection, Path.cwd() / "output")
    except Exception as error:
        exit_code = 1
        result["error"] = error.diagnostic() if isinstance(error, ProjectError) else {"code": "E_GEOMETRY", "message_ko": str(error)[:2048]}
    encoded = canonical_bytes(result)
    if len(encoded) > 256 * 1024:
        return 3
    with Path("result.partial").open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace("result.partial", "result.json")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
