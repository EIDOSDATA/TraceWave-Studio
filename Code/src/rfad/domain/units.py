"""! @brief 명시적 단위와 입력 상태를 가진 불변 스칼라 값을 관리한다.

08번 문서의 Quantity 계약 중 유한 실수, SI 변환, 누락 상태를 구현한다.
표현식, 복소수, 충돌 후보, 불확도 및 물성 모델은 별도 구현 대상이다.
"""

from dataclasses import dataclass
from enum import StrEnum
import math
from types import MappingProxyType


class QuantityError(ValueError):
    """! @brief 단위, 차원, 수치 또는 입력 상태의 계약 위반을 나타낸다."""


class Dimension(StrEnum):
    """! @brief 초기 스칼라 입력에서 지원하는 물리 차원을 구분한다."""

    LENGTH = "length"
    FREQUENCY = "frequency"
    TIME = "time"
    ANGLE = "angle"
    IMPEDANCE = "impedance"
    CONDUCTIVITY = "conductivity"
    POWER = "power"
    DIMENSIONLESS = "dimensionless"


class QuantityStatus(StrEnum):
    """! @brief 값의 입력 경로와 가용 상태를 검증 합격 상태와 구분한다."""

    USER_ENTERED = "user_entered"
    SOURCE_DEFAULT = "source_default"
    ESTIMATED = "estimated"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNSUPPORTED = "unsupported"
    CONFLICTING = "conflicting"


@dataclass(frozen=True, slots=True)
class _Unit:
    """! @brief 단위의 물리 차원과 SI 배율을 보관한다."""

    dimension: Dimension
    scale: float


_UNITS = MappingProxyType(
    {
        "m": _Unit(Dimension.LENGTH, 1.0),
        "mm": _Unit(Dimension.LENGTH, 1.0e-3),
        "um": _Unit(Dimension.LENGTH, 1.0e-6),
        "Hz": _Unit(Dimension.FREQUENCY, 1.0),
        "kHz": _Unit(Dimension.FREQUENCY, 1.0e3),
        "MHz": _Unit(Dimension.FREQUENCY, 1.0e6),
        "GHz": _Unit(Dimension.FREQUENCY, 1.0e9),
        "s": _Unit(Dimension.TIME, 1.0),
        "ms": _Unit(Dimension.TIME, 1.0e-3),
        "us": _Unit(Dimension.TIME, 1.0e-6),
        "ns": _Unit(Dimension.TIME, 1.0e-9),
        "rad": _Unit(Dimension.ANGLE, 1.0),
        "deg": _Unit(Dimension.ANGLE, math.pi / 180.0),
        "ohm": _Unit(Dimension.IMPEDANCE, 1.0),
        "S/m": _Unit(Dimension.CONDUCTIVITY, 1.0),
        "W": _Unit(Dimension.POWER, 1.0),
        "mW": _Unit(Dimension.POWER, 1.0e-3),
        "1": _Unit(Dimension.DIMENSIONLESS, 1.0),
    }
)

_NUMERIC_STATUSES = frozenset(
    {
        QuantityStatus.USER_ENTERED,
        QuantityStatus.SOURCE_DEFAULT,
        QuantityStatus.ESTIMATED,
    }
)


def _unit_definition(unit: str) -> _Unit:
    """! @brief 지원 단위의 정의를 조회하고 알 수 없는 단위를 거부한다."""
    if not isinstance(unit, str) or unit not in _UNITS:
        raise QuantityError(f"지원하지 않는 단위입니다: {unit!r}")
    return _UNITS[unit]


def _finite_float(value: int | float) -> float:
    """! @brief 숫자를 유한 float로 변환하고 불리언과 문자열을 거부한다."""
    if type(value) not in (int, float):
        raise QuantityError("값은 불리언을 제외한 정수 또는 실수여야 합니다.")
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise QuantityError("값이 float64 범위를 벗어납니다.") from error
    if not math.isfinite(number):
        raise QuantityError("NaN과 Infinity는 설계값으로 사용할 수 없습니다.")
    if number == 0.0:
        return 0.0
    return number


def _checked_conversion(original: float, converted: float) -> float:
    """! @brief 변환의 오버플로와 0으로 소실되는 언더플로를 거부한다."""
    number = _finite_float(converted)
    if original != 0.0 and number == 0.0:
        raise QuantityError("단위 변환 결과가 float64의 최소 크기보다 작습니다.")
    return number


