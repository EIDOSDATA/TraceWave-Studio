"""! @brief 공개 서비스의 봉인 worker로 고정 PEC 다이폴 한 수준을 검증한다.

@details 임의 worker 교체, 전체 패키지 복사, 빈 runtime과 외부 raw 주입은 없다.
3수준 캠페인의 실행/예산 집계는 별도 제어기를 사용하며 이 도구는 한 수준만 수행한다.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfad.application.canonical import canonical_hash
from rfad.application.projects import ProjectService
from rfad.application.rf_reference_contract import CASE, GRIDS_MM, PROFILE, validate_radiation
from rfad.application.solver import RUNTIME_PROFILE
from rfad.application.solver_runtime import SolverRuntime
from rfad.domain.rf_reference import assess_dipole
from catalog_pcb_verification.common import call, wait, read_json_artifact, publish_report, require


def run(workspace, report_path, grid_mm, *, prepare_only=False, native_audit=None):
    """! @brief 한 사례의 준비/실행/재후처리와 runtime 없는 재열기를 기록한다."""
    workspace, report_path = Path(workspace).resolve(), Path(report_path).resolve()
    require(not workspace.exists() and not report_path.exists(), "새 workspace와 새 보고서 경로가 필요합니다.")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema": "rfad.reference-worker-verification/0.1", "status": "running",
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "workspace": str(workspace),
              "case": CASE, "grid_mm": grid_mm, "prepare_only": prepare_only, "jobs": [],
              "native_solves_requested": 0, "worker_invocations_requested": 0,
              "physics_validated": False, "formal_convergence": "not_established",
              "manufacturing": None, "measurement": None}
    started = time.monotonic()
    publish_report(report_path, report)
    try:
        runtime = SolverRuntime(audit=native_audit)
        report["runtime_identity"] = runtime.identity
        with ProjectService(workspace, solver_runtime=runtime) as service:
            def execute(method, data, context=None, *, worker=False, solve=False, timeout=180):
                """! @brief 접수 ID와 최초 실패를 기록하고 자동 재시도하지 않는다."""
                task = call(service, method, data, context, mutation=True)
                entry = {"method": method, "job_id": task["job_id"], "state": "accepted"}
                report["jobs"].append(entry)
                report["worker_invocations_requested"] += int(worker)
                report["native_solves_requested"] += int(solve)
                publish_report(report_path, report)
                operation, status = wait(service, task, timeout_seconds=timeout)
                entry.update(state=status["state"], states=[event["state"] for event in status["events"]])
                publish_report(report_path, report)
                return operation

            project = execute("project.open", {"path": "projects/reference-" + uuid4().hex[:12],
                                               "open_mode": "create", "name": "고정 PEC 다이폴 참조"})
            context = {"project_id": project["project_id"]}
            report["project_id"] = project["project_id"]
            snapshot = execute("snapshot.create", {"expected_revision": project["revision_id"],
                                "description": "사용자 PCB와 구분되는 고정 합성 다이폴 참조"}, context)
            original = read_json_artifact(service, snapshot["artifact"])
            planned = execute("solver.plan", {"snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
                "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE,
                "settings": {"case": CASE, "grid_mm": grid_mm}}, context)
            plan = read_json_artifact(service, planned["analysis_plan"]["artifact"])
            prepared = execute("solver.prepare", {
                "analysis_plan": {key: planned["analysis_plan"][key] for key in ("plan_id", "content_hash")},
                "budget": {"timeout_seconds": 120}}, context, worker=True)
            preparation = read_json_artifact(service, prepared["preparation_artifact"])
            report.update(snapshot=snapshot, analysis_plan=planned["analysis_plan"],
                          prepared_plan=prepared["prepared_plan"], preparation_artifact=prepared["preparation_artifact"],
                          mesh_statistics=preparation["mesh_statistics"], original_project_hash=canonical_hash(original))
            if not prepare_only:
                task = {"kind": "em_analysis", "prepared_plan": {
                    key: prepared["prepared_plan"][key] for key in ("prepared_plan_id", "content_hash")},
                    "execution_mode": "solve_and_postprocess"}
                solved = execute("job.submit", {"task_plan": task, "budget": {"timeout_seconds": 300}},
                                 context, worker=True, solve=True, timeout=360)
                normalized = read_json_artifact(service, solved["normalized_result"])
                result_view = call(service, "result.open", {"artifact_id": solved["artifact_id"]}, context)
                radiation_ref = next(item for item in result_view["files"] if item["role"] == "radiation_result")
                radiation = read_json_artifact(service, {key: radiation_ref[key] for key in ("uri", "sha256", "bytes")})
                validate_radiation(plan, radiation)
                row = radiation["frequencies"][0]
                assessment = assess_dipole(radiation["recording"]["theta_deg"], row["normalized_power"], row["metrics"])
                repeated = execute("job.submit", {"task_plan": {**task, "execution_mode": "postprocess_only",
                    "raw_result_id": solved["artifact_id"]}, "budget": {"timeout_seconds": 120}}, context, worker=True)
                again = read_json_artifact(service, repeated["normalized_result"])
                require(normalized["samples"] == again["samples"] and normalized["raw_manifest"] == again["raw_manifest"]
                        and normalized["radiation_summary"] == again["radiation_summary"],
                        "독립 후처리가 원시 manifest 또는 포트/방사 결과를 변경했습니다.")
                report.update(artifact_id=solved["artifact_id"], normalized_result=solved["normalized_result"],
                              postprocess_result=repeated["normalized_result"], termination=normalized["termination"],
                              independent_assessment=assessment, postprocess_identical=True)
            require(read_json_artifact(service, snapshot["artifact"]) == original, "계산 중 봉인 원본이 달라졌습니다.")
        with ProjectService(workspace, auto_run=False) as reopened:
            require(read_json_artifact(reopened, snapshot["artifact"]) == original, "재열기 원본이 다릅니다.")
            if prepare_only:
                require(read_json_artifact(reopened, prepared["preparation_artifact"]) == preparation, "재열기 준비 근거가 다릅니다.")
            else:
                require(call(reopened, "result.open", {"artifact_id": solved["artifact_id"]}, context) == result_view,
                        "runtime 없는 재열기에서 결과가 달라졌습니다.")
        report.update(status="prepared" if prepare_only else "completed", reopened_without_runtime=True)
    except Exception as error:
        report.update(status="failed", error={"type": type(error).__name__, "message": str(error),
                                             "details": getattr(error, "details", None)})
    report.update(finished_at_utc=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic() - started)
    publish_report(report_path, report)
    return report


def main():
    """! @brief 준비만 요청하면 native solve를 접수하지 않는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--grid-mm", type=float, choices=GRIDS_MM, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--native-audit", type=Path)
    options = parser.parse_args()
    report = run(options.workspace, options.report, options.grid_mm,
                 prepare_only=options.prepare_only, native_audit=options.native_audit)
    print(json.dumps({"status": report["status"], "report": str(options.report), "physics_validated": False}, ensure_ascii=False))
    return 0 if report["status"] in ("prepared", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
