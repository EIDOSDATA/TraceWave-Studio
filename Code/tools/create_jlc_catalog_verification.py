"""! @brief JLC0206 원문과 시험 기하를 공개 명령으로 연결하고 미정 입력을 보존한다."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.application.projects import ProjectService
from rfad.application.catalog_api import query
from rfad.catalog.service import CatalogService
from rfad.domain.units import Quantity
from catalog_pcb_verification.common import call, read_json_artifact, require, wait
from verify_pcb_worker import create_fixture


CODE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ID = "native_template:3945cd94afe2d81e4bc7fe9d41c52b96bb1cc133fe0f5f6fdfae3081c53ef2a8"
RECORD_ID = "PCB040237"
SOURCE_SHA256 = "74a20626c8cb724aa1b96af18d1ee374d3334941d70b8467fcb1f55e01e53826"
SOURCE_POINTER = "/body/list/65"
CORE_MM = 0.5
COPPER_MM = 0.035
COPPER_SOURCES = (
    "https://jlcpcb.com/capabilities/pcb-capabilities",
    "https://jlcpcb.com/resources/custom-pcb",
    "https://jlcpcb.com/help/article/jlcpcb-copper-weight",
)


def file_hash(path):
    """! @brief 원본 자료를 변경하지 않고 SHA-256을 계산한다."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def missing_choice(reason):
    """! @brief 근거가 없는 물성은 추정값 없이 미정 선택으로 만든다."""
    return {"mode": "missing", "reason": reason}


def catalog_read(catalog, method, data):
    """! @brief 명시적 카탈로그 인스턴스를 읽기 전용 공개 API에 전달한다."""
    return query(method, {"contract_version": "rfad.api/2.0", "context": {}, "input": data}, catalog)


def prepare_geometry_fixture(fixture):
    """! @brief 복사한 시험 입력에서 물성과 적용 대역을 제거하고 기하와 포트만 재사용한다."""
    prepared = deepcopy(fixture)
    document = prepared["document"]
    document["metadata"]["name"] = "JLC0206 카탈로그 연결 검증용 기하"
    document["metadata"]["description"] = (
        "pcb_worker_smoke.json의 내부 연결 검증용 원형 외형, 선, 원호, 50 ohm 포트를 재사용한다. "
        "제조용 안테나 또는 검증된 IFA가 아니다. fixture 물성과 적용 대역은 모두 제거했다. "
        "JLC0206 코어와 JLCPCB 공개 2층 1 oz 완성 외층의 명목 0.035 mm를 선택한다. "
        "실측 완성 두께를 보증하지 않으며 미정 물성과 적용 대역은 채우지 않는다."
    )
    prepared["description"] = "JLC0206 선택 전 기하만 보존한 내부 연결 시험 입력. 실제 해석 미실행."
    for index, material in enumerate(document["materials"], start=1):
        material["name"] = "선택 전 미정 재료 " + str(index)
        material["source_refs"] = []
        material["assumptions"] = ["기하 연결용 fixture의 시험 물성은 채택하지 않음"]
        for field in ("epsilon_r", "tan_delta", "conductivity"):
            value = material[field]
            material[field] = Quantity.missing(value["dimension"], value["display_unit"]).to_dict()
        for boundary in ("min", "max"):
            material["validity_hz"][boundary] = Quantity.missing("frequency", "Hz").to_dict()
    for port in document["ports"]:
        for boundary in ("min", "max"):
            port["validity_hz"][boundary] = Quantity.missing("frequency", "Hz").to_dict()
    return prepared


