"""! @brief JLCPCB의 복합 코어를 분리하되 동박 포함 및 완성 두께를 추정하지 않는다."""

import re

from rfad.catalog.stackup_draft_common import finish, issue, layer, new_draft, object_raw, positive
from rfad.catalog.stackup_draft_jlc_evidence import capture_jlc_components


def convert_jlc(reader, template: dict, components: list[dict]) -> dict:
    """! @brief 명시한 코어 양면 구조만 풀고 두께의 알려진 값과 미정값을 구분한다."""
    draft = new_draft(reader, template, "native_templates")
    raw = object_raw(template)
    evidence_by_order = capture_jlc_components(reader, draft, template, components)
    draft["nominal_thickness_mm"] = positive(raw.get("plateThickness"))
    if template["kind"] == "jlc_user_defined_template":
        issue(draft, "user_defined_template", "원문은 사용자 정의 템플릿이며 제조업체 고정 제작 사양이 아닙니다.")
    for row in components:
        value = object_raw(row)
        order = row["component_order"]
        evidence = evidence_by_order[order]
        thickness_pointer = "/basicDataList/" + str(order) + "/dielectricThick"
        key = "component:" + str(order)
        material = value.get("material")
        label = value.get("layerName")
        label = label if type(label) is str and label else material
        if material == "Copper":
            layer(draft, key, str(label), "conductor", None, "copper_finished_thickness_unspecified", evidence, order)
            issue(draft, "copper_finished_thickness_unknown", "원문의 동박 수치는 보존했으나 도금 후 완성 두께인지 확인되지 않았습니다.", [key])
        elif material in ("Core", "Prepreg"):
            dielectric_key = key + ":dielectric"
            thickness = positive(value.get("dielectricThick"))
            name = value.get("materialName")
            contradiction = (type(name) is str and re.search(r"\bwith copper\b", name, re.IGNORECASE) is not None)
            explicit_exclusion = value.get("plateContainCopper") is False
            if not explicit_exclusion or contradiction:
                thickness = None
                issue(draft, "copper_inclusion_unresolved", "유전체 수치에 동박이 포함되는지 확정할 수 없어 두께를 미정으로 남겼습니다.", [dielectric_key])
            elif thickness is None:
                issue(draft, "dielectric_thickness_missing", "원문에 사용할 수 있는 양의 유전체 두께가 없습니다.", [dielectric_key])
            if material == "Core":
                if type(value.get("layerName")) is not str or re.fullmatch(r"L[1-9][0-9]*/L[1-9][0-9]*", value["layerName"]) is None:
                    issue(draft, "core_faces_unidentified", "복합 코어의 양면 도체 이름이 명시되지 않았습니다. 층 구성을 직접 정의하십시오.", blocker=True)
                    continue
                top, bottom = value["layerName"].split("/")
                layer(draft, key + ":top", top, "conductor", None, "core_copper_finished_thickness_unspecified", evidence, order)
                layer(draft, dielectric_key, "Core " + str(order + 1), "dielectric", thickness,
                      "source_dielectric_excluding_copper" if thickness is not None else "core_copper_inclusion_unresolved", evidence, order,
                      thickness_pointer=thickness_pointer)
                layer(draft, key + ":bottom", bottom, "conductor", None, "core_copper_finished_thickness_unspecified", evidence, order)
                issue(draft, "copper_finished_thickness_unknown", "코어 양면 구리 수치는 근거로 남겼으나 완성 도체 두께로 자동 채택하지 않았습니다.", [key + ":top", key + ":bottom"])
            else:
                layer(draft, dielectric_key, "Prepreg " + str(order + 1), "dielectric", thickness,
                      "source_dielectric_excluding_copper" if thickness is not None else "dielectric_thickness_unresolved", evidence, order,
                      thickness_pointer=thickness_pointer)
        else:
            issue(draft, "unsupported_component", "지원하지 않는 원문 구성 요소가 있습니다. 전체 층 구성을 직접 정의하십시오.", blocker=True)
    if not components:
        issue(draft, "empty_native_components", "원문 템플릿에 층 구성 행이 없습니다.", blocker=True)
    return finish(draft, raw.get("plateLayerNumber"), require_count=True)
