"""! @brief 출력 worker의 Python, 글꼴, 설치 명세와 닫힌 실행 소스를 봉인한다."""
import hashlib
import json
import math
from pathlib import Path

from rfad.application import source_bundle
from rfad.application.canonical import canonical_bytes
from rfad.application.cad_runtime import file_hash
from rfad.domain.errors import ProjectError

CODE_ROOT = Path(__file__).resolve().parents[3]


class ExchangeRuntime:
    """! @brief 사용자 RPC가 실행 파일이나 설치 환경을 바꿀 수 없도록 고정한다."""
    def __init__(self, python, *, manifest=None, entry=None, timeout_seconds=120.0):
        """! @brief native 모듈을 import하지 않고 파일 identity를 읽는다."""
        self.python = Path(python).resolve(strict=True)
        self.manifest = Path(manifest or CODE_ROOT / "runtime_profiles/python-exchange-windows-x64.json").resolve(strict=True)
        self.entry = Path(entry or CODE_ROOT / "tools/exchange_worker.py").resolve(strict=True)
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600:
            raise ProjectError("E_SCHEMA", "출력 worker 시간 제한이 유효하지 않습니다.")
        self.timeout_seconds = timeout_seconds
        with self.entry.open("rb") as stream:
            self.entry_bytes = stream.read(256 * 1024 + 1)
        with self.manifest.open("rb") as stream:
            self.manifest_bytes = stream.read(128 * 1024 + 1)
        if len(self.entry_bytes) > 256 * 1024 or len(self.manifest_bytes) > 128 * 1024:
            raise ProjectError("E_RESOURCE", "출력 실행 명세/진입점 크기 상한을 초과했습니다.")
        value = json.loads(self.manifest_bytes)
        if value.get("schema") != "rfad.runtime.python/0.1" or value.get("qt_allowed") is not False:
            raise ProjectError("E_VERSION", "Qt 없는 고정 출력 환경 명세가 필요합니다.")
        fonts = value.get("fonts", [])
        if type(fonts) is not list or len(fonts) > 1:
            raise ProjectError("E_VERSION", "출력 글꼴은 고정한 한 개의 subset용 TTF만 지원합니다.")
        self.font_bytes = None
        for font in fonts:
            if (type(font) is not dict or set(font) != {"name", "path", "sha256", "bytes", "embedding"}
                    or font["embedding"] != "subset" or type(font["bytes"]) is not int or not 0 < font["bytes"] <= 32 * 1024 * 1024):
                raise ProjectError("E_VERSION", "출력 글꼴 명세가 유효하지 않습니다.")
            with Path(font["path"]).open("rb") as stream:
                self.font_bytes = stream.read(font["bytes"] + 1)
            if len(self.font_bytes) != font["bytes"] or hashlib.sha256(self.font_bytes).hexdigest() != font["sha256"]:
                raise ProjectError("E_HASH", "출력 글꼴의 원문 bytes가 고정 명세와 다릅니다.")
        try:
            bundle = source_bundle.build(CODE_ROOT, source_bundle.EXCHANGE, overrides={"tools/exchange_worker.py": self.entry_bytes})
        except source_bundle.BundleError as error:
            raise ProjectError(error.code, str(error)) from error
        self.source_bytes = canonical_bytes(bundle["sources"])
        if len(self.source_bytes) > 4 * 1024 * 1024:
            raise ProjectError("E_RESOURCE", "출력 worker 소스의 직렬화 크기가 4 MiB를 초과했습니다.")
        self.identity = {"profile_id": value["profile_id"], "python_sha256": file_hash(self.python),
            "manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest(),
            "entry_sha256": hashlib.sha256(self.entry_bytes).hexdigest(),
            "source_sha256": source_bundle.source_hash(bundle["code_files"]),
            "source_bundle": bundle["source_bundle"], "code_files": bundle["code_files"]}

    def verify(self, expected):
        """! @brief 접수 후 소스/환경이 바뀌면 묵시적으로 다시 실행하지 않는다."""
        current = ExchangeRuntime(self.python, manifest=self.manifest, entry=self.entry, timeout_seconds=self.timeout_seconds)
        if current.identity != expected:
            raise ProjectError("E_VERSION", "접수한 출력 환경 또는 구현이 변경되었습니다. 다시 검토하십시오.")
