"""! @brief 실행 진입점의 모든 Python 의존 소스를 봉인하고 격리 import를 검증한다.

@details 이 모듈은 검증 전 rfad 패키지를 읽지 않도록 표준 라이브러리만 사용한다.
조건문과 함수 내부 import도 포함하며 실제 한 실행의 로딩 기록으로 소스를 줄이지 않는다.
"""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys


SCHEMA = "rfad.source-bundle/0.1"
CAD = "rfad.source.cad/0.1"
SOLVER = "rfad.source.openems/0.1"
HOST = "rfad.source.host-calculation/0.1"
HOST_CONTROL = "rfad.source.host-control/0.1"
HOST_MATH = "rfad.source.host-math/0.1"
EXCHANGE = "rfad.source.exchange/0.1"
MAX_FILES = 192
ROOTS = {
    CAD: ("worker.py",),
    EXCHANGE: ("tools/exchange_worker.py",),
    SOLVER: ("tools/openems_worker.py", "tools/wsl_supervisor.py"),
    HOST: ("src/rfad/application/rpc.py", "src/rfad/application/projects.py",
           "src/rfad/application/design_sweep_service.py", "src/rfad/application/design_sweep_runner.py",
           "tools/wsl_supervisor.py"),
    HOST_CONTROL: ("src/rfad/application/host_calculation_context.py", "tools/wsl_supervisor.py"),
    HOST_MATH: ("tools/host_calculation_worker.py",),
}
LIMITS = {CAD: 2 * 1024**2, SOLVER: 4 * 1024**2, HOST: 4 * 1024**2, EXCHANGE: 4 * 1024**2,
          HOST_CONTROL: 4 * 1024**2, HOST_MATH: 4 * 1024**2}
# @brief 가변 이름의 로더는 manifest 경로를 사용하는 이 모듈과 고정 worker bootstrap만 허용한다.
BOOTSTRAPS = {"src/rfad/application/source_bundle.py", "src/rfad/_source_loading.py", "worker.py", "tools/openems_worker.py", "tools/wsl_supervisor.py", "tools/exchange_worker.py", "tools/host_calculation_worker.py"}
DYNAMIC = {"src/rfad/adapters/network_hdf5.py": {"h5py", "numpy"}}


class BundleError(ValueError):
    """! @brief native import 이전에도 코드가 있는 제한 오류를 전달한다."""

    def __init__(self, message, code="E_HASH"):
        """! @brief 제품 오류와 같은 식별을 보존하되 제품 패키지를 import하지 않는다."""
        super().__init__(message)
        self.code = code

    def diagnostic(self):
        """! @brief worker의 기존 오류 봉투에 사용할 유한 진단을 반환한다."""
        return {"code": self.code, "message_ko": str(self)}


