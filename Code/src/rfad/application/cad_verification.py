"""! @brief 기존 STEP 패키지를 바꾸지 않는 재검수 입력과 결과의 봉인을 담당한다."""

from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from rfad.application.cad import PROFILE
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError


def verification_input(service, state, context, data):
    """! @brief 완료한 원본 패키지의 manifest, sidecar와 불변 snapshot을 대조한다."""
    service._project(state, context)
    original = state["jobs"].get(data["job_id"])
    if (original is None or original.get("context") != context or original.get("state") != "completed"
            or original.get("operation_method") not in {"geometry.build", "export.build"} or "cad" not in original):
        raise ProjectError("E_NOT_FOUND", "현재 프로젝트의 완료된 STEP 출력 작업을 선택하십시오.")
    artifacts = original.get("artifacts", [])
    mapped = {item["role"]: item for item in artifacts}
    if len(mapped) != len(artifacts) or not {"manifest", "sidecar", "step"} <= mapped.keys():
        raise ProjectError("E_HASH", "원본 STEP 패키지의 필수 파일 역할이 다릅니다.")
    manifest_ref = mapped["manifest"]
    if manifest_ref["sha256"] != data["manifest_sha256"]:
        raise ProjectError("E_CONFLICT", "검토한 STEP 패키지 manifest가 달라졌습니다. 목록을 다시 읽으십시오.")
    for role, limit in (("manifest", 256 * 1024), ("sidecar", 1024 * 1024)):
        if not 0 < mapped[role]["bytes"] <= limit:
            raise ProjectError("E_RESOURCE", "원본 STEP 메타데이터가 허용 크기를 초과했습니다.")
    manifest = json.loads(service.journal.read_artifact(manifest_ref))
    snapshot = original["snapshot"]
    if (manifest.get("schema") != "rfad.cad-manifest/0.1" or manifest.get("run_id") != original["run_id"]
            or manifest.get("snapshot") != snapshot or manifest.get("input_sha256") != original["cad"]["input"]["sha256"]
            or manifest.get("runtime") != original["cad"]["runtime"] or manifest.get("status") != "generated_unverified"
            or manifest.get("artifacts") != [item for item in artifacts if item["role"] != "manifest"]):
        raise ProjectError("E_HASH", "STEP manifest가 완료 작업의 원본과 일치하지 않습니다.")
    registered = state["snapshots"].get(snapshot["snapshot_id"])
    if registered != snapshot or snapshot["project_id"] != context["project_id"]:
        raise ProjectError("E_HASH", "STEP 원본 snapshot의 소유 프로젝트 또는 기록이 다릅니다.")
    document = service._load({"current": snapshot["artifact"]})
    sidecar = json.loads(service.journal.read_artifact(mapped["sidecar"]))
    if (sidecar.get("schema") != "rfad.step-sidecar/0.1" or sidecar.get("profile") != PROFILE
            or sidecar.get("snapshot") != snapshot or sidecar.get("run_id") != original["run_id"]
            or sidecar.get("projection_sha256") != manifest["input_sha256"] or sidecar.get("unit") != "mm"
            or sidecar.get("source_semantics") != document or canonical_hash(document) != snapshot["content_hash"]):
        raise ProjectError("E_HASH", "STEP sidecar의 단위, 원본 의미 정보 또는 snapshot 결합이 다릅니다.")
    step = next((item for item in sidecar.get("files", []) if item.get("path") == "model.step"), None)
    if step is None or any(step.get(key) != mapped["step"].get(key) for key in ("sha256", "bytes", "role", "media_type")):
        raise ProjectError("E_HASH", "STEP 파일이 원본 sidecar의 출력과 다릅니다.")
    body_map = sidecar.get("body_map")
    if type(body_map) is not list or not 0 < len(body_map) <= 256:
        raise ProjectError("E_HASH", "STEP body 목록이 유효하지 않습니다.")
    service.journal.verify_file(mapped["step"])
    return deepcopy(snapshot), {
        "schema": "rfad.step-verification-input/0.1", "profile": PROFILE,
        "project_id": context["project_id"], "snapshot": deepcopy(snapshot), "original_job_id": original["job_id"],
        "original_run_id": original["run_id"], "source_manifest_sha256": manifest_ref["sha256"],
        "step_schema": sidecar["step_schema"], "tolerance_mm": 1e-6,
        "files": {name: deepcopy(mapped[role]) for name, role in (
            ("model.step", "step"), ("sidecar.json", "sidecar"), ("manifest.json", "manifest"))},
    }


