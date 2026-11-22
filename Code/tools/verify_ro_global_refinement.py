"""! @brief RO4350B 8분할의 기존 물리 입력에서 일반 격자만 세분화해 손실을 확인한다."""
import argparse
import json
from pathlib import Path
import shutil
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))

from pcb_loss_execution import assess_available, blocked_job, execute_case
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_compute import limits
from rfad.application.pcb_loss_study import plan_guard, validate_study
from rfad.application.pcb_solver import PROFILE, validate_pcb_plan
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from verify_ifa_convergence import execute_phase, save_report
from verify_pcb_power_balance import load_result
from verify_ro_grid_ablation import sha, source


GRIDS = (0.38, 0.36)


def refine(reference_file, archived, destination):
    """! @brief 원본을 읽기 전용으로 검증한 뒤 별도 작업본에서 두 후속 수준을 처리한다."""
    producer = json.loads(reference_file.read_bytes())
    base, = (row for row in producer["runs"].values() if row["settings"]["feature_subdivisions"] == 8)
    if producer["status"] != "completed" or base["status"] != "completed":
        raise ValueError("완료된 봉인 8분할 연구를 사용하십시오.")
    archived_raw, old = source(archived, base)
    original_plan = old["provenance"]["analysis_plan"]
    if original_plan["case"]["settings"] != base["settings"] or base["settings"]["grid_mm"] != 0.4:
        raise ValueError("고정 기준 격자 0.40 mm의 설정이 다릅니다.")
    levels = (0.4, *GRIDS)
    study = {
        "schema": "rfad.pcb-loss-study/0.1",
        "id": "ro4350b-local8-general-grid-refinement/0.1",
        "fixture": producer["study"]["fixture"],
        "acceptance_profile": producer["study"]["acceptance_profile"],
        "cases": [{"axis": "mesh", "label": "local8-grid-" + format(grid, ".2f"),
                   "settings": {**base["settings"], "grid_mm": grid}} for grid in levels],
    }
    validate_study(study)
    pointer_before = sha(archived / "current.json")
    destination.mkdir()
    output = destination / "report.json"
    workspace = destination / "workspace"
    runtime = SolverRuntime()
    shutil.copytree(archived, workspace)
    subject = producer["subject"]
    context = subject["context"]
    report = {"schema": "rfad.ro-local8-global-refinement/0.1", "status": "running",
              "source_report_sha256": sha(reference_file), "study": study, "runs": {},
              "preflight_guards": [], "physics_validated": False,
              "archived_reference": {
                  "normalized_result": base["normalized_result"], "native_input_sha256": sha(archived_raw["pcb.xml"]),
                  "same_solver_identity": runtime.identity == original_plan["runtime_identity"],
                  "historical_result_reused_for_assessment": False,
              }}
    run_rows = report["runs"]
    with ProjectService(workspace, solver_runtime=runtime) as service:
        save_report(output, report)
        previous = None
        pending_rows = []
        for case in study["cases"]:
            settings = case["settings"]
            row = run_rows[canonical_hash(settings)] = {"settings": settings, "status": "pending"}
            planned = execute_phase(service, report, output, row, "plan", "solver.plan", {
                "snapshot": {key: subject["snapshot"][key] for key in ("snapshot_id", "content_hash")},
                "analysis_profile": PROFILE, "runtime_profile": runtime.identity["runtime_profile"],
                "settings": settings,
            }, context)
            reference = row["analysis_plan"] = planned["analysis_plan"]
            plan = json.loads(service.journal.read_artifact(reference["artifact"]))
            validate_pcb_plan(plan)
            if previous is None:
                if (plan["source_semantics"] != original_plan["source_semantics"]
                        or plan["snapshot"] != original_plan["snapshot"]
                        or plan["normalization"] != original_plan["normalization"]
                        or plan["case"]["settings"] != original_plan["case"]["settings"]):
                    raise ValueError("새 기준의 물리 원본·스냅샷·설정이 보존 기준과 다릅니다.")
            else:
                report["preflight_guards"].append(plan_guard(previous, plan, "mesh"))
            previous = plan
            budget = {"timeout_seconds": limits(settings)["max_wall_time_seconds"]}
            prepared = execute_phase(service, report, output, row, "prepare", "solver.prepare", {
                "analysis_plan": {key: reference[key] for key in ("plan_id", "content_hash")},
                "budget": budget,
            }, context)
            preparation = json.loads(service.journal.read_artifact(prepared["preparation_artifact"]))
            xml, = (artifact for artifact in preparation["files"] if artifact["role"] == "native_input")
            if settings["grid_mm"] == levels[0]:
                report["archived_reference"]["same_baseline_native_xml"] = xml["sha256"] == sha(archived_raw["pcb.xml"])
            row.update(numerical_grid_points=plan["resource_estimate"]["estimated_grid_points"], native_input=xml,
                       preparation_artifact=prepared["preparation_artifact"], status="prepared")
            pending_rows.append(row)
            save_report(output, report)
            print(settings["grid_mm"], "prepared", row["numerical_grid_points"], flush=True)
        for row in pending_rows:
            try:
                execute_case(service, report, output, row, subject)
                row["power_balance"] = load_result(service, row, subject)
                normalized = json.loads(service.journal.read_artifact(row["normalized_result"]))
                row["native_statistics"] = normalized["native_statistics"]
                row["termination"] = normalized["termination"]
            except (RuntimeError, ValueError) as error:
                row.update(status="not_evaluated", diagnostic=str(error))
                blocked = blocked_job(service, row)
                if blocked is None:
                    save_report(output, report)
                    raise
                row["confirmed_terminal"] = blocked
            save_report(output, report)
            print(row["settings"]["grid_mm"], row["status"], flush=True)
    if pointer_before != sha(archived / "current.json"):
        raise ValueError("보존 원본의 저장 포인터가 시험 중 바뀌었습니다.")
    report["source_workspace_pointer_unchanged"] = True
    report["assessment"] = assess_available(study, run_rows)
    report["status"] = "completed" if all(row["status"] == "completed" for row in run_rows.values()) else "partial"
    save_report(output, report)
    return report["status"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("reference", "workspace", "destination"):
        parser.add_argument(key, type=Path)
    args = parser.parse_args()
    status = refine(args.reference.resolve(), args.workspace.resolve(), args.destination.resolve())
    raise SystemExit(0 if status == "completed" else 1)
