"""! @brief 해석형 도체의 종류와 출처를 유지하는 명시적 평면 변환을 제공한다."""

from copy import deepcopy
import math

from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity, QuantityError


MAX_SELECTION = 16
MAX_COORDINATE_MM = 1e6


def fail(message, field, code="E_GEOMETRY"):
    """! @brief 원본을 바꾸기 전에 입력 위치가 있는 오류를 발생시킨다."""
    raise ProjectError(code, message, details={"field_path": field})


def number(value, field):
    """! @brief bool, 문자열, 비유한 수치를 기하 입력으로 받지 않는다."""
    if type(value) not in (int, float):
        fail("유한 숫자를 입력하십시오.", field, "E_UNIT")
    try:
        result = float(value)
    except OverflowError:
        fail("숫자 범위를 초과했습니다.", field, "E_UNIT")
    if not math.isfinite(result):
        fail("유한 숫자를 입력하십시오.", field, "E_UNIT")
    return result


def scalar(document, value, dimension="length", unit="mm", field="geometry"):
    """! @brief 미정 수량을 추정하지 않고 명시한 표시 단위로 해석한다."""
    quantity = resolve_scalar(document, value, dimension, field)
    if quantity.value_si is None:
        fail("미정 수량은 정밀 편집 후보로 계산할 수 없습니다.", field, "E_CONFLICT")
    try:
        result = quantity.as_unit(unit)
    except (QuantityError, ValueError, OverflowError):
        fail("기존 수량을 정밀 편집 단위로 표현할 수 없습니다. 원본은 유지됩니다.", field, "E_RESOURCE")
    if dimension == "length" and abs(result) > MAX_COORDINATE_MM:
        fail("정밀 편집의 좌표/치수 상한 1000000 mm를 초과했습니다.", field, "E_RESOURCE")
    return result


def replace_literal(document, old, value, unit, field):
    """! @brief 바뀌는 리터럴만 갱신하며 참조, 원래 단위와 출처를 보존한다."""
    dimension = "angle" if unit == "deg" else "length"
    original = scalar(document, old, dimension, unit, field)
    if value == original:
        return deepcopy(old)
    if "parameter_id" in old:
        fail("매개변수에 연결된 치수입니다. 해당 매개변수를 편집하십시오.", field, "E_CONFLICT")
    converted = Quantity.from_value(number(value, field), unit)
    if dimension == "length" and abs(value) > MAX_COORDINATE_MM:
        fail("정밀 편집의 좌표/치수 상한을 초과했습니다.", field, "E_RESOURCE")
    if converted.value_si == old["value_si"]:
        return deepcopy(old)
    return {**deepcopy(old), "value_si": converted.value_si, "status": "user_entered"}


def point(document, values, field="geometry"):
    """! @brief 원본 점을 서비스 좌표 mm로 해석한다."""
    return [scalar(document, item, field=f"{field}.{index}") for index, item in enumerate(values)]


def point_fields(geometry):
    """! @brief 외곽과 구멍을 포함한 모든 위치 수량의 경로를 반환한다."""
    if geometry["kind"] == "planar_region":
        for index, values in enumerate(geometry["outer"]):
            yield f"outer.{index}", values
        for hole_index, hole in enumerate(geometry["holes"]):
            for index, values in enumerate(hole):
                yield f"holes.{hole_index}.{index}", values
    else:
        for name in (("start", "end") if geometry["kind"] == "line_path" else ("center",)):
            yield name, geometry[name]


def rotation_sin_cos(angle):
    """! @brief 직각 회전은 정확한 계수로 작은 잔여 좌표를 만들지 않는다."""
    reduced = math.remainder(angle, 360.0)
    if reduced in (0.0, 90.0, -90.0, 180.0, -180.0):
        return {0.0: (0.0, 1.0), 90.0: (1.0, 0.0), -90.0: (-1.0, 0.0),
                180.0: (0.0, -1.0), -180.0: (0.0, -1.0)}[reduced]
    radians = math.radians(reduced)
    return math.sin(radians), math.cos(radians)


