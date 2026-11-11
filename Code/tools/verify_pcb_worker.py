"""! @brief 명시적 시험 PCB를 공개 명령으로 구성하고 실제 WSL 해석과 결과 수명을 검증한다."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_solver import PROFILE
from rfad.application.projects import ProjectService
from rfad.application.solver import RUNTIME_PROFILE
from rfad.application.solver_jobs import SolverRuntime
from rfad.domain.errors import ProjectError
from verify_openems_worker import call, wait


def create_fixture(service, fixture):
    """! @brief 직접 journal 변경 없이 공개 생성/편집/저장 명령으로 시험 설계를 만든다."""
    document = deepcopy(fixture["document"])
    if document["parameters"] or document["extensions"]:
        raise ValueError("이 실행 fixture 도구는 명시적 리터럴 설계만 생성합니다.")
    project_path = "projects/pcb-" + uuid4().hex[:12]
    opened, _ = wait(service, call(service, "project.open", {
        "path": project_path, "open_mode": "create", "name": document["metadata"]["name"],
    }, mutation=True))
    context = {"project_id": opened["project_id"]}
    revision = opened["revision_id"]
    if document["metadata"]["description"]:
        changed = call(service, "project.apply_command", {
            "expected_revision": revision, "command_id": str(uuid4()), "type": "metadata.set",
            "payload": {key: document["metadata"][key] for key in ("name", "description")},
        }, context, mutation=True)
        revision = changed["new_revision"]
    frame_id = opened["document"]["frames"]["board"]["id"]
    document["board"]["frame_id"] = frame_id
    for shape in document["geometry"]:
        shape["frame_id"] = frame_id
    entities = [("board", document["board"])]
    for kind, collection in (("material", "materials"), ("layer", "stackup"), ("net", "nets"), ("geometry", "geometry"), ("port", "ports")):
        values = sorted(document[collection], key=lambda item: item["kind"] == "via") if kind == "geometry" else document[collection]
        entities.extend((kind, value) for value in values)
    for kind, value in entities:
        changed = call(service, "project.apply_command", {
            "expected_revision": revision, "command_id": str(uuid4()), "type": kind + ".set", "payload": {kind: value},
        }, context, mutation=True)
        revision = changed["new_revision"]
    wait(service, call(service, "project.save", {"expected_revision": revision}, context, mutation=True))
    snapshot, _ = wait(service, call(service, "snapshot.create", {
        "expected_revision": revision, "description": fixture["description"],
    }, context, mutation=True))
    return context, project_path, snapshot


def exercise_cancellation(service, runtime, context, task_plan):
    """! @brief 실제 guest 실행을 관측한 뒤 취소하고 이전 완료 결과를 보존하는지 검사한다."""
    before = call(service, "solver.latest", {}, context)
    task = call(service, "job.submit", {"task_plan": task_plan, "budget": {"timeout_seconds": 120}}, context, mutation=True)
    deadline = time.monotonic() + 60
    observed = False
    while time.monotonic() < deadline:
        job = service.journal.read()["jobs"][task["job_id"]]
        if job["state"] in {"completed", "failed", "interrupted"}:
            raise RuntimeError("취소 전에 작업이 종료되었습니다.")
        try:
            guest = runtime.transport.inspect(job["run_id"], job["solver"]["nonce"])
        except ProjectError:
            # @brief 준비 복사 전에 아직 없는 guest 경로는 다음 조회에서 다시 확인한다.
            time.sleep(0.1)
            continue
        if guest.get("phase") == "running" and guest.get("state") not in {"completed", "failed"}:
            observed = True
            break
        time.sleep(0.1)
    if not observed:
        raise RuntimeError("실행 중인 guest를 관측하지 못했습니다.")
    call(service, "job.cancel", {"job_id": task["job_id"], "reason": "PCB 실제 실행 취소 검증"}, mutation=True)
    while time.monotonic() < deadline:
        status = call(service, "job.status", {"job_id": task["job_id"]})
        if status["state"] in {"cancelled", "completed", "failed", "interrupted"}:
            break
        time.sleep(0.1)
    job = service.journal.read()["jobs"][task["job_id"]]
    guest = runtime.transport.inspect(job["run_id"], job["solver"]["nonce"])
    if (status["state"] != "cancelled" or job["solver"]["resource_reserved"]
            or guest.get("termination_confirmed") is not True or guest.get("outcome_unknown")
            or call(service, "solver.latest", {}, context) != before):
        raise RuntimeError("취소/종료 확인 또는 이전 결과 보존에 실패했습니다.")
    return {"job_id": task["job_id"], "state": "cancelled", "termination_confirmed": True, "previous_result_preserved": True}


def radiation_pages(service, context, artifact_id, index):
    """! @brief 공개 읽기 전용 API의 모든 theta 페이지를 중복 없이 복원한다."""
    pages, offset = [], 0
    while offset is not None:
        page = call(service, "solver.radiation", {"artifact_id": artifact_id, "frequency_index": index, "theta_offset": offset}, context)
        if page["theta_offset"] != sum(item["returned_count"] for item in pages):
            raise RuntimeError("방사 패턴 페이지가 중복되거나 누락되었습니다.")
        pages.append(page)
        offset = page["next_offset"]
    return pages


def run(workspace, report_path, fixture_path, *, exercise_cancel=False, radiation_frequencies=None, radiation_step=15):
    """! @brief plan/prepare/solve/후처리/조회/재시작을 확인하고 물리 검증과 구분해 기록한다."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture.get("schema") != "rfad.pcb-runtime-fixture/0.1":
        raise ValueError("지원하지 않는 PCB 시험 입력입니다.")
    if radiation_frequencies:
        fixture["settings"]["radiation"] = {"frequency_hz": radiation_frequencies, "theta_step_deg": radiation_step, "phi_step_deg": radiation_step}
    started = time.monotonic()
    report = {"schema": "rfad.pcb-worker-verification/0.1", "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
              "ifa_execution_tested": fixture.get("case_kind") == "ifa_feed", "ifa_accuracy_tested": False,
              "nf2ff_tested": False, "formal_convergence_tested": False, "material_values": "explicit_test_assumptions",
              "fixture_case": fixture.get("case_kind", "circular_pcb"), "geometry_kinds": sorted({shape["kind"] for shape in fixture["document"]["geometry"]})}
    runtime = SolverRuntime()
    with ProjectService(workspace, solver_runtime=runtime) as service:
        context, project_path, snapshot = create_fixture(service, fixture)
        plan, _ = wait(service, call(service, "solver.plan", {
            "snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
            "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE, "settings": fixture["settings"],
        }, context, mutation=True))
        prepared, prepare_status = wait(service, call(service, "solver.prepare", {
            "analysis_plan": {key: plan["analysis_plan"][key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 120},
        }, context, mutation=True))
        task_plan = {"kind": "em_analysis", "prepared_plan": {key: prepared["prepared_plan"][key] for key in ("prepared_plan_id", "content_hash")},
                     "execution_mode": "solve_and_postprocess"}
        task = call(service, "job.submit", {"task_plan": task_plan, "budget": {"timeout_seconds": 120}}, context, mutation=True)
        edited = call(service, "project.apply_command", {
            "expected_revision": snapshot["revision_id"], "command_id": str(uuid4()), "type": "metadata.set",
            "payload": {"name": "해석 접수 후 편집한 PCB", "description": "접수된 입력 snapshot은 변경하지 않음"},
        }, context, mutation=True)
        solved, solve_status = wait(service, task)
        result = json.loads(service.journal.read_artifact(solved["normalized_result"]))
        chart = call(service, "solver.samples", {"artifact_id": solved["artifact_id"]}, context)
        if chart["snapshot"] != snapshot or chart["snapshot"]["revision_id"] == edited["new_revision"]:
            raise RuntimeError("해석 결과의 고정 입력 스냅샷이 변경되었습니다.")
        repeated, repeat_status = wait(service, call(service, "job.submit", {
            "task_plan": {**task_plan, "execution_mode": "postprocess_only", "raw_result_id": solved["artifact_id"]},
            "budget": {"timeout_seconds": 120},
        }, context, mutation=True))
        repeated_result = json.loads(service.journal.read_artifact(repeated["normalized_result"]))
        if result["samples"] != repeated_result["samples"] or result["raw_manifest"] != repeated_result["raw_manifest"]:
            raise RuntimeError("독립 후처리에서 원시 자료 또는 표본이 변경되었습니다.")
        radiation = []
        if "radiation" in fixture["settings"]:
            for index in range(len(fixture["settings"]["radiation"]["frequency_hz"])):
                pages = radiation_pages(service, context, solved["artifact_id"], index)
                repeated_pages = radiation_pages(service, context, repeated["artifact_id"], index)
                if [{k: v for k, v in page.items() if k != "artifact_id"} for page in pages] != [{k: v for k, v in page.items() if k != "artifact_id"} for page in repeated_pages]:
                    raise RuntimeError("독립 NF2FF 후처리에서 필드 또는 전력 비율이 변경되었습니다.")
                radiation.append(pages)
            report.update(nf2ff_tested=True, radiation_summary=result["radiation_summary"], radiation_pages=[len(pages) for pages in radiation],
                          postprocess_radiation_identical=True, radiation_settings=fixture["settings"]["radiation"])
        if exercise_cancel:
            report["cancellation"] = exercise_cancellation(service, runtime, context, task_plan)
        view = call(service, "result.open", {"artifact_id": solved["artifact_id"]}, context)
        latest = call(service, "solver.latest", {}, context)
        report.update(workspace=str(workspace.resolve()), project_path=project_path, project_id=context["project_id"], snapshot=snapshot,
                      analysis_plan=plan["analysis_plan"], prepared_plan=prepared["prepared_plan"], artifact_id=solved["artifact_id"],
                      result=solved["normalized_result"], assessment=result["assessment"], native_statistics=result["native_statistics"],
                      mesh_statistics=result["mesh_statistics"], termination=result["termination"], sample_count=len(chart["samples"]),
                      postprocess_samples_identical=True, snapshot_preserved_during_edit=True, qt_found=result["provenance"]["runtime"]["qt_found"],
                      states={name: [event["state"] for event in status["events"]] for name, status in (("prepare", prepare_status), ("analysis", solve_status), ("postprocess_only", repeat_status))})
    with ProjectService(workspace, auto_run=False) as reopened:
        if (call(reopened, "result.open", {"artifact_id": solved["artifact_id"]}, context) != view
                or call(reopened, "solver.samples", {"artifact_id": solved["artifact_id"]}, context) != chart
                or call(reopened, "solver.latest", {}, context) != latest):
            raise RuntimeError("해석기 없는 서비스 재시작 후 결과가 변경되었습니다.")
        for index, pages in enumerate(radiation):
            if radiation_pages(reopened, context, solved["artifact_id"], index) != pages:
                raise RuntimeError("해석기 없는 재시작 후 방사 결과가 변경되었습니다.")
    report.update(status="passed", result_restored_without_solver=True, elapsed_seconds=time.monotonic() - started)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_bytes(report))
    print(json.dumps({"status": report["status"], "report": str(report_path.resolve()), "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))


def main():
    """! @brief 새 검증 저장소와 보고서에만 시험 결과를 남긴다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parents[1] / "fixtures/pcb_worker_smoke.json")
    parser.add_argument("--exercise-cancel", action="store_true")
    parser.add_argument("--radiation-frequency-hz", type=float, nargs="+")
    parser.add_argument("--radiation-step-deg", type=int, choices=(5, 10, 15, 30), default=15)
    args = parser.parse_args()
    try:
        run(args.workspace, args.report, args.fixture, exercise_cancel=args.exercise_cancel,
            radiation_frequencies=args.radiation_frequency_hz, radiation_step=args.radiation_step_deg)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
