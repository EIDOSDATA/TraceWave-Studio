"""! @brief 중단 연구의 이미 완료한 사전 고정 축만 원본 참조를 보존하여 별도 조회한다."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))

from loss_recalculation import load_producer, validate_producer_plan
from pcb_loss_execution import assess_available
from rfad.application.canonical import canonical_hash, canonical_bytes
from rfad.application.pcb_loss_study import validate_study
from rfad.application.projects import ProjectService
from rfad.application.radiation_study import require
from verify_pcb_power_balance import load_result


def derive(source, axis, destination):
    """! @brief 미완료 수준/기준 변경을 허용하지 않고 완료 축의 native 파일만 다시 검증한다."""
    original = load_producer(source)
    original_bytes = source.read_bytes()
    require(json.loads(original_bytes) == original, "축 추출 시작 중 원래 보고서가 바뀌었습니다.")
    require(not destination.exists(), "기존 축 보고서를 덮어쓸 수 없습니다.")
    result = deepcopy(original)
    result["study"]["cases"] = [case for case in original["study"]["cases"] if case["axis"] == axis]
    result["study"]["id"] += "/" + axis + "-derived"
    result["study"]["description"] = "Completed prespecified axis only; full original study and incomplete cases are retained separately."
    validate_study(result["study"])
    keys = {canonical_hash(case["settings"]) for case in result["study"]["cases"]}
    result["runs"] = {key: value for key, value in original["runs"].items() if key in keys}
    require(all(item["status"] == "completed" for item in result["runs"].values()), "사전 고정 축에 미완료 수준이 있습니다.")
    with ProjectService(Path(original["workspace"]), auto_run=False) as service:
        before = sorted(service.journal.read()["jobs"])
        for entry in result["runs"].values():
            plan = json.loads(service.journal.read_artifact(entry["analysis_plan"]["artifact"]))
            validate_producer_plan(plan)
            require(plan["case"]["settings"] == entry["settings"] and plan["runtime_identity"] == original["runtime_identity"]
                    and plan["snapshot"] == original["subject"]["snapshot"], "완료 축의 실제 원본/설정/생산자가 다릅니다.")
            require(load_result(service, entry, original["subject"]) == entry["power_balance"], "원래 봉인 손실과 보고서가 다릅니다.")
        require(sorted(service.journal.read()["jobs"]) == before, "축 추출에서 새 작업을 만들었습니다.")
    result["preflight_guards"] = [guard for guard in original["preflight_guards"] if guard["axis"] == axis]
    result["assessment"] = assess_available(result["study"], result["runs"])
    result["status"] = "completed"
    require(source.read_bytes() == original_bytes, "축 추출 중 원래 보고서가 바뀌었습니다.")
    result["derivation"] = {"source_report": str(source.resolve()), "source_sha256": hashlib.sha256(original_bytes).hexdigest(),
                            "source_study_hash": canonical_hash(original["study"]), "axis": axis,
                            "original_study_completion_claimed": False, "new_fdtd_jobs": 0, "job_ids_before": before, "job_ids_after": before}
    destination.parent.mkdir(parents=True, exist_ok=True)
    assessment_path = destination.with_name(destination.stem + ".assessment.json")
    with assessment_path.open("xb") as stream:
        stream.write(canonical_bytes(result["assessment"]))
    result["assessment_artifact"] = {"path": assessment_path.name, "sha256": hashlib.sha256(assessment_path.read_bytes()).hexdigest()}
    with destination.open("xb") as stream:
        stream.write(canonical_bytes(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--axis", choices=("mesh", "local_mesh", "termination", "curve"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = derive(args.report, args.axis, args.output)
    print(json.dumps({"status": result["status"], "assessment": result["assessment"]["status"], "native_cases": len(result["runs"])}))
