"""! @brief 닫힌 소스와 실제 설치/글꼴을 검증한 뒤 도면 형식 모듈을 실행한다."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys


def main():
    """! @brief 소유 프로세스의 시작 메시지를 받기 전에는 제품/native 모듈을 import하지 않는다."""
    raw = sys.stdin.buffer.readline(131073)
    if len(raw) > 131072 or not raw.endswith(b"\n"):
        return 2
    request = json.loads(raw)
    if request.get("schema") != "rfad.exchange-worker/0.1":
        return 2
    root = Path(__file__).resolve().parents[1]
    expected = request["runtime"]
    relative = "src/rfad/application/source_bundle.py"
    record = next(item for item in expected["code_files"] if item["path"] == relative)
    if type(record["bytes"]) is not int or not 0 < record["bytes"] <= 4 * 1024 * 1024:
        return 2
    with (root / relative).open("rb") as stream:
        bootstrap = stream.read(record["bytes"] + 1)
    if len(bootstrap) != record["bytes"] or hashlib.sha256(bootstrap).hexdigest() != record["sha256"]:
        return 2
    loader = {"__name__": "_rfad_exchange_bootstrap", "__file__": str(root / relative)}
    exec(compile(bootstrap, str(root / relative), "exec"), loader)
    loader["install_guard"](root, expected["source_bundle"], expected["code_files"])
    from rfad.application.source_bundle import source_hash
    from rfad.application.canonical import canonical_bytes
    from rfad.domain.errors import ProjectError
    from rfad.runtime_platform import machine_name

    result = {"schema": "rfad.exchange-worker-result/0.1", "run_id": request["run_id"],
              "nonce": request["nonce"], "input_sha256": request["input_sha256"]}
    code = 0
    try:
        if (source_hash(expected["code_files"]) != expected["source_sha256"]
                or hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() != expected["python_sha256"]
                or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != expected["entry_sha256"]):
            raise ProjectError("E_VERSION", "출력 worker 실행 소스 또는 Python hash가 다릅니다.")
        with (root / "runtime.json").open("rb") as stream:
            runtime_raw = stream.read(128 * 1024 + 1)
        if len(runtime_raw) > 128 * 1024 or hashlib.sha256(runtime_raw).hexdigest() != expected["manifest_sha256"]:
            raise ProjectError("E_HASH", "출력 runtime 명세 hash가 다릅니다.")
        runtime = json.loads(runtime_raw)
        python = runtime["python"]
        if (platform.python_implementation() != python["implementation"] or sys.platform != python["platform"]
                or machine_name(process=True).upper() != python["architecture"].upper()
                or ".".join(str(v) for v in sys.version_info[:2]) != python["version_series"]):
            raise ProjectError("E_VERSION", "출력 Python/OS/CPU가 고정 설치와 다릅니다.")
        installed = {re.sub(r"[-_.]+", "-", item.metadata["Name"]).lower(): item.version for item in importlib.metadata.distributions()}
        packages = {re.sub(r"[-_.]+", "-", item["name"]).lower(): item["version"] for item in runtime["packages"]}
        if any(installed.get(name) != version for name, version in packages.items()) or set(installed) - set(packages) - {"pip", "setuptools", "wheel"}:
            raise ProjectError("E_VERSION", "출력 패키지가 고정한 설치 명세와 다릅니다.")
        if runtime.get("qt_allowed") is not False or any(re.match(r"^(pyqt|pyside|shiboken|qt)", name) for name in installed):
            raise ProjectError("E_UNSUPPORTED", "출력 환경에 Qt를 허용하지 않습니다.")
        font_path = None
        if runtime.get("fonts"):
            font = runtime["fonts"][0]
            font_path = root / "fonts/primary.ttf"
            with font_path.open("rb") as stream:
                font_raw = stream.read(32 * 1024 * 1024 + 1)
            if len(font_raw) != font["bytes"] or hashlib.sha256(font_raw).hexdigest() != font["sha256"]:
                raise ProjectError("E_HASH", "봉인된 출력 글꼴 bytes가 다릅니다.")
        with (root / "input.json").open("rb") as stream:
            payload = stream.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024 or hashlib.sha256(payload).hexdigest() != request["input_sha256"]:
            raise ProjectError("E_HASH", "출력 입력 hash/크기가 다릅니다.")
        value = json.loads(payload)
        expected_schema = "rfad.pcb-import-input/0.1" if request["operation"] == "parse" else "rfad.exchange-input/0.1"
        if canonical_bytes(value) != payload or value.get("schema") != expected_schema:
            raise ProjectError("E_HASH", "출력 입력의 정규 바이트/profile이 다릅니다.")
        output = root / "output"
        if request["operation"] == "parse":
            from rfad.adapters.exchange.pcb import parse_package
            if value.get("run_id") != request["run_id"]:
                raise ProjectError("E_HASH", "PCB 입력 parser 실행 ID가 다릅니다.")
            records = value.get("files")
            if type(records) is not list or not 1 <= len(records) <= 40:
                raise ProjectError("E_RESOURCE", "PCB 입력은 1~40개 원문 파일이어야 합니다.")
            files = {}
            seen = set()
            total = 0
            for record in records:
                name = record.get("path")
                artifact = record.get("artifact", {})
                size = artifact.get("bytes")
                if (type(name) is not str or not 1 <= len(name) <= 120 or name in (".", "..")
                        or any(char in name for char in ("/", "\\", ":")) or any(ord(char) < 32 for char in name)
                        or name.casefold() in seen or type(size) is not int or not 0 < size <= 16 * 1024 * 1024):
                    raise ProjectError("E_SCHEMA", "PCB 원문 파일명/크기가 유효하지 않습니다.")
                seen.add(name.casefold())
                total += size
                if total > 16 * 1024 * 1024:
                    raise ProjectError("E_RESOURCE", "PCB 원문 합계는 16 MiB 이하입니다.")
                source = root / "input-files" / name
                stat = source.lstat()
                if source.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400 or not source.is_file() or stat.st_size != size:
                    raise ProjectError("E_HASH", "봉인 PCB 원문 파일의 종류/크기가 다릅니다.")
                with source.open("rb") as stream:
                    raw = stream.read(size + 1)
                if len(raw) != size or hashlib.sha256(raw).hexdigest() != artifact.get("sha256"):
                    raise ProjectError("E_HASH", "봉인 PCB 원문 파일의 바이트 hash가 다릅니다.")
                files[name] = raw
            parsed = canonical_bytes(parse_package(files, value["format"], value["options"]))
            if len(parsed) > 768 * 1024 or total + len(parsed) > 16 * 1024 * 1024:
                raise ProjectError("E_RESOURCE", "PCB parser 결과 768 KiB 또는 원문/결과 합계 16 MiB 상한을 초과했습니다.")
            output.mkdir()
            (output / "parse.json").write_bytes(parsed)
            result["parsed"] = {"path": "parse.json", "bytes": len(parsed), "sha256": hashlib.sha256(parsed).hexdigest()}
        elif value.get("profile") == "rfad.exchange.drawing/0.1":
            from rfad.adapters.exchange.drawing import generate, verify
        elif value.get("profile") in ("rfad.exchange.kicad-board/0.1", "rfad.exchange.kicad-footprint/0.1", "rfad.exchange.cam/0.1"):
            from rfad.adapters.exchange.pcb import generate, verify
        else:
            raise ProjectError("E_UNSUPPORTED", "지원하지 않는 교환 worker profile입니다.")
        if request["operation"] == "parse":
            pass
        elif request["operation"] == "generate":
            if value["run_id"] != request["run_id"]:
                raise ProjectError("E_HASH", "출력 실행 ID가 다릅니다.")
            output.mkdir()
            result["package"] = generate(value, output, font_path=font_path)
        elif request["operation"] == "verify":
            with (root / "verification-package.json").open("rb") as stream:
                package_raw = stream.read(256 * 1024 + 1)
            if len(package_raw) > 256 * 1024 or hashlib.sha256(package_raw).hexdigest() != request["package_sha256"]:
                raise ProjectError("E_HASH", "재검수할 원본 패키지의 hash가 다릅니다.")
            result["verification"] = verify(value, root / "original", json.loads(package_raw))
            output.mkdir()
            (output / "verification.json").write_bytes(canonical_bytes(result["verification"]))
        else:
            raise ProjectError("E_UNSUPPORTED", "지원하지 않는 출력 worker 작업입니다.")
    except Exception as error:
        code = 1
        result["error"] = error.diagnostic() if isinstance(error, ProjectError) else {"code": "E_GEOMETRY", "message_ko": str(error)[:2048]}
    encoded = canonical_bytes(result)
    if len(encoded) > 512 * 1024:
        return 3
    with (root / "result.partial").open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(root / "result.partial", root / "result.json")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
