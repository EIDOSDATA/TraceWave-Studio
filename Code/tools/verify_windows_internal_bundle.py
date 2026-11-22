"""! @brief ZIP 수신본을 실제 Windows에서 새 폴더와 새 Python으로 실행한다."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

if __package__:
    from .build_internal_bundle import verify
    from .internal_bundle_inputs import read_bytes
else:
    from build_internal_bundle import verify
    from internal_bundle_inputs import read_bytes


def install_compiler_runtime(source, destination, required):
    """! @brief 공식 공급처의 DLL을 고정 해시와 대조한 뒤 새 수신본에 연결한다."""
    if source is None:
        raise ValueError("공식 WinLibs 압축을 푼 mingw64/bin 경로가 필요합니다.")
    files = {}
    for name, digest in required.items():
        data = read_bytes(source / name)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"외부 WinLibs DLL의 SHA256이 다릅니다. {name}")
        files[name] = data
    for name, data in files.items():
        with (destination / name).open("xb") as output:
            output.write(data)


def smoke(archive, root, runtime=None):
    """! @brief 선택 worker 없이 새 작업 영역의 실제 GUI 편집, 저장과 서비스 재열기를 확인한다."""
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or sys.maxsize < 2**32:
        raise RuntimeError("Windows x64 CPython 3.12에서 실행하십시오.")
    if root.exists():
        raise FileExistsError(root)
    identity = verify(archive)
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("bundle-manifest.json"))
    required = manifest.get("external_compiler_runtime")
    if required and runtime is None:
        raise ValueError("--compiler-bin에 고정 WinLibs의 mingw64/bin 경로를 지정하십시오.")
    root.mkdir(parents=True)
    binding = root / "실제 배포 수신본"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(binding)
    code = binding / "Code"
    python_environment = root / "기본 파이썬"
    workspace = root / "새 작업 영역"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(python_environment)], check=True, timeout=90)
    python = python_environment / "Scripts/python.exe"
    executable = code / "build/windows-release/bin/tracewave_gui.exe"
    if required:
        install_compiler_runtime(runtime, executable.parent, required)
    report = root / "Windows 구동 검증.json"
    clean = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "RFAD_CAD_PYTHON", "RFAD_EXCHANGE_PYTHON"):
        clean.pop(name, None)
    windows = Path(os.environ["SystemRoot"])
    clean["PATH"] = str(windows / "System32") + os.pathsep + str(windows)
    version = subprocess.check_output([str(python), "-I", "-c",
        "import importlib.util,sys; assert not any(importlib.util.find_spec(n) for n in ('h5py','numpy','OCP')); print(sys.version.split()[0])"],
        env=clean, cwd=root, timeout=15, text=True).strip()
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.run([str(executable), "--python", str(python), "--source", str(code / "src"),
        "--workspace", str(workspace), "--canvas-smoke-test", "--smoke-report", str(report)],
        cwd=root, env=clean, capture_output=True, stdin=subprocess.DEVNULL,
        timeout=210, startupinfo=startup, check=False)
    if process.returncode != 0 or not report.is_file():
        raise RuntimeError(f"재열기 시험 실패 {process.returncode}; {process.stderr!r}; {report}")
    report_data = json.loads(report.read_bytes())
    if (not report_data["passed"] or report_data["service_sessions"] < 2 or
            not report_data["snapshot_id"] or report_data["revision_id"] != report_data["saved_revision"]):
        raise RuntimeError("새 작업 영역에서 저장 후 재열기 근거가 유효하지 않습니다.")
    result = {
        "archive": identity, "windows_new_extraction": True, "base_python": version,
        "native_path": "Windows System32 and Windows only", "optional_python_imports_absent": True,
        "no_optional_workers": True, "studio": report_data,
        "external_compiler_runtime_verified": bool(required),
    }
    (root / "실행 요약.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("windows_new_extraction", "base_python", "no_optional_workers")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("root", type=Path)
    parser.add_argument("--compiler-bin", type=Path)
    args = parser.parse_args()
    smoke(args.archive.resolve(), args.root.resolve(), args.compiler_bin)
