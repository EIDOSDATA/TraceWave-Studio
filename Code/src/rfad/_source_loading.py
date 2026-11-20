"""! @brief 서비스 세션에서 실제 컴파일한 제품 원문을 기록하고 오래된 pyc 재사용을 막는다."""
import hashlib
import importlib.util
from pathlib import Path
import stat
import sys
import threading

_BOOTSTRAP_CODE = sys._getframe().f_code
_ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.RLock()
_LOADED = {}
_PINNED = {}
_LIMIT = 4 * 1024 * 1024


def _read(path):
    """! @brief 링크/비정상 경로와 무한 읽기를 거절하고 실제 source bytes를 반환한다."""
    path = Path(path)
    if not path.resolve().is_relative_to(_ROOT):
        raise ImportError("제품 소스가 세션 root 밖에 있습니다.")
    for item in (path, *path.parents):
        if item == _ROOT.parent:
            break
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ImportError("제품 소스에 링크/재분석 경로를 허용하지 않습니다.")
    with path.open("rb") as stream:
        raw = stream.read(_LIMIT + 1)
    if len(raw) > _LIMIT:
        raise ImportError("제품 소스 파일 한도를 초과했습니다.")
    return raw


def _record(path, raw):
    """! @brief 실제 로딩/고정 기록과 다른 바이트를 새 세션 코드로 묵시 채택하지 않는다."""
    relative = path.relative_to(_ROOT).as_posix()
    digest = hashlib.sha256(raw).hexdigest()
    with _LOCK:
        for previous in (_LOADED.get(relative), _PINNED.get(relative)):
            if previous is not None and previous != digest:
                raise ImportError("세션 중 제품 소스가 변경되었습니다: " + relative)
        _LOADED[relative] = digest


class _SourceLoader:
    """! @brief 확인한 같은 원문 bytes만 실행하며 bytecode cache를 읽거나 만들지 않는다."""
    def __init__(self, path, raw):
        self.path, self.raw = path, raw

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(self.get_code(module.__name__), module.__dict__)

    def get_code(self, fullname):
        """! @brief 일반 import와 python -m 진입점에 같은 확인 원문을 제공한다."""
        _record(self.path, self.raw)
        return compile(self.raw, str(self.path), "exec")


class _SourceFinder:
    """! @brief 제품 패키지는 현재 source root만 사용하고 설치 fallback을 차단한다."""
    _rfad_control_loader = True

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("rfad."):
            return None
        base = _ROOT / "src" / Path(*fullname.split("."))
        package = base / "__init__.py"
        source = package if package.is_file() else base.with_suffix(".py")
        if not source.is_file():
            raise ModuleNotFoundError("제품 source가 없습니다: " + fullname)
        raw = _read(source)
        _record(source, raw)
        return importlib.util.spec_from_file_location(fullname, source, loader=_SourceLoader(source, raw),
            submodule_search_locations=[str(source.parent)] if source == package else None)


def install(package_code):
    """! @brief 최초 두 bootstrap의 실행 code를 원문과 대조한 뒤 import 기록을 시작한다."""
    if any(getattr(loader, "_rfad_sealed_guard", False) for loader in sys.meta_path):
        return
    if any(getattr(loader, "_rfad_control_loader", False) for loader in sys.meta_path):
        return
    allowed = {"rfad", "rfad._source_loading"}
    if any(name.startswith("rfad.") and name not in allowed for name in sys.modules):
        raise ImportError("세션 source loader 전에 제품 모듈이 이미 로딩되었습니다.")
    for name, code in (("rfad", package_code), ("rfad._source_loading", _BOOTSTRAP_CODE)):
        path = Path(sys.modules[name].__file__).resolve()
        raw = _read(path)
        expected = compile(raw, code.co_filename, "exec")
        if expected != code:
            raise ImportError("bootstrap의 실행 code와 실제 원문이 다릅니다: " + name)
        _record(path, raw)
    sys.meta_path.insert(0, _SourceFinder())


def pin(records):
    """! @brief 세션 계산 closure를 실제 로딩 기록과 대조하고 이후 지연 import도 같은 bytes로 제한한다."""
    with _LOCK:
        for record in records:
            relative = record["path"]
            raw = _read(_ROOT / relative)
            digest = hashlib.sha256(raw).hexdigest()
            if len(raw) != record["bytes"] or digest != record["sha256"]:
                raise ImportError("세션 계산 source pin이 실제 파일과 다릅니다: " + relative)
            if relative in _LOADED and _LOADED[relative] != digest:
                raise ImportError("이미 로딩한 제어 code와 고정할 원문이 다릅니다: " + relative)
            if relative in _PINNED and _PINNED[relative] != digest:
                raise ImportError("고정된 세션 계산 source가 변경되었습니다: " + relative)
        _PINNED.update({record["path"]: record["sha256"] for record in records})


def verify(records):
    """! @brief 실행/게시 직전 세션 원문과 현재 디스크 및 실제 import 기록의 일치를 재검사한다."""
    pin(records)
