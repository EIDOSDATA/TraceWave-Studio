"""! @brief 출처값의 채택 제한과 독립된 물성 조건 비교를 정의한다."""

from rfad.catalog.review import missing


def adoption_blocks(record: dict, property_name: str) -> list[str]:
    """! @brief 상수 모델에 자동 축약해서는 안 되는 공개 관측 조건을 반환한다."""
    result = []
    if record.get("data_conflict") or "published_source_conflict" in str(record.get("review_flags", "")):
        result.append("published_source_conflict")
    if record.get("relative_permeability") not in (None, 1, 1.0):
        result.append("nonunit_relative_permeability")
    descriptors = " ".join(str(record.get(field, "")) for field in
                           ("value_type", "material_family", "model", "axis", "anisotropy")).casefold()
    if record.get("anisotropic") or any(word in descriptors for word in ("anisotrop", "orthotrop", "tensor")):
        result.append("anisotropic_or_tensor_material")
    if any(record.get(field) is not None for field in ("epsilon_tensor", "epsilon_r_tensor", "permittivity_tensor")):
        result.append("anisotropic_or_tensor_material")
    kind = str(record.get("value_type", "")).casefold()
    if property_name == "dk" and "effective" in kind:
        result.append("effective_permittivity")
    if property_name == "dk" and "process_and_design" in kind:
        result.append("ambiguous_process_and_design")
    if any(record.get(property_name + suffix) is not None for suffix in ("_min", "_max")):
        result.append("range_requires_explicit_value")
    if record.get(property_name + "_comparison") or (property_name == "df" and record.get("df_limit_operator")):
        result.append("qualified_value_requires_explicit_value")
    if "range" in kind or (property_name == "df" and any(word in kind for word in ("maximum", "limit"))):
        result.append("published_range_or_limit")
    return sorted(set(result))


def conditions(record: dict, property_name: str) -> dict:
    """! @brief Df 전용 조건과 공통 관측 조건을 합치지 않고 비교용 사본을 만든다."""
    result = {field: record.get(field) for field in (
        "manufacturer", "product", "laminate_manufacturer", "material_form", "construction",
        "glass_style", "resin_content_pct", "thickness_mm", "axis", "conditioning",
        "temperature_c", "conditioning_temperature_c", "relative_humidity_pct",
    )}
    if property_name == "df":
        result.update(frequency_ghz=record.get("df_frequency_ghz"), method=record.get("df_method"))
    else:
        result.update(frequency_ghz=record.get("frequency_ghz"), method=record.get("method"))
    return result


def incomplete_conditions(record: dict, property_name: str) -> bool:
    """! @brief 미기재 조건을 확인하되 공식 자료라는 이유로 채워 넣지 않는다."""
    value = conditions(record, property_name)
    return any(missing(value[field]) for field in ("frequency_ghz", "method", "axis"))
