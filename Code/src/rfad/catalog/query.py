"""! @brief 카탈로그 읽기 요청의 개체, 필터와 페이지 범위를 검증한다."""

from dataclasses import dataclass
import math

from .models import CatalogError


ENTITIES = (
    "observations", "products", "stackups", "sources", "native_templates", "native_components", "native_evidence",
)
MAX_RESULT_BYTES = 48 * 1024
MAX_PAGE_SIZE = 100
MAX_RAW_CHARACTERS = 8192
MAX_TEXT_CHARACTERS = 512

TEXT_FILTERS = {
    "observations": {"publisher", "product", "product_id", "stackup_id", "source_id",
                     "dataset_role", "material_form", "value_type", "review_flag"},
    "products": {"publisher", "product", "dataset_role", "laminate_manufacturer"},
    "stackups": {"publisher", "source_stackup_id"},
    "sources": {"publisher"},
    "native_templates": {"publisher", "template_key", "stackup_id", "source_id", "kind", "review_flag"},
    "native_components": {"publisher", "template_id", "stackup_id", "source_id", "kind", "review_flag"},
    "native_evidence": {"kind"},
}
NUMBER_FILTERS = {
    "observations": {"frequency_ghz", "thickness_mm", "thickness_min_mm", "thickness_max_mm"},
    "stackups": {"nominal_thickness_mm", "nominal_thickness_min_mm", "nominal_thickness_max_mm"},
}
INTEGER_FILTERS = {
    "observations": {"layer_count"}, "stackups": {"layer_count"},
    "native_components": {"component_order"},
}
BOOLEAN_FILTERS = {"sources": {"local_available"}, "stackups": {"native_available"}}


@dataclass(frozen=True)
class SearchQuery:
    """! @brief SQL 문자열과 분리된 검증 완료 검색 요청이다."""

    entity: str
    filters: dict
    query: str
    limit: int
    offset: int
    catalog_id: str | None


@dataclass(frozen=True)
class DetailQuery:
    """! @brief 원문 JSON의 문자 단위 조각을 요청한다."""

    entity: str
    identifier: str
    raw_offset: int
    raw_limit: int
    catalog_id: str | None


def _fields(value: object, required: set[str], optional: set[str]) -> dict:
    """! @brief 필수키 누락과 지원하지 않는 요청 필드를 거부한다."""
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - optional:
        raise CatalogError("E_SCHEMA", "카탈로그 요청의 필수 필드 또는 지원 필드를 확인하십시오.")
    return value


