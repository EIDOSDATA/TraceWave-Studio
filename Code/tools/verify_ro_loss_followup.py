"""! @brief 동일 native 입력을 증명한 원시 참조만 재사용하여 RO4350B 국부 손실을 심화 검증한다."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import PROFILE, validate_pcb_plan
from rfad.application.pcb_loss_study import validate_study, plan_guard
from rfad.application.pcb_loss_convergence import assess_losses
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from rfad.application.radiation_study import require
from loss_recalculation import load_producer, run as recalculate
from verify_ifa_convergence import execute_phase, save_report
from verify_openems_worker import call
from verify_pcb_power_balance import load_result
from pcb_loss_execution import execute_case


def equivalent_inputs(original, candidate, original_xml, candidate_xml):
    """! @brief 예산 profile만 달라질 수 있으며 snapshot/물리 설정/정규화/실제 XML은 같아야 한다."""
    require(original["snapshot"] == candidate["snapshot"] and original["source_semantics"] == candidate["source_semantics"]
            and original["normalization"] == candidate["normalization"], "참조 원본 또는 정규화가 다릅니다.")
    a, b = deepcopy(original["case"]), deepcopy(candidate["case"])
    a["settings"].pop("compute_profile", None)
    b["settings"].pop("compute_profile", None)
    require(a == b, "예산 외의 물리 입력/격자/기록이 달라 원시 참조를 재사용할 수 없습니다.")
    require(original["runtime_identity"]["manifest_sha256"] == candidate["runtime_identity"]["manifest_sha256"], "native 설치가 다릅니다.")
    require(all(original_xml[key] == candidate_xml[key] for key in ("bytes", "sha256")), "새 준비 XML과 실제 실행한 XML의 바이트가 다릅니다.")
    return {"same_snapshot_and_source": True, "same_physical_case_except_compute_profile": True,
            "same_normalization_and_install": True, "native_xml_bytes_identical": True,
            "original_xml": original_xml, "candidate_xml": candidate_xml, "fdtd_reexecuted": False}


def run(producer_path, manifest_path, destination):
    """! @brief 세 비교 계획을 먼저 준비하고 검증된 기준 하나와 두 새 native 실행을 결합한다."""
    require(not destination.exists(), "기존 심화 연구를 덮어쓸 수 없습니다.")
    original = load_producer(producer_path)
    require(original["status"] == "completed" and all(e["status"] == "completed" for e in original["runs"].values()), "완료 원시 생산자 연구가 필요합니다.")
    study = json.loads(manifest_path.read_bytes())
    validate_study(study)
    require(len(study["cases"]) == 3 and all(c["axis"] == "local_mesh" for c in study["cases"]), "고정 국부 3수준 연구가 필요합니다.")
    baseline = next(e for e in original["runs"].values() if e["settings"]["feature_subdivisions"] == study["cases"][0]["settings"]["feature_subdivisions"])
    destination.mkdir(parents=True)
    runtime = SolverRuntime()
    report_path = destination / "report.json"
    report = {"schema": "rfad.pcb-loss-equivalent-input-study/0.1", "study": study, "producer_report": str(producer_path.resolve()),
              "producer_report_sha256": hashlib.sha256(producer_path.read_bytes()).hexdigest(), "workspace": original["workspace"],
              "subject": original["subject"], "runtime_identity": runtime.identity, "runs": {}, "status": "preparing",
              "physics_validated": False, "fabrication_validated": False, "measurement_validated": False}
    save_report(report_path, report)
    # @brief 다른 producer의 필드는 원래 계획으로 재계산한다. 비교 계획의 실행 결과로 바꿔 게시하지 않는다.
    corrected = recalculate(producer_path, destination / "reference-calculation")
    reference_power = corrected["runs"][canonical_hash(baseline["settings"])]["power_balance"]
    require(corrected["calculator_identity"]["native_install_manifest_sha256"] == runtime.identity["manifest_sha256"], "참조 계산기의 설치가 다릅니다.")
    current_files = {item["path"]: item for item in runtime.identity["code_files"]}
    for item in corrected["calculator_identity"]["files"]:
        if item["path"] != "tools/openems_worker.py":
            require(item == current_files[item["path"]], "참조와 새 실행의 공통 계산기 소스가 다릅니다.")
    report["reference_calculation"] = {"report": str((destination / "reference-calculation/report.json").resolve()),
                                       "calculator_identity": corrected["calculator_identity"]}
    context = original["subject"]["context"]
    with ProjectService(Path(original["workspace"]), solver_runtime=runtime) as service:
        plans, preparations = [], []
        for case in study["cases"]:
            entry = {"settings": case["settings"], "status": "pending"}
            key = canonical_hash(case["settings"])
            report["runs"][key] = entry
            planned = execute_phase(service, report, report_path, entry, "plan", "solver.plan", {
                "snapshot": {k: original["subject"]["snapshot"][k] for k in ("snapshot_id", "content_hash")},
                "analysis_profile": PROFILE, "runtime_profile": runtime.identity["runtime_profile"], "settings": case["settings"]}, context)
            entry["analysis_plan"] = planned["analysis_plan"]
            plan = json.loads(service.journal.read_artifact(entry["analysis_plan"]["artifact"]))
            validate_pcb_plan(plan)
            started = time.monotonic()
            prepared = execute_phase(service, report, report_path, entry, "prepare", "solver.prepare", {
                "analysis_plan": {k: entry["analysis_plan"][k] for k in ("plan_id", "content_hash")},
                "budget": {"timeout_seconds": plan["resource_estimate"]["max_wall_time_seconds"]}}, context)
            entry.update(prepared_plan=prepared["prepared_plan"], preparation_artifact=prepared["preparation_artifact"],
                         preflight_preparation_seconds=time.monotonic()-started)
            plans.append(plan)
            preparations.append(json.loads(service.journal.read_artifact(prepared["preparation_artifact"])))
        report["preflight_guards"] = [plan_guard(a,b,"local_mesh") for a,b in zip(plans,plans[1:])]
        opened = call(service, "result.open", {"artifact_id": baseline["artifact_id"]}, context)
        files = {item["role"]: item for item in opened["files"]}
        for item in opened["files"]:
            service.journal.verify_file({k:item[k] for k in ("uri","bytes","sha256")})
        old_plan = json.loads(service.journal.read_artifact(baseline["analysis_plan"]["artifact"]))
        old_normalized = json.loads(service.journal.read_artifact({k:files["normalized_result"][k] for k in ("uri","bytes","sha256")}))
        require(old_normalized["provenance"]["analysis_plan"] == old_plan and old_normalized["power_balance"] == baseline["power_balance"], "기존 raw 생산자의 계획/정규화가 다릅니다.")
        old_command = old_normalized["raw_manifest"]["execution"]["command"]
        require("--numThreads=" + str(plans[0]["case"]["num_threads"]) in old_command and "--exact-endcriteria" in old_command
                and "--engine=multithreaded" in old_command, "기존 raw 실행기의 스레드/종료 정책이 다릅니다.")
        new_xml = next(item for item in preparations[0]["files"] if item["role"] == "native_input")
        proof = equivalent_inputs(old_plan, plans[0], files["raw/pcb.xml"], new_xml)
        first = report["runs"][canonical_hash(study["cases"][0]["settings"])]
        first.update(status="completed", source_kind="verified_existing_raw", original_artifact_id=baseline["artifact_id"],
                     original_producer_analysis_plan=baseline["analysis_plan"], power_balance=reference_power, equivalence=proof,
                     actual_producer_runtime=original["runtime_identity"], fdtd_executed=False)
        report.update(status="running", all_comparison_plans_prepared_before_new_fdtd=True)
        save_report(report_path, report)
        for case in study["cases"][1:]:
            entry = report["runs"][canonical_hash(case["settings"])]
            print(json.dumps({"local":case["settings"]["feature_subdivisions"],"status":"starting"}),flush=True)
            execute_case(service,report,report_path,entry,original["subject"])
            entry.update(source_kind="new_native_execution", fdtd_executed=True,
                         power_balance=load_result(service,entry,original["subject"]))
            save_report(report_path, report)
        powers = [report["runs"][canonical_hash(c["settings"])]["power_balance"] for c in study["cases"]]
        report.update(status="completed", assessment=assess_losses(powers,study["acceptance_profile"]),
                      all_completed_energy_closure=all(p["full_energy_closure"]=="within_initial_numerical_budget" for p in powers))
        save_report(report_path, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer-report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.producer_report,args.manifest,args.destination)
    print(json.dumps({"status":result["status"],"loss_stability":result["assessment"]["status"]}))
    raise SystemExit(0 if result["assessment"]["status"]=="passed" and result["all_completed_energy_closure"] else 1)
