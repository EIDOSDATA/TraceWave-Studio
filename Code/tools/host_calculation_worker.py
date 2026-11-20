"""! @brief 검증한 source bytes로만 계산하며 journal/프로젝트 writer를 열지 않는다."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    """! @brief 작은 소유 envelope와 고정 파일만 받아 유한 계산 결과를 반환한다."""
    raw = sys.stdin.buffer.readline(65537)
    if len(raw) > 65536 or not raw.endswith(b"\n"):
        return 2
    request = json.loads(raw)
    if set(request) != {"schema", "run_id", "nonce", "input_sha256", "identity_hash", "runtime"} or request["schema"] != "rfad.host-worker/0.1":
        return 2
    root = Path(__file__).resolve().parents[1]
    expected = request["runtime"]
    relative = "src/rfad/application/source_bundle.py"
    record = next(row for row in expected["code_files"] if row["path"] == relative)
    with (root / relative).open("rb") as stream:
        bootstrap = stream.read(record["bytes"] + 1)
    if len(bootstrap) != record["bytes"] or hashlib.sha256(bootstrap).hexdigest() != record["sha256"]:
        return 2
    loader = {"__name__": "_rfad_host_bootstrap", "__file__": str(root / relative)}
    exec(compile(bootstrap, str(root / relative), "exec"), loader)
    loader["install_guard"](root, expected["source_bundle"], expected["code_files"])
    from rfad.application.source_bundle import HOST_MATH
    from rfad.adapters.network_backend import installation_metadata
    from rfad.application.canonical import canonical_bytes
    from rfad.domain.errors import ProjectError
    from rfad.domain.host_calculation import execute
    result = {key: request[key] for key in ("run_id", "nonce", "input_sha256", "identity_hash")}
    result["schema"] = "rfad.host-worker-result/0.1"
    try:
        if expected["source_bundle"]["profile"] != HOST_MATH:
            raise ProjectError("E_VERSION", "host worker는 닫힌 수학 source profile만 실행합니다.")
        if installation_metadata() != expected["packages"] or hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() != expected["python_sha256"]:
            raise ProjectError("E_VERSION", "host 계산 Python/패키지 환경이 고정 기록과 다릅니다.")
        with (root / "input.json").open("rb") as stream:
            payload = stream.read(8 * 1024**2 + 1)
        if len(payload) > 8 * 1024**2 or hashlib.sha256(payload).hexdigest() != request["input_sha256"]:
            raise ProjectError("E_HASH", "host 계산 입력의 크기/hash가 다릅니다.")
        value = json.loads(payload)
        if set(value) != {"operation", "inputs"} or canonical_bytes(value) != payload:
            raise ProjectError("E_SCHEMA", "host 계산 입력이 정규 JSON 계약과 다릅니다.")
        result["operation"] = value["operation"]
        engine = {"profile": "rfad.host-math/0.1", "identity_hash": request["identity_hash"],
                  "math_source_sha256": expected["source_bundle"]["source_sha256"], "packages": expected["packages"]}
        result["value"] = execute(value["operation"], value["inputs"], engine)
    except ProjectError as error:
        result["error"] = error.diagnostic()
    encoded = canonical_bytes(result)
    if len(encoded) > 8 * 1024**2:
        result.pop("value", None)
        result["error"] = ProjectError("E_RESOURCE", "host 계산 결과 8 MiB 한도를 초과했습니다.").diagnostic()
        encoded = canonical_bytes(result)
    output = root / "output"
    output.mkdir()
    (output / "result.json").write_bytes(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
