"""! @brief 카탈로그의 안정 식별자, 불변 개체와 공통 오류를 정의한다."""

from dataclasses import dataclass
import hashlib
import json
from typing import Any


CATALOG_SCHEMA = "rfad.catalog/0.1"
CATALOG_USER_VERSION = 1
CATALOG_IMPORT_VERSION = "rfad.catalog.import/1"


class CatalogError(ValueError):
    """! @brief 출처 자료와 파생 인덱스의 실패 원인을 전달한다."""

    def __init__(self, code: str, message: str, *, details: dict | None = None):
        """! @brief 진단 코드와 원본을 변경하지 않는 오류 정보를 보관한다."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {} if details is None else details

    def to_dict(self) -> dict:
        """! @brief GUI와 명령행이 공유할 직렬화 가능한 진단을 반환한다."""
        return {"code": self.code, "message": self.message, "details": self.details}


def canonical_json(value: Any) -> str:
    """! @brief 원문 타입을 보존하는 유한 JSON의 결정적인 표현을 반환한다."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_id(kind: str, *parts: Any) -> str:
    """! @brief 파일명 대신 공개 주체와 원문 식별 조건에서 안정 ID를 만든다."""
    digest = hashlib.sha256(canonical_json([kind, *parts]).encode("utf-8")).hexdigest()
    return kind + ":" + digest


@dataclass(frozen=True)
class ProductIdentity:
    """! @brief 공개 주체와 역할을 구분하는 제품 라벨이며 검증된 고유 소재는 아니다."""

    publisher: str
    product: str
    dataset_role: str
    laminate_manufacturer: str | None = None

    @property
    def product_id(self) -> str:
        """! @brief 원자재 공급사가 다른 같은 라벨도 분리한다."""
        return stable_id("product", self.publisher, self.product, self.dataset_role, self.laminate_manufacturer)


@dataclass(frozen=True)
class StackupIdentity:
    """! @brief 공개 업체별 적층 식별자를 표현하며 제작 가능성을 승인하지 않는다."""

    publisher: str
    source_stackup_id: str

    @property
    def stackup_id(self) -> str:
        """! @brief 업체가 다른 동일 적층 라벨의 충돌을 방지한다."""
        return stable_id("stackup", self.publisher, self.source_stackup_id)


@dataclass(frozen=True)
class ObservationIdentity:
    """! @brief 원래 관측 ID와 출처 및 프로젝트와 독립된 자료 역할을 보존한다."""

    record_id: str
    source_id: str
    dataset_role: str


@dataclass(frozen=True)
class PropertyObservation:
    """! @brief 원문의 한 물성과 조건을 표현하며 해석에 채택한 값은 만들지 않는다."""

    record_id: str
    property_name: str
    unit: str
    scalar: int | float | None
    minimum: int | float | None
    maximum: int | float | None
    value_type: str | None
    frequency_ghz: int | float | None
    frequency_scope: str
    raw_json: str


@dataclass(frozen=True)
class CatalogSource:
    """! @brief 공개 주체와 원문 보관 상태를 원자재 공급사와 분리해 표현한다."""

    source_id: str
    publisher: str
    url: str
    local_path: str | None
    local_available: bool
    raw_json: str