def transform(document, geometry, operation, values):
    """! @brief 회전/미러를 한 형상의 복제본에 적용하고 해석형 및 연결 ID를 보존한다."""
    result = deepcopy(geometry)
    prefix = "geometry." + geometry["id"]
    if operation == "rotate":
        angle = number(values["angle_deg"], "angle_deg")
        if abs(angle) > 360000.0:
            fail("회전각은 절댓값 360000 deg 이내여야 합니다.", "angle_deg", "E_RESOURCE")
        pivot = [number(values[key], key) for key in ("pivot_x_mm", "pivot_y_mm")]
        if any(abs(value) > MAX_COORDINATE_MM for value in pivot):
            fail("회전 중심이 좌표 상한을 초과했습니다.", "pivot_x_mm", "E_RESOURCE")
        sine, cosine = rotation_sin_cos(angle)

        def convert(x, y):
            """! @brief 명시한 중심에 대한 강체 회전을 계산한다."""
            return [pivot[0] + cosine * (x - pivot[0]) - sine * (y - pivot[1]),
                    pivot[1] + sine * (x - pivot[0]) + cosine * (y - pivot[1])]

        def convert_angle(value):
            """! @brief 원래 연속 각 표현에 명시 회전량을 더한다."""
            return value + angle
    elif operation == "translate":
        dx = number(values["dx_mm"], "dx_mm")
        dy = number(values["dy_mm"], "dy_mm")

        def convert(x, y):
            """! @brief 기판 XY에서 같은 피치의 강체 이동을 적용한다."""
            return [x + dx, y + dy]
    elif operation == "mirror":
        axis = values["axis"]
        if axis not in ("x", "y"):
            fail("미러 축은 수평 x 또는 수직 y여야 합니다.", "axis", "E_SCHEMA")
        offset = number(values["offset_mm"], "offset_mm")
        if abs(offset) > MAX_COORDINATE_MM:
            fail("미러 축이 좌표 상한을 초과했습니다.", "offset_mm", "E_RESOURCE")

        def convert(x, y):
            """! @brief x 축은 Y 고정 수평선, y 축은 X 고정 수직선이다."""
            return [x, 2 * offset - y] if axis == "x" else [2 * offset - x, y]

        def convert_angle(value):
            """! @brief 반사 후 방향각을 바꾸며 층이나 상하면은 바꾸지 않는다."""
            return -value if axis == "x" else 180.0 - value
    else:
        fail("지원하지 않는 강체 변환입니다.", "operation", "E_UNSUPPORTED")
    for (path, source), (_, destination) in zip(point_fields(geometry), point_fields(result)):
        updated = convert(*point(document, source, prefix + "." + path))
        for index, value in enumerate(updated):
            destination[index] = replace_literal(document, source[index], value, "mm", f"{prefix}.{path}.{index}")
    if operation == "translate":
        return result
    if geometry["kind"] == "arc_path":
        old = scalar(document, geometry["start_angle"], "angle", "deg", prefix + ".start_angle")
        result["start_angle"] = replace_literal(document, geometry["start_angle"], convert_angle(old), "deg", prefix + ".start_angle")
        if operation == "mirror":
            sweep = scalar(document, geometry["sweep_angle"], "angle", "deg", prefix + ".sweep_angle")
            result["sweep_angle"] = replace_literal(document, geometry["sweep_angle"], -sweep, "deg", prefix + ".sweep_angle")
    elif geometry["kind"] == "pad" and geometry["pad_shape"] == "rectangle":
        old = scalar(document, geometry["rotation"], "angle", "deg", prefix + ".rotation")
        result["rotation"] = replace_literal(document, geometry["rotation"], convert_angle(old), "deg", prefix + ".rotation")
    return result
