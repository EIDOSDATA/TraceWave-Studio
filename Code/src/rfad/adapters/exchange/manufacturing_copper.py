"""! @brief IPC 및 ODB 원문의 원형 선폭 동박을 단위와 넷이 정해진 편집 객체로 변환한다."""

import math


def trace(layer, net, source, width, start, end, center=None, clockwise=None):
    """! @brief 중심선 좌표와 진행 방향이 유효한 직선 및 원호만 mm 기준으로 구성한다."""
    if (not isinstance(layer, str) or not layer or not isinstance(net, str)
            or not math.isfinite(width) or width <= 0 or start == end
            or any(not math.isfinite(x) or abs(x) > 1e6 for point in (start, end, center or []) for x in point)):
        return None
    item = {"layer": layer, "net": net, "source_id": source, "width_mm": width,
            "start_mm": start, "end_mm": end, "kind": "line_path"}
    if center is not None:
        radius = math.dist(start, center)
        if (radius < 1e-6 or abs(radius - math.dist(end, center)) > 2e-6
                or type(clockwise) is not bool):
            return None
        first, last = (math.degrees(math.atan2(y - center[1], x - center[0])) for x, y in (start, end))
        sweep = -((first - last) % 360) if clockwise else (last - first) % 360
        if abs(sweep) < 1e-8:
            return None
        item.update(kind="arc_path", center_mm=center, radius_mm=radius, start_angle_deg=first, sweep_angle_deg=sweep)
    return item
