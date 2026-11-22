"""! @brief 계산을 접수하기 전 실제 PCB 격자선과 해석 입력의 기하를 읽는다."""

from bisect import bisect_left, bisect_right
import math

from rfad.application.canonical import canonical_hash
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.errors import ProjectError


METHOD = "solver.preview"


def _box(bounds):
    """! @brief 해석기에 전달하는 축별 좌표로 사각 체적을 표시한다."""
    return {"kind": "box", "bounds_mm": bounds}


def _poly(points, z_range):
    """! @brief 실제로 투영한 평면 꼭짓점과 높이를 유지한다."""
    return {"kind": "polygon", "points_mm": points, "z_mm": z_range}


def _circle(center, radius, z_range):
    """! @brief 원통 또는 배럴의 실제 원형 경계를 유지한다."""
    return {"kind": "circle", "center_mm": center, "radius_mm": radius, "z_mm": z_range}


def _board(board, z_range):
    """! @brief 유전체 체적의 native 외곽을 같은 매개변수로 표시한다."""
    if board["kind"] == "circle":
        return _circle(board["center_mm"], board["radius_mm"], z_range)
    if board["kind"] == "polygon":
        return _poly(board["outer_mm"], z_range)
    return _box([*board["bounds_mm"], z_range])


def model_review(document, plan):
    """! @brief 표시 장면 대신 실제 plan case의 소비 대상과 제외 대상을 정리한다."""
    from rfad.application.pcb_geometry import shape_polygons
    from rfad.application.pcb_surfaces import native_surface_name
    from rfad.domain.object_names import display_names
    from rfad.domain.pcb_features import records
    from rfad.domain.physical_setup import candidates

    case = plan["case"]
    board = case["board"]
    layers = {row["id"]: row["name"] for row in document["stackup"]}
    geometry_names = display_names(document)
    surfaces, parts = candidates(document)
    names = {**geometry_names, **{row["id"]: row["name"] for row in [*surfaces, *parts]}}
    names.update({row["id"]: row["name"] for key in ("board.cutouts", "pcb.holes")
                  for row in records(document, key) if "name" in row})
    included = []

    def add(identity, name, role, native, primitives):
        """! @brief 안정 객체 ID로 실제 입력 속성과 표시 경계를 연결한다."""
        included.append({"id": identity, "name": name, "role": role, "native_property": native, "primitives": primitives})

    for row in case["layers"]:
        if row["role"] == "dielectric":
            z = row["z_min_mm"]
            add(row["id"], layers[row["id"]], "dielectric", "dielectric_" + row["id"],
                [_board(board, [z, z + row["thickness_mm"]])])
    for row in case.get("environment", {}).get("parts", []):
        key = row["id"]
        add(key, names[key], "environment", "environment_" + key,
            [_box([list(axis) for axis in zip(start, stop)]) for start, stop in row["boxes_mm"]])
    for row in case.get("surface_layers", []):
        key = row["id"]
        z_range = row["bounds_mm"][2]
        if row["profile"] == "rectangular_tiles":
            pieces = [_box([*tile, z_range]) for tile in row["tiles_mm"]]
        elif row["profile"] == "linear_polygon_tiles":
            pieces = [_poly(tile, z_range) for tile in row["linear_tiles_mm"]]
        else:
            pieces = [_board(board, z_range)]
            pieces.extend({**_box([*hole, z_range]), "opening": True} for hole in row["openings_mm"])
        add(key, names[key], "surface", native_surface_name(row), pieces)
    for row in case.get("mechanical_voids", []):
        key = row["id"]
        z_range = row["z_mm"]
        if row["kind"] == "polygon":
            pieces = [_poly(row["outline_mm"], z_range)]
        elif row["kind"] == "circle":
            pieces = [_circle(row["witness_mm"], row["radius_mm"], z_range)]
        else:
            start, stop = row["start_mm"], row["stop_mm"]
            dx, dy = stop[0] - start[0], stop[1] - start[1]
            radius = row["radius_mm"]
            scale = radius / math.hypot(dx, dy)
            nx, ny = -dy * scale, dx * scale
            polygon = [[start[0] + nx, start[1] + ny], [start[0] - nx, start[1] - ny],
                       [stop[0] - nx, stop[1] - ny], [stop[0] + nx, stop[1] + ny]]
            pieces = [_poly(polygon, z_range), _circle(start, radius, z_range), _circle(stop, radius, z_range)]
        add(key, names.get(key, "기계 절삭"), "void", "mechanical_void_" + key, pieces)
    for row in case["shapes"]:
        key = row["id"]
        polygons = shape_polygons(row, case["settings"]["curve_tolerance_mm"])
        z = row["sheet_z_mm"]
        add(key, geometry_names[key], "conductor", "conductor_" + key, [_poly(points, [z, z]) for points in polygons])
    for row in case.get("vias", []):
        key = row["id"]
        z_range = [row["z_min_mm"], row["z_max_mm"]]
        add(key, geometry_names[key], "via", "via_" + key,
            [_circle(row["center_mm"], row["outer_radius_mm"], z_range),
             {**_circle(row["center_mm"], row["inner_radius_mm"], z_range), "opening": True}])
    port = case["port"]
    source = document["ports"][0]
    add(source["id"], source["name"], "port", "LumpedPort 1",
        [{"kind": "segment", "start_mm": port["start_mm"], "stop_mm": port["stop_mm"]}])
    excluded = [plan["model_report"]["omissions"], plan.get("physical_setup_omissions", [])]
    return {"included": included, "excluded": [{**row, "name": names.get(row["id"], row["id"])}
                                               for group in excluded for row in group]}


