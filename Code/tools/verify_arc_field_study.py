"""! @brief 내부 원호 PCB의 실제 전계 기록부터 같은 개정의 적응 연구 완료까지 실행한다."""

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from verify_openems_worker import call, wait, ProjectService, SolverRuntime
from test_cad_worker_process import register_fixture
from test_pcb_solver import fixture_document, SETTINGS
from rfad.application.solver_requests import PCB_PROFILE, RUNTIME_PROFILE
from rfad.cli.field_study import run


def main():
    """! @brief 새 시험 작업공간에만 합성 원호를 만들고 매 반복의 실제 작업과 원문을 보존한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    if (args.workspace / "current.json").exists():
        parser.error("새 시험 작업공간을 선택하십시오.")
    with ProjectService(args.workspace, auto_run=False) as service:
        document, saved = register_fixture(service, fixture_document(arc=True))
    with ProjectService(args.workspace, solver_runtime=SolverRuntime()) as service:
        context = {"project_id": document["project_id"]}
        def phase(method, data):
            """! @brief 검수에서 동기 대기할 때도 일반 제품의 작업 큐를 사용한다."""
            return wait(service, call(service, method, data, context, mutation=True))[0]
        settings = {**SETTINGS, "field_probe": {"frequency_hz": 10e9, "x_mm": [2, 6], "y_mm": [0, 4], "z_mm": 0.5}}
        snapshot = {key: saved[key] for key in ("snapshot_id", "content_hash")}
        plan = phase("solver.plan", {"snapshot": snapshot, "analysis_profile": PCB_PROFILE, "runtime_profile": RUNTIME_PROFILE, "settings": settings})
        prepared = phase("solver.prepare", {"analysis_plan": {key: plan["analysis_plan"][key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 300}})
        solved = phase("job.submit", {"task_plan": {"kind": "em_analysis", "execution_mode": "solve_and_postprocess",
            "prepared_plan": {key: prepared["prepared_plan"][key] for key in ("prepared_plan_id", "content_hash")}}, "budget": {"timeout_seconds": 300}})
        source = {"kind": "solver", "artifact_id": solved["artifact_id"]}
        pin = call(service, "result.describe", {"source": source}, context)["pin"]
        field = call(service, "result.field.describe", {"source": source, "pin": pin}, context)
        counts = next(item["shape"] for row in field["monitors"] if row["monitor_id"] == "probe_electric"
                      for item in row["components"] if item["component"] == "x")
        report = run(service, document["project_id"], SimpleNamespace(resume=None, artifact=solved["artifact_id"], name="원호 전계 적응 연구",
                     monitor="probe_electric", component="x", frequency_index=0, normal="z", index=0, roi=[0, counts[0], 0, counts[1]],
                     threshold=0.01, max_rules=2, memory_mib=512, rounds=2, tolerance=1e-8))
        if report["state"] != "completed" or not report["frequency_comparisons"]:
            raise RuntimeError(report["message"])
        print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
