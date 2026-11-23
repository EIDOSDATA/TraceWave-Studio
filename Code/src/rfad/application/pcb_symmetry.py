"""! @brief 단일 gap PCB의 대칭 투영, 전기 벽 급전과 실제 절반 Yee 격자를 검증한다."""

from rfad.application.pcb_geometry import fail, shape_polygons


FIELD = "settings.symmetry_plane"
EPS_MM = 1e-8


def validate(settings):
    """! @brief 사용자가 요청한 단일 대칭면과 지원하는 여기 및 관측량을 검토한다."""
    if "symmetry_plane" not in settings:
        return
    spec = settings["symmetry_plane"]
    if (type(spec) is not dict or set(spec) != {"axis", "position_mm", "wall"}
            or spec["axis"] not in ("x", "y") or spec["wall"] not in ("PEC", "PMC")
            or type(spec["position_mm"]) not in (float, int) or not -1e6 <= spec["position_mm"] <= 1e6):
        fail("E_SCHEMA", "X 또는 Y축의 유한 대칭면 좌표와 PEC 또는 PMC를 지정하세요.", FIELD)
    if spec["wall"] == "PMC":
        fail("E_UNSUPPORTED", "PMC 반영역의 접선 단일 선 급전은 자기 격자 대칭면에 놓을 수 없습니다. 전체 영역으로 해석하세요.", FIELD)
    if settings.keys() & {"field_probe", "radiation", "power_balance", "mesh_policy", "local_mesh"}:
        fail("E_UNSUPPORTED", "이 대칭 검증은 균일 최대 간격의 단일 급전 S11과 임피던스에 적용됩니다.", FIELD)


def _outline_key(loop, axis, coordinate, reflected=False):
    """! @brief 네이티브 다각형의 순환 시작점과 감기 방향을 제외한 경계를 대조한다."""
    points = [tuple(round(2 * coordinate - v if reflected and d == axis else v, 9) for d, v in enumerate(point))
              for point in loop]
    start = min(range(len(points)), key=points.__getitem__)
    forward = tuple(points[start:] + points[:start])
    return min(forward, (forward[0], *reversed(forward[1:])))


