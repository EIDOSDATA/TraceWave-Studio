"""! @brief 변경한 규칙 필드만 서비스에서 환산하고 미수정 SI/출처/미정 상태를 보존한다."""

from copy import deepcopy

from rfad.application.design_rule_forms import forms
from rfad.application.target_editor_values import fail,number,sources
from rfad.domain.design_rules import RULES
from rfad.domain.target_constraints import BOARD_LIMITS
from rfad.domain.units import Quantity,QuantityError,units_for_dimension


def quantity(original,prefix,values,changed,reason):
    """! @brief 단위만 바꾼 값과 직접 수치 변경을 구분한다."""
    local = {key[len(prefix)+1:] for key in changed if key.startswith(prefix+".")}
    if not local:
        return deepcopy(original)
    mode,unit = values[prefix+".mode"],values[prefix+".unit"]
    if unit not in units_for_dimension(original["dimension"]):
        fail("수량 차원과 단위가 다릅니다.",prefix+".unit","E_UNIT")
    if mode not in ("value","missing","not_applicable") or mode != "value" and "value" in local:
        fail("숫자 변경은 직접 입력을 명시한 경우에만 가능합니다.",prefix+".mode")
    try:
        if local == {"unit"}:
            return Quantity(original["value_si"],original["dimension"],unit,original["status"],original["source_refs"]).to_dict()
        refs = sources(original["source_refs"],reason)
        if mode != "value":
            return Quantity(None,original["dimension"],unit,mode,refs).to_dict()
        numeric = number(values[prefix+".value"],prefix+".value")
        return Quantity.from_value(numeric,unit,status="user_entered",source_refs=refs).to_dict()
    except QuantityError as error:
        fail(str(error),prefix+".value","E_UNIT")


def edited(document,selection,changes,reason):
    """! @brief 읽기 전용 출처 필드나 임의 키로 원본을 덮어쓰지 못하게 한다."""
    descriptors,original,record = forms(document,selection)
    if record is None or not descriptors:
        fail("목표와 매개변수를 먼저 선택하십시오.","selection","E_CONFLICT")
    fields = {row["key"]:row for row in descriptors}
    values = {key:deepcopy(row["value"]) for key,row in fields.items()}
    changed = set()
    for key,value in changes.items():
        descriptor = fields.get(key)
        if descriptor is None or descriptor["readonly"]:
            fail("알 수 없거나 읽기 전용인 규칙 필드입니다.",key)
        if type(value) is not (bool if descriptor["editor"] == "bool" else str):
            fail("편집 값의 형식이 다릅니다.",key)
        if descriptor["editor"] == "choice" and value not in {row["value"] for row in descriptor["choices"]}:
            fail("지원하는 선택값이 아닙니다.",key)
        if value != values[key]:
            values[key] = value
            changed.add(key)
    section = selection["section"]
    if section == "target":
        for key in BOARD_LIMITS:
            record[key] = quantity(record[key],key,values,changed,reason)
        record["manufacturing_profile_id"] = values["manufacturing_profile_id"] or None
    elif section == "parameter":
        for key in ("minimum","maximum"):
            record[key] = quantity(record[key],key,values,changed,reason)
        record["integer"] = values["integer"]
    elif section == "connection":
        record.update(name=values["name"],kind=values["kind"],object_ids=[values["object_a"] or None,values["object_b"] or None])
    else:
        record.update(name=values["name"],version=values["version"])
        for key in RULES:
            record["rules"][key] = quantity(record["rules"][key],key,values,changed,reason)
    if original is not None and record == original:
        fail("변경한 규칙 입력이 없습니다.","values","E_CONFLICT")
    record["source_refs"] = sources(record["source_refs"],reason)
    return record
