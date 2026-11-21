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


def project_environment(document, case, dielectric):
    """! @brief 사용자 지정 하부 개방 케이스에 별도 재료 및 최소 간극을 적용한다."""
    _, candidates_in_scene = candidates(document)
    included = [row for row in candidates_in_scene if row["include_in_em"]]
    if not included:
        return None
    settings = case["settings"]
    if len(included) > 1 or "power_balance" in settings:
        fail("E_UNSUPPORTED", "설치 해석은 케이스 하나와 일반 포트/방사 계산을 지원합니다.", "physical_setup")
    row = included[0]
    field = "part." + row["id"]
    if scalar(document, row["yaw"], "angle", field + ".yaw") != 0:
        fail("E_UNSUPPORTED", "설치 해석은 Z축 회전 0도의 축 정렬 케이스를 지원합니다.", field + ".yaw")
    start = [length(document, row[key], field + "." + key) for key in ("x", "y", "z")]
    size = [length(document, row[key], field + "." + key, positive=True) for key in ("width", "height", "depth")]
    stop = [a + width for a, width in zip(start, size)]
    if any(abs(value) > 1000 for value in start + stop):
        fail("E_RESOURCE", "설치 해석 좌표는 절댓값 1000 mm 이하를 지원합니다.", field)
    wall = length(document, row["case_thickness"], field + ".case_thickness", positive=True)
    step = settings["grid_mm"]
    if wall < 2 * step or min(size[:2]) <= 2 * wall or size[2] <= wall:
        fail("E_GEOMETRY", "빈 내부 공간과 두 격자 이상 두께의 케이스 벽이 필요합니다.", field + ".case_thickness")
    pcb = board_extents(case)
    clearances = [[lo - (start[i] + wall), (stop[i] - wall) - hi] for i, (lo, hi) in enumerate(pcb[:2])]
    ceiling = stop[2] - wall - pcb[2][1]
    if start[2] > pcb[2][0] or min(ceiling, *(gap for pair in clearances for gap in pair)) < step:
        fail("E_GEOMETRY", "케이스 하단은 PCB 하단 이하에 놓고, 벽과 덮개의 PCB 간극을 한 격자 이상 확보하십시오.", field)
    properties = dielectric(row["material_id"], field + ".material_id")
    mat = setup(document)
    scenario_id = mat["active_scenario_id"]
    scenario = next(item for item in mat["scenarios"] if item["id"] == scenario_id)
    return {"scenario_id": scenario_id, "name": scenario["name"],
            "parts": [{"id": row["id"], "name": row["name"], "kind": row["kind"], "material_id": row["material_id"],
                       "start_mm": start, "stop_mm": stop, "wall_mm": wall, "boxes_mm": _case_boxes(start, stop, wall),
                       "pcb_clearance_xy_mm": clearances, "pcb_ceiling_clearance_mm": ceiling, **properties}]}