def _text(value: object, name: str, *, maximum: int = 512, empty: bool = False) -> str:
    """! @brief 문자열을 정규화하거나 경로로 해석하지 않고 길이만 제한한다."""
    if type(value) is not str or (not value and not empty) or len(value) > maximum or "\x00" in value:
        raise CatalogError("E_SCHEMA", "카탈로그 문자열 필드가 올바르지 않습니다.", details={"field": name})
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise CatalogError("E_SCHEMA", "카탈로그 문자열의 UTF-8 인코딩이 올바르지 않습니다.") from error
    return value


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    """! @brief bool을 정수로 취급하지 않고 페이지와 층수 범위를 검사한다."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise CatalogError("E_SCHEMA", "카탈로그 정수 필드의 범위가 올바르지 않습니다.", details={"field": name})
    return value


def _number(value: object, name: str) -> float:
    """! @brief 단위가 명시된 유한 양수만 검색 조건으로 허용한다."""
    if type(value) not in (int, float):
        raise CatalogError("E_SCHEMA", "카탈로그 수치 필드는 유한 양수여야 합니다.", details={"field": name})
    try:
        number = float(value)
    except OverflowError as error:
        raise CatalogError("E_SCHEMA", "카탈로그 수치 필드가 허용 범위를 초과했습니다.", details={"field": name}) from error
    if not math.isfinite(number) or number <= 0:
        raise CatalogError("E_SCHEMA", "카탈로그 수치 필드는 유한 양수여야 합니다.", details={"field": name})
    return number


def _entity(value: object) -> str:
    """! @brief 허용된 정적 테이블 집합 밖의 개체를 거부한다."""
    if type(value) is not str or value not in ENTITIES:
        raise CatalogError("E_SCHEMA", "지원하지 않는 카탈로그 개체입니다.")
    return value


def _revision(data: dict, offset: int) -> str | None:
    """! @brief 후속 페이지는 같은 카탈로그 개정에 묶어서 읽는다."""
    revision = _text(data["catalog_id"], "catalog_id", maximum=256) if "catalog_id" in data else None
    if offset > 0 and revision is None:
        raise CatalogError("E_SCHEMA", "후속 페이지에는 첫 응답의 catalog_id가 필요합니다.")
    return revision


def parse_search(value: object) -> SearchQuery:
    """! @brief 개체별 지원 조건과 명시적인 Dk/Df 주파수 의미를 검사한다."""
    data = _fields(value, {"entity"}, {"filters", "query", "limit", "offset", "catalog_id"})
    entity = _entity(data["entity"])
    filters = data.get("filters", {})
    allowed = (TEXT_FILTERS[entity] | NUMBER_FILTERS.get(entity, set())
               | INTEGER_FILTERS.get(entity, set()) | BOOLEAN_FILTERS.get(entity, set()))
    if entity == "observations":
        allowed = allowed | {"frequency_property", "frequency_mode"}
    _fields(filters, set(), allowed)
    checked = {}
    for name, item in filters.items():
        if name in TEXT_FILTERS[entity]:
            checked[name] = _text(item, name)
        elif name in NUMBER_FILTERS.get(entity, set()):
            checked[name] = _number(item, name)
        elif name in INTEGER_FILTERS.get(entity, set()):
            checked[name] = _integer(item, name, 0 if name == "component_order" else 1, 1000000)
        elif name in BOOLEAN_FILTERS.get(entity, set()):
            if type(item) is not bool:
                raise CatalogError("E_SCHEMA", "카탈로그 가용성 필드는 bool이어야 합니다.")
            checked[name] = item
        elif name == "frequency_property" and item not in ("record", "dk", "df"):
            raise CatalogError("E_SCHEMA", "frequency_property는 record, dk 또는 df여야 합니다.")
        elif name == "frequency_mode" and item not in ("exact", "contains"):
            raise CatalogError("E_SCHEMA", "frequency_mode는 exact 또는 contains여야 합니다.")
        else:
            checked[name] = item
    if ("frequency_ghz" in checked) != ("frequency_property" in checked):
        raise CatalogError("E_SCHEMA", "주파수 검색에는 frequency_ghz와 frequency_property가 모두 필요합니다.")
    if "frequency_mode" in checked and "frequency_ghz" not in checked:
        raise CatalogError("E_SCHEMA", "frequency_mode에는 주파수 검색 조건이 필요합니다.")
    for prefix in ("thickness", "nominal_thickness"):
        low, high = checked.get(prefix + "_min_mm"), checked.get(prefix + "_max_mm")
        if low is not None and high is not None and low > high:
            raise CatalogError("E_SCHEMA", "두께 검색의 최솟값이 최댓값보다 큽니다.")
    limit = _integer(data.get("limit", 25), "limit", 1, MAX_PAGE_SIZE)
    offset = _integer(data.get("offset", 0), "offset", 0, 1000000)
    return SearchQuery(entity, checked, _text(data.get("query", ""), "query", maximum=256, empty=True),
                       limit, offset, _revision(data, offset))


def parse_detail(value: object) -> DetailQuery:
    """! @brief 전체 원문 대신 제한된 문자 구간과 안정 ID만 허용한다."""
    data = _fields(value, {"entity", "id"}, {"catalog_id", "raw_offset", "raw_limit"})
    offset = _integer(data.get("raw_offset", 0), "raw_offset", 0, 2**31 - 1)
    return DetailQuery(_entity(data["entity"]), _text(data["id"], "id", maximum=1024), offset,
                       _integer(data.get("raw_limit", 4096), "raw_limit", 1, MAX_RAW_CHARACTERS),
                       _revision(data, offset))


def escape_like(value: str) -> str:
    """! @brief 사용자가 입력한 %, _ 및 역슬래시를 LIKE 리터럴로 처리한다."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
