"""! @brief 원본/출처를 보존한 독립 손실의 네 수치 축 연구를 공개 API로 실행한다."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "src"))

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import PROFILE, validate_pcb_plan
from rfad.application.pcb_loss_study import plan_guard, validate_study
from rfad.application.projects import ProjectService
from rfad.application.solver import RUNTIME_PROFILE
from rfad.application.solver_runtime import SolverRuntime
from rfad.application.radiation_study import require
from verify_pcb_radiation_convergence import create_subject
from verify_pcb_power_balance import load_result
from verify_ifa_convergence import execute_phase, save_report
from pcb_loss_execution import blocked_job, execute_case, assess_available


def run(workspace, report_path, manifest_path, catalog=None, *, resume=False, reassess_only=False, continue_independent=False):
    """! @brief 모든 계획을 사전 봉인하고 실패/중단을 자동 교체하지 않는 연구를 수행한다."""
    study = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_study(study)
    fixture = json.loads((manifest_path.parent / study["fixture"]).read_text(encoding="utf-8"))
    runtime = None if reassess_only else SolverRuntime()
    if resume or reassess_only or (continue_independent and report_path.exists()):
        report = json.loads(report_path.read_bytes())
        require(report["study"] == study and report["fixture_hash"] == canonical_hash(fixture)
                and report["workspace"] == str(workspace.resolve()), "원래 손실 연구의 입력/경로가 다릅니다.")
        require(runtime is None or runtime.identity == report["runtime_identity"], "손실 연구의 worker가 바뀌었습니다. 새 경로를 사용하십시오.")
    else:
        require(not workspace.exists() and not report_path.exists(), "기존 손실 연구 경로를 덮어쓸 수 없습니다.")
        report = {"schema": "rfad.pcb-loss-study-run/0.1", "study": study, "fixture_hash": canonical_hash(fixture),
                  "workspace": str(workspace.resolve()), "runtime_identity": runtime.identity,
                  "started_at": datetime.now(timezone.utc).isoformat(), "runs": {}, "status": "initializing",
                  "physics_validated": False, "fabrication_validated": False, "measurement_validated": False}
        save_report(report_path, report)
    with ProjectService(workspace, solver_runtime=runtime, auto_run=not reassess_only, catalog_database=catalog) as service:
        if "subject" not in report:
            report["subject"] = create_subject(service, fixture, catalog)
            save_report(report_path, report)
        subject, plans = report["subject"], {}
        for case in study["cases"]:
            key = canonical_hash(case["settings"])
            if key in plans:
                continue
            entry = report["runs"].setdefault(key, {"settings": deepcopy(case["settings"]), "status": "pending"})
            require(entry["settings"] == case["settings"], "저장한 손실 연구의 조건이 바뀌었습니다.")
            if not reassess_only:
                planned = execute_phase(service, report, report_path, entry, "plan", "solver.plan", {
                    "snapshot": {name: subject["snapshot"][name] for name in ("snapshot_id", "content_hash")},
                    "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE, "settings": case["settings"]}, subject["context"])
                entry["analysis_plan"] = planned["analysis_plan"]
                save_report(report_path, report)
            plans[key] = json.loads(service.journal.read_artifact(entry["analysis_plan"]["artifact"]))
            validate_pcb_plan(plans[key])
        require(set(report["runs"]) == set(plans), "손실 연구의 고유 계산 목록이 다릅니다.")
        guards = []
        for axis in sorted({case["axis"] for case in study["cases"]}):
            cases = [case for case in study["cases"] if case["axis"] == axis]
            for a, b in zip(cases, cases[1:]):
                guards.append({"axis": axis, "left": a["label"], "right": b["label"],
                               **plan_guard(plans[canonical_hash(a["settings"])], plans[canonical_hash(b["settings"])], axis)})
        report.update(preflight_guards=guards, all_plans_validated_before_execution=True)
        save_report(report_path, report)
        for key, entry in report["runs"].items():
            if entry["status"] != "completed":
                blocked = blocked_job(service, entry)
                if blocked is not None and (continue_independent or reassess_only):
                    entry.update(status="blocked", blocking_job=blocked)
                    save_report(report_path, report)
                    continue
                require(not reassess_only, "미완료 계산을 재판정만으로 보완할 수 없습니다.")
                labels = [case["label"] for case in study["cases"] if canonical_hash(case["settings"]) == key]
                print(json.dumps({"cases": labels, "status": "starting"}), flush=True)
                try:
                    execute_case(service, report, report_path, entry, subject)
                except Exception:
                    blocked = blocked_job(service, entry)
                    if not continue_independent or blocked is None:
                        raise
                    entry.update(status="blocked", blocking_job=blocked)
                    save_report(report_path, report)
                    continue
            entry["power_balance"] = load_result(service, entry, subject)
            normalized = json.loads(service.journal.read_artifact(entry["normalized_result"]))
            require(normalized["provenance"]["analysis_plan"]["runtime_identity"] == report["runtime_identity"], "계산 소스가 연구의 고정 worker와 다릅니다.")
            print(json.dumps({"settings_hash": key, "energy_closure": entry["power_balance"]["full_energy_closure"]}), flush=True)
            save_report(report_path, report)
        assessment = assess_available(study, report["runs"])
        assessment["case_results"] = {key: {name: entry[name] for name in ("artifact_id", "normalized_result", "power_balance_result")} for key, entry in report["runs"].items() if entry["status"] == "completed"}
        assessment["blocked_cases"] = {key: entry["blocking_job"] for key, entry in report["runs"].items() if entry["status"] == "blocked"}
        assessment["calculator_sources"] = [{"path": path.relative_to(CODE_ROOT).as_posix(), "text": path.read_text(encoding="utf-8"),
                                               "sha256": hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()}
                                              for path in [Path(__file__), CODE_ROOT / "tools/pcb_loss_execution.py", CODE_ROOT / "src/rfad/application/pcb_loss_study.py", CODE_ROOT / "src/rfad/application/pcb_loss_convergence.py"]]
        destination = report_path.parent / (report_path.stem + ".assessments") / (canonical_hash(assessment) + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            require(json.loads(destination.read_bytes()) == assessment, "불변 손실 판정의 내용이 바뀌었습니다.")
        else:
            with destination.open("x", encoding="utf-8") as stream:
                json.dump(assessment, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        report.update(status="completed" if not assessment["blocked_cases"] else "completed_with_blocked_cases", assessment=assessment,
                      assessment_artifact={"path": str(destination.relative_to(report_path.parent)), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()},
                      completed_at=datetime.now(timezone.utc).isoformat())
        save_report(report_path, report)
    return report


def main():
    """! @brief 계산 오류와 손실 안정성 미확립을 다른 종료 코드로 보존한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resume", action="store_true")
    group.add_argument("--reassess-only", action="store_true")
    group.add_argument("--continue-independent", action="store_true")
    args = parser.parse_args()
    try:
        report = run(args.workspace, args.report, args.manifest, args.catalog, resume=args.resume, reassess_only=args.reassess_only, continue_independent=args.continue_independent)
        print(json.dumps({"status": report["status"], "loss_stability": report["assessment"]["status"]}))
        return 0 if report["assessment"]["status"] == "passed" else 1
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