def project(case):
    """! @brief 실제로 소비하는 도체 다각형과 물성, 기판 및 급전이 한 면에 대해 대칭인지 확인한다."""
    spec = case["settings"].get("symmetry_plane")
    if spec is None:
        return
    if ("ports" in case or case.get("vias") or case.get("environment") or case.get("surface_layers")
            or case.get("mechanical_voids")):
        fail("E_UNSUPPORTED", "현재 단일 급전 대칭 검증은 평면 도체와 균일 적층의 기판을 지원합니다.", FIELD)
    axis, coordinate = "xy".index(spec["axis"]), spec["position_mm"]
    board, port = case["board"], case["port"]
    low, high = board["bounds_mm"][axis]
    if (abs((low + high) / 2 - coordinate) > EPS_MM or (board["kind"] == "polygon"
            and _outline_key(board["outer_mm"], axis, coordinate) != _outline_key(board["outer_mm"], axis, coordinate, True))):
        fail("E_GEOMETRY", "기판 외곽이 지정한 면에 대해 대칭이 아닙니다.", FIELD)
    start, stop = port["start_mm"][axis], port["stop_mm"][axis]
    if port["axis"] != spec["axis"] or abs((start + stop) / 2 - coordinate) > EPS_MM:
        fail("E_PORT", "PEC 대칭면은 두 급전 단자의 중점을 지나고 급전 방향에 수직이어야 합니다.", FIELD)
    face = 2 * axis
    modes = case["boundary_conditions"]
    if modes[2 * axis] != modes[2 * axis + 1]:
        fail("E_GEOMETRY", "대칭축 양끝의 전체 영역 경계 조건이 같아야 합니다.", FIELD)
    table, reflected, kept = {}, {}, []
    tolerance = case["settings"]["curve_tolerance_mm"]
    for row in case["shapes"]:
        loops = shape_polygons(row, tolerance)
        points = [p[axis] for loop in loops for p in loop]
        if min(points) <= coordinate + EPS_MM and max(points) >= coordinate - EPS_MM:
            fail("E_UNSUPPORTED", "PEC 대칭면에 닿거나 가로지르는 도체는 전체 영역으로 해석하세요.", FIELD)
        if points[0] > coordinate:
            kept.append(row["id"])
        physical = (row["material_id"], row["sheet_z_mm"], row["thickness_m"], row["conductivity_s_per_m"])
        own = (physical, tuple(sorted(_outline_key(loop, axis, coordinate) for loop in loops)))
        if own in table:
            fail("E_GEOMETRY", "대칭 대응이 모호한 중복 도체가 있습니다.", FIELD)
        table[own] = row["id"]
        reflected[row["id"]] = (physical, tuple(sorted(_outline_key(loop, axis, coordinate, True) for loop in loops)))
    if any(key not in table for key in reflected.values()):
        fail("E_GEOMETRY", "도체의 실제 외곽, 층 또는 재료에 일치하는 반사 형상이 없습니다.", FIELD)
    pairs = {key: table[signature] for key, signature in reflected.items()}
    connected = {tuple(sorted(group)) for group in case["connectivity"]["components"]}
    if ({tuple(sorted(pairs[item] for item in group)) for group in connected} != connected
            or pairs[port["positive_geometry_id"]] != port["reference_geometry_id"]):
        fail("E_PORT", "급전 양단 또는 도체 연결 성분이 서로 대칭으로 대응하지 않습니다.", FIELD)
    terminal, identity = ("start_mm", "reference_geometry_id") if start < stop else ("stop_mm", "positive_geometry_id")
    native_port = {**port, terminal: list(port[terminal]), identity: None, "resistance_ohm": port["resistance_ohm"] / 2}
    native_port[terminal][axis] = coordinate
    case["symmetry"] = {"schema": "rfad.pcb-gap-symmetry/0.1", **spec, "face": face, "retained_sign": 1, "image_endpoint": terminal,
                        "retained_geometry_ids": sorted(kept), "mirror_pairs": pairs, "native_port": native_port,
                        "full_voltage_factor": 2, "full_current_factor": 1}
    modes[face] = "PEC"


def reduce_axis(case, name, points):
    """! @brief 전체 Yee 선마다 상대쪽 선이 있는지 확인한 뒤 대칭면에 닿는 절반을 고른다."""
    report = case.get("symmetry")
    if not report or name != report["axis"]:
        return points
    coordinate = report["position_mm"]
    if (len(points) % 2 != 1 or abs(points[len(points) // 2] - coordinate) > EPS_MM
            or any(abs(a + b - 2 * coordinate) > EPS_MM for a, b in zip(points, reversed(points)))):
        fail("E_GEOMETRY", "PEC 면이 Yee 전기장 격자선과 일치하고 반사한 모든 격자선이 짝을 이루어야 합니다.", FIELD)
    result = points[len(points) // 2:]
    stop = max(report["native_port"][key]["xy".index(name)] for key in ("start_mm", "stop_mm"))
    if sum(coordinate - EPS_MM <= v <= stop + EPS_MM for v in result) < 3:
        fail("E_GEOMETRY", "절반 급전 간극에 최소 두 셀이 필요합니다. 격자 간격을 줄이세요.", "settings.grid_mm")
    return result


def native_case(case):
    """! @brief 저장한 전체 모델을 보존하고 실제 반영역에 속하는 도체와 검증할 연결만 돌려준다."""
    if "symmetry" not in case:
        return case
    report = case["symmetry"]
    retained = set(report["retained_geometry_ids"])
    groups = [sorted(retained.intersection(group)) for group in case["connectivity"]["components"]]
    return {**case, "shapes": [row for row in case["shapes"] if row["id"] in retained],
            "port": report["native_port"], "connectivity": {**case["connectivity"], "components": sorted(g for g in groups if g)}}
