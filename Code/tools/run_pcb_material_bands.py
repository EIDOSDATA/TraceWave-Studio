"""! @brief 기존 PCB 스냅샷에 대역별 물성을 적용하고 개별 해석 결과와 위상 원본을 보존한다."""

import argparse
import json
from pathlib import Path

from verify_openems_worker import ProjectService, SolverRuntime
from verify_ifa_convergence import execute_phase, save_report
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_compute import limits
from rfad.application.pcb_material_bands import split
from rfad.application.pcb_solver import PROFILE, check_pcb_input
from rfad.application.pcb_projection import project_pcb
from rfad.application.solver import RUNTIME_PROFILE
from rfad.application.wsl_process import WslRuntime


def run(workspace, snapshot_id, settings, output, solve):
    """! @brief 모든 구간을 먼저 검토한 뒤 각 독립 native 작업의 요청 키와 결과를 저장한다."""
    runtime = SolverRuntime(transport=WslRuntime(startup_timeout_seconds=240)) if solve else None
    with ProjectService(workspace, solver_runtime=runtime, auto_run=solve) as service:
        snapshot = service.journal.read()["snapshots"][snapshot_id]
        document = json.loads(service.journal.read_artifact(snapshot["artifact"]))
        if canonical_hash(document) != snapshot["content_hash"]:
            raise ValueError("스냅샷의 해시가 원본과 다릅니다.")
        bands = split(settings, {item["id"]: item for item in document["materials"]})
        key = canonical_hash([str(workspace.resolve()), snapshot_id, settings, runtime.identity if solve else None])
        if output.exists():
            report = json.loads(output.read_bytes())
            if report.get("identity") != key:
                raise ValueError("기존 보고서의 스냅샷, 계산 환경 또는 조건이 다릅니다.")
        else:
            report = {"identity": key, "snapshot": snapshot_id, "source_hash": snapshot["content_hash"],
                      "independent_excitations": True, "continuous_phase_assumed": False, "bands": []}
            for child in bands:
                check_pcb_input(document, child)
                case = project_pcb(document, child)["case"]
                report["bands"].append({"settings": child, "materials": case["materials"]})
            save_report(output, report)
        if not solve:
            return report
        context = {"project_id": document["project_id"]}
        for child, entry in zip(bands, report["bands"], strict=True):
            if entry.get("settings") != child:
                raise ValueError("저장된 대역 계산 입력이 달라졌습니다.")
            budget = {"timeout_seconds": limits(child)["max_wall_time_seconds"]}
            planned = execute_phase(service, report, output, entry, "plan", "solver.plan", {
                "snapshot": {k: snapshot[k] for k in ("snapshot_id", "content_hash")},
                "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE, "settings": child}, context)
            prepared = execute_phase(service, report, output, entry, "prepare", "solver.prepare", {
                "analysis_plan": {k: planned["analysis_plan"][k] for k in ("plan_id", "content_hash")}, "budget": budget}, context)
            result = execute_phase(service, report, output, entry, "analysis", "job.submit", {
                "task_plan": {"kind": "em_analysis", "prepared_plan": {
                    k: prepared["prepared_plan"][k] for k in ("prepared_plan_id", "content_hash")}, "execution_mode": "solve_and_postprocess"},
                "budget": budget}, context)
            entry["artifact_id"] = result["artifact_id"]
            entry["normalized_result"] = result["normalized_result"]
            save_report(output, report)
        return report


def main():
    """! @brief 저장한 프로젝트의 스냅샷 ID, 물성 구간을 담은 solver 조건과 보고서 경로를 받는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("snapshot_id")
    parser.add_argument("settings", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solve", action="store_true", help="WSL2에서 각 구간을 독립적으로 실제 계산")
    args = parser.parse_args()
    report = run(args.workspace, args.snapshot_id, json.loads(args.settings.read_text(encoding="utf-8-sig")), args.output, args.solve)
    print(json.dumps({"bands": len(report["bands"]), "results": [row.get("artifact_id") for row in report["bands"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
