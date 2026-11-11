"""! @brief 업체 적층의 정확한 원문 층과 물성 관측을 연결하며 유사 재질을 추정하지 않는다."""

import re

from rfad.catalog.models import CatalogError, canonical_json


def _result(state: str, reason: str, record_ids=None) -> dict:
    """! @brief 원문 대응의 결과만 반환하고 물성 채택이나 프로젝트 변경은 하지 않는다."""
    return {"record_ids": [] if record_ids is None else sorted(record_ids), "state": state, "reason": reason}


def _verify_component(template: dict, component: dict, rows: list, family: str) -> None:
    """! @brief 개별 행의 소속, 위치 및 원문이 부모 템플릿과 정확히 같은지 확인한다."""
    order = component.get("component_order")
    if type(order) is not int or not 0 <= order < len(rows):
        raise CatalogError("E_HASH", "적층 구성 행의 원문 순서가 올바르지 않습니다.")
    if component.get("template_id") != template["template_id"]:
        raise CatalogError("E_HASH", "적층 구성 행이 다른 템플릿에 속합니다.")
    for field in ("stackup_id", "publisher", "source_id", "source_path", "source_sha256"):
        if component.get(field) != template.get(field):
            raise CatalogError("E_HASH", "적층 구성 행과 부모의 출처가 다릅니다.")
    expected = template["source_pointer"] + ("/basicDataList/" if family == "jlc" else "/rows/") + str(order)
    if component.get("source_pointer") != expected or canonical_json(component["raw"]) != canonical_json(rows[order]):
        raise CatalogError("E_HASH", "적층 구성 행의 위치 또는 원문이 부모 템플릿과 다릅니다.")


def _jlc_matches(template: dict, component: dict, record: dict) -> bool:
    """! @brief JLC 원문의 템플릿 ID, 배열 위치, 재질 이름과 종류를 동시에 대응한다."""
    value, raw = component["raw"], record["raw"]
    pointer = re.fullmatch(r"/body/list/([0-9]+)", template["source_pointer"])
    form = {"Core": "core", "Prepreg": "prepreg"}.get(value.get("material"))
    if pointer is None or form is None:
        return False
    location = "; body.list[" + pointer[1] + "].basicDataList[" + str(component["component_order"]) + "]"
    return (raw.get("manufacturer") == "JLCPCB"
            and raw.get("public_template_id") == template["template_key"]
            and type(raw.get("layer_index")) is int and raw["layer_index"] == component["component_order"]
            and raw.get("material_form") == form
            and type(value.get("materialName")) is str and raw.get("material_name") == value["materialName"]
            and raw.get("source_file") == template["source_path"]
            and type(raw.get("source_location")) is str and raw["source_location"].endswith(location))


def _pcbway_matches(template: dict, component: dict, record: dict) -> bool:
    """! @brief PCBWay 적층 ID와 원문 표의 1 기반 행 번호를 정확하게 대응한다."""
    value, raw = component["raw"], record["raw"]
    if type(value) is not list or len(value) < 2:
        return False
    form = {"PP": "prepreg", "CORE": "core"}.get(value[0])
    sequence = component["component_order"] + 1
    return (form is not None and raw.get("manufacturer") == "PCBWay"
            and raw.get("stackup_id") == template["template_key"]
            and type(raw.get("layer_sequence")) is int and raw["layer_sequence"] == sequence
            and raw.get("material_form") == form
            and raw.get("source_location") == template["template_key"] + "; table row " + str(sequence))


def _native_dk(component: dict, family: str):
    """! @brief 원문 Dk의 정확한 필드를 확인하며 문자열 범위나 한정자를 수치로 축약하지 않는다."""
    value = component["raw"]
    if family == "jlc":
        number = value.get("dielectricConstant")
        return number if type(number) in (int, float) else None
    if type(value) is not list or len(value) < 2 or type(value[1]) is not str:
        return None
    found = re.search(r"(?:^|\s)DK\s*:\s*([0-9]+(?:\.[0-9]+)?)(?:\s|$)", value[1], re.IGNORECASE)
    return float(found[1]) if found is not None else None


