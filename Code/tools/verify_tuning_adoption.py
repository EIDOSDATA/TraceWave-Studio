"""! @brief 실제 계산 후보를 새 프로젝트로 채택하고 단일 undo/redo와 재계산을 대조한다."""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catalog_pcb_verification.common import call, wait, require, publish_report
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.application.solver_runtime import SolverRuntime
from rfad.domain.sweep_selection import KEY
from tuning_workflow_cases import CODE
from verify_tuning_workflow import document, run_study, candidate_results


def files(folder):
    """! @brief 원본 프로젝트 폴더의 바이트를 읽기만 하여 이후 추가/변경까지 검출한다."""
    return {p.relative_to(folder).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def adopt(service, row):
    """! @brief 검토한 봉인 후보만 새 경로에 채택하고 영수증 재전송의 멱등성을 검사한다."""
    case, index = row["case"], row["selected_index"]
    require(index is not None, "유효 복소 결과가 없는 사례는 채택하지 않습니다.")
    context = case["context"]
    selected = row["results"][index]
    offered = call(service, "sweep.selection.context", {"study_id": row["study"]["study_id"], "index": index}, context)
    require(offered["eligibility"]["can_select"], "후보 채택 지원 범위 밖입니다: " + json.dumps(offered["eligibility"], ensure_ascii=False))
    inputs = {key: offered[key] for key in ("study_id", "index", "definition_hash", "source_pin")}
    inputs.update(expected_revision=offered["revision_id"], name=case["document"]["metadata"]["name"] + " / 채택 사본",
                  path="projects/" + case["kind"] + "-selected-copy",
                  reason="정확 51개 계산 표본의 최악 S11 최소 후보를 편집용으로 선택. "
                         + ("해당 S11 표본 기준 충족." if selected["explicit_samples_meet_s11"] else "S11 목표 미달을 보존하며 성능 합격으로 채택하지 않음.")
                         + " 연속 대역/제작/측정/설치 검증은 미확립.")
    preview = call(service, "sweep.selection.preview", inputs, context)
    require(preview["can_apply"], "사본 검토 실패: " + json.dumps(preview.get("issues"), ensure_ascii=False))
    request = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "sweep.selection.apply",
        "params": {"contract_version": "rfad.api/2.0", "context": context,
            "input": {**inputs, "review_hash": preview["review_hash"], "command_id": str(uuid4())},
            "request_key": str(uuid4()), "request_key_epoch": service.policy()["request_key_epoch"]}}
    first = handle_frame(canonical_bytes(request), service)
    require("error" not in first, "사본 적용 실패: " + json.dumps(first, ensure_ascii=False))
    second = handle_frame(canonical_bytes(request), service)
    require(second == first, "같은 생성 요청의 영수증 응답이 달라졌습니다.")
    response = first["result"]
    receipt = call(service, "sweep.selection.receipt", {key: request["params"][key] for key in
                   ("request_key", "request_key_epoch")}, context)
    require(receipt["status"] == "found" and receipt["response"] == response, "재조회한 생성 결과가 다릅니다.")
    copied_context = {"project_id": response["new_project_id"]}
    copied = document(service, copied_context)
    require(copied_context != context and document(service, context) == case["document"], "사본 생성이 원본을 바꾸었습니다.")
    for key in ("geometry", "materials", "ports", "targets", "stackup"):
        require(copied[key] == case["document"][key], "사본의 보존 필드가 다릅니다: " + key)
    for item in selected["candidate"]["values"]:
        require(copied["parameters"][item["id"]]["quantity"] == item["value"], "선택한 순번의 원문 값/단위/출처가 다릅니다.")
    require({key: value for key, value in copied["extensions"].items() if key != KEY} == case["document"]["extensions"],
            "기존 출처 또는 미정 환경을 바꾸었습니다.")
    call(service, "project.undo", {"expected_revision": copied["revision_id"], "command_id": str(uuid4())}, copied_context, mutation=True)
    undone = document(service, copied_context)
    require(undone["project_id"] == copied["project_id"] and undone["parameters"] == case["document"]["parameters"]
            and undone["extensions"] == case["document"]["extensions"], "한 번 실행 취소가 사본 기준 상태로 돌아가지 않았습니다.")
    call(service, "project.redo", {"expected_revision": undone["revision_id"], "command_id": str(uuid4())}, copied_context, mutation=True)
    restored = document(service, copied_context)
    require(restored["parameters"] == copied["parameters"] and restored["extensions"] == copied["extensions"], "다시 실행으로 출처/값이 복원되지 않았습니다.")
    wait(service, call(service, "project.save", {"expected_revision": restored["revision_id"]}, copied_context, mutation=True))
    snapshot, _ = wait(service, call(service, "snapshot.create", {"expected_revision": restored["revision_id"],
        "description": "선택 후보 편집 사본; 제조/측정 검증 미확립"}, copied_context, mutation=True))
    return {"context": copied_context, "path": response["path"], "response": response, "receipt": receipt,
            "preview": preview, "document": restored, "snapshot": snapshot,
            "single_undo_redo": True, "idempotent_apply": True}


