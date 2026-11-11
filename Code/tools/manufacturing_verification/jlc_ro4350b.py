"""! @brief JLC RO4350B 후보의 미정 원본과 별도 탐색 모델을 같은 프로젝트에 보존한다."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from catalog_pcb_verification.common import call, read_json_artifact, require, wait
from create_jlc_catalog_verification import catalog_read, prepare_geometry_fixture
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.catalog.service import CatalogService
from rfad.domain.material_models import LEGACY_MODEL, TOTAL_TAN_DELTA_MODEL
from rfad.domain.units import Quantity
from verify_pcb_worker import create_fixture


CODE_ROOT = Path(__file__).resolve().parents[2]
DK_RECORD = "PCB026460"
DF_RECORD = "PCB026461"
MODEL_BAND = {"min": 2.4e9, "max": 2.4835e9}
REFERENCE_SIGMA = 58e6
IACS_SOURCE = "https://nvlpubs.nist.gov/nistpubs/Legacy/circ/nbscircular31e2.pdf"
OMISSIONS = ["soldermask", "ENIG nickel/gold layers", "copper roughness", "anisotropy",
             "dielectric dispersion", "SMA launch and cable", "fabrication tolerances"]


def digest(path):
    """! @brief 파일의 원본 바이트를 바꾸지 않고 해시를 구한다."""
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(fixture, candidate):
    """! @brief 시험 물성을 먼저 제거한 뒤 출처 명목 치수와 명시 급전만 구성한다."""
    require(candidate["candidate"]["laminate_grade"] == "RO4350B", "RO4350B 후보 자료가 필요합니다.")
    prepared = prepare_geometry_fixture(fixture)
    document = prepared["document"]
    design = candidate["selected_design"]
    require(design["copper_layer_count"] == 2, "양면 동박 후보만 지원합니다.")
    require(len(document["stackup"]) == 3 and [x["role"] for x in document["stackup"]] == ["conductor", "dielectric", "conductor"],
            "동박/코어/동박 순서의 명시 IFA 기하가 필요합니다.")
    height = 0.0
    for layer in document["stackup"]:
        thickness = design["core_nominal_mm"] if layer["role"] == "dielectric" else design["outer_copper_each_nominal_mm"]
        layer["thickness"] = Quantity.from_value(thickness, "mm").to_dict()
        layer["z_min"] = Quantity.from_value(height, "mm").to_dict()
        height += thickness
    port_height = design["outer_copper_each_nominal_mm"] + design["core_nominal_mm"]
    for port in document["ports"]:
        for endpoint in ("start", "stop"):
            port["excitation_box"][endpoint][2] = Quantity.from_value(port_height, "mm").to_dict()
        port["validity_hz"] = {key: Quantity.from_value(value, "Hz").to_dict() for key, value in MODEL_BAND.items()}
        port["reference_plane"] = "탐색용 이상적 50 ohm 국부 gap 포트. 실제 SMA/케이블 기준면이 아님."
    actual_materials = []
    for index, material in enumerate(list(document["materials"])):
        actual = deepcopy(material)
        actual["id"] = str(uuid4())
        actual["name"] = "실제 납품 물성 미확정: " + ("RO4350B" if index == 0 else "JLC 동박")
        actual["source_refs"] = [candidate["candidate"]["id"]]
        actual["assumptions"] = ["납품 시료의 목표 대역 물성은 미정으로 보존하며 이 재료를 해석에 연결하지 않는다."]
        document["materials"].append(actual)
        actual_materials.append(actual["id"])
    document["metadata"].update(name="JLC RO4350B 30 mil 탐색용 IFA",
                                description="제조사 관측을 참고한 별도 탐색 모델. 명목 코어/구리만 표현하며 마스크/ENIG/거칠기/분산/실장/공차를 생략. 실제 납품 물성과 제조/측정 검증은 미정.")
    prepared["description"] = document["metadata"]["description"]
    return prepared, actual_materials


def specification(document, candidate, catalog_id):
    """! @brief 원문 관측과 대역 외 근사 선택, IACS 기준 구리를 명시적 이유로 구분한다."""
    layers = document["stackup"]
    core_id, copper_id = layers[1]["material_id"], layers[0]["material_id"]
    band = {**MODEL_BAND, "reason": "사용자가 허용한 2.400~2.4835 GHz 탐색 상수 모델 대역이며 제조사 보증/측정 대역이 아님"}
    missing = {"mode": "missing", "reason": "원본 미정값을 보존하며 이 모델에서 소비하지 않음"}
    core = {"key": "core", "name": "탐색 RO4350B: Design Dk/총 Df 근사", "model": TOTAL_TAN_DELTA_MODEL,
            "model_reason": "공개 Df를 총 전기 손실로 표현한다. 독립 전도도는 미정으로 보존하고 추가 가산하지 않음",
            "properties": {
                "epsilon_r": {"mode": "user", "value": 3.66, "record_id": DK_RECORD,
                              "reason": "Design Dk 3.66의 원문 8~40 GHz 조건을 보존하고 2.4 GHz 좁은 대역에 등방성 상수로 근사. 실측 확정값 아님"},
                "tan_delta": {"mode": "user", "value": 0.0031, "record_id": DF_RECORD,
                              "reason": "23 C/Z 방향 2.5 GHz의 typical Df를 2.4 GHz 좁은 대역에 근사. Dk와 동일 시험 조건이 아님"},
                "conductivity": deepcopy(missing)}, "validity_hz": band}
    copper = {"key": "copper", "name": "탐색 기준 구리: 100% IACS / 20 C", "model": LEGACY_MODEL,
              "model_reason": "유한 전도 sheet의 기준 구리 모델이며 JLC 완성 동박의 측정값이 아님",
              "properties": {"epsilon_r": deepcopy(missing), "tan_delta": deepcopy(missing),
                             "conductivity": {"mode": "user", "value": REFERENCE_SIGMA,
                                              "reason": "100% IACS 20 C 표준 저항률의 역수 58 MS/m를 기준 구리로 선택함. JLC 제공값 아님: " + IACS_SOURCE}},
              "validity_hz": deepcopy(band)}
    rows = [{"key": key, "name": layer["name"], "role": layer["role"], "thickness_mm": layer["thickness"]["value_si"] * 1000}
            for key, layer in zip(("bottom", "core", "top"), layers, strict=True)]
    return {"source": None, "catalog_id": catalog_id, "materials": [core, copper],
            "material_ids": {"core": core_id, "copper": copper_id}, "layers": rows,
            "layer_ids": {key: layer["id"] for key, layer in zip(("bottom", "core", "top"), layers, strict=True)},
            "material_assignments": {"bottom": "copper", "core": "core", "top": "copper"},
            "layout_reason": "RO4350B 표준 30 mil 코어와 1 oz 동박의 명목 모델. JLC 완성 명목 0.9 mm와 합계 0.832 mm 차이를 배분하지 않음",
            "notes": ["사용자가 제조사 자료를 근거로 한 탐색 근사를 허용함. 미정 실제 물성은 별도 미사용 재료로 보존함.",
                      "후보: " + candidate["candidate"]["id"],
                      "제작 서비스: https://jlcpcb.com/pcb-fabrication/high-frequency-pcb",
                      "생략 모델: " + ", ".join(OMISSIONS),
                      "기존 IFA의 XY 설계 기하를 재사용한 탐색이며 정합/수렴/제작/측정 정확도를 검증한 안테나가 아님."]}


def run(workspace, report_path, database, *, accept_approximations=False):
    """! @brief 명시적으로 허용한 새 탐색 프로젝트만 만들고 실제 미정 입력을 검증한다."""
    require(accept_approximations, "탐색 근사와 생략 항목의 명시적 수용이 필요합니다.")
    workspace, report_path, database = Path(workspace), Path(report_path), Path(database)
    require(not workspace.exists() and not report_path.exists(), "새 workspace와 보고서 경로를 지정하십시오.")
    candidate_path = CODE_ROOT / "fixtures/manufacturing/jlc_ro4350b_candidate.json"
    fixture_path = CODE_ROOT / "fixtures/ifa_feed_smoke.json"
    candidate, fixture = (json.loads(path.read_bytes()) for path in (candidate_path, fixture_path))
    before = {str(path): digest(path) for path in (candidate_path, fixture_path, database)}
    prepared, actual_ids = prepare(fixture, candidate)
    catalog_status = catalog_read(CatalogService(database), "catalog.status", {})
    require(catalog_status.get("available") is True, "읽을 수 있는 전체 PCB 카탈로그가 필요합니다.")
    catalog_id = catalog_status["catalog_id"]
    with ProjectService(workspace, catalog_database=database) as service:
        context, project_path, initial = create_fixture(service, prepared)
        original = read_json_artifact(service, initial["artifact"])
        spec = specification(original, candidate, catalog_id)
        spec["notes"].append("후보 원본 SHA-256: " + before[str(candidate_path)])
        request = {"expected_revision": initial["revision_id"], "selection_id": str(uuid4()), "specification": spec}
        preview = call(service, "pcb.selection.preview", request, context)
        require(preview["can_apply"], "탐색 선택을 적용할 수 없습니다: " + json.dumps(preview["issues"], ensure_ascii=False))
        changed = call(service, "pcb.selection.apply", {**request, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())}, context, mutation=True)
        wait(service, call(service, "project.save", {"expected_revision": changed["new_revision"]}, context, mutation=True))
        snapshot, _ = wait(service, call(service, "snapshot.create", {"expected_revision": changed["new_revision"],
                                                                  "description": "미정 납품 물성과 분리한 출처 기반 탐색 모델"}, context, mutation=True))
        document = read_json_artifact(service, snapshot["artifact"])
        for material in document["materials"]:
            if material["id"] in actual_ids:
                require(all(material[key]["value_si"] is None for key in ("epsilon_r", "tan_delta", "conductivity")), "실제 물성이 임의로 채워졌습니다.")
                require(all(value["value_si"] is None for value in material["validity_hz"].values()), "실제 적용 대역이 임의로 채워졌습니다.")
        require(not set(actual_ids) & {layer["material_id"] for layer in document["stackup"]}, "미정 납품 물성이 해석에 연결되었습니다.")
        require(document["geometry"] == original["geometry"], "선택 적용이 IFA 기하를 변경했습니다.")
        require(next(m for m in document["materials"] if m["id"] == spec["material_ids"]["core"])["conductivity"]["value_si"] is None,
                "탐색 유전체의 미정 전도도가 채워졌습니다.")
    require(all(digest(Path(path)) == value for path, value in before.items()), "원본 후보/fixture/카탈로그가 변경되었습니다.")
    report = {"schema": "rfad.jlc-ro4350b-exploratory-input/0.1", "status": "exploratory_input_created",
              "workspace": str(workspace.resolve()), "project_path": project_path, "snapshot": snapshot,
              "candidate": candidate["candidate"], "candidate_file": str(candidate_path), "source_hashes": before,
              "actual_material_ids": actual_ids, "simulation_material_ids": spec["material_ids"],
              "actual_properties_preserved_missing": True, "settings": fixture["settings"], "omissions": OMISSIONS,
              "selection_issues": preview["issues"], "input_checks": preview["input_checks"],
              "manufacturing_validated": False, "physics_validated": False}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("xb") as stream:
        stream.write(canonical_bytes(report))
    return report
