"""! @brief 봉인된 계산을 독립 식과 비교하고 기존 결과와 분리한 판정을 보존한다."""

from copy import deepcopy
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.result_radiation import load as load_radiation
from rfad.application.result_sources import resolve
from rfad.application.rf_validation_records import bounded, current_view, fail, load_json
from rfad.application.rf_validation_plan import assessment_engine
from rfad.domain.rf_reference import assess_dipole


def _row(case, label, *, expected=None, actual=None, error=None, tolerance=None, unit="ratio", state="not_evaluated", reason=""):
    """! @brief 미정 수치는 null로 두고 실제 비교의 단위와 판정 범위를 명시한다."""
    return {"case_id": case["case_id"], "case_name": case["name"], "label": label,
            "frequency_hz": 2.4e9 if case["group"] == "dipole" else None,
            "expected": expected, "actual": actual, "error": error, "tolerance": tolerance,
            "unit": unit, "state": state, "reason": reason, "criterion_source_refs": []}


def _result(service, record, case, phase):
    """! @brief 현재 사례가 소유한 성공 작업만 고정 source와 pin으로 조회한다."""
    operation = case["phase_states"][phase]["operation_result"]
    source = {"kind": "solver", "artifact_id": operation["artifact_id"]}
    resolved = resolve(service, {"project_id": record["project_id"]}, source)
    normalized = resolved["normalized"]
    plan = normalized["provenance"]["analysis_plan"]
    definition = load_json(service, record["definition"])
    expected = next(c for c in definition["cases"] if c["case_id"] == case["case_id"])
    if (plan["snapshot"] != record["snapshot"] or canonical_hash(plan["case"]) != expected["fixture_hash"]
            or plan["runtime_identity"] != definition["runtime_identity"]):
        fail("계산의 물리 조건, 원본 또는 runtime이 고정 검증 사례와 다릅니다.", "E_HASH")
    radiation, reference = load_radiation(service, resolved)
    return resolved, radiation, reference