@dataclass(frozen=True, slots=True)
class Quantity:
    """! @brief SI 값, 표시 단위, 입력 상태와 출처를 불변 객체로 보관한다.

    @param value_si 유한 SI 값. 값이 없는 상태는 None을 사용한다.
    @param dimension 표시 단위와 일치하는 물리 차원.
    @param display_unit 지원 목록의 명시적 표시 단위.
    @param status 입력 경로 또는 값의 가용 상태.
    @param source_refs 값에 연결된 출처 식별자 목록.

    conflicting은 후보와 선택 근거 모델이 준비될 때까지 거부한다.
    이 타입은 특정 물성의 양수 조건이나 유효 주파수 범위를 판단하지 않는다.
    """

    value_si: float | None
    dimension: Dimension
    display_unit: str
    status: QuantityStatus
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """! @brief 직접 생성 경로에도 동일한 수치 및 상태 규칙을 적용한다."""
        try:
            dimension = Dimension(self.dimension)
            status = QuantityStatus(self.status)
        except (TypeError, ValueError) as error:
            raise QuantityError("지원하지 않는 차원 또는 입력 상태입니다.") from error
        definition = _unit_definition(self.display_unit)
        if definition.dimension != dimension:
            raise QuantityError("표시 단위와 물리 차원이 일치하지 않습니다.")
        if status == QuantityStatus.CONFLICTING:
            raise QuantityError("conflicting은 후보 및 선택 근거 모델 구현 전 지원하지 않습니다.")
        if status in _NUMERIC_STATUSES:
            value_si = _finite_float(self.value_si)
        else:
            if self.value_si is not None:
                raise QuantityError("값이 없는 상태에는 None만 사용할 수 있습니다.")
            value_si = None
        if not isinstance(self.source_refs, (tuple, list)):
            raise QuantityError("source_refs는 출처 문자열의 목록이어야 합니다.")
        references = tuple(self.source_refs)
        if any(not isinstance(item, str) or not item.strip() for item in references):
            raise QuantityError("출처 식별자는 비어 있지 않은 문자열이어야 합니다.")
        object.__setattr__(self, "dimension", dimension)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "value_si", value_si)
        object.__setattr__(self, "source_refs", references)

    @classmethod
    def from_value(
        cls,
        value: int | float,
        unit: str,
        *,
        status: QuantityStatus = QuantityStatus.USER_ENTERED,
        source_refs: tuple[str, ...] = (),
    ) -> "Quantity":
        """! @brief 명시된 값과 단위를 SI로 변환하여 수량을 생성한다.

        @param value 지정 단위로 표현한 유한 숫자.
        @param unit 입력 단위이며 최초 표시 단위로 보존한다.
        @param status 사용자 입력, 자료 선택 또는 추정 상태.
        @param source_refs 관련 출처 식별자 목록.
        @return SI 값을 가진 불변 Quantity.
        """
        definition = _unit_definition(unit)
        number = _finite_float(value)
        value_si = _checked_conversion(number, number * definition.scale)
        return cls(value_si, definition.dimension, unit, status, source_refs)

    @classmethod
    def missing(cls, dimension: Dimension, display_unit: str) -> "Quantity":
        """! @brief 물성 등 미정 입력을 숫자 0과 구분하여 생성한다.

        @param dimension 미정값의 물리 차원.
        @param display_unit 입력에 사용할 명시적 표시 단위.
        @return value_si가 None인 미정 Quantity.
        """
        return cls(None, dimension, display_unit, QuantityStatus.MISSING)

    def as_unit(self, unit: str) -> float:
        """! @brief 원본 SI 값을 변경하지 않고 요청 단위의 값을 반환한다.

        @param unit 동일 차원을 가진 지원 단위.
        @return 지정 단위로 변환한 유한 숫자.
        @throws QuantityError 값이 없거나 차원 및 수치 범위를 위반한 경우.
        """
        definition = _unit_definition(unit)
        if definition.dimension != self.dimension:
            raise QuantityError("다른 물리 차원의 단위로 변환할 수 없습니다.")
        if self.value_si is None:
            raise QuantityError("값이 없는 상태는 숫자로 변환할 수 없습니다.")
        return _checked_conversion(self.value_si, self.value_si / definition.scale)

    def to_dict(self) -> dict[str, object]:
        """! @brief JSON으로 저장 가능한 필수 Quantity 필드의 복사본을 반환한다."""
        return {
            "value_si": self.value_si,
            "dimension": self.dimension.value,
            "display_unit": self.display_unit,
            "status": self.status.value,
            "source_refs": list(self.source_refs),
        }
