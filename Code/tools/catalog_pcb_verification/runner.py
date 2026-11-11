"""! @brief 저장된 2층 카탈로그 PCB를 변경하지 않고 단계별 통합 검증한다."""

from datetime import datetime, timezone
from pathlib import Path
import time

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.projects import ProjectService
from rfad.domain.pcb_selection import EXTENSION_KEY

from .cad import restore_cad, verify_cad
from .common import call, publish_report, read_json_artifact, require, wait
from .solver import restore_solver, verify_solver


def _current(service, project_id):
    """! @brief 저장소가 검증한 현재 원본을 읽는다."""
    return service.repository.load(service.journal.read()["projects"][project_id])


def _execute(report, workspace, project_path, mode, settings, cad_runtime, solver_runtime, expected_revision):
    """! @brief 목적별 누락 진단을 남기며 모든 worker에 같은 스냅샷만 전달한다."""
    with ProjectService(workspace, cad_runtime=cad_runtime if mode != "inspect" else None,
                        solver_runtime=solver_runtime if mode == "full" else None) as service:
        opened, _ = wait(service, call(service, "project.open", {"path": project_path, "open_mode": "open"}, mutation=True))
        document = opened["document"]
        revision = document["revision_id"]
        require(expected_revision is None or revision == expected_revision, "요청한 프로젝트 개정과 현재 개정이 다릅니다.")
        require(opened["saved_revision"] == revision, "현재 개정을 먼저 저장하십시오. 검증 도구는 설계를 저장하거나 편집하지 않습니다.")
        require(EXTENSION_KEY in document["extensions"], "검증할 프로젝트에 PCB 선택 출처가 없습니다.")
        require(sum(layer["role"] == "conductor" for layer in document["stackup"]) == 2,
                "이 통합 검증은 동박이 두 층인 PCB를 대상으로 합니다.")
        context = {"project_id": opened["project_id"]}
        report.update(project_id=opened["project_id"], revision_id=revision, document_hash=canonical_hash(document),
                      selection=call(service, "pcb.selection.get", {}, context), checks={})
        for purpose in ("geometry", "step", "em"):
            check, _ = wait(service, call(service, "design.validate", {
                "expected_revision": revision, "purpose": purpose, "profile": "rfad.design/0.1",
            }, context, mutation=True))
            require(check["revision_hash"] == report["document_hash"], "검증 중 현재 설계가 변경되었습니다.")
            report["checks"][purpose] = check
        snapshot, _ = wait(service, call(service, "snapshot.create", {
            "expected_revision": revision, "description": "카탈로그 2층 PCB CAD/해석 통합 검증 원본",
        }, context, mutation=True))
        require(read_json_artifact(service, snapshot["artifact"]) == document, "검증 원본 스냅샷이 다릅니다.")
        report["snapshot"] = snapshot
        cad_ready = all(report["checks"][purpose]["input_status"] == "valid" for purpose in ("geometry", "step"))
        em_ready = report["checks"]["em"]["input_status"] == "valid"
        try:
            if mode != "inspect" and cad_ready:
                require(cad_runtime is not None, "CAD 실행 파일을 명시해야 합니다.")
                report["cad"] = verify_cad(service, context, snapshot, document)
            if mode == "full" and cad_ready and em_ready:
                require(settings is not None, "해석 격자/대역/종료 조건을 명시해야 합니다.")
                require(solver_runtime is not None, "실제 WSL openEMS 실행을 명시해야 합니다.")
                report["solver"] = verify_solver(service, context, snapshot, settings)
            report["status"] = ("inputs_ready" if cad_ready and em_ready else "needs_inputs") if mode == "inspect" else (
                "cad_verified" if cad_ready else "needs_inputs") if mode == "cad" else (
                "passed" if cad_ready and em_ready else "needs_inputs")
        finally:
            report["project_unchanged"] = _current(service, context["project_id"]) == document
            require(report["project_unchanged"], "검증 중 프로젝트 원본이 변경되었습니다.")


def _restore(report, workspace):
    """! @brief 카탈로그 DB와 두 worker 없이 저장된 출력과 원본을 다시 확인한다."""
    if "snapshot" not in report:
        return
    with ProjectService(workspace, auto_run=False) as service:
        context = {"project_id": report["project_id"]}
        snapshot = report["snapshot"]
        require(canonical_hash(_current(service, context["project_id"])) == report["document_hash"], "재시작 후 원본이 다릅니다.")
        require(call(service, "pcb.selection.get", {}, context) == report["selection"], "재시작 후 카탈로그 선택 출처가 다릅니다.")
        require(canonical_hash(read_json_artifact(service, snapshot["artifact"])) == report["document_hash"], "재시작 후 스냅샷이 다릅니다.")
        if "cad" in report:
            restore_cad(service, context, snapshot, report["cad"])
        if "solver" in report:
            restore_solver(service, context, snapshot, report["solver"])
        report["restored_without_catalog_or_workers"] = True


def run(workspace, project_path, report_path, *, mode="inspect", settings=None, cad_runtime=None,
        solver_runtime=None, expected_revision=None):
    """! @brief 기존 보고서를 덮어쓰지 않고 실패와 입력 부족도 구조화된 보고서로 남긴다."""
    require(mode in {"inspect", "cad", "full"}, "지원하지 않는 검증 모드입니다.")
    workspace = Path(workspace).resolve(strict=True)
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {"schema": "rfad.catalog-pcb-integration/0.1", "status": "running", "mode": mode,
              "started_at": datetime.now(timezone.utc).isoformat(), "workspace": str(workspace),
              "project_path": project_path, "settings": settings, "material_values": "unchanged_saved_project",
              "physics_validated": False, "manufacturing_validated": False, "formal_convergence_tested": False}
    with report_path.open("xb") as stream:
        stream.write(canonical_bytes(report))
    try:
        _execute(report, workspace, project_path, mode, settings, cad_runtime, solver_runtime, expected_revision)
    except Exception as error:
        report.update(status="failed", error={"type": type(error).__name__, "message": str(error), "details": getattr(error, "details", None)})
    try:
        _restore(report, workspace)
    except Exception as error:
        report.update(status="failed", restoration_error={"type": type(error).__name__, "message": str(error), "details": getattr(error, "details", None)})
    report["elapsed_seconds"] = time.monotonic() - started
    publish_report(report_path, report)
    return report
