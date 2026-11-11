"""! @brief 카탈로그 PCB의 불변 원본에서 CAD 생성, STEP 교환과 재열기를 검증한다."""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from rfad.application.cad import PROFILE, TOLERANCE_MM, build_cad_input
from rfad.application.cad_runtime import CODE_ROOT
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.display_mesh import validate_display_mesh
from rfad.domain.pcb_selection import EXTENSION_KEY

from .common import call, read_json_artifact, require, wait


ROLES = {"step", "brep", "display_mesh", "sidecar", "validation", "manifest"}


def _verified_bytes(service, descriptor):
    """! @brief 게시 참조의 원본 바이트를 읽고 길이와 SHA-256을 다시 검사한다."""
    raw = service.journal.read_artifact(descriptor)
    require(len(raw) == descriptor["bytes"], "CAD artifact byte count changed")
    require(hashlib.sha256(raw).hexdigest() == descriptor["sha256"], "CAD artifact SHA-256 changed")
    return raw


def _check_mapping(sidecar, projection):
    """! @brief body 식별자와 층/재료 대응을 실제 원본 형상까지 확인한다."""
    layers = {layer["id"]: layer for layer in projection["layers"]}
    shapes = {shape["id"]: shape for shape in projection["shapes"]}
    mapped = set()
    dielectric = set()
    for body in sidecar["body_map"]:
        layer = layers[body["layer_id"]]
        require(body["role"] == layer["role"], "CAD body layer role changed")
        if body["role"] == "dielectric":
            require(body["id"] == layer["id"] and body["material_id"] == layer["material_id"],
                    "Dielectric stable ID or material assignment changed")
            require({projection["board"]["id"], layer["id"]} <= set(body["source_entity_ids"]),
                    "Dielectric body lost board or layer source")
            dielectric.add(layer["id"])
        else:
            for identity in body["source_entity_ids"]:
                require(identity in shapes and identity not in mapped, "Conductor source mapping is missing or duplicated")
                source = shapes[identity]
                material = source["material_ref"] if source["material_ref"] is not None else layers[source["layer_id"]]["material_id"]
                require(source["layer_id"] == body["layer_id"] and source["net_id"] == body["net_id"] and
                        material == body["material_id"], "Conductor layer, net or material assignment changed")
                mapped.add(identity)
    require(mapped == set(shapes), "An exported conductor is absent from CAD body mapping")
    require(dielectric == {key for key, layer in layers.items() if layer["role"] == "dielectric"},
            "A dielectric layer is absent from CAD body mapping")


def _check_metrics(expected, actual):
    """! @brief 별도 STEP reader 측정값을 생성 당시 치수/부피/위상과 비교한다."""
    require(set(expected) == set(actual), "Reopened STEP stable product names changed")
    for name, source in expected.items():
        result = actual[name]
        require(result["valid_brep"] is True, "Reopened STEP contains an invalid solid")
        for key in ("solid_count", "section_loop_count", "through_hole_count"):
            require(result[key] == source[key], "Reopened STEP topology changed: " + key)
        for key in ("bbox_mm", "center_mm"):
            require(len(result[key]) == len(source[key]) and all(
                math.isclose(left, right, rel_tol=0.0, abs_tol=TOLERANCE_MM)
                for left, right in zip(result[key], source[key])), "Reopened STEP dimensions changed: " + key)
        for key, absolute in (("volume_mm3", TOLERANCE_MM ** 3), ("section_area_mm2", TOLERANCE_MM ** 2),
                              ("thickness_mm", TOLERANCE_MM)):
            relative = 0.0 if key == "thickness_mm" else 1e-7
            require(math.isclose(result[key], source[key], rel_tol=relative, abs_tol=absolute),
                    "Reopened STEP measurement changed: " + key)


