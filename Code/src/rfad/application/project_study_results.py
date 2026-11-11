"""! @brief 봉인된 일반 연구 결과의 작은 조회와 격자 비교 판정을 담당한다."""

from copy import deepcopy
import json

from rfad.application.canonical import canonical_bytes
from rfad.application.convergence import compare_samples
from rfad.application.pcb_power import validate_result as validate_power
from rfad.application.pcb_loss_convergence import assess_losses
from rfad.application.pcb_radiation import validate_result as validate_radiation
from rfad.application.radiation_comparison import compare_cases, power_audit
from rfad.domain.errors import ProjectError


def read_case(service, study, case):
    """! @brief 등록 결과/계획/snapshot과 별도 방사/손실 파일의 봉인을 교차 확인한다."""
    record = service.journal.read()["solver_results"].get(case["result_id"])
    if record is None or record["project_id"] != study["project_id"] or record["analysis_plan_id"] != case["analysis_plan"]["plan_id"]:
        raise ProjectError("E_HASH", "연구에 등록한 결과와 계획/프로젝트가 다릅니다.")
    normalized = json.loads(service.journal.read_artifact(record["normalized"]))
    plan = normalized["provenance"]["analysis_plan"]
    expected = json.loads(service.journal.read_artifact(case["analysis_plan"]["artifact"]))
    if plan != expected or plan["snapshot"] != study["snapshot"] or plan["runtime_identity"] != study["runtime_identity"]:
        raise ProjectError("E_HASH", "연구 원본/실행 출처가 결과와 다릅니다.")
    roles = {item["role"]: item for item in record["files"]}
    radiation = None
    if "radiation_recording" in plan["case"]:
        radiation = json.loads(service.journal.read_artifact(roles["radiation_result"]["artifact"]))
        validate_radiation(plan, radiation)
    power = None
    if "loss_recording" in plan["case"]:
        power = json.loads(service.journal.read_artifact(roles["power_balance_result"]["artifact"]))
        validate_power(plan, power, radiation)
        if normalized.get("power_balance") != power:
            raise ProjectError("E_HASH", "독립 전력 결과와 정규화 결과가 다릅니다.")
    return normalized, radiation, power


def assessment(service, study):
    """! @brief 마지막 인접 격자 쌍만 판정하며 전체 세 축 수렴/실측 합격을 선언하지 않는다."""
    records = [read_case(service, study, case) for case in study["cases"]]
    spec = study["specification"]
    comparisons = []
    for index, (left, right) in enumerate(zip(records, records[1:])):
        comparison = {"left": index, "right": index + 1,
                      "port": compare_samples(left[0], right[0], spec["port_profile"])}
        if left[1] is not None:
            pair = [{"label": str(i), "axis": "mesh", "settings": study["cases"][i]["settings"],
                     "normalized_result": item[0], "radiation_result": item[1]} for i, item in ((index, left), (index + 1, right))]
            comparison["radiation"] = compare_cases(*pair, spec["radiation_profile"])
        comparisons.append(comparison)
    enough = len(records) >= max(spec["port_profile"]["minimum_levels"], spec["radiation_profile"]["minimum_levels"])
    port = comparisons[-1]["port"]["status"] if comparisons and enough else "not_established"
    radiation = comparisons[-1].get("radiation", {}).get("status", "not_evaluated") if comparisons and enough else "not_established"
    budget = power_audit(records[-1][0], records[-1][1], spec["radiation_profile"]) if records[-1][1] is not None else None
    balance = records[-1][2]["full_energy_closure"] if records[-1][2] is not None else "not_evaluated"
    losses = assess_losses([item[2] for item in records], spec["loss_profile"]) if "loss_profile" in spec and all(item[2] is not None for item in records) else None
    return {"schema": "rfad.project-study-assessment/0.1", "study_id": study["study_id"], "snapshot": study["snapshot"],
            "definition": study["definition"], "case_result_ids": [case["result_id"] for case in study["cases"]],
            "scope": "mesh_axis_only", "minimum_levels_met": enough,
            "port_stability": port, "radiation_mesh_stability": radiation, "comparisons": comparisons,
            "reference_radiation_budget": budget, "reference_energy_closure": balance, "individual_loss_stability": losses,
            "all_axes_convergence": "not_evaluated", "physics_validated": False,
            "fabrication_validated": False, "measurement_validated": False}


def view(service, state, study):
    """! @brief 원본 전체와 큰 복소 필드를 보내지 않고 상태/전력만 표시 DTO로 투영한다."""
    project = state["projects"][study["project_id"]]
    current = service._load(project)
    rows = []
    for index, case in enumerate(study["cases"]):
        row = {"index": index, "grid_mm": case["settings"]["grid_mm"], "phase": case["phase"],
               "attempt_count": len(case["attempts"]), "result_id": case.get("result_id"), "power_balance": None}
        if "result_id" in case:
            _, _, power = read_case(service, study, case)
            if power is not None:
                row["power_balance"] = {key: deepcopy(power[key]) for key in ("full_energy_closure", "max_relative_residual", "power_unit")}
                row["power_balance"]["frequencies"] = [{key: deepcopy(value) for key, value in item.items() if key not in {"sheet_components", "via_components", "dielectric_components"}}
                                                           for item in power["frequencies"]]
        rows.append(row)
    job = state["jobs"].get(study.get("current_job_id"))
    result = {"schema": "rfad.project-study-view/0.1", **{key: deepcopy(study[key]) for key in
              ("study_id", "project_id", "name", "state", "snapshot", "specification", "created_at")},
              "source_revision_matches_current": current["revision_id"] == study["snapshot"]["revision_id"],
              "cases": rows, "current_job": None if job is None else {key: job[key] for key in ("job_id", "state", "run_id")},
              "message": study.get("message", ""), "assessment": None,
              "runtime_configured": service.solver.runtime is not None,
              "runtime_matches": service.solver.runtime is not None and service.solver.runtime.identity == study["runtime_identity"],
              "power_unit": "W*s^2", "absolute_power_w": None, "physics_validated": False,
              "fabrication_validated": False, "measurement_validated": False}
    if "assessment" in study:
        result["assessment"] = json.loads(service.journal.read_artifact(study["assessment"]))
        if (result["assessment"].get("study_id") != study["study_id"] or result["assessment"].get("snapshot") != study["snapshot"]
                or result["assessment"].get("definition") != study["definition"]):
            raise ProjectError("E_HASH", "격자 판정의 연구/원본 참조가 다릅니다.")
        losses = result["assessment"].get("individual_loss_stability")
        if losses is not None:
            for comparison in losses["comparisons"]:
                components = comparison.pop("components")
                worst = max(components, key=lambda item: item["absolute_fraction_delta"] / item["allowed_fraction_delta"])
                comparison.update(component_count=len(components), worst_component=worst)
    if len(canonical_bytes(result)) > 60 * 1024:
        raise ProjectError("E_RESOURCE", "연구 표시 자료가 60 KiB를 초과했습니다.")
    return result