def selection_specification(fixture, source):
    """! @brief 기존 UUID를 명시적으로 대응하고 공개 1 oz 외층 명목 두께로 급전 높이를 갱신한다."""
    document = fixture["document"]
    layers = {layer["role"]: layer for layer in document["stackup"]}
    require(set(layers) == {"dielectric", "conductor"}, "시험 fixture의 층 구성이 변경되었습니다.")
    material_ids = {"core": layers["dielectric"]["material_id"], "copper": layers["conductor"]["material_id"]}
    materials = []
    for key, name in (("core", "JLC0206 NP-155F: 공개 Dk, 나머지 미정"), ("copper", "JLC0206 동박: 물성 미정")):
        properties = {field: missing_choice("이 선택에 확정된 물성 근거가 없어 미정으로 보존함")
                      for field in ("epsilon_r", "tan_delta", "conductivity")}
        if key == "core":
            properties["epsilon_r"] = {
                "mode": "catalog", "record_id": RECORD_ID,
                "reason": "JLC0206의 공개 계산기 Dk 4.48만 채택함. 시험 주파수와 적용 대역은 미정이며 실측값이 아님.",
            }
        materials.append({"key": key, "name": name, "properties": properties,
                          "validity_hz": {"min": None, "max": None, "reason": "원문이 적용 대역을 제공하지 않아 미정으로 보존함"}})
    port_updates = []
    for port in document["ports"]:
        box = port["excitation_box"]
        port_updates.append({
            "id": port["id"],
            "start_mm": [box["start"][0]["value_si"] * 1000, box["start"][1]["value_si"] * 1000, COPPER_MM + CORE_MM],
            "stop_mm": [box["stop"][0]["value_si"] * 1000, box["stop"][1]["value_si"] * 1000, COPPER_MM + CORE_MM],
            "reason": "시험 급전의 XY와 포트 UUID를 보존하고 명시 선택한 하부 1 oz 동박 0.035 mm + 코어 0.5 mm 접면에 배치함",
        })
    copper_reason = (
        "JLCPCB 공개 2층 Finished Outer Layer Copper 1 oz와 1 oz = 35 um 사양의 명목 두께를 선택함. "
        "실측 보증값이 아니며 JLC0206 API raw 0.03 mm는 변경하지 않음. 출처: " + "; ".join(COPPER_SOURCES)
    )
    return {
        "source": source, "materials": materials, "material_ids": material_ids,
        "layer_ids": {"component:0:dielectric": layers["dielectric"]["id"], "component:0:top": layers["conductor"]["id"]},
        "thickness_overrides": {key: {"value_mm": COPPER_MM, "reason": copper_reason}
                                for key in ("component:0:bottom", "component:0:top")},
        "material_assignments": {"component:0:bottom": "copper", "component:0:dielectric": "core", "component:0:top": "copper"},
        "port_updates": port_updates,
        "notes": [
            "사용자가 JLCPCB 후보 선택을 위임하여 순수 코어 두께가 명시된 JLC0206을 내부 연결 검증 대상으로 선택함.",
            "JLC0206은 공개 engineering calculator 후보이다. NP-155F의 현재 2층 주문 가능성이나 제작 재료를 보증하지 않는다.",
            "원문은 core 0.5 mm without copper이며 공칭 기판 두께는 0.6 mm이다. 차이를 동박에 자동 배분하지 않음.",
            "raw top/bottomConductorThick=0.03은 그대로 보존한다. 별도 공개 2층 1 oz 사양으로 각 외층 명목 두께 0.035 mm를 명시 선택함.",
            "모델 층 합계는 0.570 mm이며 공칭 0.6 mm의 차이를 층에 배분하지 않는다. 마스크/실크는 모델 범위 밖이다.",
            "pcb_worker_smoke.json의 기하와 50 ohm 포트만 재사용함. 제조용 안테나, 확정 제작 사양 또는 물리 검증 결과가 아님.",
        ],
    }


def validate_saved_inputs(document, specification):
    """! @brief 시험 물성은 제거되고 명시 선택한 공개 명목 치수만 사용했는지 검사한다."""
    materials = {material["id"]: material for material in document["materials"]}
    require(set(materials) == set(specification["material_ids"].values()), "예상 밖 재료가 최종 문서에 남았습니다.")
    for key, identity in specification["material_ids"].items():
        material = materials[identity]
        for field in ("epsilon_r", "tan_delta", "conductivity"):
            value = material[field]
            if key == "core" and field == "epsilon_r":
                require(value["value_si"] == 4.48 and value["status"] == "source_default", "JLC 원문 Dk가 보존되지 않았습니다.")
            else:
                require(value["value_si"] is None and value["status"] == "missing", "미정 물성이 임의로 채워졌습니다.")
        require(all(value["value_si"] is None and value["status"] == "missing" for value in material["validity_hz"].values()),
                "재료 적용 대역이 임의로 채워졌습니다.")
    require(len(document["stackup"]) == 3, "2층 PCB의 코어와 양면 도체 구성이 아닙니다.")
    for layer in document["stackup"]:
        expected = CORE_MM * 0.001 if layer["role"] == "dielectric" else COPPER_MM * 0.001
        require(layer["thickness"]["value_si"] == expected, "확정되지 않은 적층 치수가 채택되었습니다.")
    for port in document["ports"]:
        require(all(value["value_si"] is None for value in port["validity_hz"].values()), "시험 포트 대역이 남았습니다.")
        require(all(port["excitation_box"][endpoint][2]["value_si"] == (COPPER_MM + CORE_MM) * 0.001
                    for endpoint in ("start", "stop")), "명시 선택한 적층 접면과 급전 높이가 다릅니다.")


