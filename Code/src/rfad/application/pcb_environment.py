"""! @brief PCB 설치 환경의 형상, 재료 경계와 공기 여백을 계획에 고정한다."""

from rfad.application.pcb_geometry import fail, length, scalar
from rfad.domain.physical_setup import candidates, setup


def board_extents(case, *, sheet=False):
    """! @brief 적층 외면 또는 계산에 사용한 유전체 경계의 범위를 구한다."""
    z = [value for layer in case["layers"] if not sheet or layer["role"] == "dielectric"
         for value in (layer["z_min_mm"], layer["z_min_mm"] + layer["thickness_mm"])]
    return [*case["board"]["bounds_mm"], [min(z), max(z)]]


def scene_extents(case, *, sheet=False):
    """! @brief 공기 격자와 방사 폐곡면에 포함한 설치 물체의 외곽을 반영한다."""
    bounds = board_extents(case, sheet=sheet)
    for part in case.get("environment", {}).get("parts", []):
        bounds = [[min(a, lo), max(b, hi)] for (a, b), lo, hi in
                  zip(bounds, part["start_mm"], part["stop_mm"])]
    return bounds


def _case_boxes(start, stop, wall):
    """! @brief 바닥을 열고 맞닿는 덮개와 네 벽으로 체적을 정확히 분할한다."""
    x0, y0, z0 = start
    x1, y1, z1 = stop
    ceiling = z1 - wall
    return [
        [[x0, y0, ceiling], [x1, y1, z1]],
        [[x0, y0, z0], [x0 + wall, y1, ceiling]],
        [[x1 - wall, y0, z0], [x1, y1, ceiling]],
        [[x0 + wall, y0, z0], [x1 - wall, y0 + wall, ceiling]],
        [[x0 + wall, y1 - wall, z0], [x1 - wall, y1, ceiling]],
    ]


def _box(document, row):
    """! @brief 축 정렬된 외형의 좌표와 명시 크기를 해석 단위로 바꾼다."""
    field = "part." + row["id"]
    if scalar(document, row["yaw"], "angle", field + ".yaw") != 0:
        fail("E_UNSUPPORTED", "설치 해석은 Z축 회전 0도의 축 정렬 물체를 지원합니다.", field + ".yaw")
    start = [length(document, row[key], field + "." + key) for key in ("x", "y", "z")]
    size = [length(document, row[key], field + "." + key, positive=True) for key in ("width", "height", "depth")]
    stop = [a + width for a, width in zip(start, size)]
    if any(abs(value) > 1000 for value in start + stop):
        fail("E_RESOURCE", "설치 해석 좌표는 절댓값 1000 mm 이하를 지원합니다.", field)
    return start, stop, size


def _part(row, start, stop):
    """! @brief 중심 대신 원본 좌표와 재료 참조를 결과에 남긴다."""
    return {**{key: row[key] for key in ("id", "name", "kind", "material_id")},
            "start_mm": start, "stop_mm": stop}


def _dielectric_case(document, row, pcb, step, dielectric):
    """! @brief 하부 개방 케이스에 별도 재료와 기판까지의 간격을 적용한다."""
    field = "part." + row["id"]
    start, stop, size = _box(document, row)
    wall = length(document, row["case_thickness"], field + ".case_thickness", positive=True)
    if wall < 2 * step or min(size[:2]) <= 2 * wall or size[2] <= wall:
        fail("E_GEOMETRY", "빈 내부 공간과 두 격자 이상 두께의 케이스 벽이 필요합니다.", field + ".case_thickness")
    clearances = [[lo - (start[i] + wall), (stop[i] - wall) - hi] for i, (lo, hi) in enumerate(pcb[:2])]
    ceiling = stop[2] - wall - pcb[2][1]
    if start[2] > pcb[2][0] or min(ceiling, *(gap for pair in clearances for gap in pair)) < step:
        fail("E_GEOMETRY", "케이스 하단은 PCB 하단 이하에 놓고, 벽과 덮개의 PCB 간극을 한 격자 이상 확보하십시오.", field)
    properties = dielectric(row["material_id"], field + ".material_id")
    return {**_part(row, start, stop), "wall_mm": wall, "boxes_mm": _case_boxes(start, stop, wall),
            "pcb_clearance_xy_mm": clearances, "pcb_ceiling_clearance_mm": ceiling, **properties}


def _isolated_box(document, row, occupied_boxes, step):
    """! @brief 도체 접촉을 유도하지 않는 편평한 축 분리 거리만 인정한다."""
    field = "part." + row["id"]
    start, stop, size = _box(document, row)
    if min(size) < 2 * step:
        fail("E_GEOMETRY", "비접촉 금속 상자의 각 축 치수는 두 격자 이상이어야 합니다.", field)
    distances = [max(max(a - hi, lo - b) for a, b, lo, hi in zip(start, stop, other_start, other_stop))
                 for other_start, other_stop in occupied_boxes]
    clearance = min(distances)
    if clearance < step:
        fail("E_GEOMETRY", "금속과 PCB 외곽, 케이스 벽 또는 다른 금속 사이에 한 격자 이상의 축 방향 간극이 필요합니다.", field)
    return {**_part(row, start, stop), "boxes_mm": [[start, stop]], "metal_model": "perfect_electric_conductor",
            "electrical_connection": "isolated", "minimum_axis_clearance_mm": clearance, "material_values_consumed": False}


def project_environment(document, case, dielectric):
    """! @brief 활성 설치 환경에 포함한 유전체와 비접촉 도체를 봉인한다."""
    _, part_rows = candidates(document)
    included = [row for row in part_rows if row["include_in_em"]]
    if not included:
        return None
    cases = [row for row in included if row["kind"] == "dielectric_case"]
    settings = case["settings"]
    if len(cases) > 1 or "power_balance" in settings:
        fail("E_UNSUPPORTED", "설치 해석은 케이스 최대 하나와 일반 포트/방사 계산을 지원합니다.", "physical_setup")
    pcb = board_extents(case)
    step = settings["grid_mm"]
    parts = [_dielectric_case(document, row, pcb, step, dielectric) for row in cases]
    occupied_boxes = [list(zip(*pcb))]
    occupied_boxes.extend(box for part in parts for box in part["boxes_mm"])
    for row in included:
        if row["kind"] == "isolated_pec_box":
            metal = _isolated_box(document, row, occupied_boxes, step)
            parts.append(metal)
            occupied_boxes.extend(metal["boxes_mm"])
    model = setup(document)
    scenario_id = model["active_scenario_id"]
    scenario = next(item for item in model["scenarios"] if item["id"] == scenario_id)
    return {"scenario_id": scenario_id, "name": scenario["name"], "parts": parts}
