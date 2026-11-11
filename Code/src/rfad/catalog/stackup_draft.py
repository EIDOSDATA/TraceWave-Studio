"""! @brief 조회 카탈로그에서 사용자 검토용 적층 초안을 만든다.

@details 이 단계는 재료 물성, 완성 기판 두께, CAD 또는 해석 준비를 승인하지 않는다.
원문 파일은 변경하지 않으며 프로젝트 객체 ID와 z 좌표는 상위 계층에서 결정한다.
"""

import re

from rfad.catalog.stackup_draft_common import capture, finish, issue, layer, new_draft, object_raw, positive
from rfad.catalog.stackup_draft_jlc import convert_jlc
from rfad.catalog.stackup_draft_pcbway import convert_pcbway


def build_stackup_draft(reader, template_id: str) -> dict:
    """! @brief 열린 SelectionReader의 동일 개정에서 제조업체 템플릿을 읽는다."""
    template = reader.native_template(template_id)
    components = reader.native_components(template_id)
    if template["publisher"] == "JLCPCB" and template["kind"] in ("jlc_named_template", "jlc_user_defined_template"):
        return convert_jlc(reader, template, components)
    if template["publisher"] == "PCBWay" and template["kind"] == "pcbway_published_template":
        return convert_pcbway(reader, template, components)
    draft = new_draft(reader, template, "native_templates")
    if template["kind"] == "we_altium_native_file":
        capture(reader, draft, "native_templates", template_id,
                ["/source_id", "/file", "/native_file_sha256", "/revision_date", "/dielectric_rows"])
        issue(draft, "incomplete_native_layer_set", "WE 원자료는 유전체 행의 부분집합입니다. 완전한 도체 및 영역 순서를 직접 정의하십시오.", blocker=True)
        if any("prefix_cross_layer_fields_present" in row.get("flags_json", "") for row in components):
            issue(draft, "prefix_cross_layer_fields_present", "다른 층의 숫자 접두 필드가 혼입된 원자료가 있어 자동 층 속성으로 사용하지 않았습니다.", blocker=True)
            contaminated = next(row for row in components if "prefix_cross_layer_fields_present" in row.get("flags_json", ""))
            fields = object_raw(contaminated).get("raw_fields", {})
            prefixes = sorted(key for key in fields if re.match(r"^[0-9]", key))[:2] if type(fields) is dict else []
            capture(reader, draft, "native_components", contaminated["component_id"],
                    ["/layer_index", "/raw_fields/NAME"] + ["/raw_fields/" + key.replace("~", "~0").replace("/", "~1") for key in prefixes])
    else:
        capture(reader, draft, "native_templates", template_id, ["/source_id"])
        issue(draft, "unsupported_native_template", "이 원문 형식의 자동 층 구성을 지원하지 않습니다. 층을 직접 정의하십시오.", blocker=True)
    return finish(draft)


def build_observation_draft(reader, record_id: str) -> dict:
    """! @brief 명시적인 2층 코어 관측만 양면 도체와 유전체 초안으로 구성한다."""
    row = reader.observation(record_id)
    draft = new_draft(reader, row, "observations")
    evidence = capture(reader, draft, "observations", record_id)
    value = object_raw(row)
    known_two_layer = (row["publisher"] == "OSH Park" and value.get("stackup_id") == "OSH_2L_1.6"
                       and value.get("record_kind") == "published_stackup_layer"
                       and value.get("material_form") == "core" and value.get("layer") == "L1-L2"
                       and value.get("dataset_role") == "fabricator_published_parameter")
    if not known_two_layer:
        issue(draft, "observation_not_complete_two_layer_stackup", "이 관측만으로 전체 층수와 순서를 확정할 수 없습니다. 층을 직접 정의하십시오.", blocker=True)
        return finish(draft)
    layer(draft, "top", "L1", "conductor", None, "copper_thickness_not_in_observation", evidence, 0)
    thickness = positive(value.get("thickness_mm"))
    layer(draft, "core", "Core", "dielectric", thickness, "published_dielectric_layer_mm", evidence, 1,
          thickness_pointer="/thickness_mm")
    layer(draft, "bottom", "L2", "conductor", None, "copper_thickness_not_in_observation", evidence, 2)
    issue(draft, "copper_finished_thickness_unknown", "이 관측에는 동박의 완성 두께가 없어 미정으로 남겼습니다.", ["top", "bottom"])
    if thickness is None:
        issue(draft, "dielectric_thickness_missing", "사용할 수 있는 양의 유전체 두께가 없습니다.", ["core"])
    return finish(draft, 2)
