"""! @brief 제어/수학 합집합을 고정하고 별도 로컬 worker의 같은 source bytes 실행을 소유한다."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import struct
import sys
from tempfile import TemporaryDirectory
import threading
from uuid import uuid4

from rfad import _source_loading
from rfad.runtime_platform import machine_name, system_name
from rfad.adapters.network_backend import installation_metadata
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.native_process import run_native
from rfad.application.source_bundle import build_host_pair, HOST_CONTROL, MAX_FILES, LIMITS, BundleError
from rfad.domain.errors import ProjectError

ROOT = Path(__file__).resolve().parents[3]
MAX_BYTES = 8 * 1024**2


def capture():
    """! @brief 별도 closure의 동일 경로를 한 번만 계수하며 합집합의 기존 상한을 유지한다."""
    try:
        control, math = build_host_pair(ROOT)
        sources = dict(control["sources"])
        for path, raw in math["sources"].items():
            if path in sources and sources[path] != raw:
                raise BundleError("제어/계산 source의 같은 경로가 서로 다릅니다.")
            sources[path] = raw
        sources = dict(sorted(sources.items()))
        encoded = canonical_bytes(sources)
        if len(sources) > MAX_FILES or len(encoded) > LIMITS[HOST_CONTROL]:
            raise BundleError("제어/계산 source 합집합이 192개/4 MiB 한도를 초과했습니다.", "E_RESOURCE")
        records = [{"path": path, "bytes": len(raw.encode("utf-8")), "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()} for path, raw in sources.items()]
        manifest = {"schema": "rfad.host-calculation-source/0.3", "bundle_sha256": hashlib.sha256(encoded).hexdigest(),
                    "bundle_bytes": len(encoded), "code_files": records,
                    "control_bundle": control["source_bundle"], "math_bundle": math["source_bundle"]}
        return manifest, control, math, encoded
    except BundleError as error:
        raise ProjectError(error.code, str(error)) from error


def python_identity():
    """! @brief 실행 파일과 실제 ABI를 세션에 고정한다."""
    return {"implementation": sys.implementation.name, "version": platform.python_version(),
            "system": system_name(), "machine": machine_name(), "pointer_bits": struct.calcsize("P") * 8,
            "byteorder": sys.byteorder, "sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()}


class HostCalculationRuntime:
    """! @brief 수학 worker는 단일 writer 밖에서 계산하고 파일 게시 권한을 받지 않는다."""
    def __init__(self):
        self.identity = None
        self.source_bytes = None
        self.math = None
        self.stop = threading.Event()
        self.lock = threading.Lock()

    def establish(self):
        """! @brief 최초 계산 요청에서 전체 closure와 로딩 기록을 고정하며 native 라이브러리는 읽지 않는다."""
        if self.identity is not None:
            return self.verify()
        manifest, control, math, encoded = capture()
        try:
            _source_loading.pin(manifest["code_files"])
        except (ImportError, OSError) as error:
            raise ProjectError("E_VERSION", str(error)) from error
        try:
            identity = {**installation_metadata(), "application_source": manifest, "python": python_identity()}
        except OSError as error:
            raise ProjectError("E_VERSION", "host 계산 실행 환경의 원문 식별을 읽을 수 없습니다.") from error
        self.math, self.source_bytes, self.identity = math, encoded, identity
        return deepcopy(self.identity)

    def verify(self):
        """! @brief 이미 실행한 제어 source나 환경을 새 hash로 묵시 갱신하지 않는다."""
        if self.identity is None:
            return self.establish()
        try:
            _source_loading.verify(self.identity["application_source"]["code_files"])
        except (ImportError, OSError) as error:
            raise ProjectError("E_VERSION", "host 제어/계산 세션 원문이 변경되었습니다: " + str(error)) from error
        packages = installation_metadata()
        if any(self.identity[key] != value for key, value in packages.items()) or python_identity() != self.identity["python"]:
            raise ProjectError("E_VERSION", "host 계산 Python/고정 패키지가 세션 중 변경되었습니다.")
        return deepcopy(self.identity)

    def execute(self, operation, inputs):
        """! @brief 같은 입력/환경의 결정적 계산 영수증을 반환하며 미리보기는 workspace에 파일을 쓰지 않는다."""
        identity = self.establish()
        payload = canonical_bytes({"operation": operation, "inputs": inputs})
        if len(payload) > MAX_BYTES:
            raise ProjectError("E_RESOURCE", "host 계산 입력 8 MiB 한도를 초과했습니다.")
        if self.stop.is_set() or not self.lock.acquire(blocking=False):
            raise ProjectError("E_RESOURCE", "host 계산이 종료 중이거나 다른 계산이 실행 중입니다.")
        try:
            with TemporaryDirectory(prefix="TraceWave host calculation ") as temporary:
                stage = Path(temporary)
                for relative, source in self.math["sources"].items():
                    path = stage / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(source.encode("utf-8"))
                (stage / "input.json").write_bytes(payload)
                request = {"schema": "rfad.host-worker/0.1", "run_id": str(uuid4()), "nonce": str(uuid4()),
                    "input_sha256": hashlib.sha256(payload).hexdigest(), "identity_hash": canonical_hash(identity),
                    "runtime": {"source_bundle": self.math["source_bundle"], "code_files": self.math["code_files"],
                                "packages": installation_metadata(), "python_sha256": identity["python"]["sha256"]}}
                process = run_native([str(Path(sys.executable).resolve()), "-I", "-B", "-X", "utf8", str(stage / "tools/host_calculation_worker.py")],
                    cwd=stage, request_bytes=canonical_bytes(request) + b"\n", cancel=self.stop, timeout_seconds=60,
                    max_output_bytes=128 * 1024, output_directory=stage / "output",
                    max_file_bytes=MAX_BYTES, max_directory_bytes=MAX_BYTES, max_files=1)
                if process["termination"] != "completed" or process["returncode"] != 0:
                    raise ProjectError("E_RESOURCE", "host 계산 worker가 완료되지 않았습니다.", details={"termination": process["termination"], "stderr": process.get("stderr_tail", "")})
                try:
                    with (stage / "output/result.json").open("rb") as stream:
                        raw = stream.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise ProjectError("E_RESOURCE", "host 계산 결과 한도를 초과했습니다.")
                    response = json.loads(raw)
                except (OSError, ValueError, UnicodeError, RecursionError) as error:
                    raise ProjectError("E_HASH", "host 계산 결과 파일을 정규 JSON으로 읽을 수 없습니다.") from error
                base = {"schema", "run_id", "nonce", "input_sha256", "identity_hash"}
                permitted = (base | {"operation", "value"}, base | {"error"}, base | {"operation", "error"})
                if type(response) is not dict or set(response) not in permitted or canonical_bytes(response) != raw or response.get("schema") != "rfad.host-worker-result/0.1" or any(response.get(key) != request[key] for key in ("run_id", "nonce", "input_sha256", "identity_hash")):
                    raise ProjectError("E_HASH", "host 계산 결과의 실행/입력/source 소유가 다릅니다.")
                self.verify()
                if "error" in response:
                    error = response["error"]
                    if type(error) is not dict or type(error.get("code")) is not str or type(error.get("message_ko")) is not str or type(error.get("details", {})) is not dict:
                        raise ProjectError("E_HASH", "host 계산 오류 응답의 구조가 다릅니다.")
                    raise ProjectError(error["code"], error["message_ko"], details=error.get("details", {}))
                if response.get("operation") != operation:
                    raise ProjectError("E_HASH", "host 계산 결과의 작업 종류가 다릅니다.")
                result = response["value"]
                if type(result) is not dict:
                    raise ProjectError("E_HASH", "host 계산 값은 닫힌 object 응답이어야 합니다.")
                receipt = {"schema": "rfad.host-execution/0.1", "operation": operation, "input_sha256": request["input_sha256"],
                           "identity_hash": request["identity_hash"], "result_hash": canonical_hash(result)}
                return result, receipt
        finally:
            self.lock.release()
