"""! @brief 독립된 물성 선택을 프로젝트 재료와 역사적 선택 근거로 변환한다."""

import math
from uuid import UUID

from rfad.catalog.models import CatalogError, canonical_json
from rfad.catalog.selection_reader import SelectionReader
from rfad.catalog.selection_rules import adoption_blocks, conditions, incomplete_conditions
from rfad.domain.material_models import LEGACY_MODEL, MATERIAL_MODELS
from rfad.domain.units import Quantity


PROPERTY_FIELDS = {"epsilon_r": ("dk", "dimensionless", "1"),
                   "tan_delta": ("df", "dimensionless", "1"),
                   "conductivity": (None, "conductivity", "S/m")}


def _fields(value: object, required: set[str], optional: set[str] | None = None) -> dict:
    """! @brief 요청이 원문이나 임의 프로젝트 필드를 직접 주입하지 못하게 한다."""
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise CatalogError("E_SCHEMA", "재료 선택의 필드 구성이 잘못되었습니다.")
    return value


def _text(value: object, field: str, maximum: int = 512) -> str:
    """! @brief 사용자가 명시한 이름과 선택 이유를 제한된 문자열로 확인한다."""
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise CatalogError("E_SCHEMA", "재료 선택에 명시적인 문자열이 필요합니다.", details={"field": field})
    return value


def _number(value: object, field: str, *, positive: bool = False) -> float:
    """! @brief 참거짓, 비유한 수와 물성의 부호 오류를 수치로 채택하지 않는다."""
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or value < 0 or (positive and value == 0):
        raise CatalogError("E_SCHEMA", "재료 선택의 수치가 유효하지 않습니다.", details={"field": field})
    return float(value)


def _decision(identity: str, field: str, basis: str, value: dict, reason: str,
              evidence: dict | None = None, pointer: str | None = None) -> dict:
    """! @brief 출처 원문과 적용 당시 수량을 서로 다른 기록으로 보존한다."""
    return {"target": {"collection": "materials", "id": identity, "field": field},
            "basis": basis, "evidence_id": None if evidence is None else evidence["id"],
            "source_pointer": pointer, "value_json": canonical_json(value), "reason": reason}


def _issue(code: str, field: str, message: str) -> dict:
    """! @brief 선택 성공과 물리 검증 성공을 구분하는 검토 사항을 반환한다."""
    return {"code": code, "severity": "warning", "field": field, "message": message}


def _property(field: str, choice: dict, identity: str, reader: SelectionReader | None) -> tuple:
    """! @brief 물성 하나만 선택하며 다른 물성이나 주파수를 자동으로 채택하지 않는다."""
    _fields(choice, {"mode", "reason"}, {"value", "record_id"})
    mode = choice["mode"]
    reason = _text(choice["reason"], field + ".reason")
    if mode not in ("catalog", "user", "missing"):
        raise CatalogError("E_SCHEMA", "지원하지 않는 물성 선택 방식입니다.")
    if (mode == "user") != ("value" in choice):
        raise CatalogError("E_SCHEMA", "직접 입력 방식에만 명시적인 값이 필요합니다.")
    source_field, dimension, unit = PROPERTY_FIELDS[field]
    record = evidence = None
    if "record_id" in choice:
        if reader is None:
            raise CatalogError("E_RESOURCE", "출처가 있는 선택에는 카탈로그가 필요합니다.")
        record_id = _text(choice["record_id"], field + ".record_id", 256)
        row, evidence, _ = reader.snapshot_observation(record_id)
        record = row["raw"]
        if not isinstance(record, dict):
            raise CatalogError("E_SCHEMA", "물성 관측 원문은 객체여야 합니다.")
    if mode == "catalog" and (record is None or source_field is None):
        raise CatalogError("E_SCHEMA", "카탈로그에서는 Dk와 Df의 명시적인 관측만 선택할 수 있습니다.")
    references = () if evidence is None else (evidence["id"],)
    pointer = "/" + source_field if record is not None and source_field in record else None
    issues = []
    if mode == "missing":
        value = Quantity.missing(dimension, unit).to_dict()
        value["source_refs"] = list(references)
        basis = "missing"
    elif mode == "catalog":
        blocks = adoption_blocks(record, source_field)
        if blocks:
            raise CatalogError("E_UNSUPPORTED", "이 관측은 상수 물성으로 직접 채택할 수 없습니다. 명시적인 사용자 근사와 이유가 필요합니다.",
                               details={"field": field, "record_id": choice["record_id"], "review_reasons": blocks})
        number = _number(record.get(source_field), field, positive=field == "epsilon_r")
        value = Quantity.from_value(number, unit, status="source_default", source_refs=references).to_dict()
        basis = "published"
    else:
        number = _number(choice["value"], field, positive=field == "epsilon_r")
        value = Quantity.from_value(number, unit, source_refs=references).to_dict()
        basis = "user_override" if evidence is not None else "user_assumption"
        if record is not None and source_field is not None and adoption_blocks(record, source_field):
            issues.append(_issue("W_EXPLICIT_MATERIAL_APPROXIMATION", field,
                                 "미지원 또는 한정된 원문을 사용자가 명시적으로 근사했습니다. 물리 검증 승인이 아닙니다."))
    if record is not None and source_field is not None and incomplete_conditions(record, source_field):
        issues.append(_issue("W_SOURCE_CONDITIONS_INCOMPLETE", field,
                             "원문 주파수, 시험법 또는 방향에 미정 조건이 있습니다. 다른 물성의 조건으로 채우지 않았습니다."))
    decision = _decision(identity, field, basis, value, reason, evidence, pointer)
    return value, decision, record, issues


