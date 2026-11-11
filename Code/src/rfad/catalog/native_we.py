"""! @brief Wurth의 원본 필드와 층 접두어 중첩 위험을 변환 없이 보존한다."""

from collections import defaultdict

from rfad.catalog.models import CatalogError
from rfad.catalog.native_common import NativeWriter, integer, mapping, sequence, text


def import_we(writer: NativeWriter) -> dict:
    """! @brief 다른 층 필드가 섞인 행을 명시적으로 표시하고 해석 속성으로 쓰지 않는다."""
    relative, value = writer.read("fab_we_raw_fields.json")
    rows = sequence(value, relative)
    grouped: dict[tuple[str, str], list[tuple[int, dict]]] = defaultdict(list)
    for index, row_value in enumerate(rows):
        row = mapping(row_value, relative + f"/{index}")
        key = (text(row.get("source_id"), "source_id"), text(row.get("stackup_id"), "stackup_id"))
        grouped[key].append((index, row))
    audit_path, audit_value = writer.read("fab_we_audit.json")
    audit = sequence(audit_value, audit_path)
    seen = set()
    counts = {"templates": 0, "components": 0, "raw_fields": 0, "prefix_cross_layer_rows": 0}
    for index, item_value in enumerate(audit):
        item = mapping(item_value, audit_path + f"/{index}")
        source_id = text(item.get("source_id"), "source_id")
        filename = text(item.get("file"), "file")
        key = (source_id, filename)
        if key in seen or key not in grouped:
            raise CatalogError("catalog_native_identity", "Wurth 감사 자료와 구성행의 출처별 파일이 일치하지 않습니다.")
        seen.add(key)
        label = filename[:-8] if filename.endswith(".stackup") else filename
        template_flags = ("native_fields_require_layer_and_region_review",)
        if any(any(field[:1].isdigit() for field in mapping(row.get("raw_fields"), "raw_fields"))
               for _, row in grouped[key]):
            template_flags += ("prefix_cross_layer_fields_present",)
        reference = writer.template(
            "Wurth Elektronik", source_id, filename, label, "we_altium_native_file",
            audit_path, f"/{index}", item, template_flags,
        )
        seen_orders = set()
        for row_index, row in grouped[key]:
            order = integer(row.get("layer_index"), "layer_index")
            if order in seen_orders:
                raise CatalogError("catalog_native_identity", "같은 Wurth 원문 파일에 구성행 순번이 중복됩니다.")
            seen_orders.add(order)
            fields = mapping(row.get("raw_fields"), relative + f"/{row_index}/raw_fields")
            flags = ("raw_fields_not_validated_layer_properties",)
            if any(field[:1].isdigit() for field in fields):
                flags += ("prefix_cross_layer_fields_present",)
                counts["prefix_cross_layer_rows"] += 1
            writer.component(reference, order, "we_raw_field_record", relative,
                             f"/{row_index}", row, flags)
            counts["components"] += 1
            counts["raw_fields"] += len(fields)
        counts["templates"] += 1
    if seen != set(grouped):
        raise CatalogError("catalog_native_coverage", "Wurth 구성행 중 감사 자료와 연결되지 않은 파일이 있습니다.")
    writer.coverage(audit_path, "native_templates:/*", len(audit))
    writer.coverage(relative, "native_components:/*", len(rows))
    return counts
