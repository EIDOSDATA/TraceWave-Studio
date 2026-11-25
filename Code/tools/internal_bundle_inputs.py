"""! @brief 내부 Windows 묶음의 Git 소스, native 의존성, 고지 원문을 수집한다."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import zipfile


FILE_LIMIT = 64 * 1024 * 1024
TOTAL_LIMIT = 128 * 1024 * 1024
FOLDER_ROOTS = ("Code/src/", "Code/ui/", "Code/tools/", "Code/tests/", "Code/fixtures/")
SINGLE_FILES = {"Code/README.md", "Code/pyproject.toml", "Code/CMakeLists.txt", "Code/CMakePresets.json", "Code/.clang-format",
                "Code/.editorconfig", "Code/runtime_profiles/native-windows-x64.json",
                "Code/runtime_profiles/openems-wsl-build.json", "Code/runtime_profiles/wsl-development.json",
                "Code/runtime_profiles/vtk-headless.json",
                "01_개발문서/08_운영환경/01_파이썬_개발환경.md",
                "01_개발문서/08_운영환경/02_리눅스하위시스템_개발환경.md",
                "01_개발문서/08_운영환경/05_윈도우_내부검증_배포.md",
                "01_개발문서/08_운영환경/06_내부검증_지원범위와_미결.md"}
LOCK_FILES = re.compile(r"Code/runtime_profiles/python-[a-z0-9-]+\.(txt|json)\Z")
PROFILE = "Code/runtime_profiles/windows-internal-bundle-x64.json"
BIN = "Code/build/windows-release/bin/"
NOTICE = "third-party-notices/"
SHELL = BIN + "tracewave_shell_prototype.exe"
SHELL_NOTICE = NOTICE + "shell/"
SHELL_WINDOWS_DLLS = frozenset({"imm32.dll", "setupapi.dll", "uiautomationcore.dll"})
WINDOWS_DLLS = frozenset(name.lower() for name in (
    "ADVAPI32.dll", "bcrypt.dll", "COMCTL32.dll", "comdlg32.dll", "crypt32.dll", "GDI32.dll", "KERNEL32.dll",
    "ntdll.dll", "ole32.dll", "OLEACC.dll", "OLEAUT32.dll", "OPENGL32.dll", "SHELL32.dll", "SHLWAPI.dll",
    "USER32.dll", "UxTheme.dll", "VERSION.dll", "WINMM.dll", "WINSPOOL.DRV", "ucrtbase.dll",
))


def read_bytes(path, limit=FILE_LIMIT):
    """! @brief 새 묶음의 파일은 경로 참조가 아닌 유한한 일반 파일이어야 한다."""
    path = Path(path)
    entry = path.lstat()
    if not stat.S_ISREG(entry.st_mode) or getattr(entry, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"일반 파일이 필요합니다. {path.name}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if not 0 < len(data) <= limit or len(data) != entry.st_size:
        raise ValueError(f"파일 크기가 지원 범위를 벗어났습니다. {path.name}")
    return data


def confirmed(data, digest, label):
    """! @brief 고정 입력 해시와 다른 자료는 묶음에 넣지 않는다."""
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"봉인 SHA256이 다릅니다. {label}")
    return data


def git_sources(repository, reference):
    """! @brief 갱신 중인 작업 트리와 무관하게 명시한 커밋의 추적 파일을 보존한다."""
    # @brief 사용자 Git의 Windows 개행 설정이 고정 커밋의 ZIP 바이트에 영향을 주지 않게 한다.
    executable = ["git", "-C", str(repository), "-c", "core.autocrlf=false", "-c", "core.eol=lf"]
    revision = subprocess.check_output([*executable, "rev-parse", "--verify", "--end-of-options", reference + "^{commit}"],
                                      text=True).strip()
    raw = subprocess.check_output([*executable, "ls-tree", "-r", "-z", "--long", revision, "--", "Code", "01_개발문서/08_운영환경"])
    paths = []
    total = 0
    for line in raw.decode("utf-8").split("\0"):
        if not line:
            continue
        entry, name = line.split("\t", 1)
        if name != PROFILE and name not in SINGLE_FILES and not name.startswith(FOLDER_ROOTS) and not LOCK_FILES.fullmatch(name):
            continue
        mode, kind, _, size = entry.split()
        if mode not in ("100644", "100755") or kind != "blob" or int(size) > FILE_LIMIT:
            raise ValueError(f"묶음에서 지원하지 않는 추적 파일입니다. {name}")
        total += int(size)
        paths.append(name)
    if not paths or len(paths) > 5000 or total > TOTAL_LIMIT:
        raise ValueError("소스 묶음의 경로 수 또는 총 용량을 확인하십시오.")
    if len({name.casefold() for name in paths}) != len(paths):
        raise ValueError("Windows에서 구분할 수 없는 추적 경로가 있습니다.")

    roots = [root.rstrip("/") for root in FOLDER_ROOTS if any(name.startswith(root) for name in paths)]
    arguments = [*roots, *(name for name in paths if not name.startswith(FOLDER_ROOTS))]
    archive = subprocess.check_output([*executable, "archive", "--format=zip", revision, "--", *arguments])
    with zipfile.ZipFile(BytesIO(archive)) as source:
        records = {item.filename: item for item in source.infolist() if not item.is_dir()}
        if set(records) != set(paths):
            raise ValueError("Git 원본의 선택 파일 목록과 묶음이 다릅니다.")
        return revision, {name: source.read(item) for name, item in records.items()}


def _imports(path, objdump):
    """! @brief 검증에 사용한 GNU 도구의 PE x64 import 표만 읽는다."""
    image = subprocess.check_output([str(objdump), "-p", str(path)], stderr=subprocess.STDOUT).decode("utf-8", "replace")
    inputs = set(re.findall(r"^\s*DLL Name:\s*([A-Za-z0-9_.+-]+)\s*$", image, re.MULTILINE))
    if "file format pei-x86-64" not in image or not inputs:
        raise ValueError(f"PE x64 import를 확인할 수 없습니다. {path.name}")
    return {name.lower() for name in inputs}


def native_files(executable, runtime, profile, objdump):
    """! @brief 제품 exe에 실제 연결된 고정 DLL의 폐쇄 집합만 포함한다."""
    retained = profile["compiler"]["runtime_files"]
    sources = {"tracewave_gui.exe": executable, **{name: runtime / name for name in retained}}
    records = {"tracewave_gui.exe": read_bytes(executable)}
    for name, digest in retained.items():
        records[name] = confirmed(read_bytes(sources[name]), digest, name)
    with TemporaryDirectory(prefix="TraceWave import table ") as directory:
        root = Path(directory)
        for name, data in records.items():
            (root / name).write_bytes(data)
        imports = {name: _imports(root / name, objdump) for name in records}
    unknown = set.union(*imports.values()) - WINDOWS_DLLS - retained.keys()
    unknown = {name for name in unknown if not name.startswith("api-ms-win-crt-")}
    if unknown:
        raise ValueError("선택한 native profile의 의존 목록에 없는 파일입니다. " + ", ".join(sorted(unknown)))
    required = set()
    pending = list(imports["tracewave_gui.exe"] & retained.keys())
    while pending:
        name = pending.pop()
        if name not in required:
            required.add(name)
            pending.extend(imports[name] & retained.keys() - required)
    if required != retained.keys():
        raise ValueError("실행 파일의 실제 런타임 조합이 고정 profile과 다릅니다.")
    return {BIN + name: data for name, data in records.items()}, {
        name: sorted(values) for name, values in sorted(imports.items())}


SHELL_LICENSES = {
    "sdl3": ("LICENSE.txt", "1c040b8271b37e5076359f8fd54240e371114112924d2df81ef87c7d6a1dfdfd"),
    "imgui": ("LICENSE.txt", "c80c5789748d955c4a650562baa0d750494e2c7128c2ca66aaebe2e3c4e198bf"),
    "implot": ("LICENSE", "38bd30c2111fe7e3d8fb86d8607491239659eff1df1b1004b9a8349e20a91967"),
    "bgfx": ("LICENSE", "ac2e0d253b1584316a36a0fae1d4407fa3ebcb15f27021ab479b23d27f0c9c08"),
    "bimg": ("LICENSE", "ac2e0d253b1584316a36a0fae1d4407fa3ebcb15f27021ab479b23d27f0c9c08"),
    "bx": ("LICENSE", "ac2e0d253b1584316a36a0fae1d4407fa3ebcb15f27021ab479b23d27f0c9c08"),
    "bgfx_wrapper": ("LICENSE", "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"),
}


def shell_files(executable, dependencies, objdump):
    """! @brief 정적 연결 시제품과 고정 엔진 고지를 별도 항목으로 봉인한다."""
    image = read_bytes(executable)
    with TemporaryDirectory(prefix="TraceWave shell import ") as directory:
        checked = Path(directory) / "tracewave_shell_prototype.exe"
        checked.write_bytes(image)
        imports = _imports(checked, objdump)
    unknown = imports - WINDOWS_DLLS - SHELL_WINDOWS_DLLS
    if any(not name.startswith("api-ms-win-crt-") for name in unknown):
        raise ValueError("시제품의 정적 Windows 의존 목록을 확인하십시오. " + ", ".join(sorted(unknown)))
    files = {SHELL: image}
    for source, (name, digest) in SHELL_LICENSES.items():
        file = Path(dependencies) / f"{source}-src" / name
        files[SHELL_NOTICE + source + ".txt"] = confirmed(read_bytes(file, 256 * 1024), digest, source)
    return files, sorted(imports)


def notices(wx_archive, notice_dir, profile):
    """! @brief 정확한 wx 소스 아카이브와 관리하는 upstream 고지 바이트를 넣는다."""
    wx = profile["wx"]
    data = confirmed(read_bytes(wx_archive), wx["sha256"], wx_archive.name)
    wanted = {f"wxWidgets-3.2.12/{name}": key for key, name in wx["files"].items()}
    output = {}
    with tarfile.open(fileobj=BytesIO(data), mode="r|bz2") as source:
        for item in source:
            if item.name in wanted:
                if not item.isfile() or not 0 < item.size <= 256 * 1024:
                    raise ValueError(f"wx 고지 파일 유형 또는 크기가 다릅니다. {item.name}")
                with source.extractfile(item) as stream:
                    output[NOTICE + wanted[item.name]] = stream.read()
    if len(output) != len(wanted):
        raise ValueError("고정 wx 소스에 필요한 고지 파일이 없습니다.")
    for name, definition in profile["external_notices"].items():
        output[NOTICE + name] = confirmed(read_bytes(notice_dir / name, 256 * 1024), definition["sha256"], name)
    output[NOTICE + "source-inventory.json"] = (json.dumps(profile, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return output
