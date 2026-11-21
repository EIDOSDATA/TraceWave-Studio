"""! @brief 채택한 설치 후보를 같은 형상에서 더 세밀한 격자 또는 종료 조건으로 다시 실행한다."""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))

from catalog_pcb_verification.common import call, wait
from rfad.application.pcb_solver import PROFILE
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from verify_ifa_convergence import execute_phase, save_report
from verify_installed_port_band import inputs
from verify_installed_port_uncertainty import Circuit, PHYSICAL, ROUTES, payload, relative_bound, sampled
from verify_tuning_workflow import document


GRIDS = {"ifa": 0.43, "arc": 0.425}
END = 2.5e-5


def refine(kind, baseline, source, destination, prepare_only):
    """! @brief 저장 원본을 복사하고 원래 물리 조건을 확인한 단일 축 실험만 게시한다."""
    base = payload(source, baseline)
    normalized, *_ = inputs(source, baseline)
    reference = normalized["provenance"]["analysis_plan"]
    context = {"project_id": reference["snapshot"]["project_id"]}
    base_settings = reference["case"]["settings"]
    original_pointer = sha256((source / "current.json").read_bytes()).hexdigest()
    destination.mkdir()
    path = destination / "report.json"
    workspace = destination / "workspace"
    shutil.copytree(source, workspace)
    runtime = SolverRuntime()
    report = {"schema": "rfad.installed-single-axis-refinement/0.1", "kind": kind, "baseline": base["evidence"],
              "axes": {}, "status": "running", "numerical_accuracy_validated": False}
    save_report(path, report)
    p, serial, value = ROUTES[kind]
    circuit = Circuit(p * 1e-12, serial, value * (1e-12 if serial == "C" else 1e-9))
    base_curve = sampled(circuit, base["traces"])
    with ProjectService(workspace, solver_runtime=runtime) as service:
        current_id = document(service, context)["revision_id"]
        snapshot, _ = wait(service, call(service, "snapshot.create", {
            "expected_revision": current_id, "description": "합성 설치 후보의 단일 축 재검증"}, context, mutation=True))
        for key, value in (("end_criterion", END), ("grid_mm", GRIDS[kind])):
            settings = {**base_settings, key: value}
            row = report["axes"][key] = {"settings": settings, "status": "pending"}
            save_report(path, report)
            try:
                plan_reference = execute_phase(service, report, path, row, "plan", "solver.plan", {
                    "snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
                    "analysis_profile": PROFILE, "runtime_profile": runtime.identity["runtime_profile"],
                    "settings": settings}, context)["analysis_plan"]
                plan = json.loads(service.journal.read_artifact(plan_reference["artifact"]))
                if {key: plan["case"].get(key) for key in PHYSICAL} != base["physical"]:
                    raise ValueError("채택 사본과 보존 결과의 물리 입력이 다릅니다.")
                budget = {"timeout_seconds": plan["resource_estimate"]["max_wall_time_seconds"]}
                prepare = execute_phase(service, report, path, row, "prepare", "solver.prepare", {
                    "analysis_plan": {k: plan_reference[k] for k in ("plan_id", "content_hash")}, "budget": budget}, context)
                prepared = prepare["prepared_plan"]
                row["planned_grid_points"] = plan["resource_estimate"]["estimated_grid_points"]
                if prepare_only:
                    row.update(status="prepared", prepared_plan=prepared)
                    save_report(path, report)
                    print(kind, key, row["status"], flush=True)
                    continue
                result = execute_phase(service, report, path, row, "analysis", "job.submit", {
                    "task_plan": {"kind": "em_analysis", "execution_mode": "solve_and_postprocess",
                                  "prepared_plan": {k: prepared[k] for k in ("prepared_plan_id", "content_hash")}},
                    "budget": budget}, context)
                opened = call(service, "result.open", {"artifact_id": result["artifact_id"]}, context)
                sealed = next(item for item in opened["files"] if item["role"] == "normalized_result")
                run = sealed["uri"].split("/")[1]
                updated = payload(workspace, run)
                curve = sampled(circuit, updated["traces"])
                statistics = json.loads(service.journal.read_artifact(sealed))["native_statistics"]
                row.update(status="completed", evidence=updated["evidence"], native_statistics=statistics,
                           complex_difference_upper=relative_bound(base_curve, curve),
                           continuous_upper_db=20 * math.log10(max(abs(value) + radius for value, radius in curve)))
            except (RuntimeError, ValueError) as error:
                row.update(status="not_evaluated", error=str(error))
            save_report(path, report)
            print(kind, key, row["status"], flush=True)
    if original_pointer != sha256((source / "current.json").read_bytes()).hexdigest():
        raise ValueError("원본 저장소 포인터가 바뀌었습니다.")
    report["source_unchanged"] = True
    expected = "prepared" if prepare_only else "completed"
    report["status"] = expected if all(item["status"] == expected for item in report["axes"].values()) else "partial"
    save_report(path, report)
    return report["status"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=ROUTES)
    parser.add_argument("source", type=Path)
    parser.add_argument("baseline")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--prepare-only", action="store_true", help="계획과 실제 native XML 준비까지만 검사합니다.")
    args = parser.parse_args()
    status = refine(args.kind, args.baseline, args.source.resolve(), args.destination.resolve(), args.prepare_only)
    raise SystemExit(0 if status in {"completed", "prepared"} else 1)
