"""! @brief PCBWay 압착 합계를 개별 물리 층의 두께로 복제하지 않는 변환기이다."""

import re

from rfad.catalog.stackup_draft_common import capture, decimal_mm, finish, issue, layer, new_draft, object_raw


def convert_pcbway(reader, template: dict, components: list[dict]) -> dict:
    """! @brief 층별 압착 수치만 사용하고 코어 합계와 외층 도금량은 미정으로 둔다."""
    draft = new_draft(reader, template, "native_templates")
    raw = object_raw(template)
    group_evidence = capture(reader, draft, "native_templates", template["template_id"],
                             ["/attributes", "/column_headers", "/post_lamination_groups"])
    attributes = raw.get("attributes", {})
    if type(attributes) is not dict:
        attributes = {}
    draft["nominal_thickness_mm"] = decimal_mm(attributes.get("boardthickness"))
    headers = raw.get("column_headers")
    valid_units = (type(headers) is list and len(headers) >= 4
                   and headers[2] == "Thickness (mm)" and headers[3] == "Thickness after lamination(mm)")
    if not valid_units:
        issue(draft, "thickness_column_units_unverified", "원문 두께 열의 mm 및 압착 후 의미가 확인되지 않았습니다.")
    groups = raw.get("post_lamination_groups", {})
    for row in components:
        order = row["component_order"]
        key = "component:" + str(order)
        evidence = capture(reader, draft, "native_components", row["component_id"], ["/0", "/1", "/2", "/3"])
        value = row["raw"]
        if type(value) is not list or len(value) < 3:
            issue(draft, "unsupported_component", "PCBWay 구성 행의 형식이 올바르지 않습니다.", blocker=True)
            continue
        label = value[0]
        group = groups.get(str(order)) if type(groups) is dict else None
        if type(label) is str and re.fullmatch(r"L[1-9][0-9]*-CU", label) is not None:
            layer(draft, key, label, "conductor", None, "copper_finished_thickness_unspecified", evidence, order)
            issue(draft, "copper_finished_thickness_unknown", "동박 원문 수치는 보존했으나 도금량 또는 완성 두께로 환산하지 않았습니다.", [key])
        elif label in ("PP", "CORE"):
            thickness = None
            independent = (type(group) is dict and type(group.get("rows")) is int and group["rows"] == 1
                           and type(group.get("start")) is int and group["start"] == order)
            if valid_units and independent:
                thickness = decimal_mm(group.get("label"))
                if thickness is not None and (type(group.get("value")) not in (int, float) or group["value"] != thickness):
                    thickness = None
                    issue(draft, "lamination_value_conflict", "압착 후 문자열과 수치가 일치하지 않아 두께를 미정으로 남겼습니다.", [key])
            if not independent:
                issue(draft, "shared_lamination_total_unallocated", "여러 행의 압착 합계를 개별 층 두께로 나누거나 반복 적용하지 않았습니다.", [key])
            elif thickness is None:
                issue(draft, "dielectric_thickness_missing", "사용할 수 있는 개별 압착 후 유전체 두께가 없습니다.", [key])
            layer(draft, key, str(label) + " " + str(order + 1), "dielectric", thickness,
                  "individual_post_lamination_mm_headers_and_label_verified" if thickness is not None else "post_lamination_thickness_unresolved", evidence, order,
                  thickness_pointer="/post_lamination_groups/" + str(order) + "/value",
                  thickness_evidence=group_evidence)
        else:
            issue(draft, "unsupported_component", "지원하지 않는 PCBWay 구성 행이 있습니다. 층 구성을 직접 정의하십시오.", blocker=True)
            continue
        draft["layers"][-1]["evidence_ids"].append(group_evidence)
    if not components:
        issue(draft, "empty_native_components", "원문 템플릿에 층 구성 행이 없습니다.", blocker=True)
    count = attributes.get("layers")
    count = int(count) if type(count) is str and re.fullmatch(r"[1-9][0-9]{0,2}", count) else None
    return finish(draft, count, require_count=True)
