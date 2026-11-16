"""! @brief 설계 규칙 원본을 단위/입력 상태/출처를 유지한 작은 편집 폼으로 표시한다."""

from copy import deepcopy

from rfad.application.editor import _display_quantity
from rfad.application.target_editor_fields import field
from rfad.domain.design_rules import RULES, CONNECTION_KINDS
from rfad.domain.target_constraints import BOARD_LIMITS, empty_constraints
from rfad.domain.units import Quantity, units_for_dimension
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import object_label


SECTIONS = ("target","parameter","connection","manufacturing_profile")


def selected(document, selection):
    """! @brief 명시한 안정 ID만 조회하며 실패 시 다른 실제 대상으로 대체하지 않는다."""
    section = selection["section"]
    identity, target_id, parameter_id = (selection[key] for key in ("record_id","target_id","parameter_id"))
    target = next((row for row in document["targets"] if row["id"] == target_id),None)
    parameter = document["parameters"].get(parameter_id)
    if target_id is not None and target is None or parameter_id is not None and parameter is None:
        raise ProjectError("E_CONFLICT","목표/매개변수 선택 대상이 없습니다.")
    if section == "target":
        return (None if target is None else target.get("constraints")),target,parameter
    if section == "parameter":
        bounds = [] if target is None else target.get("constraints",{}).get("parameter_bounds",[])
        return next((row for row in bounds if row["parameter_id"] == parameter_id),None),target,parameter
    collection = "connections" if section == "connection" else "manufacturing_profiles"
    original = next((row for row in document[collection] if row["id"] == identity),None)
    if identity is not None and original is None:
        raise ProjectError("E_CONFLICT","선택한 설계 규칙이 없습니다.")
    return original,target,parameter


def blank(section, parameter=None):
    """! @brief 실제 미정과 제약 없음만 지정하고 수치/연결 의도를 자동 완성하지 않는다."""
    if section == "target":
        return empty_constraints()
    if section == "parameter":
        if parameter is None:
            return None
        quantity = parameter["quantity"]
        empty = Quantity(None,quantity["dimension"],quantity["display_unit"],"not_applicable",[]).to_dict()
        return {"parameter_id":parameter["id"],"minimum":empty,"maximum":deepcopy(empty),"integer":False,"source_refs":[]}
    if section == "connection":
        return {"id":None,"name":"","kind":"","object_ids":[None,None],"source_refs":[]}
    return {"id":None,"name":"","version":"","source_refs":[],
            "rules":{key:Quantity.missing(dimension,"mm" if dimension == "length" else "1").to_dict() for key,(_,dimension) in RULES.items()}}


def quantity_fields(raw,key,label):
    """! @brief 숫자와 단위를 같은 행에 표시하고 단위만 바꿀 때의 원본 유지 정책을 알린다."""
    number,unit,note = _display_quantity(Quantity(**raw))
    modes = (("value","직접 입력"),("missing","한계 미정"),("not_applicable","적용 안 함"))
    units = [(name,name) for name in units_for_dimension(raw["dimension"])]
    return [field(key+".mode",label+" 지정",raw["status"] if raw["status"] == "not_applicable" else ("missing" if raw["value_si"] is None else "value"),editor="choice",choices=modes),
            field(key+".value",label,number),field(key+".unit",label+" 단위",unit,editor="choice",choices=units),
            field(key+".status",label+" 원래 상태",raw["status"],readonly=True),
            field(key+".source_refs",label+" 출처",raw["source_refs"],editor="string_lines",readonly=True),
            field(key+".display_note",label+" 안내",note,readonly=True)]


def forms(document,selection):
    """! @brief 현재 한 섹션의 편집 필드와 원본을 반환한다."""
    original,target,parameter = selected(document,selection)
    section = selection["section"]
    record = deepcopy(original) if original is not None else blank(section,parameter)
    if record is None or section in ("target","parameter") and target is None:
        return [],original,record
    if section == "target":
        fields = [item for key,label in BOARD_LIMITS.items() for item in quantity_fields(record[key],key,label)]
        fields.append(field("manufacturing_profile_id","연결할 제조 규칙",record["manufacturing_profile_id"] or "",editor="choice",
                            choices=[("","지정 안 함")]+[(row["id"],row["name"]+" / "+row["version"]) for row in document["manufacturing_profiles"]]))
    elif section == "parameter":
        fields = quantity_fields(record["minimum"],"minimum","하한") + quantity_fields(record["maximum"],"maximum","상한")
        fields.append(field("integer","무차원 정수 제약",record["integer"],editor="bool"))
    elif section == "connection":
        labels = ("연결 필요","의도적 분리","기생 도체의 DC 분리")
        fields = [field("name","연결 의도 이름",record["name"]),field("kind","연결 의도",record["kind"],editor="choice",
                  choices=[("","선택 필요")]+list(zip(CONNECTION_KINDS,labels)))]
        choices = [("","미정")]+[(row["id"],object_label(document,row)) for row in document["geometry"]]
        fields += [field("object_a","첫 도체",record["object_ids"][0] or "",editor="choice",choices=choices),
                   field("object_b","둘째 도체",record["object_ids"][1] or "",editor="choice",choices=choices)]
    else:
        fields = [field("name","규칙 이름",record["name"]),field("version","자료/프로젝트 규칙 버전",record["version"])]
        fields += [item for key,(label,_) in RULES.items() for item in quantity_fields(record["rules"][key],key,label)]
    fields.append(field("source_refs","원래 출처/변경 사유",record["source_refs"],editor="string_lines",readonly=True))
    return fields,original,record
