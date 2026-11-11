"""! @brief 완료 전력 연구의 native 재실행 없는 후처리/해석기 없는 재열기를 검증한다."""

import argparse
import json
from pathlib import Path
import sys

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "src"))

from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from rfad.application.radiation_study import require
from verify_openems_worker import call
from verify_ifa_convergence import execute_phase, save_report
from verify_pcb_power_balance import load_result
from radiation_convergence.evidence import reference


def native_jobs(state):
    """! @brief 후처리 작업과 구별하여 실제 solver 실행 요청의 ID만 센다."""
    return sorted(job["job_id"] for job in state["jobs"].values() if job["kind"] == "em_analysis"
                  and job["input"]["task_plan"]["execution_mode"] == "solve_and_postprocess")


def run(report_path, proof_path):
    """! @brief 실패한 후처리를 자동 교체하지 않고 동일 키의 재조회만 허용한다."""
    report = json.loads(report_path.read_bytes())
    require(report.get("status") in {"completed", "completed_with_blocked_cases"}, "완료한 전력 연구가 필요합니다.")
    completed = {key: row for key, row in report["runs"].items()
                 if row["status"] == "completed" and row.get("source_kind") != "verified_existing_raw"}
    require(bool(completed), "재후처리할 완료 손실 결과가 없습니다.")
    workspace = Path(report["workspace"])
    if proof_path.exists():
        proof = json.loads(proof_path.read_bytes())
        require(proof["workspace"] == str(workspace) and proof["runtime_identity"] == report["runtime_identity"], "재후처리 증거의 workspace/worker가 다릅니다.")
    else:
        proof = {"schema": "rfad.pcb-power-replay/0.1", "workspace": str(workspace), "runtime_identity": report["runtime_identity"], "status": "running"}
    runtime = SolverRuntime()
    require(runtime.identity == report["runtime_identity"], "현재 worker가 원래 전력 연구와 다릅니다.")
    subject = report["subject"]
    entry = max(completed.values(), key=lambda row: row["power_balance"]["recording"]["estimated_field_bytes"])
    views, sealed = {}, {}
    with ProjectService(workspace, solver_runtime=runtime, auto_run=True) as service:
        before = native_jobs(service.journal.read())
        # @brief 별도 producer에서 재사용한 기준을 포함해 기존 등록 결과의 봉인도 모두 보존한다.
        for stored in service.journal.read()["solver_results"].values():
            for item in stored["files"]:
                ref = item["artifact"]
                sealed[ref["uri"]] = ref
        for key, row in completed.items():
            load_result(service, row, subject)
            view = call(service, "result.open", {"artifact_id": row["artifact_id"]}, subject["context"])
            views[key] = view
            for item in view["files"]:
                sealed[item["uri"]] = reference(item)
        original = json.loads(service.journal.read_artifact(entry["normalized_result"]))
        task_plan = {**entry["phases"]["analysis"]["input"]["task_plan"], "execution_mode": "postprocess_only", "raw_result_id": entry["artifact_id"]}
        repeated = execute_phase(service, proof, proof_path, proof, "postprocess", "job.submit", {
            "task_plan": task_plan, "budget": {"timeout_seconds": 180}}, subject["context"])
        normalized = json.loads(service.journal.read_artifact(repeated["normalized_result"]))
        require(all(original[name] == normalized[name] for name in ("samples", "raw_manifest", "radiation_summary", "power_balance")), "재후처리의 원시 자료/포트/방사/독립 손실이 바뀌었습니다.")
        after = native_jobs(service.journal.read())
        require(before == after, "후처리 중 native 실행 요청이 추가되었습니다.")
        for ref in sealed.values():
            service.journal.verify_file(ref)
        proof.update(native_job_ids_before=before, native_job_ids_after=after, original_sealed_files=len(sealed),
                     original_files_unchanged=True, independent_loss_identical=True, repeated_artifact_id=repeated["artifact_id"])
    with ProjectService(workspace, auto_run=False) as reopened:
        require(native_jobs(reopened.journal.read()) == before, "solver 없는 재열기에서 native 작업이 바뀌었습니다.")
        for key, row in completed.items():
            require(call(reopened, "result.open", {"artifact_id": row["artifact_id"]}, subject["context"]) == views[key], "해석기 없는 재열기 결과가 다릅니다.")
            load_result(reopened, row, subject)
    proof.update(status="passed", restored_without_solver=True, physics_validated=False)
    save_report(proof_path, proof)
    return proof


def main():
    """! @brief 재실행 없는 검증 증거를 별도 파일로 보존한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    args = parser.parse_args()
    try:
        proof = run(args.report, args.proof)
        print(json.dumps({key: proof[key] for key in ("status", "original_sealed_files", "independent_loss_identical", "restored_without_solver")}))
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
