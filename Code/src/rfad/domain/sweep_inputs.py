"""! @brief 스윕 원문 수량과 수치 설정의 단위 해석을 서비스 경계에서 수행한다."""

from copy import deepcopy
from decimal import Decimal, localcontext
import math

from rfad.adapters.network_text import number
from rfad.domain.design import _strings
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity, QuantityError, units_for_dimension


_FIELDS = (
    ("frequency_hz.start", "시작 주파수", "frequency", "Hz", False),
    ("frequency_hz.stop", "끝 주파수", "frequency", "Hz", False),
    ("frequency_hz.count", "주파수 표본 수", "dimensionless", "1", True),
    ("grid_mm", "전역 격자 간격", "length", "mm", False),
    ("air_padding_mm", "공기 여백", "length", "mm", False),
    ("curve_tolerance_mm", "곡선 근사 오차", "length", "mm", False),
    ("max_timesteps", "시간 단계 상한", "dimensionless", "1", True),
    ("end_criterion", "에너지 종료 기준", "dimensionless", "1", False),
    ("feature_subdivisions", "임계 구간 분할 수", "dimensionless", "1", True),
    ("radiation.box_clearance_mm", "방사 기록 상자 거리", "length", "mm", False),
    ("radiation.theta_step_deg", "방사 theta 간격", "angle", "deg", True),
    ("radiation.phi_step_deg", "방사 phi 간격", "angle", "deg", True),
)
_QUANTITY_FIELDS = {"value_si", "dimension", "display_unit", "status", "source_refs"}


def fail(message, field="specification", code="E_SCHEMA"):
    """! @brief 원문 위치를 남긴 계약 오류를 반환한다."""
    raise ProjectError(code, message, details={"field_path": field})


def numerical_fields():
    """! @brief 허용한 수치 경로만 공개하며 임의 JSON 경로 편집은 허용하지 않는다."""
    return [{"id": identity, "label": label, "dimension": dimension, "unit": unit,
             "integer": integer, "units": list(units_for_dimension(dimension))}
            for identity, label, dimension, unit, integer in _FIELDS]


def numerical_field(identity):
    """! @brief 지원하는 설정 경로의 차원 및 정수 계약을 조회한다."""
    if type(identity) is not str:
        fail("수치 설정 ID는 문자열이어야 합니다.", "variables.id")
    descriptor = next((row for row in numerical_fields() if row["id"] == identity), None)
    if descriptor is None:
        fail("지원하지 않는 수치 설정 축입니다.", identity, "E_UNSUPPORTED")
    return descriptor


def input_quantity(value, dimension, field):
    """! @brief 원본 Quantity는 보존하고 명시한 문자열 입력만 SI로 변환한다."""
    if type(value) is not dict:
        fail("Quantity 또는 값/단위/출처 입력이 필요합니다.", field)
    try:
        if set(value) == _QUANTITY_FIELDS:
            _strings(value["source_refs"], field + ".source_refs")
            quantity = Quantity(**value)
        elif set(value) == {"text", "unit", "source_refs"}:
            _strings(value["source_refs"], field + ".source_refs")
            if type(value["text"]) is not str or len(value["text"]) > 128:
                fail("값 문자열은 최대 128자입니다.", field)
            text = value["text"].strip()
            quantity = (Quantity.from_value(number(text, field=field), value["unit"], source_refs=value["source_refs"])
                        if text else Quantity(None, dimension, value["unit"], "missing", value["source_refs"]))
        else:
            fail("수량 입력의 필드가 다릅니다.", field)
        if quantity.dimension != dimension:
            fail("스윕 축과 수량의 차원이 다릅니다.", field, "E_UNIT")
        return quantity.to_dict()
    except (QuantityError, TypeError, ValueError) as error:
        fail("수량을 해석할 수 없습니다: " + str(error), field, "E_UNIT")


