"""! @brief PCB 설치 환경의 형상, 재료 경계와 공기 여백을 계획에 고정한다."""

import math

from rfad.application.pcb_geometry import _bounds, fail, length, scalar
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
    for surface in case.get("surface_layers", []):
        bounds = [[min(a, c), max(b, d)] for (a, b), (c, d) in zip(bounds, surface["bounds_mm"])]
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


def _ground_attachment(case, start, stop, step, field):
    """! @brief 명시한 상부 기준 패드에서 물리 외면과 모델의 도체 면을 각각 확인한다."""
    port = case["port"]
    ref = next(shape for shape in case["shapes"] if shape["id"] == port["reference_geometry_id"])
    layer = case["layers"][-1]
    if (ref["role"] != "ground" or ref["kind"] != "pad" or ref["pad_shape"] != "rectangle"
            or ref["rotation_deg"] != 0 or ref["layer_id"] != layer["id"]):
        fail("E_CONNECTIVITY", "접지 금속은 최상층의 축 정렬 사각 급전 기준 접지 패드가 필요합니다.", field)
    surface = layer["z_min_mm"] + layer["thickness_mm"]
    if not math.isclose(start[2], surface, rel_tol=0, abs_tol=1e-8):
        fail("E_CONNECTIVITY", "접지 금속의 하단 Z를 기준 패드의 실제 윗면에 맞추십시오.", field + ".z")
    if any(min(a - lo, hi - b) < step - 1e-8 for a, b, (lo, hi) in zip(start, stop, _bounds(ref))):
        fail("E_CONNECTIVITY", "금속의 접촉면을 접지 패드 안에 놓고 패드 가장자리에서 한 격자 이상 띄우십시오.", field)
    return {"ground_geometry_id": ref["id"], "ground_net_id": ref["net_id"],
            "physical_contact_z_mm": surface, "native_contact_z_mm": ref["sheet_z_mm"]}


def _metal_box(document, row, case, pcb_box, occupied_boxes, step):
    """! @brief 명시 접지 접면과 격자상 비접촉을 각각 검사한다."""
    field = "part." + row["id"]
    start, stop, size = _box(document, row)
    if min(size) < 2 * step:
        fail("E_GEOMETRY", "금속 상자의 각 축 치수는 두 격자 이상이어야 합니다.", field)
    grounded = row["kind"] == "grounded_pec_box"
    attachment = _ground_attachment(case, start, stop, step, field) if grounded else {}
    native_start = [*start[:2], attachment["native_contact_z_mm"]] if grounded else start
    separated = occupied_boxes if grounded else [pcb_box, *occupied_boxes]
    distances = [max(max(a - hi, lo - b) for a, b, lo, hi in zip(native_start, stop, other_start, other_stop))
                 for other_start, other_stop in separated]
    clearance = min(distances, default=None)
    if clearance is not None and clearance < step:
        fail("E_GEOMETRY", "금속과 PCB 외곽, 케이스 벽 또는 다른 금속 사이에 한 격자 이상의 축 방향 간극이 필요합니다.", field)
    return {**_part(row, start, stop), "boxes_mm": [[native_start, stop]], "metal_model": "perfect_electric_conductor",
            "electrical_connection": "grounded" if grounded else "isolated",
            "minimum_axis_clearance_mm": clearance, "material_values_consumed": False, **attachment}


def project_environment(document, case, dielectric):
    """! @brief 활성 설치 환경에 포함한 유전체와 금속의 연결 조건을 봉인한다."""
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
    pcb_box = list(zip(*pcb))
    occupied_boxes = [box for part in parts for box in part["boxes_mm"]]
    for row in included:
        if row["kind"] in ("isolated_pec_box", "grounded_pec_box"):
            metal = _metal_box(document, row, case, pcb_box, occupied_boxes, step)
            parts.append(metal)
            occupied_boxes.extend(metal["boxes_mm"])
    model = setup(document)
    scenario_id = model["active_scenario_id"]
    scenario = next(item for item in model["scenarios"] if item["id"] == scenario_id)
    return {"scenario_id": scenario_id, "name": scenario["name"], "parts": parts}
