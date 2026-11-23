"""! @brief 고정 WSL 런타임 캡처와 봉인 입력의 staging을 담당한다."""

import hashlib
import json
from pathlib import Path, PurePosixPath

from rfad.application.canonical import canonical_bytes
from rfad.application import source_bundle
from rfad.application.solver import RUNTIME_PROFILE
from rfad.domain.errors import ProjectError
from rfad.domain.resource_limits import MAX_WORKER_SOURCE_FILES

CODE_ROOT = Path(__file__).resolve().parents[3]


class SolverRuntime:
    """! @brief API와 분리된 고정 WSL 설치 및 worker 바이트를 캡처한다."""

    def __init__(self, transport=None, *, audit=None, manifest=None):
        """! @brief native 모듈을 호스트에 import하지 않고 설치 명세만 읽는다."""
        if transport is None:
            from rfad.application.wsl_process import WslRuntime

            transport = WslRuntime(transfer_timeout_seconds=240.0)
        self.transport = transport
        audit_data = json.loads((audit or CODE_ROOT / ".local/wsl/native-audit.json").read_bytes())
        manifest_data = json.loads((manifest or CODE_ROOT / "runtime_profiles/python-openems-linux-x64.json").read_bytes())
        if audit_data.get("status") != "passed" or audit_data.get("qt_found") is not False or manifest_data.get("qt_allowed") is not False:
            raise ProjectError("E_VERSION", "검증된 Qt 없는 openEMS 설치 명세가 필요합니다.")
        try:
            bundle = source_bundle.build(CODE_ROOT, source_bundle.SOLVER, max_files=MAX_WORKER_SOURCE_FILES)
        except source_bundle.BundleError as error:
            raise ProjectError(error.code, str(error)) from error
        self.sources, self.source_bytes = bundle["sources"], bundle["source_bytes"]
        self.manifest_bytes = canonical_bytes({"schema": "rfad.openems-worker-runtime/0.1", "python_manifest": manifest_data,
                                              "native_audit": audit_data, "source_bundle": bundle["source_bundle"]})
        self.identity = {"runtime_profile": RUNTIME_PROFILE, "manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest(),
                         "code_files": bundle["code_files"], "source_bundle": bundle["source_bundle"],
                         "transport": transport.identity()}
        supervisor = next(record for record in bundle["code_files"] if record["path"] == "tools/wsl_supervisor.py")
        if ("supervisor_sha256" in self.identity["transport"]
                and self.identity["transport"]["supervisor_sha256"] != supervisor["sha256"]):
            raise ProjectError("E_VERSION", "전송 supervisor와 봉인된 소스의 실제 바이트가 다릅니다.")


def stage_solver_job(journal, runtime, job):
    """! @brief journal에서 읽은 바이트만 새로운 작업 디렉터리로 복제한다."""
    captured = job["solver"]
    if captured["runtime"] != runtime.identity:
        raise ProjectError("E_VERSION", "재시작 후 런타임이 변경되어 자동 실행할 수 없습니다.")
    stage = journal._safe_path("solver-staging/" + job["run_id"])
    stage.mkdir(parents=True, exist_ok=False)
    sources = json.loads(journal.read_artifact(captured["source"]))
    expected = {f["path"]: f for f in captured["runtime"]["code_files"]}
    if sources.keys() != expected.keys():
        raise ProjectError("E_HASH", "worker 소스 목록이 변경되었습니다.")
    for relative, text in sources.items():
        parts = PurePosixPath(relative).parts
        if ".." in parts or PurePosixPath(relative).is_absolute() or "\\" in relative or ":" in relative or not relative.endswith(".py"):
            raise ProjectError("E_HASH", "worker 소스 경로가 유효하지 않습니다.")
        raw = text.encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != expected[relative]["sha256"] or len(raw) != expected[relative]["bytes"]:
            raise ProjectError("E_HASH", "worker 소스 해시가 변경되었습니다.")
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    manifest = journal.read_artifact(captured["manifest"])
    if hashlib.sha256(manifest).hexdigest() != captured["runtime"]["manifest_sha256"]:
        raise ProjectError("E_HASH", "worker runtime 명세 해시가 변경되었습니다.")
    (stage / "runtime.json").write_bytes(manifest)
    phase = "prepare" if job["kind"] == "em_prepare" else "analysis"
    if job["input"].get("task_plan", {}).get("execution_mode") == "postprocess_only":
        phase = "postprocess_only"
    request = {"schema": "rfad.openems-worker/0.1", "phase": phase, "run_id": job["run_id"], "nonce": captured["nonce"],
               "analysis_plan": captured["analysis_plan"], "runtime": captured["runtime"], "input_files": []}
    if "prepared_plan" in captured:
        request.update(prepared_plan=captured["prepared_plan"], preparation=captured["preparation"])
    for item in captured.get("preparation_files", []) + captured.get("raw_files", []):
        relative = "input/" + item["path"].removeprefix("output/")
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        journal.copy_artifact(item["artifact"], target.relative_to(journal.root).as_posix())
        request["input_files"].append({"path": relative, "role": item["role"], "sha256": item["sha256"], "bytes": item["bytes"]})
    (stage / "request.json").write_bytes(canonical_bytes(request))
    if "source_bundle" in captured["runtime"]:
        try:
            source_bundle.verify_stage(stage, captured["runtime"]["source_bundle"], captured["runtime"]["code_files"])
        except source_bundle.BundleError as error:
            raise ProjectError(error.code, str(error)) from error
    return stage, request
