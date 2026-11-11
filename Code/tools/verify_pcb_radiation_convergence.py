"""! @brief 동일 사용자 PCB의 기록 상자/각도/격자 방사 연구를 공개 API로 수행한다."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "src"))

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import PROFILE, validate_pcb_plan
from rfad.application.projects import ProjectService
from rfad.application.solver import RUNTIME_PROFILE
from rfad.application.solver_runtime import SolverRuntime
from rfad.application.radiation_study import AXES, require, validate_study
from rfad.application.radiation_study_guards import plan_guards
from rfad.application.radiation_assessment import assess_study
from rfad.catalog.service import CatalogService
from rfad.domain.project import validate_project
from verify_openems_worker import call
from verify_pcb_worker import create_fixture
from verify_ifa_convergence import execute_phase, save_report
from catalog_pcb_verification.common import wait
from radiation_convergence.evidence import load_cases, publish_assessment, reference, write_metrics


def create_subject(service, fixture, catalog):
    """! @brief 사용자가 이미 허용한 별도 탐색 근사를 출처와 미정 원본을 보존해 적용한다."""
    context, project_path, snapshot = create_fixture(service, fixture)
    if "catalog_selection" in fixture:
        require(catalog is not None, "출처 기반 연구에는 --catalog로 기존 카탈로그를 지정하십시오.")
        status = CatalogService(catalog).status()
        require(status.get("available") is True, "연구 출처의 카탈로그가 준비되지 않았습니다.")
        specification = deepcopy(fixture["catalog_selection"])
        specification["catalog_id"] = status["catalog_id"]
        data = {"expected_revision": snapshot["revision_id"], "selection_id": str(uuid4()), "specification": specification}
        preview = call(service, "pcb.selection.preview", data, context)
        require(preview["can_apply"] is True, "명시한 탐색 모델을 출처와 함께 적용할 수 없습니다.")
        applied = call(service, "pcb.selection.apply", {**data, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())}, context, mutation=True)
        wait(service, call(service, "project.save", {"expected_revision": applied["new_revision"]}, context, mutation=True))
        snapshot, _ = wait(service, call(service, "snapshot.create", {"expected_revision": applied["new_revision"], "description": "명시적 탐색 물성의 방사 수렴 연구; 제작 및 실측 미검증"}, context, mutation=True))
    return {"context": context, "project_path": project_path, "snapshot": snapshot}


def validate_resume(report, workspace, study, fixture, identity=None):
    """! @brief 다른 원본/판정 조건/계산 소스를 완료 연구에 이어 붙이지 않는다."""
    require(report.get("schema") == "rfad.pcb-radiation-study-run/0.1" and report.get("workspace") == str(workspace.resolve()), "방사 연구 형식 또는 workspace가 다릅니다.")
    require(report.get("study") == study and report.get("study_hash") == canonical_hash(study) and report.get("fixture_hash") == canonical_hash(fixture) and "subject" in report,
            "원래 연구 입력 또는 초기화가 완료되지 않은 연구입니다.")
    require(identity is None or report["runtime_identity"] == identity, "worker/설치가 바뀌었습니다. 기존 자료는 보존하고 새 연구를 시작하십시오.")


def preflight(service, report, path, definitions):
    """! @brief 첫 native 실행 전에 모든 실제 격자/기록 면의 독립성을 확인한다."""
    plans = {}
    subject = report["subject"]
    for case in definitions:
        entry = report["runs"].setdefault(case["settings_hash"], {"status": "pending", "settings": case["settings"]})
        require(entry["settings"] == case["settings"], "진행표의 설정이 바뀌었습니다.")
        planned = execute_phase(service, report, path, entry, "plan", "solver.plan", {
            "snapshot": {key: subject["snapshot"][key] for key in ("snapshot_id", "content_hash")},
            "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE, "settings": case["settings"]}, subject["context"])
        entry["analysis_plan"] = planned["analysis_plan"]
        entry["resource_estimate"] = planned["resource_estimate"]
        plan = json.loads(service.journal.read_artifact(planned["analysis_plan"]["artifact"]))
        validate_pcb_plan(plan)
        entry["recording"] = plan["case"]["radiation_recording"]
        plans[case["label"]] = plan
        save_report(path, report)
    guards = []
    for axis in AXES:
        rows = [row for row in definitions if row["axis"] == axis]
        for first, second in zip(rows, rows[1:]):
            guards.append({"axis": axis, "left": first["label"], "right": second["label"], **plan_guards(plans[first["label"]], plans[second["label"]], axis)})
    report["preflight_guards"] = guards
    report["all_plans_validated_before_execution"] = True
    save_report(path, report)


def execute_cases(service, report, path, definitions):
    """! @brief 동일 설정의 기준 사례를 공유하고 실패 작업을 새 실행으로 몰래 대체하지 않는다."""
    context = report["subject"]["context"]
    for case in definitions:
        entry = report["runs"][case["settings_hash"]]
        if entry["status"] == "completed":
            continue
        started = time.monotonic()
        print(json.dumps({"case": case["label"], "status": "starting"}), flush=True)
        prepared = execute_phase(service, report, path, entry, "prepare", "solver.prepare", {
            "analysis_plan": {key: entry["analysis_plan"][key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 300}}, context)
        solved = execute_phase(service, report, path, entry, "analysis", "job.submit", {
            "task_plan": {"kind": "em_analysis", "prepared_plan": {key: prepared["prepared_plan"][key] for key in ("prepared_plan_id", "content_hash")},
                          "execution_mode": "solve_and_postprocess"}, "budget": {"timeout_seconds": 300}}, context)
        opened = call(service, "result.open", {"artifact_id": solved["artifact_id"]}, context)
        field = next(item for item in opened["files"] if item["role"] == "radiation_result")
        entry.update(status="completed", artifact_id=solved["artifact_id"], normalized_result=solved["normalized_result"],
                     radiation_result=reference(field), elapsed_seconds=time.monotonic() - started)
        save_report(path, report)
        print(json.dumps({"case": case["label"], "status": "completed", "elapsed_seconds": entry["elapsed_seconds"]}), flush=True)


def run(workspace, report_path, study_path, *, resume=False, reassess_only=False, catalog_database=None):
    """! @brief 원본과 이전 판정을 보존하며 계산, 수치 수렴과 실물 검증을 분리한다."""
    study = json.loads(study_path.read_text(encoding="utf-8"))
    definitions = validate_study(study)
    fixture = json.loads((study_path.parent / study["fixture"]).read_text(encoding="utf-8"))
    require(fixture.get("schema") == "rfad.pcb-runtime-fixture/0.1", "명시적 PCB 실행 fixture가 필요합니다.")
    validate_project(fixture["document"])
    runtime = None if reassess_only else SolverRuntime()
    if resume or reassess_only:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_resume(report, workspace, study, fixture, None if runtime is None else runtime.identity)
    else:
        require(not report_path.exists() and not workspace.exists(), "기존 연구를 덮어쓸 수 없습니다. 새 경로나 --resume을 사용하십시오.")
        report = {"schema": "rfad.pcb-radiation-study-run/0.1", "status": "initializing", "started_at": datetime.now(timezone.utc).isoformat(),
                  "workspace": str(workspace.resolve()), "study": study, "study_hash": canonical_hash(study), "fixture_hash": canonical_hash(fixture),
                  "runtime_identity": runtime.identity, "runs": {}, "physics_validated": False, "measurement_validated": False, "fabrication_validated": False}
        save_report(report_path, report)
    started = time.monotonic()
    try:
        with ProjectService(workspace, solver_runtime=runtime, auto_run=not reassess_only, catalog_database=catalog_database) as service:
            if "subject" not in report:
                report["subject"] = create_subject(service, fixture, catalog_database)
                report["status"] = "running"
                save_report(report_path, report)
            if not reassess_only:
                preflight(service, report, report_path, definitions)
                execute_cases(service, report, report_path, definitions)
            cases = load_cases(service, report, definitions)
            report["assessment"] = assess_study(cases, study["acceptance_profile"])
            publish_assessment(report_path, report, cases, report["assessment"])
            csv_path = report_path.with_suffix(".power.csv")
            write_metrics(csv_path, report["assessment"])
            raw = csv_path.read_bytes()
            report["power_csv_artifact"] = {"path": csv_path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            report.update(status="completed", completed_at=datetime.now(timezone.utc).isoformat(), last_invocation_seconds=time.monotonic() - started,
                          cases=[{key: value for key, value in row.items() if key not in {"normalized_result", "radiation_result"}} for row in cases])
            report.pop("error", None)
            save_report(report_path, report)
    except Exception as error:
        report.update(status="incomplete", error=str(error))
        save_report(report_path, report)
        raise
    print(json.dumps({"status": report["status"], "numerical_stability": report["assessment"]["numerical_stability"]["status"],
                      "axes": {key: value["status"] for key, value in report["assessment"]["numerical_stability"]["axes"].items()},
                      "report": str(report_path.resolve())}), flush=True)
    return report


def main():
    """! @brief 계산 실패는 2, 완료한 수치 미확립은 1로 구분한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--study", type=Path, default=CODE_ROOT / "fixtures/pcb_radiation_convergence_study.json")
    parser.add_argument("--catalog", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resume", action="store_true")
    group.add_argument("--reassess-only", action="store_true")
    args = parser.parse_args()
    try:
        report = run(args.workspace, args.report, args.study, resume=args.resume, reassess_only=args.reassess_only, catalog_database=args.catalog)
        return 0 if report["assessment"]["numerical_stability"]["status"] == "established" else 1
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
