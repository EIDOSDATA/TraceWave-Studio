"""! @brief 공개 서비스 계약으로 실제 WSL 도파관 해석과 후처리 재실행을 검증한다."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.application.solver import PROFILE, RUNTIME_PROFILE
from rfad.application.solver_jobs import SolverRuntime
from rfad.adapters.solvers.openems.reference import compare_grids


def call(service, method, data, context=None, *, mutation=False):
    """! @brief 외부 클라이언트와 같은 request key와 JSON-RPC 경계로 호출한다."""
    params = {"contract_version": "rfad.api/2.0", "context": context or {}, "input": data}
    if mutation:
        params.update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
    response = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}), service)
    if "error" in response:
        raise RuntimeError(json.dumps(response["error"], ensure_ascii=False))
    return response["result"]


def wait(service, task):
    """! @brief 영속 작업 상태를 제한된 시간 동안 조회한다."""
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        status = call(service, "job.status", {"job_id": task["job_id"]})
        if status["state"] in {"completed", "failed", "cancelled", "interrupted"}:
            if status["state"] != "completed":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))
            return status["events"][-1]["operation_result"], status
        time.sleep(0.1)
    raise RuntimeError("service job timeout")


def run(workspace, report_path, *, exercise_cancel=False):
    """! @brief 두 격자와 저장 결과 재개방, raw 후처리 동일성을 실제 계산으로 검사한다."""
    runtime = SolverRuntime()
    report = {"schema": "rfad.openems-worker-verification/0.1", "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
              "workspace": str(workspace.resolve()), "cases": [], "ifa_tested": False, "nf2ff_tested": False, "formal_convergence_tested": False}
    started = time.monotonic()
    with ProjectService(workspace, solver_runtime=runtime) as service:
        project, _ = wait(service, call(service, "project.open", {"path": "projects/waveguide-" + uuid4().hex[:12], "open_mode": "create", "name": "WSL openEMS waveguide reference"}, mutation=True))
        context = {"project_id": project["project_id"]}
        snapshot, _ = wait(service, call(service, "snapshot.create", {"expected_revision": project["revision_id"], "description": "Explicit empty reference project"}, context, mutation=True))
        snapshot_ref = {k: snapshot[k] for k in ("snapshot_id", "content_hash")}
        normalized = []
        for grid in (1.0, 0.75):
            plan, plan_status = wait(service, call(service, "solver.plan", {"snapshot": snapshot_ref, "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE, "grid_mm": grid}, context, mutation=True))
            plan_ref = {k: plan["analysis_plan"][k] for k in ("plan_id", "content_hash")}
            prepared, prepare_status = wait(service, call(service, "solver.prepare", {"analysis_plan": plan_ref, "budget": {"timeout_seconds": 120}}, context, mutation=True))
            prepared_ref = {k: prepared["prepared_plan"][k] for k in ("prepared_plan_id", "content_hash")}
            task_plan = {"kind": "em_analysis", "prepared_plan": prepared_ref, "execution_mode": "solve_and_postprocess"}
            solved, solve_status = wait(service, call(service, "job.submit", {"task_plan": task_plan, "budget": {"timeout_seconds": 120}}, context, mutation=True))
            view = call(service, "result.open", {"artifact_id": solved["artifact_id"]}, context)
            result = json.loads(service.journal.read_artifact(solved["normalized_result"]))
            normalized.append(result)
            repeated, repeat_status = wait(service, call(service, "job.submit", {"task_plan": {**task_plan, "execution_mode": "postprocess_only", "raw_result_id": solved["artifact_id"]}, "budget": {"timeout_seconds": 120}}, context, mutation=True))
            repeated_result = json.loads(service.journal.read_artifact(repeated["normalized_result"]))
            if result["samples"] != repeated_result["samples"] or result["raw_manifest"] != repeated_result["raw_manifest"]:
                raise RuntimeError("postprocess_only changed raw data or normalized samples")
            report["cases"].append({"grid_mm": grid, "analysis_plan": plan["analysis_plan"], "prepared_plan": prepared["prepared_plan"],
                "artifact_id": solved["artifact_id"], "result": solved["normalized_result"], "assessment": result["assessment"],
                "termination": result["termination"], "native_statistics": result["native_statistics"], "mesh_statistics": result["mesh_statistics"],
                "job_ids": [s["job_id"] for s in (plan_status, prepare_status, solve_status, repeat_status)],
                "states": {name: [e["state"] for e in status["events"]] for name, status in (("prepare", prepare_status), ("analysis", solve_status), ("postprocess_only", repeat_status))},
                "postprocess_samples_identical": True, "postprocess_raw_manifest_identical": True, "result_open_file_count": len(view["files"]),
                "qt_found": result["provenance"]["runtime"]["qt_found"]})
            print(json.dumps({"grid_mm": grid, "status": "passed", "assessment": result["assessment"]}, ensure_ascii=False), flush=True)
        report["grid_comparison"] = compare_grids(normalized[0]["samples"], normalized[1]["samples"])
        if not report["grid_comparison"]["passed"]:
            raise RuntimeError("grid comparison failed")
        if exercise_cancel:
            task = call(service, "job.submit", {"task_plan": task_plan, "budget": {"timeout_seconds": 120}}, context, mutation=True)
            deadline = time.monotonic() + 40
            observed = None
            while time.monotonic() < deadline:
                job = service.journal.read()["jobs"][task["job_id"]]
                if job["state"] in {"failed", "completed", "interrupted"}:
                    raise RuntimeError("cancellation did not overlap a running worker")
                try:
                    guest = runtime.transport.inspect(job["run_id"], job["solver"]["nonce"])
                    if guest.get("phase") == "running" and guest.get("state") not in {"completed", "failed"}:
                        observed = guest
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            if observed is None:
                raise RuntimeError("did not observe active WSL worker")
            call(service, "job.cancel", {"job_id": task["job_id"], "reason": "실제 WSL 취소 검증"}, mutation=True)
            while time.monotonic() < deadline:
                status = call(service, "job.status", {"job_id": task["job_id"]})
                if status["state"] in {"cancelled", "failed", "interrupted", "completed"}:
                    break
                time.sleep(0.1)
            final_job = service.journal.read()["jobs"][task["job_id"]]
            guest = runtime.transport.inspect(final_job["run_id"], final_job["solver"]["nonce"])
            if status["state"] != "cancelled" or final_job["solver"]["resource_reserved"] or not guest["termination_confirmed"] or guest["outcome_unknown"]:
                raise RuntimeError("WSL cancellation termination was not confirmed")
            report["cancellation"] = {"job_id": task["job_id"], "state": status["state"], "guest_state": guest["state"], "termination_confirmed": True, "states": [e["state"] for e in status["events"]]}
        result_before = call(service, "result.open", {"artifact_id": report["cases"][0]["artifact_id"]}, context)
    with ProjectService(workspace, auto_run=False) as reopened:
        result_after = call(reopened, "result.open", {"artifact_id": report["cases"][0]["artifact_id"]}, context)
        if result_after != result_before:
            raise RuntimeError("reopened result differs")
    report.update(status="passed", elapsed_seconds=time.monotonic() - started, result_open_after_restart_identical=True,
                  finished_at=datetime.now(timezone.utc).isoformat())
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_bytes(report))
    print(json.dumps({"status": report["status"], "report": str(report_path.resolve()), "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))


def main():
    """! @brief 명시한 새 검증 작업 영역을 사용하며 기존 결과를 정리하지 않는다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--exercise-cancel", action="store_true")
    parser.add_argument("--reconcile-job", help="이전 interrupted 작업의 guest 취소/종료 확인만 수행")
    args = parser.parse_args()
    try:
        if args.reconcile_job:
            with ProjectService(args.workspace, auto_run=False, solver_runtime=SolverRuntime()) as service:
                print(json.dumps(service.solver.reconcile(args.reconcile_job), ensure_ascii=False))
        else:
            run(args.workspace, args.report, exercise_cancel=args.exercise_cancel)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
