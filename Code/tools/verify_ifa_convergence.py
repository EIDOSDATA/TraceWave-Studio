"""! @brief 같은 불변 IFA 입력의 격자/경계/종료 조건을 공개 API로 비교한다.

@details 결과의 실행 성공과 수치 안정성, 실측 정확도를 별도 상태로 보존한다.
완료한 계산은 재사용하고 중단된 실행을 몰래 다시 제출하지 않는다.
"""

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "src"))

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.convergence import assess_study
from rfad.application.pcb_solver import PROFILE, validate_settings
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.application.solver import RUNTIME_PROFILE
from rfad.application.solver_jobs import SolverRuntime
from rfad.domain.project import validate_project
from rfad.catalog.service import CatalogService
from verify_openems_worker import call
from catalog_pcb_verification.common import wait
from verify_pcb_worker import create_fixture


def validate_study(study):
    """! @brief 명시적 한 변수 연구만 실행 전에 확장하고 제한한다."""
    expected = {"schema", "id", "description", "fixture", "acceptance_profile", "base_settings", "cases"}
    if type(study) is not dict or set(study) != expected or study["schema"] != "rfad.ifa-convergence-study/0.1":
        raise ValueError("수렴 연구 형식 또는 필드가 다릅니다.")
    if not isinstance(study["fixture"], str) or not study["fixture"]:
        raise ValueError("명시적 실행 fixture 경로가 필요합니다.")
    profile = study["acceptance_profile"]
    if (type(profile) is not dict or set(profile) != {"id", "minimum_levels", "max_resonance_relative_shift", "max_s11_complex_delta"}
            or type(profile["id"]) is not str or not profile["id"]
            or type(profile["minimum_levels"]) is not int or not 3 <= profile["minimum_levels"] <= 6):
        raise ValueError("명시적 연구 판정 profile과 최소 3수준이 필요합니다.")
    for key in ("max_resonance_relative_shift", "max_s11_complex_delta"):
        if type(profile[key]) not in (int, float) or not 0 < profile[key] < 1:
            raise ValueError("수렴 판정 한계는 0과 1 사이의 유한 값이어야 합니다.")
    validate_settings(study["base_settings"])
    if type(study["cases"]) is not list or not 8 <= len(study["cases"]) <= 18:
        raise ValueError("격자/경계 각 3수준과 시간 종료 2수준 이상의 사례가 필요합니다.")
    result, labels = [], set()
    allowed = {"mesh": "grid_mm", "boundary": "air_padding_mm", "termination": "end_criterion"}
    for case in study["cases"]:
        if (type(case) is not dict or set(case) != {"label", "axis", "overrides"}
                or type(case["label"]) is not str or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", case["label"]) is None
                or case["label"] in labels or case["axis"] not in allowed
                or type(case["overrides"]) is not dict or set(case["overrides"]) != {allowed[case["axis"]]}):
            raise ValueError("사례 이름은 고유해야 하며 지정한 한 설정만 바꿀 수 있습니다.")
        labels.add(case["label"])
        settings = {**deepcopy(study["base_settings"]), **deepcopy(case["overrides"])}
        validate_settings(settings)
        result.append({"label": case["label"], "axis": case["axis"], "settings": settings,
                       "settings_hash": canonical_hash(settings)})
    for axis, field in allowed.items():
        values = [case["settings"][field] for case in result if case["axis"] == axis]
        minimum = 2 if axis == "termination" else profile["minimum_levels"]
        if len(values) < minimum or any((b <= a if axis == "boundary" else b >= a) for a, b in zip(values, values[1:])):
            raise ValueError("격자는 감소, 경계 거리는 증가, 종료 에너지는 감소하는 독립 연구가 필요합니다.")
    mesh = [case for case in result if case["axis"] == "mesh"][-1]["settings"]
    boundary = [case for case in result if case["axis"] == "boundary"][-1]["settings"]
    termination = [case for case in result if case["axis"] == "termination"][0]["settings"]
    if mesh != boundary or mesh != termination:
        raise ValueError("세 연구는 가장 세밀한 격자/먼 경계의 동일 기준 계산에 연결되어야 합니다.")
    return result


