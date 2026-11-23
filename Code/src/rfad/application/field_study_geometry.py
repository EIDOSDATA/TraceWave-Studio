"""! @brief 사용자가 고른 전기장 주파수와 물리 영역을 각 실제 Yee 격자에 대응시킨다."""

from bisect import bisect_left, bisect_right

from rfad.application import result_fields
from rfad.domain.errors import ProjectError


def _model(resolved, monitor):
    """! @brief 지정한 한 급전의 유효한 전기장만 연구에 사용한다."""
    if monitor not in ("electric", "probe_electric"):
        raise ProjectError("E_UNSUPPORTED", "전기장 모니터를 선택하십시오.")
    model = result_fields._model(resolved, monitor)
    if model is None:
        raise ProjectError("E_MISSING_ARTIFACT", "선택한 전기장 원문이 없습니다.")
    return model


def _axes(model, component):
    """! @brief 원문 격자선을 선택 성분의 실제 Yee 좌표로 변환한다."""
    return {axis: [result_fields._coordinate(model, model["primary_coordinates_mm"], axis, component, i)
                   for i in range(count)] for axis, count in zip("xyz", model["shape"])}


def anchor(resolved, selection):
    """! @brief 인덱스가 바뀌어도 같은 영역을 지정할 기준 주파수와 mm 범위를 고정한다."""
    monitor = selection["monitor_id"]
    model = _model(resolved, monitor)
    axes, _, indices = result_fields._selection(model, {**selection, "stride": 1})
    coords = _axes(model, selection["component"])
    normal = selection["plane"]["normal_axis"]
    return {"monitor_id": monitor, "component": selection["component"],
            "frequency_hz": model["frequency_hz"][selection["frequency_index"]], "normal_axis": normal,
            "plane_mm": coords[normal][selection["plane"]["index"]],
            "bounds_mm": {axis: [coords[axis][ids[0]], coords[axis][ids[-1]]] for axis, ids in zip(axes, indices)}}


def selection_for(resolved, region):
    """! @brief 물리 범위 안의 모든 현재 표본과 가장 가까운 단면을 선택하고 실제 위치를 보존한다."""
    monitor, component, normal = region["monitor_id"], region["component"], region["normal_axis"]
    model = _model(resolved, monitor)
    if region["frequency_hz"] not in model["frequency_hz"]:
        raise ProjectError("E_HASH", "선택한 기록 주파수가 다음 결과에 없습니다.")
    coords = _axes(model, component)
    plane = region["plane_mm"]
    normal_coords = coords[normal]
    lower, upper = normal_coords[0], normal_coords[-1]
    if normal == component:
        lower = model["primary_coordinates_mm"][normal][0]
        upper = model["next_nodes_mm"][normal]
    if not lower - 1e-9 <= plane <= upper + 1e-9:
        raise ProjectError("E_GEOMETRY", "원래 단면 위치가 현재 기록의 범위를 벗어났습니다.")
    index = min(range(len(normal_coords)), key=lambda i: abs(normal_coords[i] - plane))
    roi = {}
    for label, axis in zip("uv", (axis for axis in "xyz" if axis != normal)):
        low, high = region["bounds_mm"][axis]
        start = bisect_left(coords[axis], low - 1e-9)
        stop = bisect_right(coords[axis], high + 1e-9)
        if start >= stop:
            raise ProjectError("E_GEOMETRY", "원래 물리 영역에 해당하는 Yee 표본이 없습니다.")
        roi.update({label + "_start": start, label + "_count": stop - start})
    selection = {"monitor_id": monitor, "component": component, "frequency_index": model["frequency_hz"].index(region["frequency_hz"]),
                 "plane": {"normal_axis": normal, "index": index}, "roi": roi}
    used = anchor(resolved, selection)
    return selection, used


def compare(left, right, profile):
    """! @brief 격자 의존 기록 인덱스만 제외하고 같은 입력/실행 주체의 실제 공통 주파수 표본을 비교한다."""
    from rfad.application.convergence import compare_samples

    pair = []
    for item in (left, right):
        provenance = item["provenance"]
        plan = provenance["analysis_plan"]
        case = dict(plan["case"])
        if "field_probe" in case["settings"] and "field_recording" not in case:
            raise ProjectError("E_HASH", "선택한 전계 기록 조건에 해당하는 봉인 기록 계획이 없습니다.")
        case.pop("field_recording", None)
        pair.append({**item, "provenance": {**provenance, "analysis_plan": {**plan, "case": case}}})
    def physical_settings(item):
        """! @brief 국부 격자를 제외한 모델, 기록 영역, 해석 시간, 예산 설정을 엄격히 대조한다."""
        settings = dict(item["provenance"]["analysis_plan"]["case"]["settings"])
        settings.pop("local_mesh", None)
        return settings
    if physical_settings(left) != physical_settings(right):
        raise ProjectError("E_HASH", "국부 격자 외의 해석 또는 기록 조건이 달라졌습니다.")
    return compare_samples(*pair, profile, frequency_rows=True)
