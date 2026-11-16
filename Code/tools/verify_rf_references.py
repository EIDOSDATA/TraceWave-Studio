"""! @brief 공개 서비스의 고정 검증 캠페인을 유한 단계로 실행하고 재열기 근거를 남긴다."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catalog_pcb_verification.common import call, publish_report, require, wait
from rfad.application.canonical import canonical_hash
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime


def run(options):
    """! @brief 신규 준비와 명시한 기존 캠페인 실행을 구분하고 실패 단계는 재시도하지 않는다."""
    workspace, report_path = options.workspace.resolve(), options.report.resolve()
    require(not report_path.exists(), "이전 검증 보고서를 덮어쓸 수 없습니다.")
    require(bool(options.validation_id) == workspace.exists(), "신규 작업은 새 workspace, 재개는 기존 캠페인 ID가 필요합니다.")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {"schema": "rfad.rf-campaign-verification/0.1", "status": "running", "workspace": str(workspace),
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "prepare_only": options.prepare_only,
        "jobs": [], "physics_validated": False, "formal_convergence": "not_established",
        "manufacturing": None, "measurement": None}
    publish_report(report_path, report)
    try:
        runtime = SolverRuntime(audit=options.native_audit)
        with ProjectService(workspace, solver_runtime=runtime) as service:
            if options.validation_id:
                require(options.project_id is not None, "기존 캠페인은 명시한 프로젝트 ID도 필요합니다.")
                context = {"project_id": options.project_id}
                identity = options.validation_id
                selected = call(service, "rf.validation.get", {"validation_id": identity, "report_id": None}, context)
                project = service.journal.read()["projects"][options.project_id]
                report["project_path"] = project["path"]
                original = service.repository.read(selected["snapshot"]["artifact"])[1]
            else:
                task = call(service, "project.open", {"path": "projects/independent-rf",
                    "open_mode": "create", "name": "독립 RF 참조 검증"}, mutation=True)
                opened, _ = wait(service, task, timeout_seconds=30)
                context = {"project_id": opened["project_id"]}
                original = opened["document"]
                report["project_path"] = "projects/independent-rf"
                review = call(service, "rf.validation.preview", {"expected_revision": opened["revision_id"],
                    "name": "고정 RF 참조 / 3수준과 실행 차단 조건"}, context)
                created = call(service, "rf.validation.create", {"expected_revision": opened["revision_id"],
                    "name": review["definition"]["name"], "review_hash": review["review_hash"]}, context, mutation=True)
                identity = created["validation_id"]
            report.update(project_id=context["project_id"], validation_id=identity,
                          original_project_hash=canonical_hash(original), runtime_identity=runtime.identity)
            publish_report(report_path, report)

            def view():
                """! @brief 계획 조회는 보고서를 암묵적으로 선택하지 않는다."""
                return call(service, "rf.validation.get", {"validation_id": identity, "report_id": None}, context)

            phases = ("plan", "prepare") if options.prepare_only else ("plan", "prepare", "solve", "postprocess")
            for phase in phases:
                # @brief 전체 수준의 준비를 먼저 완료하고 고정한 순서대로만 실제 계산한다.
                for case in view()["cases"]:
                    if case["blocked_reason"]:
                        continue
                    if phase in case["phase_states"]:
                        require(case["phase_states"][phase]["state"] == "completed", "이전 미완료/실패 단계를 재시도하지 않습니다.")
                        continue
                    task = call(service, "rf.validation.advance", {"validation_id": identity,
                        "case_id": case["case_id"], "phase": phase}, context, mutation=True)
                    entry = {"case_id": case["case_id"], "phase": phase, "job_id": task["job_id"], "state": "accepted"}
                    report["jobs"].append(entry)
                    publish_report(report_path, report)
                    operation, status = wait(service, task, timeout_seconds=360 if phase == "solve" else 180)
                    entry.update(state=status["state"], states=[item["state"] for item in status["events"]],
                                 operation_result=operation)
                    publish_report(report_path, report)
            current = view()
            report["plan_view"] = current
            report["blocked_cases"] = [{"case_id": c["case_id"], "reason": c["blocked_reason"]}
                                       for c in current["cases"] if c["blocked_reason"]]
            if not options.prepare_only:
                assessment = call(service, "rf.validation.assess", {"validation_id": identity}, context, mutation=True)
                selected_report = call(service, "rf.validation.get", {"validation_id": identity,
                    "report_id": assessment["report_id"]}, context)
                report.update(assessment=assessment, assessment_view=selected_report)
            document = service._load(service.journal.read()["projects"][context["project_id"]])
            require(document == original, "검증 캠페인이 사용자의 원본문서를 바꿨습니다.")
            saved, _ = wait(service, call(service, "project.save", {"expected_revision": document["revision_id"]},
                                         context, mutation=True), timeout_seconds=30)
            report["saved"] = saved
        with ProjectService(workspace, auto_run=False) as reopened:
            document = reopened._load(reopened.journal.read()["projects"][context["project_id"]])
            require(document == original, "runtime 없는 재열기에서 원본이 바뀌었습니다.")
            again = call(reopened, "rf.validation.get", {"validation_id": identity,
                "report_id": None if options.prepare_only else assessment["report_id"]}, context)
            if not options.prepare_only:
                require(again == selected_report, "재열기에서 고정 판정 또는 출처/미정값이 바뀌었습니다.")
            require(again["manufacturing"] is None and again["measurement"] is None, "미정 조건이 임의 확정됐습니다.")
        report.update(status="prepared" if options.prepare_only else "completed", reopened_without_runtime=True)
    except Exception as error:
        report.update(status="failed", error={"type": type(error).__name__, "message": str(error),
                                              "details": getattr(error, "details", None)})
    report.update(finished_at_utc=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic() - started)
    publish_report(report_path, report)
    return report


def main():
    """! @brief 명시적으로 선택한 캠페인만 실행하며 신규/재개 보고서를 따로 보존한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--validation-id")
    parser.add_argument("--project-id")
    parser.add_argument("--native-audit", type=Path)
    options = parser.parse_args()
    report = run(options)
    print(json.dumps({"status": report["status"], "validation_id": report.get("validation_id"),
                      "project_id": report.get("project_id"), "report": str(options.report)}, ensure_ascii=False))
    return 0 if report["status"] in ("prepared", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
