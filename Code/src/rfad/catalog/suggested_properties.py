"""! @brief 적층에 정확히 대응한 관측의 공개값, 미정과 근사 필요 상태를 분리한다."""

from copy import deepcopy
import math

from rfad.catalog.selection_rules import adoption_blocks, conditions, incomplete_conditions


def missing_property(reason, *, state="missing", record_ids=()):
    """! @brief 값을 채우지 않고 누락 또는 모호성의 식별 정보를 반환한다."""
    return {"state": state, "value": None, "reason": reason, "conditions": {},
            "record_id": None, "candidate_record_ids": list(record_ids[:16]),
            "candidate_count": len(record_ids), "applicability": "not_assessed"}


def _scalar(value, field):
    """! @brief 미정, 불리언, 비유한값과 부호 오류를 공개 상수로 제안하지 않는다."""
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and (value > 0 if field == "dk" else value >= 0))
    except OverflowError:
        return False


def propose_property(reader, match, field):
    """! @brief 여러 후보는 임의 선택하지 않고 Dk/Df의 시험 조건을 각각 보존한다."""
    ids = match["record_ids"]
    if not ids:
        state = "unsupported" if match["state"] == "unsupported" else "missing"
        return missing_property(match["reason"], state=state)
    if len(ids) != 1:
        return missing_property("같은 층에 대응하는 관측이 여러 개입니다. 조건을 확인하고 직접 선택하십시오.",
                                state="ambiguous", record_ids=ids)
    row = reader.observation(ids[0])
    record = row["raw"]
    result = missing_property("원문에 해당 물성의 단일 수치가 없습니다.", record_ids=ids)
    result["record_id"] = ids[0]
    result["conditions"] = conditions(record, field)
    result["conditions"].update(
        frequency_min_ghz=record.get("frequency_min_ghz") if field == "dk" else None,
        frequency_max_ghz=record.get("frequency_max_ghz") if field == "dk" else None,
        frequency_text=record.get("df_frequency_text" if field == "df" else "frequency_text"),
        value_type=record.get("value_type"), dataset_role=record.get("dataset_role"))
    result["conditions"] = {key: value for key, value in result["conditions"].items() if value is not None}
    result["source"] = {"publisher": row["publisher"], "source_id": row["source_id"],
                        "source_location": record.get("source_location"), "raw_sha256": row["raw_sha256"]}
    blocks = adoption_blocks(record, field)
    result["review_reasons"] = blocks
    scalar = record.get(field)
    if "published_source_conflict" in blocks:
        result.update(state="ambiguous", reason="원문에 충돌 표시가 있습니다. 자동으로 값을 선택하지 않았습니다.")
    elif blocks:
        result.update(state="approximation_required", reported_value=scalar if _scalar(scalar, field) else None,
                      reason="범위, 한정자 또는 물리 모델 조건이 있어 근사값과 이유를 직접 입력해야 합니다.")
        result["reported_limits"] = {name: deepcopy(record.get(field + name))
                                     for name in ("_min", "_max", "_comparison", "_limit_operator")}
    elif _scalar(scalar, field):
        result.update(state="published", value=scalar,
                      reason="동일 적층 층의 공개값. 해석 대역 적합성은 미평가입니다.")
        if incomplete_conditions(record, field):
            result["reason"] += " 시험 조건에 미정 항목이 있습니다."
    elif scalar is not None:
        result["reason"] = "원문 수치의 타입 또는 범위가 올바르지 않아 미정으로 유지했습니다."
    return result


def property_choice(proposal):
    """! @brief 명시적으로 제안을 수용할 때 기존 공개 선택 계약으로 전달할 입력이다."""
    result = {"mode": "catalog" if proposal["state"] == "published" else "missing",
              "reason": proposal["reason"]}
    if proposal["record_id"] is not None:
        result["record_id"] = proposal["record_id"]
    return result
