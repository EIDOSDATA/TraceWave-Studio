"""! @brief 사용자 XY 전기장 단면 요청을 실제 Yee 격자와 연결한다."""

from bisect import bisect_left, bisect_right
import math

from rfad.application.pcb_boundary import pml_cells
from rfad.application.pcb_geometry import fail


NAME = "pcb_probe_E.h5"
SCHEMA = "rfad.pcb-electric-plane/0.1"
FIELD = "settings.field_probe"


def _fail(message, code="E_GEOMETRY"):
    """! @brief 오류 링크를 전기장 단면 입력으로 연결한다."""
    fail(code, message, FIELD)


def _finite(value):
    """! @brief 좌표의 유한 범위를 제한하며 bool을 수치로 받지 않는다."""
    return type(value) in (int, float) and -1e6 <= value <= 1e6


def validate_settings(settings):
    """! @brief 선택한 주파수와 순서 있는 유한 XY 범위를 검사한다."""
    if "field_probe" not in settings:
        return
    value = settings["field_probe"]
    if type(value) is not dict or set(value) != {"frequency_hz", "x_mm", "y_mm", "z_mm"}:
        _fail("전기장 단면의 주파수, XY 범위와 Z를 지정하십시오.", "E_SCHEMA")
    frequency = value["frequency_hz"]
    band = settings["frequency_hz"]
    if type(frequency) not in (int, float) or not band["start"] <= frequency <= band["stop"]:
        _fail("전기장 기록 주파수는 현재 해석 대역 안에 있어야 합니다.", "E_SCHEMA")
    for axis in ("x_mm", "y_mm"):
        bounds = value[axis]
        if type(bounds) is not list or len(bounds) != 2 or not all(_finite(item) for item in bounds) or not bounds[0] < bounds[1]:
            _fail("전기장 단면의 XY 범위를 작은 값부터 입력하십시오.", "E_SCHEMA")
    if not _finite(value["z_mm"]):
        _fail("전기장 단면의 유한 Z 좌표를 입력하십시오.", "E_SCHEMA")


def recording(case, lines):
    """! @brief PML 안쪽의 선택 범위를 원래 전기 edge 번호로 확정한다."""
    requested = case["settings"].get("field_probe")
    if requested is None:
        return None
    pml = pml_cells(case["boundary_conditions"])
    first, last = [], []
    for index, axis in enumerate("xyz"):
        nodes = lines[axis]
        low, high = pml[index * 2] + 1, len(nodes) - pml[index * 2 + 1] - 2
        if low > high:
            _fail("전기장 단면을 기록할 해석 내부 격자가 없습니다.")
        if axis == "z":
            target = requested["z_mm"]
            if not nodes[low] <= target <= nodes[high]:
                _fail("전기장 단면의 Z가 해석 내부 격자를 벗어납니다.")
            selected = min(range(low, high + 1), key=lambda item: abs(nodes[item] - target))
            first.append(selected)
            last.append(selected)
        else:
            start, stop = requested[axis + "_mm"]
            if not nodes[low] <= start < stop <= nodes[high]:
                _fail("전기장 단면의 XY가 해석 내부 격자를 벗어납니다.")
            first.append(bisect_left(nodes, start))
            last.append(bisect_right(nodes, stop) - 1)
    counts = [b - a + 1 for a, b in zip(first, last)]
    if min(counts[:2]) < 2:
        _fail("전기장 단면은 X와 Y에 실제 격자선 두 개 이상이 필요합니다.")
    points = math.prod(counts)
    if points > 4096:
        _fail("전기장 단면 범위는 최대 4096개 격자점입니다.", "E_RESOURCE")
    start = [lines[axis][index] for axis, index in zip("xyz", first)]
    stop = [lines[axis][index] for axis, index in zip("xyz", last)]
    primitive_start = [start[i] + (lines[axis][first[i] + 1] - start[i]) * .25 for i, axis in enumerate("xy")]
    primitive_stop = [stop[i] - (stop[i] - lines[axis][last[i] - 1]) * .25 for i, axis in enumerate("xy")]
    return {"schema": SCHEMA, "start_indices": first, "stop_indices": last, "start_mm": start,
            "stop_mm": stop, "primitive_start_mm": [*primitive_start, start[2]],
            "primitive_stop_mm": [*primitive_stop, stop[2]], "frequency_hz": [requested["frequency_hz"]],
            "dump_mode": 0, "dump_type": 10, "point_count": points}


def raw_names(plan):
    """! @brief 명시한 단면이 있는 계획에만 전기장 원시 파일을 요구한다."""
    return (NAME,) if "field_recording" in plan["case"] else ()