def run(workspace, report_path, database, reference_root, fixture_path):
    """! @brief 새 저장소에만 프로젝트를 저장하고 실제 실행 전 필요한 입력을 보고한다."""
    require(not workspace.exists(), "새 workspace 경로를 지정하십시오.")
    require(not report_path.exists(), "새 report 경로를 지정하십시오.")
    database_before, fixture_before = file_hash(database), file_hash(fixture_path)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    require(fixture.get("schema") == "rfad.pcb-runtime-fixture/0.1", "지원하지 않는 시험 기하 형식입니다.")
    prepared = prepare_geometry_fixture(fixture)
    catalog = CatalogService(database)
    catalog_id = catalog_read(catalog, "catalog.status", {})["catalog_id"]
    with ProjectService(workspace, catalog_database=database) as service:
        source = {"catalog_id": catalog_id, "entity": "native_templates", "id": TEMPLATE_ID}
        detail = catalog_read(catalog, "catalog.get", {"entity": "native_templates", "id": TEMPLATE_ID})
        observation = catalog_read(catalog, "catalog.get", {"entity": "observations", "id": RECORD_ID})
        require(detail["item"]["source_pointer"] == SOURCE_POINTER, "JLC 원문 위치가 변경되었습니다.")
        source_path = reference_root / detail["item"]["source_path"]
        require(file_hash(source_path) == SOURCE_SHA256 == detail["item"]["source_sha256"], "JLC 원문 SHA-256이 예상과 다릅니다.")
        require(observation["item"]["stackup_id"] == detail["item"]["stackup_id"], "Dk 관측이 선택 적층과 다릅니다.")
        draft = catalog_read(catalog, "catalog.stackup_draft", source)
        context, project_path, initial_snapshot = create_fixture(service, prepared)
        specification = selection_specification(prepared, source)
        request = {"expected_revision": initial_snapshot["revision_id"], "selection_id": str(uuid4()), "specification": specification}
        preview = call(service, "pcb.selection.preview", request, context)
        require(preview["can_apply"], "JLC 선택을 적용할 수 없습니다: " + json.dumps(preview["issues"], ensure_ascii=False))
        changed = call(service, "pcb.selection.apply", {**request, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())},
                       context, mutation=True)
        wait(service, call(service, "project.save", {"expected_revision": changed["new_revision"]}, context, mutation=True))
        snapshot, _ = wait(service, call(service, "snapshot.create", {"expected_revision": changed["new_revision"],
                                                                    "description": "JLC0206 연결 검증 입력. 공개 명목 적층 치수와 미정 RF 물성."}, context, mutation=True))
        document = read_json_artifact(service, snapshot["artifact"])
        validate_saved_inputs(document, specification)
        require(document["geometry"] == prepared["document"]["geometry"] or all(
            {key: value for key, value in shape.items() if key != "frame_id"}
            == {key: value for key, value in original.items() if key != "frame_id"}
            for shape, original in zip(document["geometry"], prepared["document"]["geometry"], strict=True)),
            "시험 기하가 좌표계 UUID 외에 변경되었습니다.")
        report = {"schema": "rfad.jlc-catalog-verification-input/0.1", "status": "needs_inputs",
                  "created_at": datetime.now(timezone.utc).isoformat(), "workspace": str(workspace.resolve()),
                  "project_path": project_path, "project_id": context["project_id"], "snapshot": snapshot,
                  "source": source, "source_path": str(source_path.resolve()), "source_sha256": SOURCE_SHA256,
                  "source_pointer": SOURCE_POINTER, "fixture_path": str(fixture_path.resolve()), "fixture_sha256": fixture_before,
                  "copper_nominal_mm": COPPER_MM, "copper_source_urls": list(COPPER_SOURCES),
                  "modeled_total_thickness_mm": CORE_MM + 2 * COPPER_MM,
                  "geometry_kind": "synthetic_connection_verification_not_manufacturing_antenna",
                  "material_ids": specification["material_ids"], "layer_ids": specification["layer_ids"],
                  "port_ids": [port["id"] for port in document["ports"]], "source_draft": draft,
                  "materials": document["materials"], "stackup": document["stackup"], "input_checks": preview["input_checks"],
                  "selection_issues": preview["issues"], "project_saved": True, "unknowns_preserved": True,
                  "cad_executed": False, "fdtd_executed": False, "database_sha256": database_before}
    require(file_hash(database) == database_before and file_hash(fixture_path) == fixture_before, "원본 자료가 변경되었습니다.")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "workspace", "project_path", "project_id")}, ensure_ascii=False))


def main():
    """! @brief 명시적인 새 경로로 재현하며 해석이나 원본 변경은 수행하지 않는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=CODE_ROOT / ".local/pcb-catalog/catalog.sqlite")
    parser.add_argument("--reference-root", type=Path, default=CODE_ROOT.parent / "00_REF/PCB RF ANT/05_PCB_Dielectric_Data_2026")
    parser.add_argument("--fixture", type=Path, default=CODE_ROOT / "fixtures/pcb_worker_smoke.json")
    options = parser.parse_args()
    try:
        run(options.workspace, options.report, options.database, options.reference_root, options.fixture)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
