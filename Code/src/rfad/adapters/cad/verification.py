"""! @brief 별도 worker가 기존 STEP의 닫힌 바이트를 다시 읽어 기하를 검수한다."""

from copy import deepcopy
import json
from pathlib import Path

from rfad.adapters.cad.bodies import _metrics, _check_pairs, _check_via_contacts
from rfad.adapters.cad.geometry import _require
from rfad.adapters.cad.native import _file
from rfad.adapters.cad.physical import external_metrics, placement_review
from rfad.adapters.cad.step_io import _read_step_shapes, _compare, verify_assemblies
from rfad.application.canonical import canonical_bytes, canonical_hash


def verify_package(projection: dict, source_dir: Path, output_dir: Path) -> dict:
    """! @brief 과거 기대값과 새 reader 측정값을 비교하고 같은 커널이라는 한계를 보존한다."""
    _require(projection.get("schema") == "rfad.step-verification-input/0.1"
             and projection.get("profile") == "rfad.step.mechanical/0.1"
             and projection.get("tolerance_mm") == 1e-6, "지원하지 않는 STEP 재검수 입력입니다.", code="E_UNSUPPORTED")
    files = projection.get("files", {})
    _require(set(files) == {"model.step", "sidecar.json", "manifest.json"}, "STEP 재검수 입력 파일이 다릅니다.", code="E_HASH")
    for name, reference in files.items():
        actual = _file(source_dir / name, reference["role"], reference["media_type"])
        _require(all(actual[key] == reference[key] for key in ("sha256", "bytes")), "STEP 재검수 파일 봉인이 다릅니다.", code="E_HASH")
    _require(files["sidecar.json"]["bytes"] <= 1024 * 1024 and files["manifest.json"]["bytes"] <= 256 * 1024,
             "STEP 재검수 메타데이터가 너무 큽니다.", code="E_RESOURCE")
    sidecar = json.loads((source_dir / "sidecar.json").read_bytes())
    manifest = json.loads((source_dir / "manifest.json").read_bytes())
    _require(files["manifest.json"]["sha256"] == projection["source_manifest_sha256"]
             and sidecar.get("snapshot") == projection["snapshot"] == manifest.get("snapshot")
             and sidecar.get("run_id") == projection["original_run_id"] == manifest.get("run_id")
             and sidecar.get("projection_sha256") == manifest.get("input_sha256")
             and sidecar.get("unit") == "mm" and sidecar.get("step_schema") == projection["step_schema"]
             and canonical_hash(sidecar.get("source_semantics")) == projection["snapshot"]["content_hash"],
             "STEP 원본의 의미 정보, 단위 또는 실행 결합이 다릅니다.", code="E_HASH")
    bodies = sidecar.get("body_map", [])
    _require(type(bodies) is list and 0 < len(bodies) <= 256 and len({item["name"] for item in bodies}) == len(bodies),
             "STEP body 식별 목록이 유효하지 않습니다.", code="E_HASH")
    expected = {body["name"]: body["metrics"] for body in bodies}
    external = {body["name"] for body in bodies if body["role"] == "environment"}
    assemblies = {}
    restored_shapes = _read_step_shapes(source_dir / "model.step", assemblies)
    actual = {name: (external_metrics if name in external else _metrics)(shape) for name, shape in restored_shapes.items()}
    verification = _compare(expected, actual, projection["tolerance_mm"])
    verified = verify_assemblies(bodies, assemblies, projection["tolerance_mm"])
    if verified:
        verification["environment_assembly_hierarchy"] = verified
    restored = [{**body, "shape": restored_shapes[body["name"]], "metrics": actual[body["name"]]} for body in bodies]
    _check_pairs(restored, projection["tolerance_mm"])
    _check_via_contacts(restored, projection["tolerance_mm"])
    verification.update({"body_overlap_checked_before_and_after": False, "body_overlap_checked_after_read": True,
                         "explicit_via_pad_contacts_checked_after_read": True,
                         "expected_geometry_source": "immutable_original_sidecar", "fresh_reader_process": True})
    placement = placement_review(restored, projection["tolerance_mm"])
    if placement:
        verification["environment_placement"] = placement
    import importlib.metadata
    import platform
    import OCP

    runtime = {"cadquery": importlib.metadata.version("cadquery"), "cadquery_ocp": importlib.metadata.version("cadquery-ocp"),
               "ocp": OCP.__version__, "python": platform.python_version(), "platform": platform.platform()}
    report = {"schema": "rfad.step-verification/0.1", "status": "generated_unverified", "run_id": projection["run_id"],
              "input": deepcopy(projection), "original_writer_runtime": sidecar.get("runtime"), "reader_runtime": runtime,
              "verification": verification, "physics_verified": False, "manufacturing_verified": False}
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "verification.json"
    with path.open("xb") as stream:
        stream.write(canonical_bytes(report))
    return {"schema": "rfad.step-verification-package/0.1", "status": "generated_unverified", "profile": projection["profile"],
            "source_snapshot": deepcopy(projection["snapshot"]), "original_job_id": projection["original_job_id"],
            "source_manifest_sha256": projection["source_manifest_sha256"], "step_schema": projection["step_schema"],
            "body_count": len(bodies), "solid_count": sum(item["solid_count"] for item in actual.values()),
            "verification": {key: value for key, value in verification.items() if key != "bodies"},
            "files": [_file(path, "verification", "application/json")]}