def _native_reopen(service, artifacts, sidecar, result):
    """! @brief 게시된 STEP/B-rep를 별도 격리 CAD 프로세스로 읽으며 다른 커널 검증을 주장하지 않는다."""
    runtime = service.cad.runtime
    require(runtime is not None, "CAD verification requires the configured isolated runtime")
    program = (
        "import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
        "from rfad.adapters.cad.native import read_step;import cadquery as cq;"
        "shape=cq.Shape.importBrep(sys.argv[3]);"
        "print(json.dumps({'step':read_step(Path(sys.argv[2])),"
        "'brep_valid':shape.isValid(),'brep_solids':len(shape.Solids())}))"
    )
    with TemporaryDirectory(prefix="TraceWave catalog STEP ") as temporary:
        step, brep = Path(temporary) / "model.step", Path(temporary) / "model.brep"
        step.write_bytes(_verified_bytes(service, artifacts["step"]))
        brep.write_bytes(_verified_bytes(service, artifacts["brep"]))
        completed = subprocess.run(
            [str(runtime.python), "-I", "-X", "utf8", "-c", program, str(CODE_ROOT / "src"), str(step), str(brep)],
            capture_output=True, timeout=60, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    require(completed.returncode == 0, "Published CAD reopen failed: " + completed.stderr.decode("utf-8", errors="replace")[-4096:])
    restored = json.loads(completed.stdout)
    require(restored["brep_valid"] is True and restored["brep_solids"] == result["solid_count"],
            "Published B-rep validity or solid count changed")
    _check_metrics({body["name"]: body["metrics"] for body in sidecar["body_map"]}, restored["step"])
    return {"status": "passed_same_kernel", "kernel_independent": False,
            "reader": "OCP STEPCAFControl_Reader", "body_count": len(restored["step"]),
            "brep_valid": True, "brep_solids": restored["brep_solids"]}


def _check_package(service, snapshot, document, result, status, projection):
    """! @brief 실제 출력의 출처, 고정 스냅샷, 형상과 표시 참조를 함께 검증한다."""
    require(result["snapshot"] == snapshot and result["profile"] == PROFILE, "CAD result snapshot or profile changed")
    require(result["status"] == "generated_unverified" and all(result[key] is False for key in
            ("physics_verified", "manufacturing_verified", "kernel_independent")), "CAD result overstates verification")
    require(status["artifacts"] == result["artifacts"], "CAD job and result artifact descriptors differ")
    artifacts = {item["role"]: item for item in result["artifacts"]}
    require(len(result["artifacts"]) == len(ROLES) and set(artifacts) == ROLES, "CAD package artifacts are incomplete or duplicated")
    for artifact in artifacts.values():
        _verified_bytes(service, artifact)
        require(artifact["snapshot_id"] == snapshot["snapshot_id"], "CAD artifact belongs to a different snapshot")
    sidecar = read_json_artifact(service, artifacts["sidecar"])
    manifest = read_json_artifact(service, artifacts["manifest"])
    validation = read_json_artifact(service, artifacts["validation"])
    mesh = read_json_artifact(service, artifacts["display_mesh"])
    require(sidecar["snapshot"] == snapshot and manifest["snapshot"] == snapshot, "CAD metadata snapshot changed")
    require(sidecar["source_semantics"] == document and canonical_hash(sidecar["source_semantics"]) == snapshot["content_hash"],
            "CAD sidecar source document changed")
    require(sidecar["source_semantics"]["extensions"][EXTENSION_KEY] == document["extensions"][EXTENSION_KEY],
            "CAD sidecar lost catalog selection evidence")
    require(sidecar["projection_sha256"] == manifest["input_sha256"] and sidecar["run_id"] == manifest["run_id"],
            "CAD projection and manifest are not bound to the same run")
    projected_hash = hashlib.sha256(canonical_bytes({**projection, "run_id": sidecar["run_id"]})).hexdigest()
    require(projected_hash == sidecar["projection_sha256"], "CAD output was not built from the expected source projection")
    require(manifest["artifacts"] == [item for item in result["artifacts"] if item["role"] != "manifest"],
            "CAD manifest artifact descriptors changed")
    require(all(item["run_id"] == sidecar["run_id"] for item in artifacts.values()), "CAD artifact run ID changed")
    require(validation == sidecar["verification"] and validation["status"] == "passed_same_kernel" and
            validation["kernel_independent"] is False, "CAD roundtrip evidence is missing")
    require(validation["body_overlap_checked_before_and_after"] is True, "CAD body overlap was not verified")
    require(len(sidecar["body_map"]) == result["body_count"], "CAD body count changed")
    _check_mapping(sidecar, projection)
    validate_display_mesh(mesh, snapshot=snapshot, run_id=sidecar["run_id"], body_map=sidecar["body_map"])
    step = _verified_bytes(service, artifacts["step"]).decode("ascii")
    require("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING" in sidecar["step_schema"] and
            sidecar["step_schema"] == result["step_schema"] and sidecar["step_schema"] in step,
            "Published STEP does not use the expected AP242 schema")
    require("SI_UNIT(.MILLI.,.METRE.)" in re.sub(r"\s+", "", step), "Published STEP length unit is not mm")
    return {"native_reopen": _native_reopen(service, artifacts, sidecar, result),
            "body_mapping": deepcopy(sidecar["body_map"]), "source_semantics_preserved": True,
            "catalog_evidence_preserved": True, "display_mesh_validated": True,
            "artifact_hashes_verified": True, "roundtrip_validation": validation}


def verify_cad(service, context, snapshot, document):
    """! @brief 같은 카탈로그 스냅샷으로 geometry.build와 export.build의 실제 결과를 검증한다."""
    require(EXTENSION_KEY in document.get("extensions", {}), "Catalog CAD verification requires a saved PCB selection")
    require(read_json_artifact(service, snapshot["artifact"]) == document, "CAD input differs from immutable snapshot")
    projection = build_cad_input(document, snapshot)
    operations = []
    for method, key, value in (("geometry.build", "projection_kind", "brep"), ("export.build", "format", "step")):
        data = {"snapshot": {name: snapshot[name] for name in ("snapshot_id", "content_hash")}, "profile": PROFILE, key: value}
        result, status = wait(service, call(service, method, data, context, mutation=True))
        require([event["state"] for event in status["events"]] == ["queued", "running", "completed"],
                "CAD job did not complete the expected lifecycle")
        evidence = _check_package(service, snapshot, document, result, status, projection)
        latest = call(service, "cad.latest", {}, context)
        require(latest["result"] == result and latest["job_id"] == status["job_id"], "Latest CAD does not identify the completed operation")
        operations.append({"method": method, "result": result, "job_status": status, **evidence})
    require(operations[0]["body_mapping"] == operations[1]["body_mapping"], "CAD geometry and STEP export mapped the same source differently")
    require(read_json_artifact(service, snapshot["artifact"]) == document, "CAD verification mutated the source snapshot")
    return {"status": "passed", "snapshot": snapshot, "operations": operations, "latest": latest,
            "physics_verified": False, "manufacturing_verified": False, "kernel_independent": False}


def restore_cad(service, context, snapshot, expected):
    """! @brief CAD 런타임과 카탈로그가 없는 재시작에서 동일 참조와 파일 바이트를 확인한다."""
    require(call(service, "cad.latest", {}, context) == expected["latest"], "Reopened latest CAD response changed")
    require(expected["snapshot"] == snapshot, "Reopened CAD verification snapshot changed")
    document = read_json_artifact(service, snapshot["artifact"])
    require(canonical_hash(document) == snapshot["content_hash"], "Reopened source snapshot content hash changed")
    for operation in expected["operations"]:
        status = call(service, "job.status", {"job_id": operation["job_status"]["job_id"]})
        require(status == operation["job_status"], "Reopened CAD job status or artifact descriptors changed")
        artifacts = {item["role"]: item for item in status["artifacts"]}
        for artifact in artifacts.values():
            _verified_bytes(service, artifact)
        sidecar = read_json_artifact(service, artifacts["sidecar"])
        require(sidecar["snapshot"] == snapshot and sidecar["source_semantics"] == document, "Reopened CAD source semantics changed")
        mesh = read_json_artifact(service, artifacts["display_mesh"])
        validate_display_mesh(mesh, snapshot=snapshot, run_id=sidecar["run_id"], body_map=sidecar["body_map"])
