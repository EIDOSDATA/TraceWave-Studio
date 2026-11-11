"""! @brief 실제 적층의 모든 유전체 제안을 적용하고 출처와 미정값의 저장을 검사한다."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.application.catalog_api import query
from rfad.application.projects import ProjectService
from rfad.catalog.service import CatalogService
from rfad.domain.pcb_selection import EXTENSION_KEY
from rfad.domain.pcb_evidence_pool import expand_selection
from rfad.domain.units import Quantity
from catalog_pcb_verification.common import call, wait, require, publish_report
from verify_pcb_selection import CASES, file_hash


def verify_case(database, catalog, catalog_id, case, workspace):
    """! @brief 사용자 프로젝트와 물성값을 변경하지 않는 독립 작업 공간을 사용한다."""
    label, entity, identity = case
    source = {"catalog_id": catalog_id, "entity": entity, "id": identity}
    materials, assignments, offset = [], {}, 0
    while offset is not None:
        page = query("catalog.stackup_suggestions", {"contract_version": "rfad.api/2.0", "context": {},
                     "input": {"source": source, "offset": offset}}, catalog)
        for layer in page["layers"]:
            material = layer["material_spec"]
            if material is not None:
                materials.append(material)
                assignments[layer["layer_key"]] = material["key"]
        offset = page["next_offset"]
    spec = {"source": source, "materials": materials, "material_assignments": assignments}
    with ProjectService(workspace, catalog_database=database) as service:
        opened, _ = wait(service, call(service, "project.open", {
            "path": "projects/selection", "open_mode": "create", "name": label + " 모든 유전체 제안"}, mutation=True))
        context = {"project_id": opened["project_id"]}
        q = lambda value: Quantity.from_value(value, "mm").to_dict()
        board = {"id": str(uuid4()), "frame_id": opened["document"]["frames"]["board"]["id"],
                 "outline": {"kind": "circle", "center": [q(0), q(0)], "radius": q(30)}, "thickness_convention": "finished"}
        receipt = call(service, "project.apply_command", {"expected_revision": opened["document"]["revision_id"],
                       "command_id": str(uuid4()), "type": "board.set", "payload": {"board": board}}, context, mutation=True)
        data = {"expected_revision": receipt["new_revision"], "selection_id": str(uuid4()), "specification": spec}
        preview = call(service, "pcb.selection.preview", data, context)
        require(preview["can_apply"], str(preview["issues"]))
        require(not preview["input_checks"]["solver_ready"], "미정 물성을 해석 준비로 승격함")
        receipt = call(service, "pcb.selection.apply", {**data, "preview_hash": preview["preview_hash"],
                       "command_id": str(uuid4())}, context, mutation=True)
        document = service.repository.load(service.journal.read()["projects"][opened["project_id"]])
        require(document["board"] == board, "기존 외형이 변경됨")
        for material in document["materials"]:
            require(material["tan_delta"]["value_si"] is None, "미정 Df를 수치로 채움")
            require(material["conductivity"]["value_si"] is None, "전도도 가정을 생성함")
            require(material["validity_hz"]["min"]["value_si"] is None, "적용 대역을 생성함")
        original = deepcopy(document["extensions"][EXTENSION_KEY])
        wait(service, call(service, "project.save", {"expected_revision": receipt["new_revision"]}, context, mutation=True))
        snapshot, _ = wait(service, call(service, "snapshot.create", {"expected_revision": receipt["new_revision"]}, context, mutation=True))
        require(json.loads(service.journal.read_artifact(snapshot["artifact"])) == document, "스냅샷 원본이 달라짐")
        undone = call(service, "project.undo", {"expected_revision": receipt["new_revision"], "command_id": str(uuid4())}, context, mutation=True)
        call(service, "project.redo", {"expected_revision": undone["new_revision"], "command_id": str(uuid4())}, context, mutation=True)
    with ProjectService(workspace, catalog_database=workspace / "absent.sqlite") as service:
        reopened = call(service, "pcb.selection.get", {}, context)["selection"]
        require(reopened == original, "카탈로그 없는 재열기에서 출처가 달라짐")
        expanded = expand_selection(reopened)
        for entry in expanded["evidence"]:
            require(entry["original_sha256"] and entry["snapshot_sha256"], "원문 해시가 사라짐")
    return {"label": label, "status": "passed", "source": source, "materials": len(materials),
            "layers": len(document["stackup"]), "document_bytes": preview["size"]["document_bytes"],
            "document_limit_bytes": preview["size"]["document_limit_bytes"], "evidence_count": len(expanded["evidence"]),
            "all_dielectric_suggestions_adopted": True, "unknown_properties_preserved": True,
            "save_snapshot_undo_redo": True, "catalog_free_reopen": True, "solver_ready": False}


def main():
    """! @brief 전체 대표 사례와 자료 불변을 새 보고서에만 기록한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    options = parser.parse_args()
    require(not options.report.exists(), "새 보고서 경로를 지정하십시오.")
    started = time.monotonic()
    before = file_hash(options.database)
    catalog = CatalogService(options.database)
    catalog_id = catalog.status()["catalog_id"]
    with tempfile.TemporaryDirectory(prefix="rfad-all-materials-") as folder:
        cases = [verify_case(options.database, catalog, catalog_id, case, Path(folder) / case[0])
                 for case in CASES if case[0] != "WE"]
    require(file_hash(options.database) == before, "원본 DB가 변경됨")
    report = {"schema": "rfad.stackup-application-verification/0.1", "status": "passed", "cases": cases,
              "database_unchanged": True, "database_sha256": before, "elapsed_seconds": round(time.monotonic() - started, 3),
              "physics_validated": False, "manufacturing_validated": False}
    options.report.parent.mkdir(parents=True, exist_ok=True)
    publish_report(options.report, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