def assess(service, state, record):
    """! @brief 계산은 다시 실행하지 않고 유한 보고서를 새 식별자로 추가한다."""
    if len(record["reports"]) >= 16:
        fail("한 캠페인의 판정 보고서 상한 16개에 도달했습니다.", "E_RESOURCE")
    plan = load_json(service, record["definition"])
    if plan["assessment_engine"] != assessment_engine():
        fail("검토 시 고정한 판정 구현이 변경되었습니다. 새 캠페인 검토가 필요합니다.", "E_VERSION")
    value = current_view(service, state, record)
    for key, item in value["validation_states"].items():
        item["reason"] = ("제작 또는 측정 조건을 입력 자료로 확정하지 않았습니다." if key in ("manufacturing", "measurement")
                          else "이 판정에서 해당 검증 축을 평가하지 않았습니다.")
    if any(phase["resource_reserved"] or phase["state"] not in ("completed", "failed", "cancelled", "interrupted")
           for case in value["cases"] for phase in case["phase_states"].values()):
        fail("실행 중이거나 종료가 미확인인 작업은 판정할 수 없습니다.", "E_CONFLICT")
    rows, comparisons, metrics_by_level, terminations = [], [], [], []
    for case in value["cases"]:
        phases = case["phase_states"]
        if case["blocked_reason"]:
            rows.append(_row(case, "실행 전 조건", state="blocked_before_execution", reason=case["blocked_reason"]))
            continue
        if phases.get("solve", {}).get("state") != "completed":
            rows.append(_row(case, "독립 참조 비교", reason="성공한 계산 원본이 없어 비교하지 않았습니다."))
            continue
        resolved, radiation, radiation_reference = _result(service, record, case, "solve")
        case.update(source=deepcopy(resolved["source"]), pin=deepcopy(resolved["pin"]),
                    evidence={"normalized": resolved["solver_record"]["normalized"], "radiation": radiation_reference})
        sample = radiation["frequencies"][0]
        comparison = assess_dipole(radiation["recording"]["theta_deg"], sample["normalized_power"], sample["metrics"])
        comparisons.append(comparison)
        metrics_by_level.append((case, sample["metrics"]))
        terminations.append(deepcopy(resolved["normalized"].get("termination")))
        for key, label, expected, actual in (
            ("maximum_pattern_error", "phi=0 정규화 전력 패턴 최대 오차", 0.0, comparison["maximum_pattern_error"]),
            ("relative_directivity_error", "이상 반파장 지향성 비교", comparison["reference_directivity"], sample["metrics"]["directivity_linear"]),
            ("efficiency_error", "PEC 방사 효율 비교", 1.0, sample["metrics"]["radiation_efficiency"]),
        ):
            limit, error = comparison["acceptance"][key], comparison[key]
            row = _row(case, label, expected=expected, actual=actual, error=error, tolerance=limit,
                state="within_preliminary_reference" if error <= limit else "requires_review",
                reason="기존 초도 이상 모델 비교 기준입니다. 유한 반경 형상의 정확해나 실측 검증이 아닙니다.")
            row["criterion_source_refs"] = [comparison["reference_source"]]
            rows.append(row)
        rows.append(_row(case, "전체 phi 패턴 최대 오차", expected=0.0,
                         actual=comparison["maximum_pattern_error_all_phi"], state="observed",
                         reason="전체 방위각 관찰값입니다. 새 합격 기준을 사후 적용하지 않습니다."))
        case["independent_comparison"] = comparison
        if phases.get("postprocess", {}).get("state") == "completed":
            repeated, repeated_radiation, repeated_reference = _result(service, record, case, "postprocess")
            equal = (repeated["normalized"]["samples"] == resolved["normalized"]["samples"]
                     and repeated_radiation == radiation)
            rows.append(_row(case, "같은 원시 결과 재후처리", actual=1 if equal else 0, expected=1,
                             state="identical" if equal else "requires_review", unit="boolean",
                             reason="등록된 동일 PreparedPlan의 원시 결과만 재사용했습니다."))
            case["postprocess_evidence"] = {"source": repeated["source"], "pin": repeated["pin"],
                "normalized": repeated["solver_record"]["normalized"], "radiation": repeated_reference}
        else:
            rows.append(_row(case, "같은 원시 결과 재후처리", reason="성공한 별도 재후처리 기록이 없습니다."))
    metrics_by_level.sort(key=lambda pair: pair[0]["level"])
    if len(metrics_by_level) == 3:
        for (previous_case, previous), (case, current) in zip(metrics_by_level, metrics_by_level[1:]):
            for key, label in (("directivity_linear", "지향성"), ("radiation_efficiency", "방사 효율")):
                change = abs(current[key] - previous[key]) / abs(previous[key]) if previous[key] != 0 else None
                rows.append(_row(case, label + " 인접 격자 상대 변화", expected=previous[key], actual=current[key],
                    error=change, state="observed", reason=previous_case["name"] + "와 비교. 격자 합격 임계값은 미정입니다."))
        value["validation_states"]["mesh"] = {"state": "observed_not_established",
            "reason": "동일 물리 조건의 세 격자를 비교했습니다. 경계/종료조건 축과 수렴 합격은 미확립입니다."}
    if comparisons:
        value["validation_states"]["independent_reference"] = {
            "state": "within_preliminary_reference" if len(comparisons) == 3 and all(c["passed"] for c in comparisons) else "requires_review",
            "reason": "이상 반파장 초도 모델과 실제 유한 반경 PEC 사례의 비교만 수행했습니다."}
        value["validation_states"]["termination"] = {"state": "recorded",
            "reason": "계산별 에너지 종료 기록입니다. 독립 시간 수렴 검증과 구분합니다.", "records": terminations}
    value.update(rows=rows, status="partial_evidence", created_at=service._now(), report_id=str(uuid4()),
                 assessment_hash=None, physics_validated=False)
    # @brief 보고서 본문의 self hash는 null이며 참조의 canonical hash로 무결성을 확인한다.
    encoded = canonical_bytes(bounded(value))
    if len(encoded) > 128 * 1024:
        fail("불변 판정 보고서가 128 KiB를 초과했습니다.", "E_RESOURCE")
    if record["usage"]["disk_bytes"] + len(encoded) > plan["budget"]["disk_bytes"]:
        fail("판정 보고서를 보존할 누적 디스크 예산이 부족합니다.", "E_RESOURCE")
    project = service._project(state, {"project_id": record["project_id"]})
    path = project["path"] + "/rf-validations/" + record["validation_id"] + "/reports/" + value["report_id"] + ".json"
    artifact = service.journal.put_immutable(path, encoded)
    report = {"report_id": value["report_id"], "created_at": value["created_at"], "status": value["status"],
              "assessment_hash": canonical_hash(value), "artifact": artifact}
    record["reports"].append(report)
    record["usage"]["disk_bytes"] += len(encoded)
    return {"validation_id": record["validation_id"], **report}
