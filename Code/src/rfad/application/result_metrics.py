"""! @brief 기록된 NF2FF 전력과 독립 손실을 분모 및 미확립 상태와 함께 표시한다."""

from copy import deepcopy
import json
import math

from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_power import validate_result as validate_balance
from rfad.application.result_radiation import request, load
from rfad.application.result_sources import resolve, read_solver_artifact
from rfad.domain.errors import ProjectError


def _table(rows):
    """! @brief 표의 항목과 단위 및 근거를 계산 서비스에서 결정한다."""
    labels = (("incident", "입사 전력", "W*s^2"), ("reflected", "반사 전력", "W*s^2"),
              ("accepted", "수용 전력", "W*s^2"), ("radiated", "방사 전력", "W*s^2"),
              ("radiation_efficiency", "방사 효율", "%"), ("total_efficiency", "총 효율", "%"),
              ("directivity_dbi", "최대 지향성", "dBi"), ("gain_dbi", "최대 이득", "dBi"),
              ("realized_gain_dbi", "최대 실현 이득", "dBi"), ("residual", "전력 수지 잔차", "W*s^2"),
              ("relative_residual", "수용 전력 대비 잔차", "%"))
    result = []
    for row in rows:
        for key, label, unit in labels:
            value = row.get(key)
            state = row.get(key + "_state", "computed_unvalidated" if value is not None else "not_recorded")
            if value is not None and unit == "%":
                value *= 100
                if not math.isfinite(value):
                    value, state = None, "overflow"
            result.append({"frequency_hz": row["frequency_hz"], "key": key, "label": label,
                           "value": value, "unit": unit, "state": state,
                           "denominator": {"radiation_efficiency": "accepted", "total_efficiency": "incident",
                                           "relative_residual": "accepted"}.get(key)})
        for loss in row["independent_losses"]:
            result.append({"frequency_hz": row["frequency_hz"], "key": loss["key"], "label": loss["label"],
                           "value": loss["value"], "unit": "W*s^2", "state": "computed_unvalidated", "denominator": None})
    return result


def metrics(service, params):
    """! @brief 실제 기록 주파수의 비율만 반환하고 S11만 있는 자료에 효율을 만들지 않는다."""
    data = request(params)
    resolved = resolve(service, params["context"], data["source"], data["pin"])
    result = {"profile": "rfad.result-metrics/0.1", "source": deepcopy(resolved["source"]), "pin": deepcopy(resolved["pin"]),
              "rows": [], "table_rows": [], "states": deepcopy(resolved["states"]), "source_refs": [],
              "warnings": [], "physics_validated": False, "status": "unavailable", "interpolation": "none",
              "port_series_source": "result.page", "power_unit": "W*s^2", "absolute_power_w": None}
    if resolved["solver_record"] is None:
        result["warnings"].append("이 자료에는 같은 계산에서 얻은 NF2FF 전력 기록이 없습니다. S11에서 방사 효율을 추정하지 않습니다.")
        return result
    try:
        radiation, reference = load(service, resolved)
    except ProjectError as error:
        if error.code != "E_MISSING_ARTIFACT":
            raise
        result["warnings"].append("선택한 계산은 방사를 기록하지 않았습니다. 효율 표본과 독립 손실은 미기록 상태입니다.")
        return result
    normalized = resolved["normalized"]
    result["reference_scope"] = deepcopy(normalized.get("reference_scope"))
    balance = normalized.get("power_balance")
    result["source_refs"].append(reference)
    if balance is not None:
        refs = [item["artifact"] for item in resolved["solver_record"]["files"] if item["role"] == "power_balance_result"]
        if len(refs) != 1:
            raise ProjectError("E_HASH", "독립 손실 원본 참조를 확인할 수 없습니다.")
        original = json.loads(read_solver_artifact(service, resolved["project"], resolved["solver_record"], refs[0]))
        if original != balance:
            raise ProjectError("E_HASH", "별도 손실 원본과 해석 결과 요약이 다릅니다.")
        validate_balance(normalized["provenance"]["analysis_plan"], original, radiation)
        result["source_refs"].append(deepcopy(refs[0]))
    by_frequency = {row["frequency_hz"]: row for row in balance["frequencies"]} if balance is not None else {}
    for field in radiation["frequencies"]:
        power = field["metrics"]
        incident, accepted, radiated = (power[name + "_power_w_s2"] for name in ("incident", "accepted", "radiated"))
        total_efficiency = radiated / incident
        total_state = "computed_unvalidated" if math.isfinite(total_efficiency) else "overflow"
        row = {"frequency_hz": field["frequency_hz"], "power_unit": "W*s^2", "absolute_power_w": None,
               "incident": incident, "reflected": incident - accepted, "accepted": accepted, "radiated": radiated,
               "independent_losses": [], "residual": None, "relative_residual": None,
               "radiation_efficiency": power["radiation_efficiency"],
               "total_efficiency": total_efficiency if total_state != "overflow" else None,
               "total_efficiency_state": total_state,
               "directivity_dbi": power["directivity_dbi"], "gain_dbi": power["gain_dbi"],
               "realized_gain_dbi": power["realized_gain_dbi"], "status": "computed_unvalidated",
               "numerical_balance_status": "not_recorded", "power_order_status": power["power_balance_status"],
               "reasons": [], "source_refs": deepcopy(result["source_refs"])}
        independent = by_frequency.get(field["frequency_hz"])
        if independent is not None:
            row.update(residual=independent["residual_w_s2"], relative_residual=independent["relative_residual"],
                       numerical_balance_status=independent["status"])
            for key, label in (("dielectric_loss_w_s2", "유전체 독립 손실"), ("conductor_loss_w_s2", "도체 독립 손실"),
                               ("sheet_loss_w_s2", "박막 도체 손실"), ("via_loss_w_s2", "비아 체적 손실")):
                if key in independent:
                    row["independent_losses"].append({"key": key, "label": label, "value": independent[key],
                                                       "state": "computed_unvalidated"})
        else:
            row["reasons"].append("독립 흡수 적분 미기록. 수용 전력과 방사 전력의 차이를 개별 손실로 분배하지 않습니다.")
        if power["power_balance_status"] == "requires_review":
            row["reasons"].append("전력 순서 또는 효율에 검토가 필요합니다. 원래 값을 잘라 보정하지 않았습니다.")
        if total_state == "overflow":
            row["reasons"].append("총 효율이 표시 숫자의 표현 범위를 초과했습니다. 원래 입사 전력과 방사 전력은 보존했습니다.")
        result["rows"].append(row)
    result.update(table_rows=_table(result["rows"]), status="computed_unvalidated")
    result["warnings"] = ["펄스 Fourier 전력 단위는 W*s^2입니다. 절대 연속파 전력 W는 미정입니다.",
                          "효율 곡선은 기록한 주파수만 표시합니다. 표본 사이의 대역 성능을 검증한 것이 아닙니다.",
                          "전력 수지의 초기 수치 기준 통과는 개별 손실, 제작 또는 실측 정확도 합격을 뜻하지 않습니다."]
    if any(row["state"] == "overflow" for row in result["table_rows"]):
        result["warnings"].append("표현 범위를 초과한 비율 또는 백분율은 수치 없이 별도 상태로 표시합니다. 원래 전력과 유한 비율은 보존했습니다.")
    if len(canonical_bytes(result)) > 256 * 1024:
        raise ProjectError("E_RESOURCE", "전력 표시 응답이 전송 상한을 초과했습니다.")
    return result
