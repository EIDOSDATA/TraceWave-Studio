"""! @brief 유한 원호/IFA 후보의 실제 계산과 원본 보존을 재현 가능한 기록으로 남긴다.

@details 명시 개발 시험이며 SMA 설치 사례, 문헌 재현 또는 실측 합격을 주장하지 않는다.
실행 전에 후보 수/예산/선택 규칙을 기록하고 실패 후보를 자동 재시도하지 않는다.
"""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catalog_pcb_verification.common import call, require, publish_report, VerificationError
from rfad.application.design_sweep_store import load_candidate, read_json
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from tuning_workflow_cases import CASES, CODE, FREQUENCIES, create_case


def document(service, context):
    """! @brief 검증 대조용 원본을 읽고 모든 변경은 공개 RPC로 수행한다."""
    return service._load(service.journal.read()["projects"][context["project_id"]])


def run_study(service, context, specification, *, timeout=2420, keep_incomplete=False):
    """! @brief 검토한 연구를 한 번 시작하며 종료/취소 확인을 구분한다."""
    inputs = {"expected_revision": document(service, context)["revision_id"], "specification": specification}
    preview = call(service, "sweep.preview", inputs, context)
    require(preview["can_create"] and preview["counts"]["invalid"] == 0 and preview["counts"]["unsupported"] == 0,
            "사전 입력 검사를 통과한 후보만 실행합니다.")
    study_id = call(service, "sweep.create", {**inputs, "review_hash": preview["review_hash"]}, context, mutation=True)["study_id"]
    call(service, "sweep.start", {"study_id": study_id}, context, mutation=True)
    deadline = time.monotonic() + timeout
    while True:
        state = call(service, "sweep.get", {"study_id": study_id}, context)
        if state["state"] not in {"running", "resuming", "cancel_requested"}:
            if not keep_incomplete:
                require(state["state"] == "completed", "연구가 완료되지 않았습니다: " + json.dumps(state, ensure_ascii=False))
            break
        if time.monotonic() >= deadline:
            cancellation = call(service, "sweep.cancel", {"study_id": study_id}, context, mutation=True)
            raise VerificationError("연구 대기 상한 도달. 취소 접수는 실제 종료 확인과 다릅니다.", cancellation)
        time.sleep(0.5)
    return {"study_id": study_id, "preview": preview, "view": state,
            "stored": service.journal.read()["sweeps"][study_id]}


def candidate_results(service, context, study):
    """! @brief 실제 표본 및 당시 평가를 보존하고 사전에 정한 최악 S11 기준으로 정렬한다."""
    rows = []
    for index in range(study["stored"]["counts"]["total"]):
        saved = load_candidate(service, study["stored"], index)
        row = {"index": index, "candidate": saved, "eligible": False}
        if saved is not None and saved.get("state") == "completed" and "dataset" in saved.get("results", {}):
            result = call(service, "sweep.result", {"study_id": study["study_id"], "index": index,
                "offset": 0, "limit": 201, "row": 0, "column": 0}, context)
            points = result["page"]["samples"]
            require([p["frequency_hz"] for p in points] == FREQUENCIES, "대역 양끝을 포함한 명시 51개 표본이 다릅니다.")
            require(result["descriptor"]["conditions"]["manufacturing"] is None and
                    result["descriptor"]["conditions"]["measurement"] is None, "실제 제작/측정 조건이 채워졌습니다.")
            assessment = read_json(service, saved["results"]["assessment"])
            require(not assessment["physics_validated"] and not assessment["continuous_band_verified"], "유한 표본을 연속 대역/실측 검증으로 확대했습니다.")
            valid = all(p["valid"] and p["magnitude_db_state"] in {"finite", "negative_infinity"} for p in points)
            #! -무한대는 최악값을 고를 때만 제외한다. 전 표본이 0반사이면 별도 상태를 보존한다.
            finite = [p["magnitude_db"] for p in points if p["magnitude_db_state"] == "finite"]
            worst = max(finite) if finite else None
            row.update(result=result, assessment=assessment, eligible=valid,
                       worst_s11_db=worst, all_zero_reflection=valid and not finite,
                       explicit_samples_meet_s11=valid and (worst is None or worst <= -10))
        rows.append(row)
    eligible = [row for row in rows if row["eligible"]]
    selected = min(eligible, key=lambda row: (float("-inf") if row["all_zero_reflection"] else row["worst_s11_db"], row["index"])) if eligible else None
    return rows, None if selected is None else selected["index"]


