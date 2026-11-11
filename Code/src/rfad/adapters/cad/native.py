"""! @brief 격리 CAD worker의 형상 생성/교환/표시 결과를 패키지로 조립한다.

@details 기하 알고리즘, body 검증, STEP 교환과 표시 mesh는 별도 모듈에서 담당한다.
무거운 CadQuery/OCP는 호출 시 로드하며 제조 또는 RF 검증 합격을 주장하지 않는다.
"""

from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re

from rfad.application.canonical import canonical_bytes
from rfad.adapters.cad.geometry import _require
from rfad.adapters.cad.bodies import _make_bodies, _metrics, _check_pairs, _check_via_contacts
from rfad.adapters.cad.step_io import _write_step, _read_step_shapes, _compare, read_step
from rfad.adapters.cad.display import _write_display_mesh

PROFILE = "rfad.step.mechanical/0.1"
SCHEMA = "rfad.cad-input/0.1"
MAX_FILE_BYTES = 64 * 1024 * 1024


def _file(path: Path, role: str, media_type: str) -> dict:
    """! @brief 닫힌 산출물의 크기와 streaming hash를 계산한다."""
    size = path.stat().st_size
    _require(0 < size <= MAX_FILE_BYTES, "CAD 산출물 크기가 허용 범위를 벗어났습니다.", code="E_RESOURCE")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": path.name, "role": role, "sha256": digest.hexdigest(), "bytes": size, "media_type": media_type}


def build_package(projection: dict, output_dir: Path) -> dict:
    """! @brief 고정 projection에서 STEP/B-rep/sidecar와 같은 커널 재입력 증거를 만든다.

    @param projection 서비스가 snapshot에서 봉인한 mm 기하와 원본 의미 정보.
    @param output_dir 새 작업 전용 디렉터리. 기존 산출물을 덮어쓰지 않는다.
    @return 최종 게시 전 확인할 파일 이름/hash와 생성 상태 manifest.
    """
    _require(projection.get("schema") == SCHEMA and projection.get("profile") == PROFILE,
             "지원하지 않는 CAD 입력 또는 STEP profile입니다.", code="E_UNSUPPORTED")
    _require(projection.get("unit") == "mm" and projection.get("angle_unit") == "deg",
             "CAD 입력 단위는 명시적인 mm/deg이어야 합니다.", code="E_UNIT")
    tolerance = projection.get("tolerance_mm")
    _require(type(tolerance) is float and tolerance == 1e-6, "지원하지 않는 CAD 허용오차입니다.", code="E_UNSUPPORTED")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: output_dir / name for name in ("model.step", "model.brep", "sidecar.json", "validation.json", "mesh.json")}
    _require(not any(path.exists() for path in paths.values()), "기존 CAD 산출물을 덮어쓸 수 없습니다.", code="E_CONFLICT")
    import cadquery as cq
    import OCP

    bodies = _make_bodies(cq, projection)
    _write_step(bodies, paths["model.step"], tolerance)
    _require(paths["model.step"].stat().st_size <= MAX_FILE_BYTES, "STEP 파일 상한을 초과했습니다.", code="E_RESOURCE")
    step = paths["model.step"].read_text(encoding="ascii")
    match = re.search(r"FILE_SCHEMA\s*\(\s*\((.*?)\)\s*\)", step, re.DOTALL)
    _require(match is not None and "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING" in match.group(1),
             "실제 STEP FILE_SCHEMA가 요청한 AP242가 아닙니다.")
    _require("SI_UNIT(.MILLI.,.METRE.)" in re.sub(r"\s+", "", step), "STEP 길이 단위가 mm로 선언되지 않았습니다.", code="E_UNIT")
    schema = match.group(1).strip().strip("'")
    expected = {body["name"]: body["metrics"] for body in bodies}
    restored_shapes = _read_step_shapes(paths["model.step"])
    restored = {name: _metrics(shape) for name, shape in restored_shapes.items()}
    validation = _compare(expected, restored, tolerance)
    restored_bodies = [{**body, "shape": restored_shapes[body["name"]], "metrics": restored[body["name"]]} for body in bodies]
    _check_pairs(restored_bodies, tolerance)
    _check_via_contacts(restored_bodies, tolerance)
    validation["explicit_via_pad_contacts_checked_before_and_after"] = True
    compound = cq.Compound.makeCompound([body["shape"] for body in bodies])
    _require(compound.exportBrep(str(paths["model.brep"])), "B-rep 파일 저장이 실패했습니다.", code="E_DISK")
    _write_display_mesh(bodies, projection, paths["mesh.json"])
    runtime = {"cadquery": importlib.metadata.version("cadquery"),
               "cadquery_ocp": importlib.metadata.version("cadquery-ocp"),
               "ocp": OCP.__version__, "python": platform.python_version(), "platform": platform.platform()}
    files = [_file(paths["model.step"], "step", "model/step"),
             _file(paths["model.brep"], "brep", "application/vnd.opencascade.brep"),
             _file(paths["mesh.json"], "display_mesh", "application/json")]
    paths["validation.json"].write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files.append(_file(paths["validation.json"], "validation", "application/json"))
    sidecar = {"schema": "rfad.step-sidecar/0.1", "status": "generated_unverified", "profile": PROFILE,
               "snapshot": deepcopy(projection["snapshot"]), "project_id": projection["project_id"],
               "revision_id": projection["revision_id"], "run_id": projection.get("run_id"),
               "projection_sha256": hashlib.sha256(canonical_bytes(projection)).hexdigest(),
               "unit": "mm", "transform": deepcopy(projection["transform"]), "runtime": runtime,
               "step_schema": schema, "writer": "OCP STEPCAFControl_Writer", "cap": "round",
               "files": files, "body_map": [{key: value for key, value in body.items() if key != "shape"} for body in bodies],
               "source_semantics": deepcopy(projection["source_semantics"]), "omissions": deepcopy(projection.get("omissions", [])),
               "brep_identity_scope": "Compound geometry only. Stable identities are STEP product names and this body_map; file/body order is not an identity.",
               "verification": validation, "manufacturing_verified": False, "rf_verified": False}
    paths["sidecar.json"].write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files.append(_file(paths["sidecar.json"], "sidecar", "application/json"))
    return {"schema": "rfad.cad-package/0.1", "status": "generated_unverified", "profile": PROFILE,
            "source_snapshot": deepcopy(projection["snapshot"]), "files": files, "step_schema": schema,
            "body_count": len(bodies), "solid_count": sum(body["metrics"]["solid_count"] for body in bodies),
            "runtime": runtime, "validation": {key: value for key, value in validation.items() if key != "bodies"}}