def mesh_intervals(case, lines):
    """! @brief 실제 격자의 좁은 입력 구간과 보수적인 자유공간 시간 간격을 계산한다."""
    rows = []
    axes = "xyz"
    settings = "settings.feature_subdivisions"
    minimums = []

    def interval(kind, axis, endpoints, path):
        """! @brief 경계 사이의 완전한 셀과 경계에 걸치는 셀을 구분한다."""
        low, high = sorted(endpoints)
        values = lines[axis]
        if not values[0] <= low < high <= values[-1]:
            return
        first = bisect_right(values, low) - 1
        stop = bisect_left(values, high)
        full = max(0, bisect_right(values, high) - bisect_left(values, low) - 1)
        rows.append({"kind": kind, "axis": axis, "bounds_mm": [low, high], "width_mm": high - low,
                     "first_line": first, "cells": stop - first, "full_cells": full, "setting_path": path})

    for axis in axes:
        values = lines[axis]
        index = min(range(len(values) - 1), key=lambda i: values[i + 1] - values[i])
        interval("minimum_cell", axis, values[index:index + 2], "settings.grid_mm")
        minimums.append(values[index + 1] - values[index])
    port = case["port"]
    axis = port["axis"]
    index = axes.index(axis)
    interval("feed_gap", axis, [port["start_mm"][index], port["stop_mm"][index]], settings)
    for surface in case.get("surface_layers", []):
        for opening in surface["openings_mm"]:
            for axis, endpoints in zip(axes, opening):
                interval("surface_opening", axis, endpoints, settings)
    for via in case.get("vias", []):
        radius = via["inner_radius_mm"]
        for axis, center in zip(axes, via["center_mm"]):
            interval("via_bore", axis, [center - radius, center + radius], settings)
    for rule in case.get("local_mesh_report", {}).get("rules", []):
        if rule["kind"] == "gap":
            for axis, record in rule["axes"].items():
                for segment in record["segments"]:
                    if segment["applied"]:
                        interval("local_gap", axis, segment["bounds_mm"], "settings.local_mesh")
    courant_s = 1e-3 / (299_792_458 * math.hypot(*(1 / width for width in minimums)))
    return {"intervals": rows[:128], "interval_total": len(rows), "vacuum_cartesian_cfl_seconds": courant_s}


def _blocking_diagnostics(document, original):
    """! @brief 실제 계획의 실패를 먼저 보이고 독립 입력 사전 검사 결과를 덧붙인다."""
    from rfad.domain.design import preflight_design

    first = original.diagnostic()
    rows = [first]
    seen = {first["details"].get("field_path") or first["code"]}
    try:
        additional = preflight_design(document, "em")
    except ProjectError:
        return rows
    for issue in additional:
        field = issue["details"].get("field_path")
        key = field or issue["code"]
        if issue["severity"] == "blocking" and key not in seen:
            rows.append(issue)
            seen.add(key)
    return rows


def read(service, params):
    """! @brief 영속 스냅샷을 쓰지 않고 개정의 준비 입력과 정확히 같은 격자선을 반환한다."""
    from rfad.application.pcb_clearance_review import planar_clearances
    from rfad.application.pcb_environment import scene_extents
    from rfad.application.pcb_execution import estimate
    from rfad.application.pcb_mesh import wavelength_reference
    from rfad.application.pcb_solver import build_pcb_plan, mesh_lines

    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    data = _fields(params["input"], {"expected_revision", "settings"}, {"include_all_diagnostics"})
    include_all = data.get("include_all_diagnostics", False)
    if type(include_all) is not bool:
        raise ProjectError("E_SCHEMA", "일괄 진단 사용 여부는 참 또는 거짓으로 입력하세요.")
    expected = _uuid(data["expected_revision"])
    state = service.journal.read()
    project = service._project(state, params["context"])
    raw, document = service.repository.read(project["current"])
    if document["revision_id"] != expected:
        raise ProjectError("E_CONFLICT", "해석 입력이 바뀌었습니다. 조건을 다시 확인하세요.")
    runtime = service.solver.runtime
    if runtime is None:
        raise ProjectError("E_UNSUPPORTED", "openEMS 실행 환경의 연결을 확인하세요.")
    snapshot = service.operations.prepare_snapshot(state, project, document, raw, {})
    try:
        plan = build_pcb_plan(document, snapshot, runtime.identity, data["settings"])
    except ProjectError as error:
        if not include_all:
            raise
        rows = _blocking_diagnostics(document, error)
        return {"revision_id": expected, "blocking_diagnostics": rows[:128], "blocking_total": len(rows)}
    case = plan["case"]
    lines = mesh_lines(case)
    bounds = scene_extents(case)
    axes = {}
    for axis, interval in zip("xyz", bounds):
        values = lines[axis]
        pml = [values[8], values[-9]]
        steps = [b - a for a, b in zip(values, values[1:])]
        axes[axis] = {"pml_inner_mm": pml, "air_before_pml_mm": [interval[0] - pml[0], pml[1] - interval[1]],
                      "min_cell_mm": min(steps), "max_cell_mm": max(steps)}
    model = model_review(document, plan)
    return {"revision_id": expected, "estimated": plan["resource_estimate"],
            "execution_estimate": estimate(plan, lines),
            "omissions": plan.get("physical_setup_omissions", {}),
            "outputs": plan.get("outputs", []), "settings": case["settings"],
            "mesh": {"lines_mm": lines, "model_bounds_mm": bounds, "axes": axes,
                     "quality_reference": wavelength_reference(case),
                     "interval_report": mesh_intervals(case, lines),
                     "planar_clearances": planar_clearances(model["included"], lines, case["settings"]["grid_mm"]),
                     **({"local_mesh_report": case["local_mesh_report"]} if "local_mesh_report" in case else {}),
                     "case_sha256": canonical_hash(case), "lines_sha256": canonical_hash(lines)},
            "model": model}
