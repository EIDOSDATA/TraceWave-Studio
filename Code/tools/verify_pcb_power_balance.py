"""! @brief 같은 탐색 PCB의 독립 손실 적분/전체 전력 수지를 공개 API로 실행하고 재조회한다."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import sys
import time

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "src"))

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import PROFILE, validate_pcb_plan
from rfad.application.pcb_power import validate_result
from rfad.application.pcb_radiation import raw_names
from rfad.application.projects import ProjectService
from rfad.application.solver import RUNTIME_PROFILE
from rfad.application.solver_runtime import SolverRuntime
from rfad.application.radiation_study import require
from verify_pcb_radiation_convergence import create_subject
from verify_openems_worker import call
from verify_ifa_convergence import execute_phase, save_report
from radiation_convergence.evidence import reference


def load_result(service, entry, subject):
    """! @brief 등록된 모든 원시 필드와 결과의 봉인을 읽고 독립 분할/잔차를 재계산한다."""
    opened = call(service, "result.open", {"artifact_id": entry["artifact_id"]}, subject["context"])
    roles = {item["role"]: item for item in opened["files"]}
    require(opened["artifact_id"] == entry["artifact_id"] and len(roles) == len(opened["files"]), "전력 결과의 식별자 또는 파일 역할이 중복되었습니다.")
    for item in opened["files"]:
        service.journal.verify_file(reference(item))
    normalized = json.loads(service.journal.read_artifact(entry["normalized_result"]))
    plan = normalized["provenance"]["analysis_plan"]
    validate_pcb_plan(plan)
    require(plan == json.loads(service.journal.read_artifact(entry["analysis_plan"]["artifact"])), "전력 수지 결과가 원래 계획과 다릅니다.")
    require(plan["snapshot"] == subject["snapshot"], "전력 수지의 원본 snapshot이 다릅니다.")
    require(plan["plan_id"] == entry["analysis_plan"]["plan_id"] and canonical_hash(plan) == entry["analysis_plan"]["content_hash"]
            and plan["case"]["settings"] == entry["settings"], "진행표의 계획/설정이 결과와 다릅니다.")
    raw_roles = {"raw/" + name for name in raw_names(plan)}
    require(set(roles) == raw_roles | {"raw_manifest", "normalized_result", "provenance", "radiation_result", "radiation_native", "power_balance_result"}, "독립 전력 수지의 필수 산출물이 다릅니다.")
    raw = normalized["raw_manifest"]
    require(raw == json.loads(service.journal.read_artifact(reference(roles["raw_manifest"])))
            and len(raw["files"]) == len(raw_roles) and {item["role"] for item in raw["files"]} == raw_roles, "원시 manifest와 원시 파일 계약이 다릅니다.")
    for item in raw["files"]:
        require(all(item[name] == roles[item["role"]][name] for name in ("bytes", "sha256")), "원시 손실 필드의 봉인이 manifest와 다릅니다.")
    for role in ("normalized_result", "radiation_result", "power_balance_result"):
        require(reference(roles[role]) == entry[role], "전력 수지의 봉인 참조가 바뀌었습니다.")
    radiation = json.loads(service.journal.read_artifact(entry["radiation_result"]))
    power = json.loads(service.journal.read_artifact(entry["power_balance_result"]))
    validate_result(plan, power, radiation)
    require(normalized["power_balance"] == power, "정규화 결과와 별도 독립 손실 산출물이 다릅니다.")
    return power


def run(workspace, report_path, manifest_path, catalog=None, *, resume=False, reassess_only=False):
    """! @brief 사전 기준을 보존하고 완료 결과를 재실행하지 않으며 오류는 자동 대체하지 않는다."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "rfad.pcb-power-study/0.1", "독립 전력 연구 manifest가 필요합니다.")
    levels = manifest.get("grid_levels_mm")
    require(type(levels) is list and 3 <= len(levels) <= 6 and all(type(value) in (int, float) and 0.05 <= value <= 5 for value in levels)
            and all(a > b for a, b in zip(levels, levels[1:])), "독립 전력 연구에는 3~6개 감소하는 격자 수준이 필요합니다.")
    fixture = json.loads((manifest_path.parent / manifest["fixture"]).read_text(encoding="utf-8"))
    runtime = None if reassess_only else SolverRuntime()
    if resume or reassess_only:
        report = json.loads(report_path.read_bytes())
        require(report["manifest"] == manifest and report["fixture_hash"] == canonical_hash(fixture)
                and report["workspace"] == str(workspace.resolve()), "기존 전력 연구의 입력/경로가 다릅니다.")
        require(runtime is None or runtime.identity == report["runtime_identity"], "기존 전력 연구의 worker가 바뀌었습니다. 새 경로를 사용하십시오.")
    else:
        require(not workspace.exists() and not report_path.exists(), "기존 전력 연구를 덮어쓸 수 없습니다.")
        report = {"schema": "rfad.pcb-power-study-run/0.1", "manifest": manifest, "fixture_hash": canonical_hash(fixture),
                  "workspace": str(workspace.resolve()), "runtime_identity": runtime.identity,
                  "started_at": datetime.now(timezone.utc).isoformat(), "status": "initializing", "runs": {},
                  "physics_validated": False, "fabrication_validated": False, "measurement_validated": False}
        save_report(report_path, report)
    with ProjectService(workspace, solver_runtime=runtime, auto_run=not reassess_only, catalog_database=catalog) as service:
        if "subject" not in report:
            report["subject"] = create_subject(service, fixture, catalog)
            save_report(report_path, report)
        subject = report["subject"]
        # @brief 모든 실제 계획을 첫 해석 전에 확정한다.
        for grid in manifest["grid_levels_mm"]:
            key = str(grid)
            settings = deepcopy(manifest["settings"])
            settings["grid_mm"] = grid
            entry = report["runs"].setdefault(key, {"settings": settings, "status": "pending"})
            require(entry["settings"] == settings, "진행표의 해석 설정이 다릅니다.")
            if not reassess_only:
                planned = execute_phase(service, report, report_path, entry, "plan", "solver.plan", {
                    "snapshot": {name: subject["snapshot"][name] for name in ("snapshot_id", "content_hash")},
                    "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE, "settings": settings}, subject["context"])
                entry["analysis_plan"] = planned["analysis_plan"]
                save_report(report_path, report)
        require(set(report["runs"]) == {str(grid) for grid in levels}, "진행표의 격자 사례 목록이 다릅니다.")
        for grid in levels:
            key = str(grid)
            entry = report["runs"][key]
            if entry["status"] != "completed":
                require(not reassess_only, "미완료 native 실행은 재판정만으로 완료할 수 없습니다.")
                print(json.dumps({"grid_mm": key, "status": "starting"}), flush=True)
                started = time.monotonic()
                prepared = execute_phase(service, report, report_path, entry, "prepare", "solver.prepare", {
                    "analysis_plan": {name: entry["analysis_plan"][name] for name in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 300}}, subject["context"])
                solved = execute_phase(service, report, report_path, entry, "analysis", "job.submit", {
                    "task_plan": {"kind": "em_analysis", "prepared_plan": {name: prepared["prepared_plan"][name] for name in ("prepared_plan_id", "content_hash")}, "execution_mode": "solve_and_postprocess"},
                    "budget": {"timeout_seconds": 300}}, subject["context"])
                opened = call(service, "result.open", {"artifact_id": solved["artifact_id"]}, subject["context"])
                roles = {item["role"]: item for item in opened["files"]}
                entry.update(status="completed", artifact_id=solved["artifact_id"], elapsed_seconds=time.monotonic() - started,
                             **{role: reference(roles[role]) for role in ("normalized_result", "radiation_result", "power_balance_result")})
                save_report(report_path, report)
            entry["power_balance"] = load_result(service, entry, subject)
            normalized = json.loads(service.journal.read_artifact(entry["normalized_result"]))
            require(normalized["provenance"]["analysis_plan"]["runtime_identity"] == report["runtime_identity"], "전력 연구의 계산 소스/설치 출처가 바뀌었습니다.")
            print(json.dumps({"grid_mm": key, "status": entry["power_balance"]["full_energy_closure"],
                              "residuals": [row["relative_residual"] for row in entry["power_balance"]["frequencies"]]}), flush=True)
            save_report(report_path, report)
        report["status"] = "completed"
        report["full_energy_closure"] = "within_initial_numerical_budget" if all(entry["power_balance"]["full_energy_closure"] == "within_initial_numerical_budget" for entry in report["runs"].values()) else "requires_review"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        ordered_entries = [(str(grid), report["runs"][str(grid)]) for grid in levels]
        assessment = {"schema": "rfad.pcb-power-assessment/0.1", "manifest_hash": canonical_hash(manifest),
                      "fixture_hash": report["fixture_hash"], "full_energy_closure": report["full_energy_closure"],
                      "sources": [{"path": path.relative_to(CODE_ROOT).as_posix(), "text": path.read_text(encoding="utf-8"),
                                   "sha256": hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()} for path in
                                  [Path(__file__).resolve(), CODE_ROOT / "src/rfad/application/pcb_power.py"]],
                      "cases": [{"grid_mm": key, "artifact_id": entry["artifact_id"], "normalized_result": entry["normalized_result"],
                                 "power_balance_result": entry["power_balance_result"], "power_balance": entry["power_balance"]}
                                for key, entry in ordered_entries],
                      "physics_validated": False, "fabrication_validated": False, "measurement_validated": False}
        assessment_path = report_path.parent / (report_path.stem + ".assessments") / (canonical_hash(assessment) + ".json")
        assessment_path.parent.mkdir(parents=True, exist_ok=True)
        if assessment_path.exists():
            require(json.loads(assessment_path.read_bytes()) == assessment, "불변 전력 판정 파일의 내용이 바뀌었습니다.")
        else:
            with assessment_path.open("x", encoding="utf-8") as stream:
                json.dump(assessment, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        report["assessment_artifact"] = {"path": str(assessment_path.relative_to(report_path.parent)),
                                         "sha256": hashlib.sha256(assessment_path.read_bytes()).hexdigest()}
        csv_path = report_path.with_suffix(".power.csv")
        fields = ["grid_mm", "frequency_hz", "incident_power_w_s2", "reflected_power_w_s2", "accepted_power_w_s2", "radiated_power_w_s2",
                  "dielectric_loss_w_s2", "conductor_loss_w_s2", "independent_absorption_power_w_s2", "residual_w_s2", "relative_residual", "status"]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for key, entry in ordered_entries:
                writer.writerows({"grid_mm": key, **row} for row in entry["power_balance"]["frequencies"])
        report["csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        save_report(report_path, report)
    return report


def main():
    """! @brief 계산 완료/초기 잔차 미충족/입력 오류를 별도 종료 코드로 반환한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=CODE_ROOT / "fixtures/pcb_power_balance_study.json")
    parser.add_argument("--catalog", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resume", action="store_true")
    group.add_argument("--reassess-only", action="store_true")
    args = parser.parse_args()
    try:
        report = run(args.workspace, args.report, args.manifest, args.catalog, resume=args.resume, reassess_only=args.reassess_only)
        print(json.dumps({"status": report["status"], "full_energy_closure": report["full_energy_closure"]}))
        return 0 if report["full_energy_closure"] == "within_initial_numerical_budget" else 1
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
