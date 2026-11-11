"""! @brief 원시 생산자와 새 후처리 소스를 구분하고 불변 필드의 손실을 재계산한다."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.pcb_loss_study import validate_study
from rfad.application.pcb_power import validate_result
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from rfad.application.radiation_study import require
from pcb_loss_execution import assess_available
from verify_openems_worker import call
from verify_ifa_convergence import save_report
from radiation_convergence.evidence import reference


CODE = Path(__file__).resolve().parents[1]
OLD_METHOD = "quarter_cell_volume_and_sheet_excess/0.1"
NEW_METHOD = "quarter_cell_volume_and_native_sheet_override/0.1"


def load_producer(path):
    """! @brief 파생 보고서도 유한 크기/사례 집합/설정 hash를 검증하여 잘못된 축 판정을 막는다."""
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    require(len(raw) <= 8 * 1024 * 1024, "생산자 보고서가 8 MiB를 넘습니다.")
    result = json.loads(raw)
    require(result.get("schema") == "rfad.pcb-loss-study-run/0.1", "독립 손실 생산자 보고서가 필요합니다.")
    validate_study(result["study"])
    expected = {canonical_hash(case["settings"]) for case in result["study"]["cases"]}
    require(set(result["runs"]) == expected and all(canonical_hash(entry["settings"]) == key for key,entry in result["runs"].items()), "생산자 보고서의 사례/설정 hash가 다릅니다.")
    return result


def validate_producer_plan(plan):
    """! @brief 폐기한 개발 분할의 이름 한 개만 허용하고 기하/물성/설정 변화는 거절한다."""
    expected = build_pcb_plan(plan["source_semantics"], plan["snapshot"], plan["runtime_identity"], plan["case"]["settings"])
    expected["plan_id"] = plan["plan_id"]
    comparison = deepcopy(plan)
    recording = comparison["case"]["loss_recording"]
    migrated = recording["method"] == OLD_METHOD
    if migrated:
        require(recording["schema"] == "rfad.pcb-loss-recording/0.2" and bool(plan["case"]["vias"]), "알 수 없는 손실 기록 이전입니다.")
        recording["method"] = NEW_METHOD
    require(comparison == expected, "재계산은 원래 기하/물성/급전/기록/격자의 변경을 허용하지 않습니다.")
    return {"producer_plan_preserved": True, "only_legacy_recording_method_label_differs": migrated}


def run(producer_report, destination):
    """! @brief 각 원시 결과를 새 nonce로 후처리만 하고 원본 결과/판정을 덮어쓰지 않는다."""
    original = load_producer(producer_report)
    require(original["status"] in {"completed", "completed_with_blocked_cases"}, "완료된 생산자 연구가 필요합니다.")
    require(not destination.exists(), "기존 손실 재계산 경로를 덮어쓸 수 없습니다.")
    workspace = Path(original["workspace"]).resolve()
    require(not destination.is_relative_to(workspace) and not workspace.is_relative_to(destination), "재계산 출력은 원래 workspace와 겹치지 않아야 합니다.")
    runtime = SolverRuntime()
    require(runtime.identity["manifest_sha256"] == original["runtime_identity"]["manifest_sha256"], "필드 생산자와 설치/정규화가 다른 native 환경입니다.")
    sources = dict(runtime.sources)
    sources["tools/openems_worker.py"] = (CODE / "tools/loss_recalculation_native.py").read_text(encoding="utf-8")
    calculator = {"schema": "rfad.loss-calculator-identity/0.1", "native_install_manifest_sha256": runtime.identity["manifest_sha256"],
                  "transport": runtime.identity["transport"], "entrypoint_source": "tools/loss_recalculation_native.py",
                  "files": [{"path": path, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": len(text.encode("utf-8"))} for path,text in sources.items()]}
    destination.mkdir(parents=True)
    report_path = destination / "report.json"
    report = {"schema": "rfad.pcb-loss-recalculation-study/0.1", "producer_report": str(producer_report.resolve()),
              "producer_report_sha256": hashlib.sha256(producer_report.read_bytes()).hexdigest(), "study": original["study"],
              "native_producer_runtime": original["runtime_identity"], "calculator_identity": calculator,
              "runs": {}, "status": "running", "fdtd_executed": False, "original_artifacts_modified": False,
              "physics_validated": False, "fabrication_validated": False, "measurement_validated": False}
    save_report(report_path, report)
    with ProjectService(workspace, auto_run=False) as service:
        before = sorted(service.journal.read()["jobs"])
        for key, entry in original["runs"].items():
            if entry["status"] != "completed":
                report["runs"][key] = deepcopy(entry)
                continue
            opened = call(service, "result.open", {"artifact_id": entry["artifact_id"]}, original["subject"]["context"])
            roles = {item["role"]: reference(item) for item in opened["files"]}
            for ref in roles.values():
                service.journal.verify_file(ref)
            normalized = json.loads(service.journal.read_artifact(roles["normalized_result"]))
            plan = normalized["provenance"]["analysis_plan"]
            require(plan == json.loads(service.journal.read_artifact(entry["analysis_plan"]["artifact"]))
                    and plan["case"]["settings"] == entry["settings"]
                    and plan["runtime_identity"] == original["runtime_identity"] and plan["snapshot"] == original["subject"]["snapshot"], "원시 생산자/계획/출처가 다릅니다.")
            guard = validate_producer_plan(plan)
            radiation = json.loads(service.journal.read_artifact(roles["radiation_result"]))
            identity, nonce = str(uuid4()), uuid4().hex
            stage = destination / identity
            stage.mkdir()
            for path,text in sources.items():
                target = stage / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode("utf-8"))
            records = []
            for role,value in (("plan",plan),("radiation",radiation),("statistics",normalized["native_statistics"])):
                path = stage / "input" / (role + ".json")
                path.parent.mkdir(exist_ok=True)
                data = canonical_bytes(value)
                path.write_bytes(data)
                records.append({"path": path.relative_to(stage).as_posix(), "role": role, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            for name in ("pcb.xml", "pcb_loss_E.h5", "pcb_loss_J.h5", "pcb_loss_rotH.h5"):
                ref = roles["raw/" + name]
                target = stage / "input/raw" / name
                _copy_external(service, ref, target)
                records.append({"path": target.relative_to(stage).as_posix(), "role": "raw/" + name, "bytes": ref["bytes"], "sha256": ref["sha256"]})
            producer = {"snapshot": plan["snapshot"], "analysis_plan": entry["analysis_plan"], "normalized_result": entry["normalized_result"],
                        "original_power_balance_result": entry["power_balance_result"],
                        "raw_fields": {name:roles["raw/" + name] for name in ("pcb.xml","pcb_loss_E.h5","pcb_loss_J.h5","pcb_loss_rotH.h5")}, "plan_guard": guard}
            request = {"run_id": identity, "nonce": nonce, "input_files": records, "native_producer": producer, "calculator_identity": calculator}
            (stage / "runtime.json").write_bytes(runtime.manifest_bytes)
            (stage / "request.json").write_bytes(canonical_bytes(request))
            outcome = runtime.transport.execute(stage, run_id=identity, nonce=nonce, cancel=threading.Event(), timeout_seconds=300)
            require(outcome.get("state") == "completed" and outcome.get("termination_confirmed") is True and not outcome.get("outcome_unknown"), "독립 손실 재계산 worker가 완료되지 않았습니다: " + str(outcome))
            calculated = json.loads((stage / "output/recalculation.json").read_bytes())
            require(calculated["native_producer"] == producer and calculated["calculator_identity"] == calculator and calculated["fdtd_executed"] is False, "재계산의 생산자/새 판정기 출처가 다릅니다.")
            validate_result(plan, calculated["power_balance"], radiation)
            for ref in roles.values():
                service.journal.verify_file(ref)
            power_path = stage / "output/power_balance.json"
            require(json.loads(power_path.read_bytes()) == calculated["power_balance"], "별도 손실 파일과 재계산 요약이 다릅니다.")
            report["runs"][key] = {"status": "completed", "settings": entry["settings"], "original_artifact_id": entry["artifact_id"],
                                   "native_producer": producer, "power_balance": calculated["power_balance"],
                                   "corrected_power_file": {"path": str(power_path.relative_to(destination)), "sha256": hashlib.sha256(power_path.read_bytes()).hexdigest()}, "worker_run_id": identity}
            print(json.dumps({"grid_mm":entry["settings"]["grid_mm"], "subdivisions":entry["settings"].get("feature_subdivisions",1), "status":calculated["power_balance"]["full_energy_closure"]}),flush=True)
            save_report(report_path, report)
        require(sorted(service.journal.read()["jobs"]) == before, "손실 재계산 중 원래 서비스 작업이 추가됐습니다.")
        report.update(original_job_ids_before=before, original_job_ids_after=before)
    report.update(status="completed", assessment=assess_available(original["study"], report["runs"]))
    save_report(report_path, report)
    return report


def _copy_external(service, ref, target):
    """! @brief 새 계산 staging만 복제하며 원래 workspace의 JSON 읽기 상한을 확대하지 않는다."""
    from rfad.storage.sealed_files import copy

    target.parent.mkdir(parents=True, exist_ok=True)
    copy(service.journal._safe_path(ref["uri"]), target, ref)
