"""! @brief 원본에 연관된 표시 치수와 명시적인 리터럴/매개변수 편집을 제공한다."""

from copy import deepcopy
import math

from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.planar import signed_area
from rfad.domain.precision_transform import MAX_COORDINATE_MM, fail, number, point, replace_literal, scalar
from rfad.domain.units import Quantity, QuantityError


_DIRECT = {
    "line_path": (("line.width", "선폭", ("width",), "mm"),),
    "arc_path": (("arc.radius", "중심선 반지름", ("radius",), "mm"),
                 ("arc.width", "선폭", ("width",), "mm"),
                 ("arc.start_angle", "시작각", ("start_angle",), "deg"),
                 ("arc.sweep_angle", "부호 있는 회전량", ("sweep_angle",), "deg")),
    "pad": (("pad.width", "패드 폭", ("size", 0), "mm"),
            ("pad.height", "패드 높이", ("size", 1), "mm"),
            ("pad.rotation", "패드 회전각", ("rotation",), "deg")),
    "via": (("via.finished_hole_diameter", "완성 구멍 지름", ("finished_hole_diameter",), "mm"),
            ("via.plating_thickness", "도금 두께", ("plating_thickness",), "mm"),
            ("via.tool_hole_diameter", "드릴 지름", ("tool_hole_diameter",), "mm")),
}


def descriptors(geometry):
    """! @brief 직접 결합 가능한 수량과 유도 치수를 구분한다."""
    if geometry["kind"] == "pad" and geometry["pad_shape"] == "circle":
        return (("pad.diameter", "패드 지름", ("size", 0), "mm"),)
    return _DIRECT.get(geometry["kind"], ())


def at(geometry, path):
    """! @brief 고정된 도메인 경로만 순회하며 문자열 표현식을 실행하지 않는다."""
    value = geometry
    for component in path:
        value = value[component]
    return value


def put(geometry, path, value):
    """! @brief 검증된 고정 경로의 값 하나를 후보에 교체한다."""
    target = geometry
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value


def _anchors(document, geometry):
    """! @brief 화면에 표시할 수 있는 치수 기준점만 mm로 반환한다."""
    if geometry["kind"] == "line_path":
        return [point(document, geometry[key]) for key in ("start", "end")]
    if geometry["kind"] == "planar_region":
        return [point(document, geometry["outer"][0])]
    return [point(document, geometry["center"])]


def _derived(key, label, value, unit, anchors, *, editable=False, reason="모델에서 계산한 읽기 전용 치수입니다.", kind="linear"):
    """! @brief 수동 표시 문자열과 구별되는 모델 유도 치수 DTO를 만든다."""
    return {"key": key, "label": label, "value": value, "unit": unit, "status": "derived",
            "editable": editable, "parameter_id": None, "field_path": None, "kind": kind,
            "anchors_mm": anchors, "binding_supported": False, "read_only_reason": "" if editable else reason,
            "source_refs": []}


