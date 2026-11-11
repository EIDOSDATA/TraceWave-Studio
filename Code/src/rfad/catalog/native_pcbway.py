"""! @brief PCBWay 원문 행과 압착 후 합계의 rowspan 의미를 보존한다."""

from rfad.catalog.models import CatalogError
from rfad.catalog.native_common import NativeWriter, integer, mapping, sequence, text


def import_pcbway(writer: NativeWriter) -> dict:
    """! @brief 압착 합계를 개별 유전체 두께로 바꾸지 않고 저장한다."""
    relative, value = writer.read("fab_pcbway_stackups.json")
    templates = sequence(value, relative)
    counts = {"templates": 0, "components": 0, "shared_post_lamination_group_rows": 0}
    for index, template_value in enumerate(templates):
        pointer = f"/{index}"
        template = mapping(template_value, relative + pointer)
        key = text(template.get("stackup_id"), pointer + "/stackup_id")
        rows = sequence(template.get("rows"), pointer + "/rows")
        groups = mapping(template.get("post_lamination_groups"), pointer + "/post_lamination_groups")
        reference = writer.template(
            "PCBWay", text(template.get("source_id"), "source_id"), key, key,
            "pcbway_published_template", relative, pointer, template,
            ("lamination_group_totals_must_not_be_summed_per_row",),
        )
        for order, row in enumerate(rows):
            sequence(row, pointer + f"/rows/{order}")
            flags = ()
            if str(order) in groups:
                group = mapping(groups[str(order)], pointer + "/post_lamination_groups")
                start = integer(group.get("start"), "post_lamination_groups/start")
                size = integer(group.get("rows"), "post_lamination_groups/rows")
                if size == 0 or not start <= order < start + size <= len(rows):
                    raise CatalogError("catalog_native_group", "PCBWay 압착 합계의 적용 행 범위가 유효하지 않습니다.")
                if size > 1:
                    flags = ("shared_post_lamination_group_total_not_layer_thickness",)
                    counts["shared_post_lamination_group_rows"] += 1
            writer.component(reference, order, "pcbway_html_row", relative,
                             pointer + f"/rows/{order}", row, flags)
        counts["templates"] += 1
        counts["components"] += len(rows)
    writer.coverage(relative, "native_templates:/*", len(templates))
    writer.coverage(relative, "native_components:/*/rows/*", counts["components"])
    return counts