def build_material(spec: dict, reader: SelectionReader | None) -> dict:
    """! @brief 명시적인 입력만으로 재료와 선택 기록을 만들며 프로젝트를 변경하지 않는다.

    @param spec key/id/name/properties/validity_hz를 가진 재료 입력이며 UUID는 호출자가 주입한다.
    @param reader 같은 카탈로그 개정을 읽는 선택 reader이다. 완전 수동 입력은 None을 허용한다.
    @return key, material, decisions, issues를 반환한다. 근거는 공유 reader에 중복 없이 누적한다.
    """
    _fields(spec, {"key", "id", "name", "properties", "validity_hz"}, {"model", "model_reason"})
    if ("model" in spec) != ("model_reason" in spec):
        raise CatalogError("E_SCHEMA", "손실 모델을 선택할 때 모델과 이유를 함께 지정하십시오.")
    model = spec.get("model", LEGACY_MODEL)
    if type(model) is not str or model not in MATERIAL_MODELS:
        raise CatalogError("E_UNSUPPORTED", "지원하지 않는 재료 손실 모델입니다.")
    key = _text(spec["key"], "key", 128)
    identity = _text(spec["id"], "id", 36)
    try:
        if str(UUID(identity)) != identity:
            raise ValueError("noncanonical UUID")
    except ValueError as error:
        raise CatalogError("E_SCHEMA", "재료에 정규 UUID가 필요합니다.") from error
    name = _text(spec["name"], "name", 256)
    _fields(spec["properties"], set(PROPERTY_FIELDS))
    validity = _fields(spec["validity_hz"], {"min", "max", "reason"})
    validity_reason = _text(validity["reason"], "validity_hz.reason")
    material = {"id": identity, "name": name, "model": model,
                "source_refs": [], "assumptions": [], "validity_hz": {}}
    decisions, issues, records = [], [], {}
    if "model" in spec:
        model_reason = _text(spec["model_reason"], "model_reason")
        decisions.append(_decision(identity, "model", "user_assumption", model, model_reason))
        material["assumptions"].append("model: " + model_reason)
    for field in PROPERTY_FIELDS:
        value, decision, record, warnings = _property(field, spec["properties"][field], identity, reader)
        material[field] = value
        material["source_refs"].extend(value["source_refs"])
        material["assumptions"].append(field + ": " + decision["reason"])
        decisions.append(decision)
        issues.extend(warnings)
        records[field] = record
    for boundary in ("min", "max"):
        field = "validity_hz." + boundary
        if validity[boundary] is None:
            value = Quantity.missing("frequency", "Hz").to_dict()
            basis = "missing"
        else:
            value = Quantity.from_value(_number(validity[boundary], field, positive=True), "Hz").to_dict()
            basis = "user_assumption"
        material["validity_hz"][boundary] = value
        decisions.append(_decision(identity, field, basis, value, validity_reason))
    lower, upper = (material["validity_hz"][field]["value_si"] for field in ("min", "max"))
    if lower is not None and upper is not None and lower > upper:
        raise CatalogError("E_SCHEMA", "사용자가 지정한 적용 대역의 하한이 상한보다 큽니다.")
    material["source_refs"] = list(dict.fromkeys(material["source_refs"]))
    material["assumptions"].append("validity_hz: " + validity_reason)
    if records["epsilon_r"] is not None and records["tan_delta"] is not None:
        if conditions(records["epsilon_r"], "dk") != conditions(records["tan_delta"], "df"):
            issues.append(_issue("W_INDEPENDENT_PROPERTY_CONDITIONS", "properties",
                                 "Dk와 Df의 원문 조건이 다릅니다. 각 선택을 독립적으로 보존했으며 같은 측정 쌍으로 확정하지 않았습니다."))
    if material["source_refs"]:
        issues.append(_issue("W_USER_DEFINED_MODEL_BAND", "validity_hz",
                             "적용 대역은 사용자의 상수 모델 가정이며 원문의 보증 대역을 확장한 것이 아닙니다."))
    return {"key": key, "material": material, "decisions": decisions, "issues": issues}
