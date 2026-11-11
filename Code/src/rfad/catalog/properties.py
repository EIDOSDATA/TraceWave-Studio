"""! @brief 공개 물성의 값 종류와 조건을 채택값으로 바꾸지 않고 표현한다."""

from dataclasses import asdict, dataclass
import math

from .models import CatalogError, canonical_json


MAX_PROPERTY_BYTES = 8192


@dataclass(frozen=True)
class PublishedValue:
    """! @brief 무차원 공개값의 단일값, 범위와 한정자를 독립 보존한다."""

    representation: str
    scalar: int | float | None
    minimum: int | float | None
    maximum: int | float | None
    comparison: str | None
    limit_operator: str | None
    text: str | None
    unit: str = "1"


@dataclass(frozen=True)
class PublishedFrequency:
    """! @brief 명시적 주파수와 단위 환산만 표현하며 적용 대역을 만들지 않는다."""

    scope: str
    point_ghz: int | float | None
    minimum_ghz: int | float | None
    maximum_ghz: int | float | None
    point_hz: int | float | None
    minimum_hz: int | float | None
    maximum_hz: int | float | None
    text: str | None


def _number(record: dict, field: str):
    """! @brief 보고된 숫자를 보존하고 bool이나 비유한 수를 물성으로 해석하지 않는다."""
    value = record.get(field)
    try:
        valid = value is None or (type(value) in (int, float) and math.isfinite(value))
    except OverflowError:
        valid = False
    if not valid:
        raise CatalogError("E_SCHEMA", "물성의 수치 필드가 유효하지 않습니다.", details={"field": field})
    return value


def _hertz(value):
    """! @brief 주파수 의미를 확대하지 않고 GHz를 Hz로 환산한다."""
    converted = None if value is None else value * 1_000_000_000
    try:
        valid = converted is None or math.isfinite(converted)
    except OverflowError:
        valid = False
    if not valid:
        raise CatalogError("E_SCHEMA", "주파수 단위 환산의 범위를 벗어났습니다.")
    return converted


def property_views(record: dict) -> dict:
    """! @brief 원문은 별도로 보존하면서 표시용 물성 DTO를 제한된 크기로 만든다.

    @details df의 전용 주파수가 없으면 공통 주파수를 복사하지 않는다.
    모든 축약 필드는 원래 관측의 raw_json에서 다시 읽을 수 있다.
    """
    for maximum in (128, 64):
        truncated = []

        def text(field):
            """! @brief 한정자와 설명의 축약을 명시하고 원문 타입을 추정하지 않는다."""
            value = record.get(field)
            if value is None:
                return None
            if type(value) is not str:
                truncated.append(field)
                return None
            if len(value) > maximum:
                truncated.append(field)
                return value[:maximum]
            return value

        def frequency(prefix, scope, *, ranges):
            """! @brief 지정한 원문 필드의 주파수만 독립된 조건으로 옮긴다."""
            point = _number(record, prefix + "frequency_ghz")
            low = _number(record, "frequency_min_ghz") if ranges else None
            high = _number(record, "frequency_max_ghz") if ranges else None
            return asdict(PublishedFrequency(
                scope, point, low, high, _hertz(point), _hertz(low), _hertz(high),
                text(prefix + "frequency_text"),
            ))

        properties = {}
        for name in ("dk", "df"):
            scalar = _number(record, name)
            low = _number(record, name + "_min")
            high = _number(record, name + "_max")
            comparison = text(name + "_comparison")
            operator = text("df_limit_operator") if name == "df" else None
            raw_text = text(name + "_text")
            if comparison or operator:
                representation = "qualified"
            elif scalar is not None and (low is not None or high is not None):
                representation = "scalar_and_range"
            elif scalar is not None:
                representation = "scalar"
            elif low is not None or high is not None:
                representation = "range"
            elif raw_text:
                representation = "text_only"
            else:
                representation = "missing"
            properties[name] = {
                "value": asdict(PublishedValue(representation, scalar, low, high, comparison, operator, raw_text)),
                "frequency": frequency("df_" if name == "df" else "",
                                       "explicit_df" if name == "df" else "record", ranges=name == "dk"),
                "method": {"value": text("df_method" if name == "df" else "method"),
                           "scope": "explicit_df" if name == "df" else "record"},
            }
        result = {
            "schema": "rfad.catalog.properties/0.1", "readiness": "not_assessed",
            "properties": properties,
            "record_context": {
                "frequency": frequency("", "record_not_automatically_assigned_to_df", ranges=True),
                "method": text("method"), "axis": text("axis"), "value_type": text("value_type"),
                "material_form": text("material_form"), "glass_style": text("glass_style"),
                "construction": text("construction"), "conditioning": text("conditioning"),
                "thickness_mm": _number(record, "thickness_mm"),
                "resin_content_pct": _number(record, "resin_content_pct"),
                "temperature_c": _number(record, "temperature_c"),
                "relative_humidity_pct": _number(record, "relative_humidity_pct"),
            },
            "source": {"record_id": text("record_id"), "source_id": text("source_id"),
                       "source_location": text("source_location")},
            "truncated_fields": sorted(set(truncated)),
            "raw_json_is_authoritative": True,
        }
        if len(canonical_json(result).encode("utf-8")) <= MAX_PROPERTY_BYTES:
            return result
    raise CatalogError("E_RESOURCE", "물성 표시 DTO의 크기가 허용 범위를 초과했습니다.")