def _native_records(reader, source: dict, draft: dict) -> dict:
    """! @brief 지원 업체의 구조만 조회하며 중복 관측을 임의로 하나로 선택하지 않는다."""
    template = reader.native_template(source["id"])
    family = {("JLCPCB", "jlc_named_template"): "jlc", ("PCBWay", "pcbway_published_template"): "pcbway"}.get(
        (template["publisher"], template["kind"]))
    layers = [layer for layer in draft["layers"] if layer["role"] == "dielectric"]
    if family is None or type(template.get("stackup_id")) is not str:
        reason = ("사용자 정의 템플릿은 고정 제작 사양이 아니며 연결된 물성 관측이 없습니다. 원문 표시값을 자동 채택하지 않았습니다."
                  if template["kind"] == "jlc_user_defined_template" else
                  "고정 공개 적층에 정확히 대응하는 물성 관측을 지원하지 않습니다.")
        return {layer["key"]: _result("unsupported", reason) for layer in layers}
    rows = template["raw"].get("basicDataList" if family == "jlc" else "rows")
    if type(rows) is not list:
        raise CatalogError("E_SCHEMA", "적층 원문의 구성 행 배열이 없습니다.")
    components = reader.native_components(source["id"])
    by_order = {}
    for component in components:
        _verify_component(template, component, rows, family)
        order = component["component_order"]
        if order in by_order:
            raise CatalogError("E_HASH", "적층 원문의 구성 행 순서가 중복됩니다.")
        by_order[order] = component
    records = reader.stackup_observations(template["stackup_id"], template["publisher"], template["source_id"])
    output = {}
    for layer in layers:
        key = layer["key"]
        match = re.fullmatch(r"component:([0-9]+)(:dielectric)?", key)
        component = by_order.get(int(match[1])) if match is not None else None
        if component is None:
            output[key] = _result("missing", "유전체 층과 원문 구성 행을 정확히 연결할 수 없습니다.")
            continue
        predicate = _jlc_matches if family == "jlc" else _pcbway_matches
        candidates = [record for record in records if predicate(template, component, record)]
        if not candidates:
            output[key] = _result("missing", "같은 적층과 원문 층의 물성 관측이 없습니다. 직접 입력할 수 있습니다.")
        elif len(candidates) == 1 and candidates[0]["raw"].get("dk") != _native_dk(component, family):
            output[key] = _result("unsupported", "원문 층과 정리된 관측의 Dk가 달라 자동 제안하지 않았습니다.")
        else:
            output[key] = _result("matched", "같은 적층 ID, 출처와 원문 층 위치가 일치합니다.",
                                  [record["record_id"] for record in candidates])
    return output


def resolve_layer_records(reader, source: dict, draft: dict) -> dict:
    """! @brief 유전체 층 key별 정확한 관측 후보를 반환한다.

    @return 각 값은 record_ids, state(matched/missing/unsupported), reason을 가진다.
    @details 두께는 입력 draft의 검토 결과를 사용하며 이 연결기가 복원하거나 추정하지 않는다.
    """
    if source["catalog_id"] != draft["catalog_id"] or source["catalog_id"] != reader.catalog()["catalog_id"]:
        raise CatalogError("E_CONFLICT", "적층 초안과 물성 제안의 카탈로그 개정이 다릅니다.")
    identity_field = "template_id" if source["entity"] == "native_templates" else "record_id"
    if source["id"] != draft[identity_field]:
        raise CatalogError("E_CONFLICT", "적층 초안과 물성 제안의 원문 선택이 다릅니다.")
    if source["entity"] == "native_templates":
        return _native_records(reader, source, draft)
    record = reader.observation(source["id"])
    raw = record["raw"]
    supported = (record["publisher"] == "OSH Park" and raw.get("manufacturer") == "OSH Park"
                 and raw.get("stackup_id") == "OSH_2L_1.6" and raw.get("record_kind") == "published_stackup_layer"
                 and raw.get("material_form") == "core" and raw.get("layer") == "L1-L2"
                 and raw.get("dataset_role") == "fabricator_published_parameter")
    return {layer["key"]: (_result("matched", "선택한 2층 코어 관측 자체를 제안합니다.", [source["id"]])
                            if supported else _result("unsupported", "이 관측만으로 정확한 기판 유전체 층을 연결할 수 없습니다."))
            for layer in draft["layers"] if layer["role"] == "dielectric"}
