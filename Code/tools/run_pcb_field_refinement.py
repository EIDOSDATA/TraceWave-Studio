"""! @brief 봉인된 전계에서 다음 격자를 검토하고 같은 스냅샷의 실제 해석 결과를 비교한다."""

import argparse
import json
from pathlib import Path

from verify_openems_worker import ProjectService, SolverRuntime, call
from verify_ifa_convergence import execute_phase, save_report
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_compute import limits
from rfad.application.wsl_process import WslRuntime


def compare(old, new):
    """! @brief 원본과 새 격자의 동일 주파수에서 복소 S11과 독립 적분 전력을 대조한다."""
    before, after = old["samples"], new["samples"]
    if [p["frequency_hz"] for p in before] != [p["frequency_hz"] for p in after]:
        raise ValueError("주파수 표본이 달라졌습니다.")
    report = {"samples": len(after), "max_abs_delta_s11": max(abs(complex(*p["s11"]) - complex(*q["s11"]))
                                                             for p, q in zip(before, after)),
              "termination": [old["termination"], new["termination"]]}
    if "power_balance" in old:
        keys = ("frequency_hz", "accepted_power_w_s2", "radiated_power_w_s2", "dielectric_loss_w_s2",
                "conductor_loss_w_s2", "via_loss_w_s2", "residual_w_s2", "relative_residual", "status")
        report["power_balance"] = [[{k: row[k] for k in keys if k in row}
                                    for row in result["power_balance"]["frequencies"]] for result in (old, new)]
    return report


def run(args):
    """! @brief 선택한 고정 원본의 다음 조건을 만들고 요청 시 일반 작업 큐로 제출한다."""
    runtime = SolverRuntime(transport=WslRuntime(startup_timeout_seconds=args.startup_seconds)) if args.solve else None
    with ProjectService(args.workspace, solver_runtime=runtime) as service:
        record = service.journal.read()["solver_results"][args.artifact]
        old = json.loads(service.journal.read_artifact(record["normalized"]))
        context = {"project_id": record["project_id"]}
        source = {"kind": "solver", "artifact_id": args.artifact}
        pin = call(service, "result.describe", {"source": source}, context)["pin"]
        request = {"source": source, "pin": pin, "monitor_id": args.monitor, "component": args.component,
                   "frequency_index": args.frequency_index, "plane": {"normal_axis": args.normal, "index": args.index},
                   "roi": dict(zip(("u_start", "u_count", "v_start", "v_count"), args.roi)),
                   "threshold_fraction": args.threshold, "max_rules": args.max_rules, "memory_limit_mib": args.memory_mib}
        identity = canonical_hash([str(args.workspace.resolve()), request, args.solve, args.research_threads])
        if args.output.exists():
            report = json.loads(args.output.read_text(encoding="utf-8"))
            if report.get("request_hash") != identity:
                raise ValueError("기존 보고서와 작업 영역 또는 입력이 다릅니다.")
            if "comparison" in report:
                return report
        else:
            report = {"request_hash": identity, "source": source, "request": request,
                      "proposal": call(service, "result.field.refine", request, context)}
            save_report(args.output, report)
        proposal = report["proposal"]
        if not args.solve or proposal["status"] != "refined":
            return report
        original = old["provenance"]["analysis_plan"]
        snapshot = {k: original["snapshot"][k] for k in ("snapshot_id", "content_hash")}
        execution = dict(proposal["settings"])
        if args.research_threads is not None:
            execution["compute_profile"] = {"kind": "tuning_refinement/0.1", "num_threads": args.research_threads}
        report["execution_settings"] = execution
        budget = {"timeout_seconds": limits(execution)["max_wall_time_seconds"]}
        planned = execute_phase(service, report, args.output, report, "plan", "solver.plan",
                                {"snapshot": snapshot, "analysis_profile": original["analysis_profile"],
                                 "runtime_profile": original["runtime_profile"], "settings": execution}, context)
        prepared = execute_phase(service, report, args.output, report, "prepare", "solver.prepare", {
            "analysis_plan": {k: planned["analysis_plan"][k] for k in ("plan_id", "content_hash")}, "budget": budget}, context)
        solved = execute_phase(service, report, args.output, report, "solve", "job.submit", {
            "task_plan": {"kind": "em_analysis", "prepared_plan": {k: prepared["prepared_plan"][k]
                          for k in ("prepared_plan_id", "content_hash")}, "execution_mode": "solve_and_postprocess"},
            "budget": budget}, context)
        new = json.loads(service.journal.read_artifact(solved["normalized_result"]))
        if canonical_hash(new["mesh_statistics"]["lines_mm"]) != proposal["next_mesh_sha256"]:
            raise ValueError("실제 해석 격자가 검토한 격자와 다릅니다.")
        report.update(artifact_id=solved["artifact_id"], comparison=compare(old, new))
        save_report(args.output, report)
        return report


def main():
    """! @brief 이전 풀이의 전계 ROI와 메모리 상한을 지정한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("artifact", help="이전 솔버 결과 UUID")
    parser.add_argument("output", type=Path)
    parser.add_argument("--monitor", choices=("electric", "probe_electric"), required=True)
    parser.add_argument("--component", choices=tuple("xyz"), required=True)
    parser.add_argument("--frequency-index", type=int, required=True)
    parser.add_argument("--normal", choices=tuple("xyz"), required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--roi", nargs=4, type=int, metavar=("U_START", "U_COUNT", "V_START", "V_COUNT"), required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--max-rules", type=int, default=2)
    parser.add_argument("--memory-mib", type=int, required=True)
    parser.add_argument("--startup-seconds", type=int, default=60, help="WSL2 기동 및 파일 전송 제한 시간")
    parser.add_argument("--research-threads", type=int, choices=range(1, 9),
                        help="기존 수치 연구용 900초 계산 프로필과 스레드 수를 명시적으로 선택")
    parser.add_argument("--solve", action="store_true", help="같은 설계 스냅샷에서 새 격자로 해석 및 비교")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({"status": report["proposal"]["status"], "artifact_id": report.get("artifact_id"),
                      "report": str(args.output.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