def run(destination):
    """! @brief 신규 검증 경로에 실행 전 계획과 성공/실패 근거를 따로 남긴다."""
    destination = destination.resolve()
    require(destination.is_relative_to((CODE / ".local").resolve()) and not destination.exists(), "Code/.local 아래의 새 검증 경로가 필요합니다.")
    destination.mkdir(parents=True)
    runtime = SolverRuntime()
    started = time.monotonic()
    plan = {"schema": "rfad.verification.tuning-workflow-plan/0.1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "finite_software_workflow_with_explicit_test_geometry_and_ideal_gap",
        "runtime_identity": runtime.identity, "cases": list(CASES), "frequency_hz": FREQUENCIES,
        "initial_native_solve_limit": 6, "copy_recheck_solve_limit": 2, "automatic_failed_retry": False,
        "wall_seconds_each_study": 2400, "global_solve_limit": 8, "candidate_concurrency": 1,
        "selection_rule": "minimum worst S11 over the exact 51 valid samples; lowest ordinal breaks ties; all failures remain failures",
        "selection_does_not_imply_acceptance": True, "s11_limit_db": -10,
        "manufacturing": None, "measurement": None, "sma_model": None, "measurement_reference_plane": None,
        "installed_environment_em": None, "physics_validated": False, "continuous_band_verified": False,
        "fixture_sha256": sha256((CODE / "fixtures/ifa_feed_smoke.json").read_bytes()).hexdigest(),
        "tool_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), CODE / "tools/tuning_workflow_cases.py")}}
    publish_report(destination / "plan.json", plan)
    report = {"schema": "rfad.verification.tuning-workflow/0.1", "status": "running", "plan": plan,
              "workspace": str(destination / "workspace"), "cases": []}
    try:
        with ProjectService(destination / "workspace", solver_runtime=runtime) as service:
            for kind in CASES:
                case = create_case(service, kind)
                row = {"case": case}
                report["cases"].append(row)
                publish_report(destination / "report.json", report)
                print(kind + ": running three fixed candidates", flush=True)
                study = run_study(service, case["context"], case["specification"])
                results, selected = candidate_results(service, case["context"], study)
                require(all(item["eligible"] for item in results), "고정 후보 중 유효 복소 결과가 없는 항목이 있습니다. 실패를 합격으로 집계하지 않습니다.")
                require(document(service, case["context"]) == case["document"], "연구 중 원본이 변경되었습니다.")
                row.update(study=study, results=results, selected_index=selected, source_unchanged=True)
                publish_report(destination / "report.json", report)
                print(kind + ": completed; selected editing candidate=" + str(selected), flush=True)
            require(sum(row["study"]["stored"]["usage"]["native_solves"] for row in report["cases"]) <= 6, "사전 고정한 실제 계산 상한을 초과했습니다.")
        with ProjectService(destination / "workspace", auto_run=False) as reopened:
            for row in report["cases"]:
                case = row["case"]
                require(document(reopened, case["context"]) == case["document"], "재열기 뒤 원본이 다릅니다.")
                results, selected = candidate_results(reopened, case["context"], row["study"])
                require(results == row["results"] and selected == row["selected_index"], "runtime 없는 재열기 결과가 다릅니다.")
        report.update(status="passed", runtime_free_reopen=True, physics_validated=False, continuous_band_verified=False)
    except Exception as error:
        report.update(status="failed", error={"type": type(error).__name__, "message": str(error), "details": getattr(error, "details", None)})
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        publish_report(destination / "report.json", report)
    print(json.dumps({"status": report["status"], "seconds": report["elapsed_seconds"], "report": str(destination / "report.json")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="명시 원호/IFA 유한 후보 실제 계산 검증")
    parser.add_argument("--destination", type=Path, required=True)
    run(parser.parse_args().destination)
