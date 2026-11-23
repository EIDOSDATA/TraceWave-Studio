"""! @brief Windows openEMS와 전용 Python을 고정 자산에서 설치하고 실제 DLL을 감사한다."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
from zipfile import ZipFile


CODE = Path(__file__).resolve().parents[1]
PROFILE_FILE = CODE / "runtime_profiles/python-openems-windows-x64.json"
ROOT = CODE / ".local/openems-windows"


def sha256(path):
    """! @brief 큰 배포 원본을 메모리에 복사하지 않고 해시를 확인한다."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def validate(path, digest):
    """! @brief 해시가 다른 외부 파일을 압축 해제하거나 실행하지 않는다."""
    if sha256(path) != digest:
        raise ValueError(f"고정 SHA-256과 다릅니다. {path.name}")


def retrieve(cache, asset):
    """! @brief 공식 자산을 가져와 전체 해시를 검증한 뒤 설치 캐시에 연결한다."""
    name = asset["url"].rsplit("/", 1)[1]
    path = cache / name
    if not path.is_file():
        print(f"다운로드 중  {name}", flush=True)
        with TemporaryDirectory(prefix=".openems-fetch-", dir=cache) as directory:
            pending = Path(directory) / name
            request = Request(asset["url"], headers={"User-Agent": "TraceWaveStudio-Setup"})
            with urlopen(request, timeout=90) as response, pending.open("xb") as target:
                shutil.copyfileobj(response, target)
            validate(pending, asset["sha256"])
            pending.replace(path)
    validate(path, asset["sha256"])
    return path


def expand(archive, target):
    """! @brief 압축 해제 도중 중단되면 기존 런타임 경로를 유지한다."""
    if target.exists():
        return
    with TemporaryDirectory(prefix=".openems-expand-", dir=target.parent) as directory:
        unpacked = Path(directory) / "asset"
        with ZipFile(archive) as source:
            source.extractall(unpacked)
        unpacked.rename(target)


def install(profile, cache):
    """! @brief Studio의 3.12 서비스와 분리해 cp314 native worker를 구성한다."""
    ROOT.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    python = ROOT / "python/tools/python.exe"
    expand(retrieve(cache, profile["python"]), ROOT / "python")
    expand(retrieve(cache, profile["native"]), ROOT / "native")
    worker = ROOT / "venv/Scripts/python.exe"
    if not worker.is_file():
        subprocess.run([str(python), "-I", "-m", "venv", str(ROOT / "venv")], check=True)
    pip = [str(worker), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check"]
    subprocess.run([*pip, "install", "--require-hashes", "--only-binary=:all:",
                    "-r", str(PROFILE_FILE.with_suffix(".txt"))], check=True)
    wheels = []
    for name, digest in profile["native"]["wheels"].items():
        wheel = ROOT / "native/openEMS/python" / name
        validate(wheel, digest)
        wheels.append(str(wheel))
    subprocess.run([*pip, "install", "--no-index", "--no-deps", *wheels], check=True)
    subprocess.run([*pip, "check"], check=True)
    subprocess.run([str(worker), "-I", "-B", "-X", "utf8", str(Path(__file__).resolve()), "--audit"], check=True)


def audit(profile):
    """! @brief 실제 Windows 모듈 경로를 설치된 실행 파일과 패키지 봉인에 연결한다."""
    if (platform.python_version() != profile["python"]["validated_version"]
            or platform.machine() != profile["python"]["architecture"]
            or Path(sys.prefix).resolve() != (ROOT / "venv").resolve()):
        raise ValueError("고정 Windows openEMS worker Python이 필요합니다.")
    sys.path.insert(0, str(CODE / "src"))
    from rfad.adapters.solvers.openems.windows import mapped_files

    native = ROOT / "native/openEMS"
    with os.add_dll_directory(str(native)):
        import CSXCAD
        import openEMS

        if CSXCAD.__version__ != "0.7.0" or openEMS.__version__ != "0.37.0":
            raise ValueError("실제로 읽힌 Windows binding 버전이 다릅니다.")
        actual = mapped_files("self")
        if not any(path.name.lower() == "openems.dll" for path in actual):
            raise ValueError("실제로 로딩한 Windows openEMS.dll이 없습니다.")
        if any(re.match(r"(?:lib)?qt[0-9]", path.name, re.IGNORECASE) for path in actual):
            raise ValueError("Windows 해석 worker에서 Qt를 로딩했습니다.")
        files = {path.resolve() for path in native.rglob("*") if path.suffix.lower() in (".dll", ".exe")}
        for module in (CSXCAD, openEMS):
            files.update(path.resolve() for path in Path(module.__file__).parent.rglob("*.pyd"))
    installed = {re.sub(r"[-_.]+", "-", item.metadata["Name"]).lower(): item.version
                 for item in importlib.metadata.distributions()}
    if any(installed.get(item["name"]) != item["version"] for item in profile["packages"]):
        raise ValueError("고정 Windows openEMS wheel 버전이 다릅니다.")
    report = {"schema": "rfad.runtime.openems-windows-audit/0.1", "status": "passed", "qt_found": False,
              "packages": installed,
              "native_files": [{"path": str(path), "sha256": sha256(path)} for path in sorted(files)]}
    pending = ROOT / "native-audit.partial.json"
    pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(ROOT / "native-audit.json")
    print("Windows openEMS 0.37.0 / CSXCAD 0.7.0 native 감사 완료", flush=True)


def main():
    """! @brief Windows 공급 자산 설치 또는 격리 Python의 감사를 선택한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--cache", type=Path)
    options.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine() != "AMD64":
        parser.error("Windows x64에서 실행하십시오.")
    profile = json.loads(PROFILE_FILE.read_bytes())
    if args.audit:
        audit(profile)
    else:
        install(profile, args.cache.resolve())


if __name__ == "__main__":
    main()
