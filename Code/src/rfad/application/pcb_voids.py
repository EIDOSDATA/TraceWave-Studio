"""! @brief 명시된 비도금 관통 홀과 내부 절삭을 PCB 해석의 공기 체적으로 투영한다."""

import math

from rfad.application.pcb_contacts import _polygon, _polygons_too_close, _segment_distance_squared, _segment_hits_polygon
from rfad.application.pcb_geometry import _bounds, _inside_board, fail, length, point, scalar, shape_polygons
from rfad.domain.pcb_features import records
from rfad.domain.planar import decompose_region


def _profile(document, row, field, step, tolerance):
    """! @brief 실제 완성 치수를 사용하고 곡선의 검사용 polygon과 해석형 정보를 구한다."""
    shape = row["shape"]
    kind = shape["kind"]
    if kind == "polygon":
        outer = [point(document, pair, field + ".outer") for pair in shape["outer"]]
        tile = decompose_region(outer, [])[0]
        witness = [math.fsum(pair[axis] for pair in tile) / len(tile) for axis in range(2)]
        return {"outline_mm": outer, "witness_mm": witness}, {"kind": "planar_region", "outer_mm": outer}, outer
    center = point(document, shape["center"], field + ".center")
    value = "diameter" if kind == "circle" else "finished_width"
    width = length(document, shape[value], field + "." + value, positive=True)
    if width < 2 * step:
        fail("E_GEOMETRY", "관통 홀 또는 슬롯의 완성 폭을 최소 두 격자로 표현하십시오.", field)
    result = {"witness_mm": center, "radius_mm": width / 2}
    if kind == "circle":
        footprint = {"kind": "pad", "pad_shape": "circle", "center_mm": center, "size_mm": [width, width]}
    else:
        finished = length(document, shape["finished_length"], field + ".finished_length", positive=True)
        angle = scalar(document, shape["rotation"], "angle", field + ".rotation")
        axis = [math.cos(angle), math.sin(angle)]
        start, stop = ([round(v + sign * direction * (finished - width) / 2, 12) for v, direction in zip(center, axis)]
                       for sign in (-1, 1))
        if start == stop:
            fail("E_GEOMETRY", "격자 정밀도에서 슬롯 중심선의 길이를 표현할 수 없습니다.", field)
        result.update(start_mm=start, stop_mm=stop)
        footprint = {"kind": "line_path", "start_mm": start, "end_mm": stop, "width_mm": width}
    return result, footprint, shape_polygons(footprint, tolerance)[0]


def project_voids(document, case, polygons_by_id):
    """! @brief 기판 경계, 급전, 구리 및 비아를 침범하지 않는 내부 공기 영역을 구한다."""
    cutouts, holes = (records(document, key) for key in ("board.cutouts", "pcb.holes"))
    if not (cutouts or holes):
        return []
    if "power_balance" in case["settings"]:
        fail("E_UNSUPPORTED", "기계 절삭은 일반 해석을 지원합니다. 독립 손실 적분은 별도 검증이 필요합니다.", "pcb.mechanical")
    step = case["settings"]["grid_mm"]
    tolerance = case["settings"]["curve_tolerance_mm"]
    guard = max(step / 2, 2 * tolerance)
    surfaces = {row["id"] for row in case.get("surface_layers", [])}
    conductor_polygons = [_polygon(poly, "geometry." + identity)
                          for identity, polygons in polygons_by_id.items() for poly in polygons]
    for via in case["vias"]:
        radius = via["outer_radius_mm"]
        footprint = {"kind": "pad", "pad_shape": "circle", "center_mm": via["center_mm"], "size_mm": [2 * radius] * 2}
        conductor_polygons.append(_polygon(shape_polygons(footprint, tolerance)[0], "geometry." + via["id"]))
    planes = [v for layer in case["layers"] if layer["role"] == "dielectric"
              for v in (layer["z_min_mm"], layer["z_min_mm"] + layer["thickness_mm"])]
    port_a, port_b = (case["port"][key][:2] for key in ("start_mm", "stop_mm"))
    preceding, result = [], []
    for row in [*cutouts, *holes]:
        field = "pcb.mechanical." + row["id"]
        if surfaces.intersection(row["surface_cut_ids"]):
            fail("E_UNSUPPORTED", "관통 절삭과 연결된 표면층 개구는 별도의 명시 마스크 개구가 필요합니다.", field)
        shape = row["shape"]
        profile, footprint, polygon = _profile(document, row, field, step, tolerance)
        planar = _polygon(polygon, field)
        bounds = _bounds(footprint)
        if not _inside_board(case["board"], footprint) or min(b - a for a, b in bounds) < 2 * step:
            fail("E_GEOMETRY", "관통 절삭은 기판 내부에 두고 두 격자 이상의 완성 크기를 지정하십시오.", field)
        # @brief 기판 외곽이나 다른 절삭과 거의 닿는 형상은 외곽 notch로 바꾸지 않는다.
        board = case["board"]
        if board["kind"] == "circle":
            outer_guard = board["radius_mm"] - max(math.dist(p, board["center_mm"]) for p in polygon)
        else:
            outer_guard = min(min(low - a, b - high) for (low, high), (a, b) in zip(bounds, board["bounds_mm"]))
        if outer_guard < guard or any(_polygons_too_close(planar, other, guard) for other in preceding):
            fail("E_GEOMETRY", "기판 외곽과 다른 절삭에서 충분한 해석 간격을 확보하십시오.", field)
        if (_segment_hits_polygon(port_a, port_b, planar)
                or any(_segment_distance_squared(port_a, port_b, a, b) <= guard ** 2 for a, b, _ in planar["edges"])
                or any(_polygons_too_close(planar, copper, guard) for copper in conductor_polygons)):
            fail("E_CONNECTIVITY", "관통 절삭이 도체, 비아 또는 급전 간극에 너무 가깝습니다. 해석 구리 개구를 명시하십시오.", field)
        preceding.append(planar)
        result.append({"id": row["id"], "kind": shape["kind"], "bounds_mm": bounds, "z_mm": [min(planes), max(planes)], **profile})
    return result
