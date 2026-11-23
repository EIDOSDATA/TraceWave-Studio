"""! @brief 사용자 전기장 및 자기장 요청을 각 장의 실제 Yee 격자에 연결한다."""

from bisect import bisect_left, bisect_right
import math

from rfad.application.pcb_boundary import pml_cells
from rfad.application.pcb_geometry import fail


NAME = "pcb_probe_E.h5"
MAGNETIC_NAME = "pcb_probe_H.h5"
SCHEMA = "rfad.pcb-electric-plane/0.1"
REGION_SCHEMA = "rfad.pcb-field-region/0.1"
FIELD = "settings.field_probe"


def _fail(message, code="E_GEOMETRY"):
    """! @brief 오류 링크를 필드 기록 입력으로 연결한다."""
    fail(code, message, FIELD)


def _finite(value):
    """! @brief 좌표의 유한 범위를 제한하며 bool을 수치로 받지 않는다."""
    return type(value) in (int, float) and -1e6 <= value <= 1e6


def validate_settings(settings):
    """! @brief 선택한 주파수, 순서 있는 평면 또는 상자 범위와 자기장 선택을 검사한다."""
    if "field_probe" not in settings:
        return
    value = settings["field_probe"]
    keys = {"frequency_hz", "x_mm", "y_mm", "z_mm"}
    if (type(value) is not dict or not keys <= set(value) <= keys | {"magnetic"}
            or type(value.get("magnetic", False)) is not bool):
        _fail("필드의 주파수, XYZ 범위와 자기장 기록 선택을 확인하십시오.", "E_SCHEMA")
    frequency = value["frequency_hz"]
    band = settings["frequency_hz"]
    if type(frequency) not in (int, float) or not band["start"] <= frequency <= band["stop"]:
        _fail("필드 기록 주파수는 현재 해석 대역 안에 있어야 합니다.", "E_SCHEMA")
    if sum(type(value[axis + "_mm"]) is list for axis in "xyz") < 2:
        _fail("필드는 두 축 범위와 한 단면 좌표 또는 세 축 범위가 필요합니다.", "E_SCHEMA")
    for axis in "xyz":
        bounds = value[axis + "_mm"]
        if _finite(bounds):
            continue
        if type(bounds) is not list or len(bounds) != 2 or not all(_finite(item) for item in bounds) or not bounds[0] < bounds[1]:
            _fail("필드 기록의 각 축 범위는 유한하고 증가해야 합니다. 단면의 법선축은 좌표 한 값을 입력하십시오.", "E_SCHEMA")


def _region(requested, lines, pml, magnetic):
    """! @brief E의 primary 및 H의 dual 격자에서 독립적으로 안쪽 선과 native dump box를 결정한다."""
    first, last, start, stop, primitive_start, primitive_stop = [], [], [], [], [], []
    for index, axis in enumerate("xyz"):
        primary = lines[axis]
        nodes = [(a + b) * 0.5 for a, b in zip(primary, primary[1:])] if magnetic else primary
        low, high = pml[index * 2] + 1, len(primary) - pml[index * 2 + 1] - 2
        if low > high:
            _fail("필드를 기록할 해석 내부 격자가 없습니다.")
        target = requested[axis + "_mm"]
        if type(target) is list:
            if not nodes[low] <= target[0] < target[1] <= nodes[high]:
                _fail("필드 기록 범위가 PML 안쪽의 실제 격자를 벗어납니다.")
            left = bisect_left(nodes, target[0])
            right = bisect_right(nodes, target[1]) - 1
            if right <= left:
                _fail("필드 기록 구간은 각 범위 축에 실제 격자선 두 개 이상이 필요합니다.")
        else:
            if not nodes[low] <= target <= nodes[high]:
                _fail("필드 단면 좌표가 해석 내부 격자를 벗어납니다.")
            left = right = min(range(low, high + 1), key=lambda item: abs(nodes[item] - target))
        first.append(left)
        last.append(right)
        start.append(nodes[left])
        stop.append(nodes[right])
        inset_low = (nodes[left + 1] - nodes[left]) * .25 if left < right else 0
        inset_high = (nodes[right] - nodes[right - 1]) * .25 if left < right else 0
        primitive_start.append(nodes[left] + inset_low)
        primitive_stop.append(nodes[right] - inset_high)
    points = math.prod(b - a + 1 for a, b in zip(first, last))
    if points > 4096:
        _fail("필드 기록 범위는 장별 최대 4096개 격자점입니다.", "E_RESOURCE")
    legacy = not magnetic and type(requested["z_mm"]) is not list and not requested.get("magnetic")
    return {"schema": SCHEMA if legacy else REGION_SCHEMA, "start_indices": first, "stop_indices": last,
            "start_mm": start, "stop_mm": stop, "primitive_start_mm": primitive_start, "primitive_stop_mm": primitive_stop,
            "frequency_hz": [requested["frequency_hz"]], "dump_mode": 0, "dump_type": 11 if magnetic else 10, "point_count": points}


def recording(case, lines):
    """! @brief 기존 평면 저장 형식을 보존하고 선택한 경우 같은 단일 급전에서 H 기록도 예약한다."""
    requested = case["settings"].get("field_probe")
    if requested is None:
        return None
    pml = pml_cells(case["boundary_conditions"])
    result = _region(requested, lines, pml, False)
    if requested.get("magnetic"):
        result["magnetic"] = _region(requested, lines, pml, True)
    return result


def raw_names(plan):
    """! @brief 실제 계획한 필드 모니터의 원시 파일만 요구한다."""
    region = plan["case"].get("field_recording")
    if region is None:
        return ()
    return (NAME, MAGNETIC_NAME) if "magnetic" in region else (NAME,)
