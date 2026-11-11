"""! @brief JLCPCB API의 원시 템플릿과 복합 구성행을 변환 없이 보존한다."""

from collections import defaultdict
import re

from rfad.catalog.models import CatalogError
from rfad.catalog.native_common import NativeWriter, integer, mapping, sequence, text


RESPONSE_PATH = re.compile(r"raw/FAB/JLC_public_API/(board_type_[13]_page_[0-9]{3}\.json)\Z")


def _audit_pages(audit: list) -> dict[str, dict[int, dict]]:
    """! @brief 감사 자료가 명시한 API 응답과 배열 순번만 사용한다."""
    pages: dict[str, dict[int, dict]] = defaultdict(dict)
    public_ids = set()
    for index, value in enumerate(audit):
        item = mapping(value, f"jlc_audit/{index}")
        match = RESPONSE_PATH.fullmatch(text(item.get("response_path"), "response_path"))
        if match is None:
            raise CatalogError("catalog_native_path", "허용되지 않은 JLC API 응답 경로입니다.")
        position = integer(item.get("template_json_index"), "template_json_index")
        public_id = text(item.get("public_template_id"), "public_template_id")
        if public_id in public_ids or position in pages[match[1]]:
            raise CatalogError("catalog_native_identity", "JLC 원문 템플릿 식별자가 중복됩니다.")
        if type(item.get("public_ui_named_template")) is not bool:
            raise CatalogError("catalog_native_shape", "JLC 명명 템플릿 구분은 명시적 참거짓 값이어야 합니다.")
        public_ids.add(public_id)
        pages[match[1]][position] = item
    return pages


def import_jlc(writer: NativeWriter) -> dict:
    """! @brief 명명 및 사용자 정의 템플릿을 구분하고 API 필드를 모두 보존한다."""
    audit_path, audit_value = writer.read("fab_jlc_stackup_audit.json")
    audit = sequence(audit_value, audit_path)
    pages = _audit_pages(audit)
    writer.evidence("jlc_stackup_audit", audit_path, "", audit)
    writer.coverage(audit_path, "native_evidence:complete_document", 1)
    counts = {"templates": 0, "named_templates": 0, "user_defined_templates": 0,
              "components": 0, "core_rows_with_conductor_fields": 0}
    for filename, positions in sorted(pages.items()):
        relative, response_value = writer.read(filename)
        response = mapping(response_value, relative)
        body = mapping(response.get("body"), relative + "/body")
        templates = sequence(body.get("list"), relative + "/body/list")
        if set(positions) != set(range(len(templates))):
            raise CatalogError("catalog_native_coverage", "JLC 감사 자료와 응답의 템플릿 순번이 일치하지 않습니다.")
        envelope = dict(response)
        envelope["body"] = {key: value for key, value in body.items() if key != "list"}
        writer.evidence("jlc_page_envelope_without_templates", relative, "", envelope)
        writer.coverage(relative, "native_evidence:root_and_body_except_body.list", 1)
        page_components = 0
        for index, value in enumerate(templates):
            pointer = f"/body/list/{index}"
            template = mapping(value, relative + pointer)
            audit_item = positions[index]
            public_id = text(template.get("impedanceDefaultTemplateAccessId"), pointer)
            if public_id != audit_item["public_template_id"]:
                raise CatalogError("catalog_native_identity", "JLC 감사 자료와 API의 템플릿 ID가 다릅니다.")
            named = audit_item["public_ui_named_template"]
            kind = "jlc_named_template" if named else "jlc_user_defined_template"
            flags = () if named else ("user_defined_template_not_public_fixed_stackup",)
            reference = writer.template(
                "JLCPCB", text(audit_item.get("source_id"), "source_id"), public_id,
                text(audit_item.get("stackup_id"), "stackup_id"), kind, relative,
                pointer, template, flags,
            )
            components = sequence(template.get("basicDataList"), pointer + "/basicDataList")
            for order, component_value in enumerate(components):
                component_pointer = pointer + f"/basicDataList/{order}"
                component = mapping(component_value, component_pointer)
                component_flags = flags
                if component.get("material") == "Core":
                    component_flags += ("core_row_may_include_top_and_bottom_copper",)
                    counts["core_rows_with_conductor_fields"] += 1
                writer.component(reference, order, "jlc_api_component", relative,
                                 component_pointer, component, component_flags)
            counts["templates"] += 1
            counts["named_templates" if named else "user_defined_templates"] += 1
            page_components += len(components)
        counts["components"] += page_components
        writer.coverage(relative, "native_templates:/body/list/*", len(templates))
        writer.coverage(relative, "native_components:/body/list/*/basicDataList/*", page_components)
    return counts
