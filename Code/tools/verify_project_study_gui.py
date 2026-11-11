"""! @brief 기존 탐색 프로젝트 사본에서 수식/출처를 보존하는 실제 연구 GUI 경로를 검증한다."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "src"))

from rfad.application.canonical import canonical_hash
from rfad.application.projects import ProjectService
from rfad.application.project_study_contract import initial_specification
from rfad.application.project_study_results import read_case
from verify_openems_worker import call, wait


def identity(path):
    """! @brief 검증 파일의 실제 바이트 식별자를 기록한다."""
    data = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def run(source_report, workspace, report_path, gui):
    """! @brief 원본 검증 workspace를 보존하고 새 사본의 실제 GUI/WSL 실행만 수행한다."""
    previous = json.loads(source_report.read_bytes())
    source = Path(previous["workspace"]).resolve()
    workspace = workspace.resolve()
    local = (CODE_ROOT / ".local").resolve()
    if (not source.is_relative_to(local) or not workspace.is_relative_to(local) or workspace.exists()
            or workspace == source or source.is_relative_to(workspace) or workspace.is_relative_to(source) or report_path.exists()):
        raise ValueError("Code/.local 아래의 원본과 겹치지 않는 새 검증 경로가 필요합니다.")
    started = time.monotonic()
    shutil.copytree(source, workspace, ignore=shutil.ignore_patterns(".writer.lock"))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    context = previous["subject"]["context"]
    with ProjectService(workspace) as service:
        state = service.journal.read()
        original_jobs = set(state["jobs"])
        document = service._load(state["projects"][context["project_id"]])
        shape = deepcopy(next(item for item in document["geometry"] if item["kind"] == "line_path"))
        base, derived = str(uuid4()), str(uuid4())
        for kind, payload in (("parameter.set", {"id": base, "name": "연구 원본 선폭", "quantity": shape["width"]}),
                              ("parameter.set_expression", {"id": derived, "name": "연구 결합 선폭", "expression": "source_width * 1",
                                  "bindings": {"source_width": base}, "dimension": "length", "display_unit": "mm"})):
            applied = call(service, "project.apply_command", {"expected_revision": document["revision_id"], "command_id": str(uuid4()),
                           "type": kind, "payload": payload}, context, mutation=True)
            document = service._load(service.journal.read()["projects"][context["project_id"]])
        shape["width"] = {"parameter_id": derived}
        applied = call(service, "project.apply_command", {"expected_revision": document["revision_id"], "command_id": str(uuid4()),
                       "type": "geometry.set", "payload": {"geometry": shape}}, context, mutation=True)
        wait(service, call(service, "project.save", {"expected_revision": applied["new_revision"]}, context, mutation=True))
        before = service._load(service.journal.read()["projects"][context["project_id"]])
    (report_path.parent / "source-before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    spec = initial_specification()
    spec.update(name="매개변수와 출처 보존 RO4350B 연구", settings=previous["manifest"]["settings"], grid_levels_mm=previous["manifest"]["grid_levels_mm"])
    specification_path = report_path.parent / "specification.json"
    specification_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gui_report = report_path.parent / "gui-smoke.json"
    args = [str(gui.resolve()), "--python", sys.executable, "--source", str(CODE_ROOT / "src"), "--workspace", str(workspace),
            "--open-project", previous["subject"]["project_path"], "--openems-wsl", "--study-smoke-test",
            "--study-specification", str(specification_path), "--smoke-report", str(gui_report)]
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1320, check=False)
    (report_path.parent / "gui-stdout.log").write_bytes(result.stdout)
    (report_path.parent / "gui-stderr.log").write_bytes(result.stderr)
    smoke = json.loads(gui_report.read_bytes())
    if result.returncode != 0 or not smoke["passed"] or smoke["study_stage"] != 10:
        raise ValueError("연구 GUI 검증 실패: " + smoke.get("error", "상태를 확인하십시오.") + "; report=" + str(gui_report))
    with ProjectService(workspace, auto_run=False) as service:
        state = service.journal.read()
        study = state["studies"][smoke["study_view"]["study_id"]]
        snapshot = json.loads(service.journal.read_artifact(study["snapshot"]["artifact"]))
        if snapshot != before or snapshot["geometry"] != before["geometry"] or not snapshot["extensions"]:
            raise ValueError("매개변수/출처/기하 원본이 연구에서 변경되었습니다.")
        current = service._load(state["projects"][context["project_id"]])
        for name in ("parameters", "materials", "geometry", "extensions"):
            if current[name] != before[name]:
                raise ValueError("연구 중 원본 설계 내용이 바뀌었습니다: " + name)
        cases = []
        for case in study["cases"]:
            normalized, radiation, power = read_case(service, study, case)
            if normalized["provenance"]["analysis_plan"]["source_semantics"] != before:
                raise ValueError("실제 worker가 다른 원본을 소비했습니다.")
            cases.append({"grid_mm": case["settings"]["grid_mm"], "result_id": case["result_id"],
                          "attempts": case["attempts"], "power_balance": power, "statistics": normalized["native_statistics"]})
        actual = [item for item in before["materials"] if item["name"].startswith("실제 납품 물성 미확정:")]
        if len(actual) != 2 or any(item[key]["value_si"] is not None for item in actual for key in ("epsilon_r", "tan_delta", "conductivity")):
            raise ValueError("실제 납품 미정 물성이 임의 보완되었습니다.")
        added = [job for key, job in state["jobs"].items() if key not in original_jobs]
        native = [job for job in added if job["kind"] == "em_analysis"]
        if len(native) != len(cases) + 1 or sum(job["state"] == "cancelled" for job in native) != 1:
            raise ValueError("재개/GUI 재연결에서 예상하지 않은 native 실행이 추가되었습니다.")
        output = {"schema": "rfad.verification.project-study-gui/0.1", "status": "passed", "design_baseline": "RFAD-D0-3.4",
                  "validated_at": datetime.now(timezone.utc).isoformat(), "workspace": str(workspace), "study_id": study["study_id"],
                  "snapshot": study["snapshot"], "source_hash": canonical_hash(before), "source_parameters_preserved": True,
                  "source_extensions_preserved": True, "actual_properties_remain_missing": True, "definition": study["definition"],
                  "runtime_identity": study["runtime_identity"], "cases": cases, "assessment": json.loads(service.journal.read_artifact(study["assessment"])),
                  "new_native_jobs": [{key: job[key] for key in ("job_id", "run_id", "state")} for job in native],
                  "gui": identity(gui), "gui_smoke": identity(gui_report), "gui_checks": smoke["study_checks"],
                  "elapsed_seconds": time.monotonic() - started, "physics_validated": False, "fabrication_validated": False, "measurement_validated": False}
    report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed", "study_id": output["study_id"], "native_completed": len(cases), "native_cancelled": 1}), flush=True)
    return output


def main():
    """! @brief 사용자 파일을 덮어쓰지 않는 명시적 검증 경로만 받는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--gui", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.source_report, args.workspace, args.report, args.gui)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