def save_report(path, report):
    """! @brief 완료 자료를 보존하며 비교 보고서만 같은 폴더에서 원자 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    with temporary.open("xb") as stream:
        stream.write(canonical_bytes(report))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def validate_resume(report, workspace, study, fixture, identity=None):
    """! @brief 다른 입력/저장소/소스로 계산을 이어 붙이지 않는다."""
    if (report.get("schema") != "rfad.ifa-convergence-run/0.1" or report.get("workspace") != str(workspace.resolve())
            or report.get("study_hash") != canonical_hash(study) or report.get("fixture_hash") != canonical_hash(fixture)
            or report.get("study") != study or "subject" not in report):
        raise ValueError("연구 입력 또는 workspace가 다르거나 초기화가 완료되지 않았습니다.")
    if identity is not None and report.get("runtime_identity") != identity:
        raise ValueError("worker 소스/설치가 바뀌었습니다. 기존 연구를 보존하고 새 workspace에서 실행하십시오.")


def execute_phase(service, report, report_path, entry, phase, method, data, context):
    """! @brief 요청 키를 먼저 저장하여 응답 직후 중단에도 같은 작업을 재접수한다."""
    phases = entry.setdefault("phases", {})
    if phase not in phases:
        phases[phase] = {"request_key": str(uuid4()), "request_key_epoch": service.policy()["request_key_epoch"],
                         "method": method, "input": deepcopy(data)}
        save_report(report_path, report)
    record = phases[phase]
    if record["method"] != method or record["input"] != data:
        raise ValueError("저장한 단계의 입력이 현재 실행과 다릅니다.")
    if "task" not in record:
        params = {"contract_version": "rfad.api/2.0", "context": context, "input": data,
                  "request_key": record["request_key"], "request_key_epoch": record["request_key_epoch"]}
        response = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}), service)
        if "error" in response:
            raise RuntimeError(json.dumps(response["error"], ensure_ascii=False))
        record["task"] = response["result"]
        save_report(report_path, report)
    deadline = time.monotonic() + 420
    while time.monotonic() < deadline:
        status = call(service, "job.status", {"job_id": record["task"]["job_id"]})
        if status["state"] in {"completed", "failed", "cancelled", "interrupted"}:
            record["state"] = status["state"]
            record["states"] = [event["state"] for event in status["events"]]
            save_report(report_path, report)
            if status["state"] != "completed":
                raise RuntimeError("저장된 작업이 정상 완료되지 않았습니다. 자동 재실행하지 않습니다: " + json.dumps(status, ensure_ascii=False))
            return status["events"][-1]["operation_result"]
        time.sleep(0.2)
    raise RuntimeError("서비스 조회 제한 시간 초과입니다. 작업 상태를 보존했으며 새 작업으로 대체하지 않습니다.")


def load_cases(service, report, definitions):
    """! @brief 봉인된 결과를 다시 읽고 별도 비교의 입력으로만 사용한다."""
    cases = []
    for case in definitions:
        entry = report["runs"][case["settings_hash"]]
        if entry.get("status") != "completed":
            raise ValueError("완료하지 않은 연구 사례가 있습니다.")
        opened = call(service, "result.open", {"artifact_id": entry["artifact_id"]}, report["subject"]["context"])
        references = [{key: item[key] for key in ("uri", "sha256", "bytes")}
                      for item in opened["files"] if item["role"] == "normalized_result"]
        if opened["artifact_id"] != entry["artifact_id"] or references != [entry["normalized_result"]]:
            raise ValueError("진행표의 결과 참조가 서비스에 봉인된 artifact와 다릅니다.")
        result = json.loads(service.journal.read_artifact(entry["normalized_result"]))
        plan = result["provenance"]["analysis_plan"]
        if plan["runtime_identity"] != report["runtime_identity"]:
            raise ValueError("연구에서 캡처한 worker와 결과의 출처가 다릅니다.")
        if (plan["snapshot"] != report["subject"]["snapshot"] or plan["plan_id"] != entry["analysis_plan"]["plan_id"]
                or result["analysis_plan_id"] != plan["plan_id"] or canonical_hash(plan) != entry["analysis_plan"]["content_hash"]
                or plan["case"]["settings"] != case["settings"] or entry["settings"] != case["settings"]):
            raise ValueError("결과의 스냅샷/계획/수치 설정이 해당 연구 사례와 다릅니다.")
        cases.append({"label": case["label"], "axis": case["axis"], "settings": case["settings"],
                      "normalized_result": result, "artifact": {"artifact_id": entry["artifact_id"], **entry["normalized_result"]}})
    return cases


def write_samples(path, cases):
    """! @brief 보간 없이 직접 계산한 복소 표본과 정의되지 않은 값을 CSV로 보존한다."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case", "axis", "frequency_hz", "s11_real", "s11_imag", "s11_db", "z_real_ohm", "z_imag_ohm", "vswr"])
        for case in cases:
            for sample in case["normalized_result"]["samples"]:
                writer.writerow([case["label"], case["axis"], sample["frequency_hz"], *sample["s11"], sample["s11_db"],
                                 *sample["impedance_ohm"], sample["vswr"]])