def seal_verification(journal, job, package, output):
    """! @brief 새 검수 보고서만 봉인하며 원래 STEP와 검증 기록에는 쓰지 않는다."""
    expected = json.loads(journal.read_artifact(job["cad"]["input"]))
    if (package.get("schema") != "rfad.step-verification-package/0.1" or package.get("profile") != PROFILE
            or package.get("source_snapshot") != job["snapshot"] or package.get("status") != "generated_unverified"
            or package.get("original_job_id") != expected["original_job_id"]
            or package.get("source_manifest_sha256") != expected["source_manifest_sha256"]):
        raise ProjectError("E_HASH", "STEP 재검수 결과가 현재 작업의 원본 패키지와 다릅니다.")
    files = package.get("files")
    if (type(files) is not list or len(files) != 1 or files[0].get("path") != "verification.json"
            or files[0].get("role") != "verification" or files[0].get("media_type") != "application/json"
            or type(files[0].get("bytes")) is not int or not 0 < files[0]["bytes"] <= 1024 * 1024):
        raise ProjectError("E_HASH", "STEP 재검수는 닫힌 검수 보고서 한 개만 게시할 수 있습니다.")
    file = files[0]
    path = journal._safe_path("cad-staging/" + job["run_id"] + "/output/verification.json")
    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) != file["bytes"] or hashlib.sha256(raw).hexdigest() != file.get("sha256"):
        raise ProjectError("E_HASH", "STEP 검수 보고서의 크기 또는 hash가 다릅니다.")
    report = json.loads(raw)
    validation = report.get("verification", {})
    if (report.get("schema") != "rfad.step-verification/0.1" or report.get("input") != expected
            or report.get("run_id") != job["run_id"] or report.get("status") != "generated_unverified"
            or validation.get("status") != "passed_same_kernel" or validation.get("kernel_independent") is not False
            or validation.get("reader") != "OCP STEPCAFControl_Reader"
            or report.get("physics_verified") is not False or report.get("manufacturing_verified") is not False
            or package.get("verification") != {key: value for key, value in validation.items() if key != "bodies"}
            or package.get("step_schema") != expected["step_schema"]
            or package.get("body_count") != len(validation.get("bodies", []))):
        raise ProjectError("E_HASH", "STEP 검수 보고서의 범위 또는 원본 결합이 다릅니다.")
    bodies = validation["bodies"]
    if (not 0 < len(bodies) <= 256 or any(type(item.get("solid_count")) is not int or item["solid_count"] <= 0 for item in bodies)
            or package.get("solid_count") != sum(item["solid_count"] for item in bodies)):
        raise ProjectError("E_HASH", "STEP 재검수의 body/solid 개수가 유효하지 않습니다.")
    base = journal.read()["projects"][job["context"]["project_id"]]["path"] + "/artifacts/" + job["run_id"]
    reference = journal.seal_file(base + "/verification.json", path, expected_sha256=file["sha256"], expected_bytes=file["bytes"])
    common = {"producer": "rfad.step-verification/0.1", "run_id": job["run_id"], "snapshot_id": job["snapshot"]["snapshot_id"],
              "profile_id": PROFILE, "status": "generated_unverified", "media_type": "application/json"}
    artifact = {**reference, **common, "artifact_id": str(uuid4()), "role": "verification"}
    manifest = {"schema": "rfad.step-verification-manifest/0.1", "run_id": job["run_id"], "snapshot": job["snapshot"],
                "original_job_id": expected["original_job_id"], "source_manifest_sha256": expected["source_manifest_sha256"],
                "input_sha256": job["cad"]["input"]["sha256"], "runtime": job["cad"]["runtime"],
                "status": "generated_unverified", "artifacts": [artifact]}
    manifest_ref = journal.put_immutable(base + "/manifest.json", canonical_bytes(manifest))
    return [artifact, {**manifest_ref, **common, "artifact_id": str(uuid4()), "role": "manifest"}]
