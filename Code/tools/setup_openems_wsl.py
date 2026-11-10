"""! @brief 전용 WSL 배포에서 Qt 없는 openEMS 개발 환경을 재현한다.

@details Windows에서 실행한다. 소스와 Python wheel은 고정하고 Ubuntu 패키지의
실제 버전은 기록한다. 기존 배포/경로를 삭제하거나 시스템 전체를 업그레이드하지 않는다.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


CODE = Path(__file__).resolve().parents[1]
PROFILE = CODE / "runtime_profiles/openems-wsl-build.json"
QT_PATTERN = re.compile(r"(?:libqt[456]|^qt[456b-]|pyqt|pyside|shiboken|appcsxcad|qcsxcad)", re.IGNORECASE)


def validate_vtk_report(report: dict, profile: dict, prefix: str) -> None:
    """! @brief VTK 재사용 근거를 고정 원본과 설치 위치에 대조한다."""
    if type(report) is not dict:
        raise RuntimeError("VTK build report must be an object.")
    expected = {
        "schema": "rfad.runtime.vtk-build/0.1", "status": "passed",
        "version": profile["version"], "commit": profile["commit"],
        "source_archive_sha256": profile["source_archive_sha256"], "prefix": prefix,
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise RuntimeError("VTK build report differs from the pinned source or installation prefix.")
    libraries = report.get("libraries")
    if not isinstance(libraries, list) or not libraries or report.get("library_count") != len(libraries):
        raise RuntimeError("VTK build report has no complete library inventory.")
    names = []
    for library in libraries:
        name = library.get("name", "") if isinstance(library, dict) else ""
        digest = library.get("sha256", "") if isinstance(library, dict) else ""
        if type(name) is not str or "/" in name or "\\" in name or not name.startswith("libvtk") or ".so" not in name or re.search("qt", name, re.IGNORECASE):
            raise RuntimeError("Invalid or forbidden VTK library in build report.")
        if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError("VTK library hash is missing or invalid.")
        names.append(name)
    if len(set(names)) != len(names) or report.get("qt_dynamic_dependencies") != []:
        raise RuntimeError("VTK build report contains duplicate libraries or Qt dependencies.")


def ensure_user(profile: dict) -> None:
    """! @brief 전용 배포의 일반 사용자를 준비하고 기존 계정의 home을 검증한다."""
    command = ["wsl.exe", "-d", profile["distribution"], "-u", "root", "--exec"]
    probe = subprocess.run([*command, "getent", "passwd", profile["user"]], capture_output=True, timeout=30)
    if probe.returncode == 2:
        subprocess.run([*command, "/usr/sbin/useradd", "--create-home", "--shell", "/bin/bash", profile["user"]], check=True, timeout=30)
        probe = subprocess.run([*command, "getent", "passwd", profile["user"]], capture_output=True, check=True, timeout=30)
    elif probe.returncode != 0:
        raise RuntimeError("Cannot inspect the dedicated Linux user.")
    fields = probe.stdout.decode("utf-8").strip().split(":")
    if len(fields) != 7 or fields[2] == "0" or fields[5] != "/home/tracewave":
        raise RuntimeError("Existing user differs from the dedicated non-root development profile.")


class Builder:
    """! @brief 셸 문자열 대신 명시적 인수로 WSL의 제한된 개발 경로를 구성한다."""

    def __init__(self, log, jobs: int):
        """! @brief 고정 배포와 소스 profile을 읽는다."""
        self.profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.log = log
        self.jobs = jobs
        self.root = self.profile["root"]
        self.prefix = self.profile["prefix"]
        self.vtk = self.profile["vtk_prefix"]
        self.source = self.root + "/openEMS-Project"
        self.python = self.root + "/openems-venv/bin/python"
        self.code = self.run(["wslpath", "-u", str(CODE)]).strip()

    def run(self, arguments: list[str], *, root: bool = False, check: bool = True, capture: bool = True) -> str:
        """! @brief 실행 인수와 결과를 기록하고 오류를 다음 단계로 넘기지 않는다."""
        user = "root" if root else self.profile["user"]
        args = ["wsl.exe", "-d", self.profile["distribution"], "-u", user, "--exec", *arguments]
        self.log.write((json.dumps(args, ensure_ascii=False) + "\n").encode("utf-8"))
        self.log.flush()
        if capture:
            result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            self.log.write(result.stdout)
            output = result.stdout.decode("utf-8", errors="replace")
        else:
            result = subprocess.run(args, stdout=self.log, stderr=subprocess.STDOUT, timeout=7200)
            output = ""
        self.log.flush()
        if check and result.returncode != 0:
            raise RuntimeError(f"Command failed ({result.returncode}): {arguments[0]}. Inspect setup-openems.log.")
        return output

    def dependencies(self, install: bool) -> None:
        """! @brief 설치 전 전이 의존성의 Qt 유입을 검사하고 필요한 패키지만 추가한다."""
        if install:
            self.run(["apt-get", "update"], root=True, capture=False)
        packages = self.profile["system_dependencies"]
        plan = self.run(["apt-get", "--simulate", "--no-install-recommends", "install", *packages], root=True)
        names = re.findall(r"^Inst ([^ ]+)", plan, re.MULTILINE)
        if any(QT_PATTERN.search(name) for name in names):
            raise RuntimeError("Qt found in apt installation plan; nothing installed.")
        if names and not install:
            raise RuntimeError("Missing native dependencies; rerun with --install-dependencies after reviewing the plan log.")
        if install:
            self.run(["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "-y", "--no-install-recommends", "install", *packages], root=True, capture=False)
        installed = self.run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}\t${binary:Package}\t${Version}\n"])
        if any(QT_PATTERN.search(line.split("\t")[1]) for line in installed.splitlines() if line.startswith("ii\t") or line.startswith("ii \t")):
            raise RuntimeError("Qt is installed in the dedicated distribution; audit the environment before proceeding.")
        (CODE / ".local/wsl/dpkg-installed.tsv").write_text(installed, encoding="utf-8")

    def checkout(self) -> None:
        """! @brief 배포 태그와 실제 commit/submodule이 고정 profile과 같은지 확인한다."""
        self.run(["mkdir", "-p", self.root])
        exists = self.run(["python3", "-c", "import os,sys;print(int(os.path.exists(sys.argv[1])))", self.source]).strip()
        if exists == "0":
            self.run(["git", "clone", "--branch", self.profile["tag"], "--depth", "1", self.profile["repository"], self.source], capture=False)
        actual = self.run(["git", "-C", self.source, "rev-parse", "HEAD"]).strip()
        if actual != self.profile["commit"]:
            raise RuntimeError("Existing source commit differs; no automatic checkout or overwrite performed.")
        if self.run(["git", "-C", self.source, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all"]).strip():
            raise RuntimeError("Tracked meta source was modified; inspect it before rebuilding.")
        overrides = self.run([
            "python3", "-c", "import json,os,sys;print(json.dumps([p for p in sys.argv[1:] if os.path.lexists(p)]))",
            self.source + "/localConfig.cmake",
            *[self.source + "/" + name + "/localConfig.cmake" for name in self.profile["submodules"]],
        ])
        if json.loads(overrides):
            raise RuntimeError("Unpinned localConfig.cmake override exists; inspect it before rebuilding.")
        for name, expected in self.profile["submodules"].items():
            current = self.run(["git", "-C", self.source, "ls-tree", "HEAD", name]).split()
            if len(current) != 4 or current[2] != expected:
                raise RuntimeError("Pinned submodule tree differs from profile: " + name)
            status = self.run(["git", "-C", self.source, "submodule", "status", name]).strip()
            if status.startswith("+") or status.startswith("U"):
                raise RuntimeError("Existing submodule checkout differs; no automatic overwrite: " + name)
            if not status.startswith("-") and self.run(["git", "-C", self.source + "/" + name, "status", "--porcelain", "--untracked-files=no"]).strip():
                raise RuntimeError("Tracked submodule source was modified: " + name)
        self.run(["git", "-C", self.source, "submodule", "update", "--init", "--depth", "1", *self.profile["submodules"]], capture=False)
        for name, expected in self.profile["submodules"].items():
            actual = self.run(["git", "-C", self.source + "/" + name, "rev-parse", "HEAD"]).strip()
            if actual != expected:
                raise RuntimeError("Source submodule mismatch: " + name)

    def build_native(self, name: str) -> None:
        """! @brief GUI 구성요소 없이 각 고정 C++ 라이브러리를 순서대로 빌드한다."""
        build = self.root + "/build-" + name
        flags = ["-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_INSTALL_PREFIX=" + self.prefix]
        if name != "fparser":
            flags += ["-DFPARSER_ROOT_DIR=" + self.prefix, "-DCSXCAD_ROOT_DIR=" + self.prefix, "-DVTK_DIR=" + self.vtk + "/lib/cmake/vtk-9.3"]
        self.run(["cmake", "-S", self.source + "/" + name, "-B", build, "-G", "Ninja", *flags], capture=False)
        self.run(["cmake", "--build", build, "--parallel", str(self.jobs)], capture=False)
        self.run(["cmake", "--install", build], capture=False)

    def python_environment(self) -> None:
        """! @brief 무거운 해석 패키지를 서비스 환경과 분리해 해시 고정으로 설치한다."""
        for name in ("service-venv", "openems-venv"):
            self.run(["python3", "-m", "venv", self.root + "/" + name], capture=False)
        self.run([self.python, "-m", "pip", "install", "--require-hashes", "--only-binary=:all:", "-r", self.code + "/runtime_profiles/" + self.profile["python_lock"]], capture=False)

    def bindings(self) -> None:
        """! @brief 네트워크 build isolation 없이 검증한 native 원본의 Python 확장을 설치한다."""
        env = ["env", "CSXCAD_INSTALL_PATH=" + self.prefix, "OPENEMS_INSTALL_PATH=" + self.prefix,
               "OPENEMS_NOSCM=1", "CSXCAD_NOSCM=1", "MPLBACKEND=Agg"]
        for name in ("CSXCAD", "openEMS"):
            self.run([*env, self.python, "-m", "pip", "install", "--no-deps", "--no-build-isolation", self.source + "/" + name + "/python"], capture=False)
        self.run([self.python, "-m", "pip", "check"], capture=False)
        imports = "import CSXCAD,openEMS;from importlib.metadata import version;print('CSXCAD',version('CSXCAD'),'openEMS',version('openEMS'))"
        self.run([*env, self.python, "-c", imports], capture=False)

    def verify_vtk(self) -> str:
        """! @brief 건너뛴 VTK 빌드도 완료 보고서와 고정 commit/hash가 있어야 재사용한다."""
        report_path = self.vtk.rsplit("/", 1)[0] + "/build-report.json"
        report = json.loads(self.run(["cat", report_path]))
        profile = json.loads((CODE / "runtime_profiles/vtk-headless.json").read_text(encoding="utf-8"))
        validate_vtk_report(report, profile, self.vtk)
        return report_path

    def audit(self) -> None:
        """! @brief 실제 Python 패키지와 native 의존성을 검사하여 로컬 근거를 남긴다."""
        vtk_report_path = self.verify_vtk()
        program = r'''
import hashlib, importlib.metadata as metadata, json, pathlib, re, subprocess, sys
import CSXCAD, openEMS
prefix, vtk, manifest_path, vtk_report_path = map(pathlib.Path, sys.argv[1:])
manifest = json.loads(manifest_path.read_text())
vtk_report = json.loads(vtk_report_path.read_text())
packages = {re.sub(r"[-_.]+", "-", x.metadata["Name"]).lower(): x.version for x in metadata.distributions()}
expected = {x["name"]: x["version"] for x in manifest["packages"]}
expected.update({"csxcad": "0.7.0", "openems": "0.37.0"})
assert not (set(packages) - set(expected) - {"pip"}), "Unpinned Python packages"
assert all(packages.get(k) == v for k,v in expected.items()), "Package version mismatch"
assert not any(re.match(r"^(qt|pyqt|pyside|shiboken)", k) for k in packages), "Qt Python package"
files = sorted({p.resolve() for p in prefix.rglob("*.so*") if p.is_file()})
files += sorted(p for p in (prefix/"bin").iterdir() if p.is_file())
files += sorted(pathlib.Path(CSXCAD.__file__).parent.glob("*.so"))
files += sorted(pathlib.Path(openEMS.__file__).parent.glob("*.so"))
vtk_files = sorted({p.resolve() for p in (vtk/"lib").glob("*.so*") if p.is_file()})
vtk_expected = {item["name"]: item["sha256"] for item in vtk_report["libraries"]}
vtk_actual = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in vtk_files}
assert vtk_actual == vtk_expected, "Installed VTK libraries differ from the verified build report"
files += vtk_files
records=[]
for p in files:
 if p.read_bytes()[:4] != b"\x7fELF":
  continue
 result = subprocess.run(["ldd", str(p)],capture_output=True,text=True,check=True)
 output = result.stdout + result.stderr
 assert "not found" not in output and not re.search(r"libQt[456]|libvtk[^\s]*Qt", output, re.IGNORECASE), output
 records.append({"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"ldd":result.stdout})
assert records, "No native files audited"
print(json.dumps({"schema":"rfad.runtime.openems-audit/0.1","status":"passed","python":sys.version,"packages":packages,"qt_found":False,"native_files":records,"vtk_library_count":len(vtk_files),"vtk_build_report_sha256":hashlib.sha256(vtk_report_path.read_bytes()).hexdigest(),"product_adapter_tested":False,"physics_tested":False},indent=2))
'''
        result = self.run(["env", "MPLBACKEND=Agg", self.python, "-c", program,
                           self.prefix, self.vtk, self.code + "/runtime_profiles/python-openems-linux-x64.json", vtk_report_path])
        report = json.loads(result)
        report["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["source_commit"] = self.profile["commit"]
        report["submodules"] = self.profile["submodules"]
        report["build_profile_sha256"] = hashlib.sha256(PROFILE.read_bytes()).hexdigest()
        (CODE / ".local/wsl/native-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    """! @brief 이미 실행 가능한 전용 WSL 배포의 개발 의존성과 native build를 구성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dependencies", action="store_true")
    parser.add_argument("--skip-vtk-build", action="store_true", help="Reuse the VTK prefix already built and audited by build_headless_vtk.sh")
    parser.add_argument("--jobs", type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Run this WSL orchestration tool on Windows.")
    output = CODE / ".local/wsl"
    output.mkdir(parents=True, exist_ok=True)
    try:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        if profile["distribution"] != "TraceWave-Dev" or profile["root"] != "/home/tracewave/rfad-runtime" or profile["qt_allowed"] is not False:
            raise RuntimeError("Unexpected dedicated runtime profile.")
        ensure_user(profile)
        with (output / "setup-openems.log").open("ab") as log:
            builder = Builder(log, args.jobs)
            release = builder.run(["cat", "/etc/os-release"])
            if 'VERSION_ID="24.04"' not in release or 'ID=ubuntu' not in release:
                raise RuntimeError("Expected the dedicated Ubuntu 24.04 distribution.")
            builder.dependencies(args.install_dependencies)
            builder.checkout()
            builder.python_environment()
            if not args.skip_vtk_build:
                builder.run(["bash", builder.code + "/tools/build_headless_vtk.sh", builder.root, str(args.jobs)], capture=False)
            builder.run(["test", "-f", builder.vtk + "/lib/cmake/vtk-9.3/vtk-config.cmake"])
            builder.verify_vtk()
            for name in ("fparser", "CSXCAD", "openEMS"):
                print("Building " + name, flush=True)
                builder.build_native(name)
            builder.bindings()
            builder.audit()
        print("Native build and imports completed. Run check_openems_environment.py for numerical verification.")
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
