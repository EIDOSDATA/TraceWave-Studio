"""! @brief CAD 결과 파일과 원본 결합을 검증하고 불변 패키지로 봉인한다."""

import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from rfad.application.cad import PROFILE
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.display_mesh import MAX_MESH_BYTES, validate_display_mesh
from rfad.domain.errors import ProjectError

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 128 * 1024 * 1024
OUTPUTS = {"model.step": "step", "model.brep": "brep", "sidecar.json": "sidecar", "validation.json": "validation", "mesh.json": "display_mesh"}


def seal_cad_outputs(journal, job: dict, package: dict, output: Path) -> list[dict]:
    """! @brief 닫힌 필수 파일을 검증하고 마지막에 패키지 manifest를 만든다."""
    if package.get("schema") != "rfad.cad-package/0.1" or package.get("status") != "generated_unverified":
        raise ProjectError("E_HASH", "CAD 패키지 계약 또는 검증 상태가 다릅니다.")
    files = package.get("files")
    if type(files) is not list or len(files) != len(OUTPUTS) or {item.get("path") for item in files} != set(OUTPUTS):
        raise ProjectError("E_HASH", "CAD 필수 파일 목록이 다르거나 중복되었습니다.")
    if any(type(item.get("bytes")) is not int or not 0 < item["bytes"] <= MAX_FILE_BYTES for item in files) or sum(item["bytes"] for item in files) > MAX_PACKAGE_BYTES:
        raise ProjectError("E_RESOURCE", "CAD 패키지 파일 크기가 상한을 초과했습니다.")
    if package.get("profile") != PROFILE or package.get("source_snapshot") != job["snapshot"]:
        raise ProjectError("E_HASH", "CAD 패키지의 원본 스냅샷 또는 출력 profile이 다릅니다.")
    for name in ("body_count", "solid_count"):
        if type(package.get(name)) is not int or not 0 < package[name] <= 256:
            raise ProjectError("E_HASH", "CAD 결과의 body/solid 개수가 유효하지 않습니다.")
    validate_cad_contents(journal, job, package, files)
    state = journal.read()
    project = state["projects"][job["context"]["project_id"]]
    base = project["path"] + "/artifacts/" + job["run_id"]
    artifacts = []
    for item in files:
        if item.get("role") != OUTPUTS[item["path"]]:
            raise ProjectError("E_HASH", "CAD 산출물의 역할이 다릅니다.")
        path = journal._safe_path("cad-staging/" + job["run_id"] + "/output/" + item["path"])
        reference = journal.seal_file(base + "/" + item["path"], path, expected_sha256=item["sha256"], expected_bytes=item["bytes"])
        artifacts.append({**reference, "artifact_id": str(uuid4()), "role": item["role"], "media_type": item["media_type"],
                          "producer": "rfad.cad/0.1", "run_id": job["run_id"], "snapshot_id": job["snapshot"]["snapshot_id"],
                          "profile_id": PROFILE, "status": "generated_unverified"})
    manifest = {"schema": "rfad.cad-manifest/0.1", "run_id": job["run_id"], "snapshot": job["snapshot"],
                "input_sha256": job["cad"]["input"]["sha256"], "runtime": job["cad"]["runtime"],
                "status": "generated_unverified", "artifacts": artifacts}
    manifest_ref = journal.put_immutable(base + "/manifest.json", canonical_bytes(manifest))
    return [*artifacts, {**manifest_ref, "artifact_id": str(uuid4()), "role": "manifest", "media_type": "application/json",
                        "producer": "rfad.cad/0.1", "run_id": job["run_id"], "snapshot_id": job["snapshot"]["snapshot_id"],
                        "profile_id": PROFILE, "status": "generated_unverified"}]


def validate_cad_contents(journal, job: dict, package: dict, files: list[dict]) -> None:
    """! @brief 요청 옵션과 무관하게 실제 STEP 헤더 및 sidecar 결합을 검사한다."""
    base = "cad-staging/" + job["run_id"] + "/output/"
    def read_small(name, limit):
        with journal._safe_path(base + name).open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ProjectError("E_RESOURCE", "CAD 메타데이터 파일이 상한을 초과했습니다.")
        expected = next(item for item in files if item["path"] == name)
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ProjectError("E_HASH", "CAD 메타데이터가 선언한 파일 hash와 다릅니다.")
        return json.loads(raw)
    sidecar = read_small("sidecar.json", 1024 * 1024)
    validation = read_small("validation.json", 1024 * 1024)
    if (sidecar.get("schema") != "rfad.step-sidecar/0.1" or sidecar.get("snapshot") != job["snapshot"]
            or sidecar.get("profile") != PROFILE or sidecar.get("run_id") != job["run_id"]
            or sidecar.get("projection_sha256") != job["cad"]["input"]["sha256"]
            or sidecar.get("unit") != "mm" or sidecar.get("status") != "generated_unverified"
            or canonical_hash(sidecar.get("source_semantics")) != job["snapshot"]["content_hash"]):
        raise ProjectError("E_HASH", "STEP sidecar가 원본 또는 현재 실행 파일에 결합되지 않았습니다.")
    embedded = {item["path"]: item for item in sidecar.get("files", [])}
    if embedded != {item["path"]: item for item in files if item["path"] != "sidecar.json"}:
        raise ProjectError("E_HASH", "STEP sidecar가 실제 파일 목록과 다릅니다.")
    if (validation.get("status") != "passed_same_kernel" or validation.get("kernel_independent") is not False
            or sidecar.get("verification") != validation or len(sidecar.get("body_map", [])) != package["body_count"]):
        raise ProjectError("E_HASH", "CAD 재입력 검증 근거 또는 body mapping이 다릅니다.")
    mesh = read_small("mesh.json", MAX_MESH_BYTES)
    validate_display_mesh(mesh, snapshot=job["snapshot"], run_id=job["run_id"], body_map=sidecar["body_map"])
    with journal._safe_path(base + "model.step").open("rb") as stream:
        header = stream.read(65536).decode("ascii")
    match = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'\s*\)\s*\)", header)
    if match is None or match.group(1) != package.get("step_schema") or sidecar.get("step_schema") != match.group(1) or not match.group(1).startswith("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING"):
        raise ProjectError("E_HASH", "실제 STEP schema가 AP242 profile과 다릅니다.")
