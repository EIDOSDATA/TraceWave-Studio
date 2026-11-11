"""! @brief JLC 원본 템플릿의 정확한 필드를 묶어 반복 근거의 크기를 줄인다."""

from rfad.catalog.models import CatalogError, canonical_json
from rfad.catalog.stackup_draft_common import capture, object_raw


_TEMPLATE_FIELDS = ("appointName", "receptionDisplayName", "plateLayerNumber", "plateThickness")
_MATERIAL_FIELDS = {
    "Copper": ("material", "layerName", "materialName", "plateContainCopper", "topConductorThick", "botConductorThick"),
    "Prepreg": ("material", "materialName", "plateContainCopper", "dielectricThick"),
    "Core": ("material", "layerName", "materialName", "plateContainCopper", "dielectricThick",
             "topConductorThick", "botConductorThick"),
}


def _check_component(template: dict, component: dict, original: object, index: int) -> dict:
    """! @brief 구성 행의 타입, 순서와 원문 위치가 템플릿 내부 값과 정확히 같은지 검증한다."""
    value = object_raw(component)
    if type(component.get("component_order")) is not int or component["component_order"] != index:
        raise CatalogError("E_SCHEMA", "JLC 구성 행 순서와 템플릿 배열 위치가 다릅니다.")
    if component.get("template_id") != template["template_id"]:
        raise CatalogError("E_HASH", "JLC 구성 행의 부모 템플릿이 일치하지 않습니다.")
    for field in ("source_id", "source_path", "source_sha256"):
        if component.get(field) != template.get(field):
            raise CatalogError("E_HASH", "JLC 구성 행과 템플릿의 출처가 일치하지 않습니다.")
    pointer = template.get("source_pointer")
    if type(pointer) is not str:
        raise CatalogError("E_SCHEMA", "JLC 템플릿 원문 위치가 문자열이 아닙니다.")
    if component.get("source_pointer") != pointer + "/basicDataList/" + str(index):
        raise CatalogError("E_HASH", "JLC 구성 행의 원문 위치가 템플릿 내부 위치와 다릅니다.")
    try:
        equal = canonical_json(value) == canonical_json(original)
    except (ValueError, TypeError, OverflowError) as error:
        raise CatalogError("E_SCHEMA", "JLC 원문 구성 행이 유한 JSON으로 표현되지 않습니다.") from error
    if not equal:
        raise CatalogError("E_HASH", "JLC 구성 행의 값 또는 타입이 원본 템플릿 내부 값과 다릅니다.")
    return value


def _fits(entries: list[tuple[str, bool, object]]) -> bool:
    """! @brief reader와 동일한 개별 사본 및 pointer 상한 안에서만 묶는다."""
    if len(entries) > 64:
        return False
    raw = canonical_json({"values": {path: value for path, exists, value in entries if exists},
                          "missing": sorted(path for path, exists, _ in entries if not exists)})
    return len(raw) <= 4096 and len(raw.encode("utf-8")) <= 8192


def capture_jlc_components(reader, draft: dict, template: dict, components: list[dict]) -> dict[int, str]:
    """! @brief 채택/거부 필드와 구리 수치를 템플릿 원문 hash 및 origin 아래 묶어 보존한다.

    @return 원문 구성 행 순서별 근거 ID. 한 행의 판단 필드는 같은 사본에 담긴다.
    """
    raw = object_raw(template)
    originals = raw.get("basicDataList")
    if type(originals) is not list or len(originals) != len(components):
        raise CatalogError("E_HASH", "JLC 원본 템플릿과 구성 행 목록의 개수가 일치하지 않습니다.")
    groups = [(None, [("/" + field, field in raw, raw.get(field)) for field in _TEMPLATE_FIELDS])]
    for index, component in enumerate(components):
        value = _check_component(template, component, originals[index], index)
        material = value.get("material")
        fields = _MATERIAL_FIELDS.get(material, ("material", "layerName", "materialName")) if type(material) is str else ("material",)
        prefix = "/basicDataList/" + str(index) + "/"
        groups.append((index, [(prefix + field, field in value, value.get(field)) for field in fields]))
    entries, orders = [], []
    result = {}

    def flush() -> None:
        """! @brief 현재 묶음의 원문 필드를 reader로 다시 읽어 봉인한다."""
        identity = capture(reader, draft, "native_templates", template["template_id"], [item[0] for item in entries])
        for order in orders:
            result[order] = identity

    for order, group in groups:
        if not _fits(group):
            raise CatalogError("E_RESOURCE", "JLC 한 구성 행의 필수 근거가 사본 크기 상한을 초과했습니다.")
        if entries and not _fits(entries + group):
            flush()
            entries, orders = [], []
        entries.extend(group)
        if order is not None:
            orders.append(order)
    if entries:
        flush()
    return result
