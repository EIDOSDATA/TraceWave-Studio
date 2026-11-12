"""! @brief 템플릿 표시 입력을 명시 Quantity로 변환하고 원문과 구분한다."""

from copy import deepcopy

from rfad.domain.design import _fail, _fields
from rfad.domain.template_geometry import literal
from rfad.domain.units import Quantity, QuantityError


def normalize_inputs(card: dict, inputs: object) -> dict:
    """! @brief UI의 숫자 문자열 또는 기존 Quantity만 수용하여 SI로 한 번 변환한다."""
    descriptors = {item["key"]: item for item in card["input_fields"]}
    _fields(inputs, set(descriptors), "explicit_inputs")
    result = {}
    for key, descriptor in descriptors.items():
        value = inputs[key]
        field = "explicit_inputs." + key
        reference = card.get("reference_inputs", {}).get(key)
        if value == {"source": "card"} and reference is not None:
            result[key] = deepcopy(reference["quantity"])
            continue
        if type(value) is dict and set(value) == {"value", "unit"}:
            if type(value["value"]) is not str or not value["value"].strip() or len(value["value"]) > 128:
                _fail("E_UNIT", "숫자 표시 입력은 비어 있지 않은 문자열이어야 합니다.", field)
            try:
                normalized = Quantity.from_value(float(value["value"]), value["unit"]).to_dict()
            except (TypeError, ValueError, OverflowError, QuantityError):
                _fail("E_UNIT", "표시 입력의 숫자 또는 단위가 올바르지 않습니다.", field)
        else:
            normalized = deepcopy(value)
        literal({"parameters": {}}, normalized, descriptor["dimension"], field)
        if reference is not None:
            original = reference["quantity"]
            normalized["source_refs"] = list(dict.fromkeys([*normalized["source_refs"], *original["source_refs"]]))
            if normalized["value_si"] != original["value_si"] and normalized["status"] == "source_default":
                normalized["status"] = "user_entered"
        result[key] = normalized
    return result
