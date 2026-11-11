"""! @brief 실제 수집 카탈로그의 대표 적층을 별도 임시 프로젝트로 적용하고 재열기를 검사한다."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from rfad.application.cad import build_cad_input
from rfad.application.catalog_api import query
from rfad.application.projects import ProjectService
from rfad.catalog.service import CatalogService
from rfad.domain.pcb_selection import EXTENSION_KEY
from rfad.domain.units import Quantity


CASES = (
    ("JLC2", "native_templates", "native_template:1bf6669c9f6b68f170fb327b1aacbea48a7c3ba6db3c4763bc7247236b3f6da5"),
    ("JLC4", "native_templates", "native_template:009d4afd600cfdd128292be7f9b1c7e9e1b42d8f6f8d8cf348d91da82fe239d0"),
    ("PCBWay4", "native_templates", "native_template:04c59e7ce48ab62cc4ca2409a7bc1a08e8a84d0bf9563d6cffda5b90b7969239"),
    ("WE", "native_templates", "native_template:00bff43ad4ab2ead6ed8abaa1493e3934e2580164b4d7e9062a306933678b4cf"),
    ("OSH2", "observations", "PCB056952"),
)


def require(condition, message):
    """! @brief 검증을 python 최적화 옵션과 무관하게 실행한다."""
    if not condition:
        raise RuntimeError(message)


def file_hash(path):
    """! @brief 큰 SQLite도 전체 메모리에 적재하지 않고 비교한다."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_case(database, catalog, catalog_id, case, root):
    """! @brief 원문 조회, 명시적 시험 입력, 원자 적용, snapshot과 DB 없는 재열기를 검사한다."""
    label, entity, identity = case
    service = ProjectService(root, auto_run=False, catalog_database=database)
    project_id = None

    def envelope(value, *, read=False):
        """! @brief 공개 요청과 같은 개정/영수증 경계를 사용한다."""
        result = {"contract_version": "rfad.api/2.0", "context": {} if project_id is None else {"project_id": project_id}, "input": value}
        if not read:
            result.update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
        return result

    def complete(method, value):
        """! @brief 실제 journal에 접수한 자료 작업을 완료한다."""
        job = service.mutate(method, envelope(value))
        require(service.run_next(), "job did not run")
        status = service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": job["job_id"]}})
        require(status["state"] == "completed", str(status))
        return status["events"][-1]["operation_result"]

    def document():
        """! @brief 저장된 원본을 매번 검증해 읽는다."""
        return service.repository.load(service.journal.read()["projects"][project_id])

    try:
        opened = complete("project.open", {"path": "projects/selection", "open_mode": "create", "name": label + " 선택 검증"})
        project_id = opened["project_id"]
        q = lambda value: Quantity.from_value(value, "mm").to_dict()
        board = {"id": str(uuid4()), "frame_id": opened["document"]["frames"]["board"]["id"],
                 "outline": {"kind": "circle", "center": [q(0), q(0)], "radius": q(30)}, "thickness_convention": "finished"}
        service.mutate("project.apply_command", envelope({"expected_revision": document()["revision_id"], "command_id": str(uuid4()),
                                                         "type": "board.set", "payload": {"board": board}}))
        source = {"catalog_id": catalog_id, "entity": entity, "id": identity}
        draft = query("catalog.stackup_draft", {"contract_version": "rfad.api/2.0", "context": {}, "input": source}, catalog)
        spec = {"source": source, "materials": []}
        if label == "OSH2":
            spec["materials"] = [{"key": "core", "name": "OSH 관측과 시험용 가정", "properties": {
                "epsilon_r": {"mode": "catalog", "record_id": identity, "reason": "공개값과 조건의 원문 보존 확인"},
                "tan_delta": {"mode": "missing", "reason": "Df 미정 보존 확인"},
                "conductivity": {"mode": "missing", "reason": "전도도 미정 보존 확인"}},
                "validity_hz": {"min": None, "max": None, "reason": "모델 적용 대역 미정"}}]
            spec["material_assignments"] = {"core": "core"}
        data = {"expected_revision": document()["revision_id"], "selection_id": str(uuid4()), "specification": spec}
        raw_preview = service.pcb_selection.preview(envelope(data, read=True))
        result = {"label": label, "source": source, "draft_layers": len(draft["layers"]),
                  "draft_issues": draft["issues"], "unresolved_thicknesses": sum(layer["thickness_mm"] is None for layer in draft["layers"]),
                  "original_preview_can_apply": raw_preview["can_apply"], "original_preview_bytes": raw_preview["size"]["document_bytes"]}
        if not draft["layers"]:
            require(not raw_preview["can_apply"], "incomplete native stackup was silently applied")
            return {**result, "status": "manual_layout_required"}
        spec["thickness_overrides"] = {layer["key"]: {
            "value_mm": 0.035 if layer["role"] == "conductor" else 0.4,
            "reason": "검증 도구만의 명시적 기하 가정. 제작 사양 또는 제조업체 공개값이 아님."}
            for layer in draft["layers"] if layer["thickness_mm"] is None}
        preview = service.pcb_selection.preview(envelope(data, read=True))
        result.update(completed_preview_bytes=preview["size"]["document_bytes"], issues=preview["issues"])
        if not preview["can_apply"]:
            require(all(item["code"] == "E_RESOURCE" for item in preview["issues"] if item["severity"] == "blocker"), str(preview["issues"]))
            return {**result, "status": "project_budget_rejected"}
        before = document()
        request = envelope({**data, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())})
        receipt = service.mutate("pcb.selection.apply", request)
        applied = document()
        require(applied["board"] == before["board"], "board outline changed")
        require(service.mutate("pcb.selection.apply", request) == receipt, "idempotent replay changed")
        complete("project.save", {"expected_revision": receipt["new_revision"]})
        snapshot = complete("snapshot.create", {"expected_revision": receipt["new_revision"]})
        captured = json.loads(service.journal.read_artifact(snapshot["artifact"]))
        require(captured == applied, "snapshot lost source evidence")
        cad = build_cad_input(captured, snapshot)
        require(cad["source_semantics"] == captured, "CAD projection lost source semantics")
        undone = service.mutate("project.undo", envelope({"expected_revision": applied["revision_id"], "command_id": str(uuid4())}))
        require(document()["stackup"] == before["stackup"], "undo did not restore stackup")
        service.mutate("project.redo", envelope({"expected_revision": undone["new_revision"], "command_id": str(uuid4())}))
        expected = deepcopy(document()["extensions"][EXTENSION_KEY])
        service.close()
        service = ProjectService(root, auto_run=False, catalog_database=root / "absent.sqlite")
        require(service.pcb_selection.get(envelope({}, read=True))["selection"] == expected, "reopen depended on installed catalog")
        require(service.mutate("pcb.selection.apply", request) == receipt, "receipt replay depended on catalog")
        return {**result, "status": "passed", "evidence_count": len(expected["evidence"]), "catalog_free_reopen": True,
                "save_snapshot_undo_redo": True, "cad_input_layers": len(cad["layers"]),
                "rf_simulation_executed": False, "source_semantics_preserved": True}
    finally:
        service.close()


def main():
    """! @brief 검증 보고서는 새 파일에만 쓰고 사용자의 설계나 원본 자료는 변경하지 않는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    options = parser.parse_args()
    if options.report.exists():
        parser.error("report already exists; select a new path")
    started = time.monotonic()
    catalog = CatalogService(options.database)
    catalog_id = catalog.status()["catalog_id"]
    before = file_hash(options.database)
    with tempfile.TemporaryDirectory(prefix="rfad-pcb-selection-") as folder:
        cases = [verify_case(options.database, catalog, catalog_id, case, Path(folder) / case[0]) for case in CASES]
    require(all(item["status"] == "passed" for item in cases if item["label"] in ("OSH2", "JLC2")), "two-layer workflow did not pass")
    after = file_hash(options.database)
    require(before == after, "catalog database changed")
    report = {"schema": "rfad.pcb-selection-verification/0.1", "catalog_id": catalog_id, "database_sha256": after,
              "database_unchanged": True, "elapsed_seconds": round(time.monotonic() - started, 3),
              "physical_validation_state": "not_validated", "cases": cases}
    options.report.parent.mkdir(parents=True, exist_ok=True)
    with options.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"report": str(options.report), "results": {item["label"]: item["status"] for item in cases}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