def numeric_setting(identity, value):
    """! @brief 기존 solver 숫자 계약으로 변환하며 정수와 미정 상태를 강제한다."""
    descriptor = numerical_field(identity)
    quantity = Quantity(**input_quantity(value, descriptor["dimension"], identity))
    if quantity.value_si is None:
        fail("해석 설정의 명시적 수치가 필요합니다.", identity, "E_CONFLICT")
    try:
        result = quantity.as_unit(descriptor["unit"])
    except QuantityError as error:
        fail(str(error), identity, "E_UNIT")
    if descriptor["integer"]:
        # @brief 각도 SI 왕복의 최대 2 ULP만 허용하며 임의 소수 입력을 정수로 반올림하지 않는다.
        nearest = round(result)
        tolerance = 2 * math.ulp(result) if descriptor["dimension"] == "angle" else 0.0
        if abs(result - nearest) > tolerance or abs(nearest) > 2**53 - 1:
            fail("이 설정에는 정확한 정수가 필요합니다.", identity, "E_UNIT")
        return int(nearest)
    return result


def set_setting(settings, identity, value):
    """! @brief 허용 목록의 수치 필드만 설정하며 기존 중첩 구조를 보존한다."""
    numerical_field(identity)
    if type(settings) is not dict:
        fail("명시한 해석 설정이 필요합니다.", "settings", "E_CONFLICT")
    path = identity.split(".")
    current = settings
    for key in path[:-1]:
        if key not in current or type(current[key]) is not dict:
            fail("대상 설정 묶음을 먼저 명시하십시오.", identity, "E_CONFLICT")
        current = current[key]
    current[path[-1]] = numeric_setting(identity, value)


def normalize_settings(settings, inputs=None):
    """! @brief 원문 숫자 설정 복사본에 사용자가 바꾼 필드만 적용한다."""
    if settings is not None and type(settings) is not dict:
        fail("해석 설정은 객체 또는 미정이어야 합니다.", "settings")
    result = deepcopy(settings)
    if inputs is None:
        return result
    if type(inputs) is not dict or len(inputs) > len(_FIELDS) + 1:
        fail("수치 설정 입력 목록이 유효하지 않습니다.", "settings_inputs")
    for identity, value in inputs.items():
        if identity == "radiation.frequency_hz":
            if (type(result) is not dict or type(result.get("radiation")) is not dict
                    or type(value) is not list or not 1 <= len(value) <= 3):
                fail("명시 방사 설정과 1~3개의 기록 주파수가 필요합니다.", identity)
            frequencies = []
            for index, item in enumerate(value):
                parsed = input_quantity(item, "frequency", f"{identity}.{index}")
                if parsed["value_si"] is None:
                    fail("기록 주파수는 명시한 유한 수량이어야 합니다.", identity, "E_CONFLICT")
                frequencies.append(parsed["value_si"])
            result["radiation"]["frequency_hz"] = frequencies
            continue
        set_setting(result, identity, value)
    return result


def normalize_budget(budget, inputs=None):
    """! @brief 시간/메모리 표시 입력만 서비스 숫자로 환산하고 원문은 호출자 사본에 남긴다."""
    if type(budget) is not dict:
        fail("명시 자원 예산 객체가 필요합니다.", "budget")
    result = deepcopy(budget)
    if inputs is None:
        return result
    units = {"wall_seconds": {"s": 1, "min": 60, "h": 3600},
             "ram_bytes": {"MiB": 2**20, "GiB": 2**30}, "disk_bytes": {"MiB": 2**20, "GiB": 2**30}}
    if type(inputs) is not dict or set(inputs) - set(units):
        fail("지원하는 시간/RAM/디스크 입력 필드만 지정하십시오.", "budget_inputs")
    for key, value in inputs.items():
        field = "budget_inputs." + key
        if type(value) is not dict or set(value) != {"text", "unit"} or type(value["unit"]) is not str or value["unit"] not in units[key]:
            fail("명시 수치 문자열과 지원 예산 단위가 필요합니다.", field)
        if type(value["text"]) is not str:
            fail("예산 값은 문자열이어야 합니다.", field)
        text = value["text"].strip()
        number(text, field=field)
        with localcontext() as context:
            context.prec = len(text) + 32
            converted = Decimal(text) * units[key][value["unit"]]
        if key == "wall_seconds":
            numeric = float(converted)
            if not math.isfinite(numeric) or (converted != 0 and numeric == 0):
                fail("예산 환산 결과가 유한 범위를 벗어났습니다.", field, "E_RESOURCE")
            result[key] = numeric
        else:
            if converted != converted.to_integral_value() or not 0 < converted <= 2**53 - 1:
                fail("메모리 예산은 유한한 양의 정수 바이트여야 합니다.", field, "E_RESOURCE")
            result[key] = int(converted)
    return result