def run(source_report, report_path):
    """! @brief 후보별 단 한 번 재계산하고 원본, 결과 및 runtime 없는 재열기를 확인한다."""
    require(not report_path.exists(), "기존 검증 기록을 덮어쓰지 않습니다.")
    original = json.loads(source_report.read_bytes())
    require(original["status"] == "passed", "완료된 원본 계산 기록이 필요합니다.")
    workspace = Path(original["workspace"]).resolve()
    require(workspace.is_relative_to((CODE / ".local").resolve()), "검증 workspace 범위 밖입니다.")
    runtime = SolverRuntime()
    require(runtime.identity == original["plan"]["runtime_identity"], "실제 worker 코드가 원래 계산 환경과 다릅니다. 묵시 재검산하지 않습니다.")
    before = {row["case"]["kind"]: files(workspace / row["case"]["path"]) for row in original["cases"]}
    started = time.monotonic()
    report = {"schema": "rfad.verification.tuning-adoption/0.1", "status": "running", "workspace": str(workspace),
        "source_report_sha256": sha256(source_report.read_bytes()).hexdigest(), "cases": [],
        "repeat_complex_absolute_tolerance": 1e-10, "native_recheck_limit": 2,
        "physics_validated": False, "manufacturing": None, "measurement": None}
    #! 새 계산을 시작하기 전에 재검산 수와 수치 재현 검사 상한을 별도 기록한다.
    publish_report(report_path.with_name(report_path.stem + "-plan.json"), deepcopy(report))
    try:
        with ProjectService(workspace, solver_runtime=runtime) as service:
            for row in original["cases"]:
                copied = adopt(service, row)
                record = {"kind": row["case"]["kind"], "copy": copied}
                report["cases"].append(record)
                publish_report(report_path, report)
                spec = deepcopy(row["case"]["specification"])
                axis = spec["variables"][0]
                axis["values"] = [axis["values"][row["selected_index"]]]
                spec["name"] += " / 새 사본 단일 재검산"
                spec["budget"].update(max_candidates=1, max_native_solves=1, wall_seconds=600)
                repeated = run_study(service, copied["context"], spec, timeout=620)
                results, selected = candidate_results(service, copied["context"], repeated)
                require(selected == 0 and results[0]["eligible"], "새 사본의 단일 재계산이 완료되지 않았습니다.")
                old = row["results"][row["selected_index"]]["result"]["page"]["samples"]
                new = results[0]["result"]["page"]["samples"]
                difference = max(abs(complex(a["real"], a["imag"]) - complex(b["real"], b["imag"])) for a, b in zip(old, new))
                require(difference <= report["repeat_complex_absolute_tolerance"], "새 사본의 동일 입력 계산이 사전 수치 재현 상한을 벗어났습니다.")
                record.update(study=repeated, results=results, max_complex_difference=difference)
                require(document(service, row["case"]["context"]) == row["case"]["document"], "재계산이 원본을 바꾸었습니다.")
                require(files(workspace / row["case"]["path"]) == before[row["case"]["kind"]], "원본 프로젝트/과거 결과 파일이 변경됐습니다.")
                publish_report(report_path, report)
                print(record["kind"] + ": adoption, undo/redo, original preservation and actual recheck passed", flush=True)
        with ProjectService(workspace) as reopened:
            for row in report["cases"]:
                copied = row["copy"]
                opened, _ = wait(reopened, call(reopened, "project.open", {"path": copied["path"], "open_mode": "open"}, mutation=True))
                require(opened["document"] == copied["document"], "저장 사본을 재열었을 때 원본이 다릅니다.")
                results, selected = candidate_results(reopened, copied["context"], row["study"])
                require(selected == 0 and results == row["results"], "runtime 없는 재열기 결과가 다릅니다.")
        report.update(status="passed", runtime_free_reopen=True)
    except Exception as error:
        report.update(status="failed", error={"type": type(error).__name__, "message": str(error), "details": getattr(error, "details", None)})
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        publish_report(report_path, report)
    print(json.dumps({"status": report["status"], "report": str(report_path), "seconds": report["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="실제 원호/IFA 후보의 사본 채택과 재계산 검증")
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    options = parser.parse_args()
    run(options.source_report, options.report)
