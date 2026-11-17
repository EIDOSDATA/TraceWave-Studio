"""! @brief 출력의 원본/검수/파일 hash를 확인하고 manifest를 마지막에 봉인한다."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from rfad.application import exchange_contract as contract
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError
from rfad.storage.sealed_files import verify
from rfad.storage.journal import MAX_STATE_BYTES
from rfad.application.job_state import append_event


def report_valid(report):
    """! @brief 형식 재입력 성공을 RF/제조 합격으로 확대하는 보고서를 거절한다."""
    if (type(report) is not dict or report.get("schema") != "rfad.exchange-verification/0.1"
            or report.get("profile") != contract.PROFILE or report.get("recipient_application_verified") is not False
            or report.get("status") != "passed_profile" or report.get("kernel_independent") is not False
            or report.get("manufacturing_verified") is not False or report.get("physics_verified") is not False):
        raise ProjectError("E_HASH", "출력 재검수 상태 또는 적용 범위가 유효하지 않습니다.")
    if len(canonical_bytes(report)) > 256 * 1024:
        raise ProjectError("E_RESOURCE", "출력 재검수 보고서가 상한을 초과했습니다.")


def checked_package(journal, job, package, output):
    """! @brief 하나라도 다른 바이트가 있으면 부분 패키지를 게시하지 않는다."""
    if (type(package) is not dict or package.get("schema") != "rfad.exchange-package/0.1"
            or package.get("profile") != contract.PROFILE or package.get("run_id") != job["run_id"]
            or package.get("source_snapshot") != job["snapshot"] or package.get("format") != job["input"]["format"]
            or package.get("status") != "generated_unverified"):
        raise ProjectError("E_HASH", "출력 패키지의 실행/스냅샷/profile이 다릅니다.")
    items = package.get("files")
    if type(items) is not list or not 3 <= len(items) < contract.MAX_FILES:
        raise ProjectError("E_RESOURCE", "출력 파일 개수가 상한을 벗어났습니다.")
    names, total = set(), 0
    for item in items:
        contract.fields(item, {"path", "role", "media_type", "bytes", "sha256"})
        name = item["path"]
        if (type(name) is not str or name in names or not re.fullmatch(r"(?:drawing(?:-\d{2})?\.(?:pdf|svg|dxf)|sidecar\.json|validation\.json)", name)
                or type(item["bytes"]) is not int or not 0 < item["bytes"] <= contract.MAX_FILE_BYTES):
            raise ProjectError("E_HASH", "출력 파일의 이름/중복/크기가 유효하지 않습니다.")
        expected_role = ("source" if name == "sidecar.json" else "verification" if name == "validation.json"
                         else "drawing" if job["input"]["options"]["mode"] == "drawing" else "fabrication_geometry")
        if item["role"] != expected_role:
            raise ProjectError("E_HASH", "출력 파일 역할이 이름과 다릅니다.")
        if expected_role in ("drawing", "fabrication_geometry") and not name.endswith("." + job["input"]["format"]):
            raise ProjectError("E_HASH", "출력 형식과 실제 파일 확장자가 다릅니다.")
        contract.hash_value(item["sha256"])
        names.add(name)
        total += item["bytes"]
        verify(output / name, {"uri": name, "bytes": item["bytes"], "sha256": item["sha256"]})
    if not {"sidecar.json", "validation.json"} <= names or total > contract.MAX_PACKAGE_BYTES:
        raise ProjectError("E_RESOURCE", "출력 원문/검수 자료가 누락됐거나 패키지 상한을 초과했습니다.")
    if {p.name for p in output.iterdir()} != names | {"manifest.json"}:
        raise ProjectError("E_HASH", "출력 폴더에 봉인하지 않은 추가/누락 파일이 있습니다.")
    for name in ("sidecar.json", "validation.json", "manifest.json"):
        if (output / name).stat().st_size > 2 * 1024 * 1024:
            raise ProjectError("E_RESOURCE", "출력 메타데이터 상한을 초과했습니다.")
    sidecar = json.loads((output / "sidecar.json").read_bytes())
    validation = json.loads((output / "validation.json").read_bytes())
    if json.loads((output / "manifest.json").read_bytes()) != package:
        raise ProjectError("E_HASH", "worker 응답과 실제 manifest가 다릅니다.")
    original = json.loads(journal.read_artifact(job["exchange"]["input"]))
    if (sidecar.get("schema") != "rfad.exchange-sidecar/0.1" or sidecar.get("snapshot") != job["snapshot"]
            or sidecar.get("profile") != contract.PROFILE or sidecar.get("run_id") != job["run_id"]
            or sidecar.get("input_sha256") != job["exchange"]["input"]["sha256"]
            or sidecar.get("source_semantics") != original["projection"]["source_semantics"]
            or sidecar.get("source_bindings") != {"names": original["names"], "dimensions": original["dimensions"]}
            or canonical_hash(sidecar.get("source_semantics")) != job["snapshot"]["content_hash"]
            or sidecar.get("format") != job["input"]["format"] or sidecar.get("options") != job["input"]["options"]
            or sidecar.get("verification") != validation or package.get("verification") != validation):
        raise ProjectError("E_HASH", "출력 sidecar가 원문/옵션/검수 결과와 다릅니다.")
    if sidecar.get("files") != [item for item in items if item["path"] != "sidecar.json"]:
        raise ProjectError("E_HASH", "출력 sidecar의 파일 대응이 다릅니다.")
    report_valid(validation)
    return items, validation


def seal(journal, job, package, output):
    """! @brief 전부 검증된 파일을 새 경로로 복제하고 완료 manifest만 게시한다."""
    output = Path(output)
    if job["exchange"]["operation"] == "generate":
        items, verification = checked_package(journal, job, package, output)
    else:
        verification = package["verification"]
        report_valid(verification)
        path = output / "verification.json"
        raw = path.read_bytes()
        if len(raw) > 256 * 1024 or json.loads(raw) != verification:
            raise ProjectError("E_HASH", "재검수 응답과 실제 보고서가 다릅니다.")
        items = [{"path": path.name, "role": "validation", "media_type": "application/json",
                  "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}]
    state = journal.read()
    project = state["projects"][job["context"]["project_id"]]
    base = project["path"] + "/exchange-artifacts/" + job["run_id"]
    artifacts = []
    for item in items:
        reference = {"uri": base + "/" + item["path"], "sha256": item["sha256"], "bytes": item["bytes"]}
        artifacts.append({**reference, "role": item["role"], "media_type": item["media_type"],
                          "profile_id": contract.PROFILE, "status": "generated_unverified"})
    manifest = {"schema": "rfad.exchange-manifest/0.1", "run_id": job["run_id"], "job_id": job["job_id"],
        "profile": contract.PROFILE, "snapshot": deepcopy(job["snapshot"]), "input_sha256": job["exchange"]["input"]["sha256"],
        "runtime": deepcopy(job["exchange"]["runtime"]), "status": "generated_unverified", "artifacts": artifacts,
        "verification": verification, "original_job_id": job["exchange"]["original_job_id"],
        "source_manifest_sha256": job["input"].get("manifest_sha256"),
        "worker_package": deepcopy(package) if job["exchange"]["operation"] == "generate" else None}
    original = state["jobs"].get(job["exchange"]["original_job_id"])
    manifest["original_writer_runtime"] = deepcopy(job["exchange"]["runtime"] if original is None else original["exchange"]["runtime"])
    manifest["current_reader_runtime"] = deepcopy(job["exchange"]["runtime"])
    encoded = canonical_bytes(manifest)
    reference = {"uri": base + "/manifest.json", "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}
    artifacts = [*artifacts, {**reference, "role": "manifest", "media_type": "application/json", "profile_id": contract.PROFILE,
                            "status": "generated_unverified"}]
    result = {"job_id": job["job_id"], "snapshot": deepcopy(job["snapshot"]), "profile": contract.PROFILE,
        "status": "generated_unverified", "artifacts": artifacts, "verification": verification,
        "original_job_id": job["exchange"]["original_job_id"], "source_manifest_sha256": job["input"].get("manifest_sha256"),
        "manufacturing_verified": False, "physics_verified": False, "kernel_independent": False}
    current = state["jobs"][job["job_id"]]
    if current["state"] != "running" or current["exchange"]["nonce"] != job["exchange"]["nonce"]:
        raise ProjectError("E_CONFLICT", "출력 게시 전에 취소 또는 소유권 변경을 확인했습니다.")
    current["exchange"]["resource_reserved"] = False
    current["artifacts"] = artifacts
    append_event(current, "completed", current["events"][-1]["timestamp"] + 1, operation_result=result)
    state_bytes = len(canonical_bytes(state)) + 4096
    if state_bytes > MAX_STATE_BYTES:
        raise ProjectError("E_RESOURCE", "출력 결과 게시가 journal 보존 상한을 초과했습니다.")
    journal._check_space(sum(item["bytes"] for item in items) + len(encoded) + state_bytes)
    for item in items:
        journal.seal_file(base + "/" + item["path"], output / item["path"],
                          expected_sha256=item["sha256"], expected_bytes=item["bytes"])
    journal.put_immutable(base + "/manifest.json", encoded)
    return result
