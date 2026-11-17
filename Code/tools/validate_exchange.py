"""! @brief 별도 복사 작업공간에서 원호/IFA 실제 도면/STEP과 재검수·원문 보존을 검사한다."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import time

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))
from catalog_pcb_verification.common import call, wait, require, publish_report
from rfad.application.cad import PROFILE as STEP_PROFILE
from rfad.application.cad_runtime import CadRuntime
from rfad.application.exchange_contract import PROFILE
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.projects import ProjectService
from rfad.application.canonical import canonical_hash


def file_hash(path):
    """! @brief 대형 과거 원시 파일도 고정 크기 블록으로 읽어 메모리 사용을 제한한다."""
    digest = sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def files(root):
    """! @brief 원본의 파일 추가/삭제까지 포함하여 실제 바이트를 비교한다."""
    return {path.relative_to(root).as_posix(): file_hash(path)
            for path in sorted(root.rglob("*")) if path.is_file() and path.name != ".writer.lock"}


def completed(service, method, data, context):
    """! @brief GUI와 같은 TaskRef/상태 조회로 실제 완료만 수용한다."""
    task = call(service, method, data, context, mutation=True)
    result, status = wait(service, task, timeout_seconds=240)
    return task, result, status


def run(options):
    """! @brief 원본 workspace에는 서비스를 열지 않고 새 복사본에서만 출력 작업을 만든다."""
    source_report = options.source_report.resolve(strict=True)
    source = json.loads(source_report.read_bytes())
    require(source.get("status") == "passed", "완료된 단계9 채택 사례 기록이 필요합니다.")
    original = Path(source["workspace"]).resolve(strict=True)
    workspace, report_path = options.workspace.resolve(), options.report.resolve()
    local = (CODE / ".local").resolve()
    require(original.is_relative_to(local) and workspace.is_relative_to(local) and report_path.is_relative_to(local),
            "이 검증은 Code/.local 아래의 명시 작업공간과 기록만 사용합니다.")
    require(not workspace.exists() and not report_path.exists(), "기존 작업공간/검증 기록을 덮어쓰지 않습니다.")
    require(not workspace.is_relative_to(original) and not original.is_relative_to(workspace), "원본의 하위/상위 경로로 복제할 수 없습니다.")
    original_files = files(original)
    shutil.copytree(original, workspace)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema": "rfad.verification.exchange-workflow/0.1", "status": "running",
        "source_workspace": str(original), "workspace": str(workspace), "source_report_sha256": sha256(source_report.read_bytes()).hexdigest(),
        "original_file_count": len(original_files), "original_file_hashes_sha256": canonical_hash(original_files),
        "native_solver_runs": 0, "physics_validated": False, "manufacturing_validated": False,
        "independent_recipient_application_validated": False, "cases": []}
    started = time.monotonic()
    publish_report(report_path, report)
    saved = []
    try:
        runtime = ExchangeRuntime(options.exchange_python)
        cad = CadRuntime(options.cad_python)
        report["exchange_runtime"] = deepcopy(runtime.identity)
        report["cad_runtime"] = deepcopy(cad.identity)
        with ProjectService(workspace, exchange_runtime=runtime, cad_runtime=cad) as service:
            original_state = service.journal.read()
            before_projects = deepcopy(original_state["projects"])
            before_solver_results = deepcopy(original_state["solver_results"])
            for row in source["cases"]:
                context = row["copy"]["context"]
                document = service._load(original_state["projects"][context["project_id"]])
                require(document == row["copy"]["document"], "채택 사본의 보존된 문서와 현재 문서가 다릅니다.")
                _, snapshot, _ = completed(service, "snapshot.create", {"expected_revision": document["revision_id"],
                    "description": "단계10 동일 원본 도면/STEP 교환; 제작/실측 미확립"}, context)
                reference = {key: snapshot[key] for key in ("snapshot_id", "content_hash")}
                offered = call(service, "export.context", {"snapshot": reference}, context)
                case = {"kind": row["kind"], "context": context, "document_sha256": canonical_hash(document),
                        "snapshot": snapshot, "outputs": [], "original_source_and_unknowns_preserved": False}
                report["cases"].append(case)
                for format_name in ("pdf", "svg", "dxf", "step"):
                    data = {"snapshot": reference, "profile": STEP_PROFILE if format_name == "step" else PROFILE,
                            "format": format_name}
                    if format_name != "step":
                        data["options"] = offered["default_options"]
                    _, preview, _ = completed(service, "export.preview", data, context)
                    if format_name != "step":
                        require(preview["can_build"], "연관 도면 검토 실패: " + json.dumps(preview.get("issues"), ensure_ascii=False))
                        data["review_hash"] = preview["review_hash"]
                    task, built, build_status = completed(service, "export.build", data, context)
                    displayed = call(service, "export.get", {"job_id": task["job_id"]}, context)
                    artifacts = built["artifacts"]
                    source_ref = next(item for item in artifacts if item["uri"].endswith("/sidecar.json"))
                    sidecar = json.loads(service.journal.read_artifact(source_ref))
                    require(sidecar["source_semantics"] == document, "출력 sidecar가 원문 출처/미정값을 바꾸었습니다.")
                    hashes = {item["uri"]: file_hash(workspace / item["uri"]) for item in artifacts}
                    require(all(hashes[item["uri"]] == item["sha256"] for item in artifacts), "게시 파일 해시가 다릅니다.")
                    verify_task, verification, verify_status = completed(service, "export.verify", {
                        "job_id": task["job_id"], "manifest_sha256": displayed["manifest_sha256"]}, context)
                    require(all(file_hash(workspace / uri) == digest for uri, digest in hashes.items()),
                            "재검수가 원래 출력/검수 파일을 변경했습니다.")
                    checked = call(service, "export.get", {"job_id": verify_task["job_id"]}, context)
                    saved.extend([(context, task["job_id"], displayed), (context, verify_task["job_id"], checked)])
                    case["outputs"].append({"format": format_name, "build_task": task, "build": built,
                        "verification_task": verify_task, "verification": verification,
                        "build_state": build_status["state"], "verification_state": verify_status["state"],
                        "original_package_hashes_preserved": True, "source_sidecar_exact": True})
                    publish_report(report_path, report)
                    print(row["kind"] + " " + format_name + ": generated and reverified in a separate job; source preserved", flush=True)
                require(service._load(service.journal.read()["projects"][context["project_id"]]) == document,
                        "출력이 편집 사본 원본을 변경했습니다.")
                case["original_source_and_unknowns_preserved"] = True
            after_state = service.journal.read()
            require(after_state["projects"] == before_projects, "출력이 current/saved/history를 변경했습니다.")
            require(after_state["solver_results"] == before_solver_results, "도면 출력이 기존 계산 결과를 변경했습니다.")
        with ProjectService(workspace, auto_run=False) as reopened:
            for context, job_id, expected in saved:
                require(call(reopened, "export.get", {"job_id": job_id}, context) == expected, "실행 환경 없는 재열기 결과가 다릅니다.")
        require(files(original) == original_files, "검증이 원래 단계9 작업공간의 파일을 변경했습니다.")
        report.update(status="passed", runtime_free_reopen=True, original_workspace_all_bytes_unchanged=True,
                      project_current_saved_history_unchanged=True, past_solver_results_unchanged=True)
    except Exception as error:
        report.update(status="failed", error={"type": type(error).__name__, "message": str(error), "details": getattr(error, "details", None)})
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        publish_report(report_path, report)
    print(json.dumps({"status": report["status"], "report": str(report_path), "seconds": report["elapsed_seconds"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="보존된 원호/IFA 사본의 실제 도면/STEP 출력 및 재검수")
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--exchange-python", type=Path, required=True)
    parser.add_argument("--cad-python", type=Path, required=True)
    run(parser.parse_args())