def _display_value(quantity, unit):
    """! @brief 표시 범위를 벗어난 기존 원본을 바꾸지 않고 미표시로 돌려준다."""
    if quantity.value_si is None:
        return None
    try:
        value = quantity.as_unit(unit)
    except (QuantityError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or (unit == "mm" and abs(value) > MAX_COORDINATE_MM):
        return None
    return value


def dimensions(document, geometry):
    """! @brief 현재 개정의 원본에서 치수를 계산하며 미정값과 파라미터 결합을 표시한다."""
    result = []
    prefix = "geometry." + geometry["id"]
    try:
        anchors = _anchors(document, geometry)
    except (ProjectError, QuantityError, ValueError):
        anchors = []
    if geometry["kind"] == "line_path":
        if len(anchors) == 2:
            editable = all("parameter_id" not in value and value.get("value_si") is not None for value in geometry["end"])
            result.append(_derived("line.length", "중심선 길이", math.dist(*anchors), "mm", anchors,
                                   editable=editable, reason="끝점이 매개변수에 연결되어 있습니다. 해당 매개변수를 편집하십시오."))
        else:
            row = _derived("line.length", "중심선 길이", None, "mm", [], reason="끝점 좌표가 미정입니다.")
            row["status"] = "missing"
            result.append(row)
    for key, label, path, unit in descriptors(geometry):
        original = at(geometry, path)
        quantity = resolve_scalar(document, original, "angle" if unit == "deg" else "length", prefix)
        bound = original.get("parameter_id")
        value = _display_value(quantity, unit)
        outside = quantity.value_si is not None and value is None
        reason = "매개변수 속성에서 값을 편집하십시오." if bound else ("미정 수량입니다. 값을 명시적으로 입력할 수 있습니다." if value is None else "")
        if outside:
            reason = "기존 수량이 정밀 표시 범위를 벗어났습니다. 원본은 속성에서 확인하십시오."
        editable = bound is None
        row_anchors = deepcopy(anchors)
        kind = "angular" if unit == "deg" else "scalar"
        if key == "arc.radius" and anchors and value is not None:
            angle = resolve_scalar(document, geometry["start_angle"], "angle", prefix + ".start_angle")
            if angle.value_si is not None:
                radians = angle.as_unit("rad")
                endpoint = [anchors[0][0] + value * math.cos(radians), anchors[0][1] + value * math.sin(radians)]
                if all(abs(coordinate) <= MAX_COORDINATE_MM for coordinate in endpoint):
                    row_anchors += [endpoint]
            kind = "radial"
        result.append({"key": key, "label": label, "value": value, "unit": unit, "status": "unsupported" if outside else quantity.status.value,
                       "editable": editable, "parameter_id": bound, "field_path": prefix + "." + ".".join(map(str, path)),
                       "kind": kind, "anchors_mm": row_anchors, "binding_supported": True,
                       "read_only_reason": reason, "source_refs": list(quantity.source_refs)})
    if geometry["kind"] == "arc_path":
        radius = resolve_scalar(document, geometry["radius"], "length")
        sweep = resolve_scalar(document, geometry["sweep_angle"], "angle")
        radius_value = _display_value(radius, "mm")
        sweep_value = _display_value(sweep, "rad")
        length = None if radius_value is None or sweep_value is None else radius_value * abs(sweep_value)
        result.append(_derived("arc.length", "중심선 원호 길이", length, "mm", anchors))
    if geometry["kind"] == "planar_region":
        try:
            loops = [[point(document, item) for item in loop] for loop in [geometry["outer"], *geometry["holes"]]]
            area = abs(signed_area(loops[0])) - math.fsum(abs(signed_area(loop)) for loop in loops[1:])
            perimeter = math.fsum(math.dist(a, b) for loop in loops for a, b in zip(loop, loop[1:] + loop[:1]))
            result.extend((_derived("region.area", "구멍을 뺀 도체 면적", area, "mm^2", anchors, kind="scalar"),
                           _derived("region.perimeter", "구멍 포함 경계 길이", perimeter, "mm", anchors)))
        except ProjectError:
            pass
    return result


def set_dimension(document, geometry, key, value, unit):
    """! @brief 선택한 한 치수만 변경하고 연관 객체 및 출처 사본은 건드리지 않는다."""
    value = number(value, "value")
    result = deepcopy(geometry)
    prefix = "geometry." + geometry["id"]
    if key == "line.length" and geometry["kind"] == "line_path":
        try:
            length = Quantity.from_value(value, unit).as_unit("mm")
        except (QuantityError, ValueError, TypeError) as error:
            fail(str(error), "unit", "E_UNIT")
        if not 0 < length <= MAX_COORDINATE_MM:
            fail("선의 길이는 양수이며 1000000 mm 이하여야 합니다.", "value", "E_UNIT")
        start, end = (point(document, geometry[name], prefix + "." + name) for name in ("start", "end"))
        original_length = math.dist(start, end)
        if original_length == 0:
            fail("길이가 0인 선의 방향은 정할 수 없습니다.", "dimension_key")
        for index in (0, 1):
            coordinate = start[index] + (end[index] - start[index]) / original_length * length
            result["end"][index] = replace_literal(document, geometry["end"][index], coordinate, "mm", prefix + f".end.{index}")
        return result
    descriptor = next((row for row in descriptors(geometry) if row[0] == key), None)
    if descriptor is None:
        fail("편집 가능한 치수를 선택하십시오.", "dimension_key", "E_UNSUPPORTED")
    _, _, path, display_unit = descriptor
    try:
        converted = Quantity.from_value(value, unit).as_unit(display_unit)
    except (QuantityError, ValueError, TypeError) as error:
        fail(str(error), "unit", "E_UNIT")
    if display_unit == "mm" and abs(converted) > MAX_COORDINATE_MM:
        fail("치수가 정밀 편집 상한 1000000 mm를 초과했습니다.", "value", "E_RESOURCE")
    old = at(geometry, path)
    if "parameter_id" in old:
        fail("결합된 치수는 해당 매개변수에서 편집하십시오.", "dimension_key", "E_CONFLICT")
    new_value = Quantity.from_value(converted, display_unit).value_si
    updated = deepcopy(old) if old["value_si"] == new_value else {**deepcopy(old), "value_si": new_value, "status": "user_entered"}
    put(result, path, updated)
    if key == "pad.diameter":
        other = geometry["size"][1]
        if "parameter_id" in other:
            fail("원형 패드 지름이 매개변수에 연결되어 있습니다.", "dimension_key", "E_CONFLICT")
        result["size"][1] = deepcopy(other) if other["value_si"] == new_value else {**deepcopy(other), "value_si": new_value, "status": "user_entered"}
    return result


def bind_dimension(document, geometry, key, parameter_id):
    """! @brief 직접 수량만 명시적으로 매개변수에 결합하며 이전 원문은 명령 출처에 남긴다."""
    descriptor = next((row for row in descriptors(geometry) if row[0] == key), None)
    parameter = document["parameters"].get(parameter_id)
    if descriptor is None or parameter is None:
        fail("직접 치수와 기존 매개변수를 선택하십시오.", "parameter_id", "E_CONFLICT")
    _, _, path, unit = descriptor
    dimension = "angle" if unit == "deg" else "length"
    if parameter["quantity"]["dimension"] != dimension:
        fail("치수와 매개변수의 물리 차원이 다릅니다.", "parameter_id", "E_UNIT")
    if parameter["quantity"]["value_si"] is None:
        fail("미정 매개변수를 가동 치수에 결합할 수 없습니다.", "parameter_id", "E_CONFLICT")
    scalar(document, {"parameter_id": parameter_id}, dimension, unit, "parameter_id")
    result = deepcopy(geometry)
    put(result, path, {"parameter_id": parameter_id})
    if key == "pad.diameter":
        result["size"][1] = {"parameter_id": parameter_id}
    return result