def canonical(value):
    """! @brief 문자열/정수 manifest를 기존 canonical JSON과 같은 바이트로 직렬화한다."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _path(value):
    """! @brief 역슬래시/드라이브/상위 경로와 비정규 Python 경로를 거부한다."""
    if (type(value) is not str or "\\" in value or ":" in value or not value.endswith(".py")
            or PurePosixPath(value).is_absolute() or any(part in ("", ".", "..") for part in value.split("/"))):
        raise BundleError("실행 소스의 상대 경로가 유효하지 않습니다.")
    if value != "worker.py" and not value.startswith(("src/rfad/", "tools/")):
        raise BundleError("실행 소스가 허용한 패키지 경계를 벗어났습니다.")
    return value


def _regular(root, relative):
    """! @brief 선택한 파일과 모든 부모의 링크/재분석점 및 root 탈출을 차단한다."""
    path = root.joinpath(*PurePosixPath(_path(relative)).parts)
    current = path
    while current != root:
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise BundleError("실행 소스에 링크 또는 재분석점이 있습니다.")
        current = current.parent
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or not path.resolve().is_relative_to(root):
        raise BundleError("실행 소스는 root 안의 독립된 일반 파일이어야 합니다.")
    return path


def _text(root, relative, overrides, limit, normalize):
    """! @brief 파일별 상한을 먼저 검사하고 profile의 줄바꿈 규칙을 적용한다."""
    raw = overrides.get(relative)
    if raw is None:
        with _regular(root, relative).open("rb") as stream:
            raw = stream.read(limit + 1)
    if type(raw) is not bytes or len(raw) > limit:
        raise BundleError("실행 소스 한 파일의 크기가 상한을 초과했습니다.", "E_RESOURCE")
    text = raw.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n") if normalize else text


def _module_path(root, module, overrides):
    """! @brief 제품 모듈은 설치 패키지 대신 지정 root의 두 명시 경로만 탐색한다."""
    if module != "rfad" and not module.startswith("rfad."):
        return None
    if not all(part.isidentifier() for part in module.split(".")):
        raise BundleError("제품 import 이름이 유효하지 않습니다.")
    stem = "src/" + module.replace(".", "/")
    matches = [name for name in (stem + "/__init__.py", stem + ".py") if name in overrides or (root / name).exists()]
    if len(matches) > 1:
        raise BundleError("같은 제품 이름의 패키지와 모듈이 중복됩니다.")
    return matches[0] if matches else None


def _dependencies(root, relative, text, overrides):
    """! @brief 모든 AST 분기/함수와 상대 import를 보수적으로 읽고 동적 호출을 등록 대조한다."""
    tree = ast.parse(text, filename=relative)
    module = relative[4:-3].replace("/", ".") if relative.startswith("src/") else ""
    package = module.rpartition(".")[0]
    dependencies, dynamic = set(), set()
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]
                if item.name == "rfad" or item.name.startswith("rfad."):
                    dependencies.add(item.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".") if package else []
                if node.level > len(parts):
                    raise BundleError("상대 import가 제품 패키지 밖으로 나갑니다.")
                base = ".".join(parts[:len(parts) - node.level + 1] + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            for item in node.names:
                aliases[item.asname or item.name] = base + "." + item.name
            if base == "rfad" or base.startswith("rfad."):
                dependencies.add(base)
                for item in node.names:
                    child = base + "." + item.name
                    if item.name != "*" and _module_path(root, child, overrides):
                        dependencies.add(child)
                    elif item.name != "*":
                        base_path = _module_path(root, base, overrides)
                        if base_path and base_path.endswith("/__init__.py"):
                            body = ast.parse(_text(root, base_path, overrides, 4 * 1024**2, False))
                            exported = {node.name for node in ast.walk(body) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                            exported.update(node.id for node in ast.walk(body) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))
                            for declaration in ast.walk(body):
                                if isinstance(declaration, (ast.Import, ast.ImportFrom)):
                                    exported.update(alias.asname or alias.name.split(".")[0] for alias in declaration.names)
                            if item.name not in exported:
                                raise BundleError("패키지가 제공하지 않는 제품 의존 이름입니다: " + child)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts = []
        function = node.func
        while isinstance(function, ast.Attribute):
            parts.insert(0, function.attr)
            function = function.value
        if isinstance(function, ast.Name):
            parts.insert(0, aliases.get(function.id, function.id))
        name = ".".join(parts)
        if name in ("__import__", "importlib.import_module"):
            value = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            if type(value) is not str or value not in DYNAMIC.get(relative, set()):
                raise BundleError("등록하지 않은 동적 import가 있습니다: " + relative, "E_UNSUPPORTED")
            dynamic.add(relative + ":" + value)
            if value == "rfad" or value.startswith("rfad."):
                dependencies.add(value)
        elif name in ("exec", "eval", "importlib.util.spec_from_file_location", "runpy.run_path"):
            if relative not in BOOTSTRAPS:
                raise BundleError("등록하지 않은 실행 코드 로더가 있습니다: " + relative, "E_UNSUPPORTED")
    return dependencies, dynamic


def source_hash(records):
    """! @brief 경로와 실제 실행 바이트 해시를 정렬한 집합의 identity를 반환한다."""
    return hashlib.sha256(canonical({record["path"]: record["sha256"] for record in records})).hexdigest()


def build(root, profile, *, overrides=None, max_files=MAX_FILES):
    """! @brief 명시 진입점부터 전이 의존 소스 원문 전체를 유한 묶음으로 캡처한다."""
    if profile not in ROOTS:
        raise BundleError("지원하지 않는 소스 묶음 profile입니다.", "E_VERSION")
    if type(max_files) is not int or not 1 <= max_files <= MAX_FILES:
        raise BundleError("소스 파일 한도는 공통 상한을 완화할 수 없습니다.", "E_RESOURCE")
    root = Path(root).resolve(strict=True)
    overrides = {} if overrides is None else overrides
    if any(_path(key) != key for key in overrides):
        raise BundleError("덮어쓸 진입점 경로가 유효하지 않습니다.")
    if overrides and not ((profile == CAD and set(overrides) == {"worker.py"})
                          or (profile == EXCHANGE and set(overrides) == {"tools/exchange_worker.py"})):
        raise BundleError("호스트가 명시한 CAD/출력 진입점만 별도 바이트로 제공할 수 있습니다.")
    sources, dynamic, pending = {}, set(), set(ROOTS[profile])
    limit = LIMITS[profile]
    try:
        while pending:
            relative = min(pending)
            pending.remove(relative)
            if relative in sources:
                continue
            if len(sources) >= max_files:
                raise BundleError("실행 의존 소스 파일 수가 공통 상한을 초과했습니다.", "E_RESOURCE")
            text = _text(root, relative, overrides, limit, profile not in (CAD, EXCHANGE, HOST_CONTROL, HOST_MATH) and relative != "tools/wsl_supervisor.py")
            sources[relative] = text
            dependencies, imports = _dependencies(root, relative, text, overrides)
            dynamic.update(imports)
            for module in dependencies:
                parts = module.split(".")
                for length in range(1, len(parts) + 1):
                    needed = ".".join(parts[:length])
                    path = _module_path(root, needed, overrides)
                    if path is None:
                        raise BundleError("제품 의존 소스가 없습니다: " + needed)
                    if path not in sources:
                        pending.add(path)
            if sum(len(value.encode("utf-8")) for value in sources.values()) > limit:
                raise BundleError("실행 의존 소스 바이트가 상한을 초과했습니다.", "E_RESOURCE")
        sources = dict(sorted(sources.items()))
        raw = canonical(sources)
        if len(raw) > limit:
            raise BundleError("실행 소스 JSON 묶음이 상한을 초과했습니다.", "E_RESOURCE")
    except (OSError, UnicodeError, SyntaxError, RecursionError) as error:
        raise BundleError("실행 의존 소스를 읽거나 분석할 수 없습니다: " + str(error)[:512], "E_VERSION") from error
    records = [{"path": path, "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(), "bytes": len(value.encode("utf-8"))}
               for path, value in sources.items()]
    descriptor = {"schema": SCHEMA, "profile": profile, "entry_points": list(ROOTS[profile]),
                  "dynamic_imports": sorted(dynamic), "source_sha256": source_hash(records)}
    return {"sources": sources, "source_bytes": raw, "code_files": records, "source_bundle": descriptor}


def validate_descriptor(descriptor, records):
    """! @brief 구형 identity와 별도로 새 묶음 profile/파일 목록의 유한 형식을 검사한다."""
    if (type(descriptor) is not dict or set(descriptor) != {"schema", "profile", "entry_points", "dynamic_imports", "source_sha256"}
            or descriptor.get("schema") != SCHEMA or descriptor.get("profile") not in ROOTS):
        raise BundleError("실행 소스 묶음의 명시 profile이 유효하지 않습니다.", "E_VERSION")
    if descriptor["entry_points"] != list(ROOTS[descriptor["profile"]]):
        raise BundleError("실행 소스 묶음의 진입점이 profile과 다릅니다.")
    if type(records) is not list or not 1 <= len(records) <= MAX_FILES:
        raise BundleError("실행 소스 파일 개수가 공통 상한을 벗어났습니다.", "E_RESOURCE")
    seen = set()
    for record in records:
        if (type(record) is not dict or set(record) != {"path", "bytes", "sha256"}
                or type(record["bytes"]) is not int or not 0 <= record["bytes"] <= LIMITS[descriptor["profile"]]
                or type(record["sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}", record["sha256"])):
            raise BundleError("실행 소스 파일의 크기/해시가 유효하지 않습니다.")
        path = _path(record["path"])
        if path in seen:
            raise BundleError("실행 소스 경로가 중복됩니다.")
        seen.add(path)
    if sum(record["bytes"] for record in records) > LIMITS[descriptor["profile"]]:
        raise BundleError("실행 소스 원문 크기의 합계가 profile 상한을 초과했습니다.", "E_RESOURCE")
    if not set(descriptor["entry_points"]) <= seen or source_hash(records) != descriptor["source_sha256"]:
        raise BundleError("실행 소스 목록의 봉인 또는 필수 진입점이 다릅니다.")
    if (type(descriptor["dynamic_imports"]) is not list or len(descriptor["dynamic_imports"]) > 64
            or any(type(value) is not str or len(value) > 256 for value in descriptor["dynamic_imports"])
            or descriptor["dynamic_imports"] != sorted(set(descriptor["dynamic_imports"]))):
        raise BundleError("동적 의존 소스 등록이 유효하지 않습니다.")


def verify_stage(root, descriptor, records):
    """! @brief 실행 전 실제 파일 집합/바이트/전이 의존성을 다시 검증한다."""
    validate_descriptor(descriptor, records)
    root = Path(root).resolve(strict=True)
    expected = {record["path"]: record for record in records}
    found = set()
    for base in (root / "src", root / "tools"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise BundleError("실행 소스 디렉터리에 링크/재분석점이 있습니다.")
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                if path.suffix in (".pyc", ".pyo", ".pyd", ".so") or path.name == "__pycache__":
                    raise BundleError("봉인하지 않은 bytecode/native 모듈이 실행 패키지에 있습니다.")
                if path.suffix == ".py":
                    found.add(relative)
    if (root / "worker.py").exists():
        found.add("worker.py")
    if any(path.name != "worker.py" and path.suffix in (".py", ".pyc", ".pyo", ".pyd", ".so") for path in root.iterdir()):
        raise BundleError("실행 root에 봉인하지 않은 코드 파일이 있습니다.")
    if found != set(expected):
        raise BundleError("실제 실행 소스 목록에 추가 또는 누락된 파일이 있습니다.")
    for relative, record in expected.items():
        with _regular(root, relative).open("rb") as stream:
            raw = stream.read(record["bytes"] + 1)
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise BundleError("실제 실행 소스의 바이트가 봉인과 다릅니다.")
    overrides = {"worker.py": (root / "worker.py").read_bytes()} if descriptor["profile"] == CAD else None
    actual = build(root, descriptor["profile"], overrides=overrides)
    if actual["source_bundle"] != descriptor or actual["code_files"] != records:
        raise BundleError("실제 의존 소스 closure가 봉인과 다릅니다.")
    return actual


class _SealedLoader:
    """! @brief 해시를 확인한 같은 바이트를 컴파일하여 기존/새 pyc를 사용하지 않는다."""

    def __init__(self, raw, filename):
        """! @brief 검증한 불변 bytes와 traceback의 실제 파일명을 보존한다."""
        self.raw, self.filename = raw, filename

    def create_module(self, spec):
        """! @brief 표준 Python 모듈 객체 생성을 사용한다."""
        return None

    def exec_module(self, module):
        """! @brief 재읽기/bytecode cache 없이 검증한 소스만 실행한다."""
        exec(compile(self.raw, self.filename, "exec"), module.__dict__)


class _SealedImports:
    """! @brief rfad 이름은 봉인된 경로만 로딩하며 설치된 동명 패키지로 우회하지 않는다."""
    _rfad_sealed_guard = True

    def __init__(self, root, records):
        """! @brief 파일을 제품 모듈 이름에 대응시키고 외부 라이브러리는 기존 runtime 검증에 맡긴다."""
        self.root = root
        self.modules = {}
        for record in records:
            path = record["path"]
            if path.startswith("src/rfad/"):
                name = path[4:-3].replace("/", ".").removesuffix(".__init__")
                self.modules[name] = record

    def find_spec(self, fullname, path=None, target=None):
        """! @brief 누락/변조를 import 순간에도 차단하고 실제 source loader를 고정한다."""
        if fullname != "rfad" and not fullname.startswith("rfad."):
            return None
        record = self.modules.get(fullname)
        if record is None:
            raise ModuleNotFoundError("봉인하지 않은 제품 모듈: " + fullname)
        source = _regular(self.root, record["path"])
        with source.open("rb") as stream:
            raw = stream.read(record["bytes"] + 1)
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise BundleError("import할 실행 소스의 봉인이 변경되었습니다.")
        package = source.name == "__init__.py"
        return importlib.util.spec_from_file_location(fullname, source, loader=_SealedLoader(raw, str(source)),
            submodule_search_locations=[str(source.parent)] if package else None)


def install_guard(root, descriptor, records):
    """! @brief 제품 import 전에 모든 source를 검증하고 설치 fallback을 막는다."""
    root = Path(root).resolve(strict=True)
    verify_stage(root, descriptor, records)
    guard = _SealedImports(root, records)
    for name in tuple(sys.modules):
        if name != "rfad" and not name.startswith("rfad."):
            continue
        raise BundleError("소스 검증 전에 이미 로딩된 제품 모듈이 있습니다.")
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, guard)
    return guard