def publish_assessment(report_path, report, cases, assessment):
    """! @brief 현재 진행표와 별도로 판정기/입력 근거를 가진 불변 재판정 기록을 만든다."""
    evaluator = []
    for path in (CODE_ROOT / "src/rfad/application/convergence.py", Path(__file__).resolve()):
        data = path.read_text(encoding="utf-8").encode("utf-8")
        evaluator.append({"path": path.relative_to(CODE_ROOT).as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    record = {"schema": "rfad.ifa-convergence-assessment/0.1", "created_at": datetime.now(timezone.utc).isoformat(),
              "study_hash": report["study_hash"], "fixture_hash": report["fixture_hash"], "evaluator": evaluator,
              "inputs": [{"label": case["label"], "axis": case["axis"], "artifact": case["artifact"]} for case in cases],
              "assessment": assessment}
    data = canonical_bytes(record)
    directory = report_path.with_name(report_path.stem + ".assessments")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (str(uuid4()) + ".json")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    reference = {"path": path.relative_to(report_path.parent).as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    report.setdefault("assessment_history", []).append(reference)
    report["assessment_artifact"] = reference


def run(workspace, report_path, study_path, *, resume=False, reassess_only=False, catalog_database=None):
    """! @brief 수렴 연구를 실행하고 원본 계산과 독립된 판정/근거를 게시한다."""
    study = json.loads(study_path.read_text(encoding="utf-8"))
    definitions = validate_study(study)
    fixture = json.loads((study_path.parent / study["fixture"]).read_text(encoding="utf-8"))
    if fixture.get("schema") != "rfad.pcb-runtime-fixture/0.1" or fixture.get("case_kind") != "ifa_feed":
        raise ValueError("명시적 IFA 실행 fixture가 필요합니다.")
    validate_project(fixture["document"])
    runtime = None if reassess_only else SolverRuntime()
    if resume or reassess_only:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_resume(report, workspace, study, fixture, None if runtime is None else runtime.identity)
    else:
        if report_path.exists() or workspace.exists():
            raise ValueError("새 workspace/report를 사용하거나 --resume으로 기존 연구를 확인하십시오.")
        report = {"schema": "rfad.ifa-convergence-run/0.1", "status": "initializing", "started_at": datetime.now(timezone.utc).isoformat(),
                  "workspace": str(workspace.resolve()), "study": study, "study_hash": canonical_hash(study), "fixture_hash": canonical_hash(fixture),
                  "runtime_identity": runtime.identity, "runs": {}, "physics_validated": False, "measurement_validated": False}
        save_report(report_path, report)
    started = time.monotonic()
    with ProjectService(workspace, solver_runtime=runtime, auto_run=not reassess_only, catalog_database=catalog_database) as service:
        if "subject" not in report:
            context, project_path, snapshot = create_fixture(service, fixture)
            if "catalog_selection" in fixture:
                spec = deepcopy(fixture["catalog_selection"])
                status = CatalogService(catalog_database).status()
                if not status.get("available"):
                    raise ValueError("출처를 보존할 명시적 카탈로그가 필요합니다.")
                spec["catalog_id"] = status["catalog_id"]
                data = {"expected_revision": snapshot["revision_id"], "selection_id": str(uuid4()), "specification": spec}
                preview = call(service, "pcb.selection.preview", data, context)
                if not preview["can_apply"]:
                    raise ValueError("연구의 출처 선택을 적용할 수 없습니다.")
                applied = call(service, "pcb.selection.apply", {**data, "preview_hash": preview["preview_hash"], "command_id": str(uuid4())}, context, mutation=True)
                snapshot, _ = wait(service, call(service, "snapshot.create", {"expected_revision": applied["new_revision"],
                                               "description": "출처 기반 탐색 수렴 연구"}, context, mutation=True))
            report["subject"] = {"context": context, "project_path": project_path, "snapshot": snapshot}
            report["status"] = "running"
            save_report(report_path, report)
        subject = report["subject"]
        if not reassess_only:
            try:
                for case in definitions:
                    entry = report["runs"].setdefault(case["settings_hash"], {"settings": case["settings"], "status": "pending"})
                    if entry["settings"] != case["settings"]:
                        raise ValueError("저장된 실행의 수치 설정이 다릅니다.")
                    snapshot = subject["snapshot"]
                    planned = execute_phase(service, report, report_path, entry, "plan", "solver.plan", {
                        "snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
                        "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE, "settings": case["settings"],
                    }, subject["context"])
                    entry["analysis_plan"] = planned["analysis_plan"]
                    entry["resource_estimate"] = planned["resource_estimate"]
                    plan = json.loads(service.journal.read_artifact(planned["analysis_plan"]["artifact"]))
                    entry["mesh_policy_report"] = plan["case"].get("mesh_policy_report")
                    save_report(report_path, report)
                report["all_plans_validated_before_execution"] = True
                save_report(report_path, report)
            except Exception as error:
                report.update(status="incomplete", error=str(error))
                save_report(report_path, report)
                raise
            for case in definitions:
                entry = report["runs"].setdefault(case["settings_hash"], {"settings": case["settings"], "status": "pending"})
                if entry["settings"] != case["settings"]:
                    raise ValueError("저장된 실행의 수치 설정이 다릅니다.")
                if entry["status"] == "completed":
                    continue
                print(json.dumps({"case": case["label"], "status": "starting", "settings": case["settings"]}, ensure_ascii=False), flush=True)
                tick = time.monotonic()
                try:
                    prepared = execute_phase(service, report, report_path, entry, "prepare", "solver.prepare", {
                        "analysis_plan": {key: entry["analysis_plan"][key] for key in ("plan_id", "content_hash")},
                        "budget": {"timeout_seconds": 300},
                    }, subject["context"])
                    solved = execute_phase(service, report, report_path, entry, "analysis", "job.submit", {
                        "task_plan": {"kind": "em_analysis", "prepared_plan": {key: prepared["prepared_plan"][key] for key in ("prepared_plan_id", "content_hash")},
                                      "execution_mode": "solve_and_postprocess"}, "budget": {"timeout_seconds": 300},
                    }, subject["context"])
                    entry.update(status="completed", artifact_id=solved["artifact_id"], normalized_result=solved["normalized_result"],
                                 elapsed_seconds=time.monotonic() - tick)
                    save_report(report_path, report)
                    print(json.dumps({"case": case["label"], "status": "completed", "elapsed_seconds": entry["elapsed_seconds"]}), flush=True)
                except Exception as error:
                    entry.update(status="failed_or_interrupted", error=str(error))
                    report.update(status="incomplete", error=str(error))
                    save_report(report_path, report)
                    raise
        cases = load_cases(service, report, definitions)
        report["assessment"] = assess_study(cases, study["acceptance_profile"])
        publish_assessment(report_path, report, cases, report["assessment"])
        csv_path = report_path.with_suffix(".samples.csv")
        write_samples(csv_path, cases)
        csv_bytes = csv_path.read_bytes()
        report["samples_csv_artifact"] = {"path": csv_path.name, "bytes": len(csv_bytes), "sha256": hashlib.sha256(csv_bytes).hexdigest()}
        report.update(status="completed", completed_at=datetime.now(timezone.utc).isoformat(),
                      last_invocation_seconds=time.monotonic() - started, samples_csv=str(csv_path.resolve()),
                      cases=[{key: value for key, value in case.items() if key != "normalized_result"} for case in cases])
        save_report(report_path, report)
    print(json.dumps({"status": report["status"], "report": str(report_path.resolve()),
                      "numerical_stability": report["assessment"]["numerical_stability"]["status"],
                      "axes": {axis: data["status"] for axis, data in report["assessment"]["numerical_stability"]["axes"].items()}}, ensure_ascii=False), flush=True)
    return report


def main():
    """! @brief 판정 미확립은 계산 실패와 다른 종료 코드로 전달한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--study", type=Path, default=CODE_ROOT / "fixtures/ifa_convergence_study.json")
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
