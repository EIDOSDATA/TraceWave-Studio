"""! @brief API와 분리된 고정 CAD 실행 파일과 소스 identity를 캡처한다."""

import hashlib
import json
import math
from pathlib import Path

from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError
from rfad.domain.resource_limits import MAX_WORKER_SOURCE_FILES

CODE_ROOT = Path(__file__).resolve().parents[3]


def file_hash(path: Path) -> str:
    """! @brief 큰 native 파일도 일정 크기의 버퍼로 해시한다."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class CadRuntime:
    """! @brief API 입력으로 변경할 수 없는 호스트 CAD 실행 설정이다."""

    def __init__(self, python: Path, *, manifest: Path | None = None, entry: Path | None = None, timeout_seconds: float = 120.0):
        """! @brief 실행 파일과 고정 설치 명세를 확인하고 실행 식별을 봉인한다."""
        self.python = Path(python).resolve(strict=True)
        self.manifest = (manifest or CODE_ROOT / "runtime_profiles/python-cad-windows-x64.json").resolve(strict=True)
        self.entry = (entry or CODE_ROOT / "tools/cad_worker.py").resolve(strict=True)
        if not self.python.is_file() or not self.entry.is_file() or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600:
            raise ProjectError("E_SCHEMA", "CAD 실행 설정 또는 시간 제한이 유효하지 않습니다.")
        self.timeout_seconds = timeout_seconds
        self.entry_bytes = self.entry.read_bytes()
        source_files = {path.relative_to(CODE_ROOT).as_posix(): path.read_bytes().decode("utf-8") for path in sorted((CODE_ROOT / "src/rfad").rglob("*.py"))}
        self.source_bytes = canonical_bytes(source_files)
        if len(self.source_bytes) > 2 * 1024 * 1024 or len(source_files) > MAX_WORKER_SOURCE_FILES:
            raise ProjectError("E_RESOURCE", "CAD worker 소스 묶음이 지원 상한을 초과했습니다.")
        self.manifest_bytes = self.manifest.read_bytes()
        if len(self.manifest_bytes) > 128 * 1024:
            raise ProjectError("E_RESOURCE", "CAD 런타임 명세가 너무 큽니다.")
        manifest_data = json.loads(self.manifest_bytes)
        if manifest_data.get("schema") != "rfad.runtime.python/0.1" or manifest_data.get("qt_allowed") is not False:
            raise ProjectError("E_VERSION", "Qt 없는 고정 CAD 런타임 명세가 필요합니다.")
        self.identity = {
            "profile_id": manifest_data["profile_id"],
            "manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest(),
            "python_sha256": file_hash(self.python), "entry_sha256": hashlib.sha256(self.entry_bytes).hexdigest(),
            "source_sha256": hashlib.sha256(canonical_bytes({name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in source_files.items()})).hexdigest(),
        }

    @staticmethod
    def source_hash() -> str:
        """! @brief 실제 worker가 읽는 제품 Python 소스 묶음을 식별한다."""
        records = {path.relative_to(CODE_ROOT).as_posix(): file_hash(path) for path in sorted((CODE_ROOT / "src/rfad").rglob("*.py"))}
        return hashlib.sha256(canonical_bytes(records)).hexdigest()

    def verify(self, identity: dict) -> None:
        """! @brief 접수 뒤 실행 파일이나 소스가 바뀌었으면 자동 실행하지 않는다."""
        current = {**self.identity, "python_sha256": file_hash(self.python), "entry_sha256": file_hash(self.entry),
                   "manifest_sha256": file_hash(self.manifest), "source_sha256": self.source_hash()}
        if current != identity:
            raise ProjectError("E_VERSION", "접수한 CAD 런타임 또는 구현이 변경되었습니다. 새 작업으로 요청하십시오.")
