"""! @brief 지원 형상에서 구동 치수의 직접 이동과 접촉 보존을 검토한다."""

from copy import deepcopy
import math

from rfad.application.canvas import project_canvas
from rfad.application.pcb_contacts import CONTACT_EPSILON_MM, _polygon, _polygons_too_close, _segment_hits_polygon, validate_native_contacts
from rfad.application.pcb_geometry import _inside_board, length, shape_polygons
from rfad.application.pcb_projection import project_board
from rfad.application.pcb_voids import _profile
from rfad.domain.layer_surface import single_dielectric_contact
from rfad.domain.pcb_features import owner_map, records
from rfad.domain.precision_transform import fail, point, replace_literal
from rfad.domain.smart_dimensions import EPSILON_MM, hole_sources, positions


TOLERANCE_MM = 0.005


def drive_reason(document, anchors):
    """! @brief 편집 가능한 기준점 종류와 원본 결합의 제한을 설명한다."""
    if anchors["kind"] == "holes":
        row = hole_sources(document)[anchors["ids"][1]]
        if (row.get("shape", {}).get("kind") != "circle" or row["plating"]["state"] != "unplated"
                or row["surface_cut_ids"] or row["id"] in owner_map(document)):
            return "두 번째 기준점은 풋프린트나 표면에 연결되지 않은 비도금 원형 홀이 필요합니다."
        if any("parameter_id" in value for value in row["shape"]["center"]):
            return "두 번째 홀 중심이 매개변수에 연결되어 있습니다."
        return ""
    port = next(row for row in document["ports"] if row["id"] == anchors["ids"][0])
    delta = [b - a for a, b in zip(*positions(document, anchors))]
    axes = [i for i, value in enumerate(port["direction"]) if abs(value) == 1]
    if (len(axes) != 1 or axes[0] == 2 or any(port["direction"][i] != 0 or abs(delta[i]) > EPSILON_MM
             for i in range(3) if i != axes[0]) or delta[axes[0]] * port["direction"][axes[0]] <= EPSILON_MM):
        return "구동 급전은 X 또는 Y축과 나란한 양단에 적용합니다."
    geometry = {row["id"]: row for row in document["geometry"]}
    moving = geometry.get(port["positive_geometry_id"])
    fixed = geometry.get(port["reference_geometry_id"])
    if (moving is None or fixed is None or document["board"] is None or moving["kind"] not in ("line_path", "pad")
            or moving["layer_id"] != fixed["layer_id"]
            or {moving["frame_id"], fixed["frame_id"]} != {document["board"]["frame_id"]}):
        return "같은 기판 층에서 신호 단자가 선 또는 패드인 급전을 선택하세요."
    identity = moving["id"]
    if (identity in owner_map(document) or any(row["kind"] == "via" for row in geometry.values())
            or any(identity in (row["positive_geometry_id"], row["reference_geometry_id"])
                   for row in document["ports"] if row["id"] != port["id"])
            or "parameter_id" in port["excitation_box"]["stop"][axes[0]]):
        return "비아, 다른 급전, 풋프린트 또는 매개변수와 결합된 입력에서는 참조 치수를 사용하세요."
    if any("parameter_id" in value for name in (("start", "end") if moving["kind"] == "line_path" else ("center",))
           for value in moving[name]):
        return "신호 단자의 이동 좌표가 매개변수에 연결되어 있습니다."
    return ""


def _copper(document, layer_id=None):
    """! @brief 기존 2D 투영을 같은 평면의 닫힌 도체 경계로 변환한다."""
    raw = {row["id"]: row for row in document["geometry"] if layer_id is None or row["layer_id"] == layer_id}
    scene = {row["id"]: row for row in project_canvas(document)["shapes"]}
    result, polygons = [], {}
    coordinate_keys = {"line_path": ("start", "end", "width"), "arc_path": ("center", "radius", "width"),
                       "pad": ("center", "size"), "planar_region": ("outer", "holes"),
                       "via": ("center", "finished_hole_diameter", "plating_thickness")}
    for identity, row in raw.items():
        if identity not in scene or document["board"] is None or row["frame_id"] != document["board"]["frame_id"]:
            fail("접촉을 검토할 같은 기판 좌표계의 유한 도체 형상이 필요합니다.", "anchors", "E_CONFLICT")
        projected = scene[identity]
        if row["kind"] == "via":
            width = 2 * (projected["finished_hole_diameter"] / 2 + projected["plating_thickness"]) if all(
                projected.get(key) is not None for key in coordinate_keys["via"][1:]) else None
            if width is None:
                fail("비아의 실제 외곽이 미정입니다.", "anchors", "E_CONFLICT")
            shape = {"kind": "pad", "pad_shape": "circle", "center_mm": projected["center"], "size_mm": [width, width]}
        else:
            shape = {"kind": row["kind"], **{key + "_mm": projected[key] for key in coordinate_keys[row["kind"]]}}
            if row["kind"] == "pad":
                shape.update(pad_shape=projected["pad_shape"], rotation_deg=projected["rotation"])
            elif row["kind"] == "arc_path":
                shape.update(start_angle_deg=projected["start_angle"], sweep_angle_deg=projected["sweep_angle"])
        layer = next(item for item in document["stackup"] if item["id"] == row["layer_id"])
        shape.update(id=identity, role=row["role"], net_id=row["net_id"],
                     material_id=row["material_ref"] or layer["material_id"])
        pieces = shape_polygons(shape, TOLERANCE_MM)
        result.append(shape)
        polygons[identity] = pieces
    return result, polygons


def _voids(document, excluded=None):
    """! @brief 기존 기판 홀과 절삭의 원래 경계를 낸다."""
    for collection in ("pcb.holes", "board.cutouts"):
        for row in records(document, collection):
            if row["id"] != excluded:
                if document["board"] is None or row["frame_id"] != document["board"]["frame_id"]:
                    fail("홀 또는 절삭의 기판 좌표계를 확인하세요.", "anchors", "E_CONFLICT")
                yield _profile(document, row, "pcb." + row["id"], 0, TOLERANCE_MM)[2]


def _overlap(pieces, others):
    """! @brief 가공 외곽이 닿거나 겹치는 후보를 보수적으로 검사한다."""
    polygons = [_polygon(points, "anchors") for points in pieces]
    return any(_polygons_too_close(left, _polygon(points, "anchors"), TOLERANCE_MM)
               for points in others for left in polygons)


def _move_hole(candidate, anchors, destination):
    """! @brief 고정된 첫 중심과 독립적인 두 번째 비도금 홀만 옮긴다."""
    _, moving = anchors["ids"]
    row = hole_sources(candidate)[moving]
    shape = row["shape"]
    shape["center"] = [replace_literal(candidate, original, value, "mm", "hole.center")
                       for original, value in zip(shape["center"], destination)]
    _, footprint, polygon = _profile(candidate, row, "hole.shape", 0, TOLERANCE_MM)
    if not _inside_board(project_board(candidate), footprint, TOLERANCE_MM):
        fail("이동한 홀의 외곽이 기판을 벗어납니다.", "target_mm", "E_CONFLICT")
    _, copper = _copper(candidate)
    other_voids = list(_voids(candidate, moving))
    if _overlap([polygon], [*other_voids, *(poly for polys in copper.values() for poly in polys)]):
        fail("이동한 홀이 다른 홀, 절삭 또는 도체와 겹치거나 닿습니다.", "target_mm", "E_CONFLICT")


def _contact_geometry(document, port, layer_id, pos):
    """! @brief 평면 도체와 급전 접촉 경계를 검증하고 신호 단자의 이웃을 기록한다."""
    shapes, polygons = _copper(document, layer_id)
    start, stop = pos
    axis = next(i for i in (0, 1) if abs(port["direction"][i]) == 1)
    layer = next(row for row in document["stackup"] if row["id"] == layer_id)
    if layer["role"] != "conductor":
        fail("급전 양단의 도체 층을 확인하세요.", "anchors", "E_CONFLICT")
    def level(row):
        """! @brief 봉인 층의 실제 높이와 두께를 해석과 같은 정밀도로 읽는다."""
        return (length(document, row["z_min"], "stackup.z_min"),
                length(document, row["thickness"], "stackup.thickness", positive=True))

    z_min, thickness = level(layer)
    surface = single_dielectric_contact(z_min, thickness,
        [level(row) for row in document["stackup"] if row["role"] == "dielectric"],
        tolerance=1e-8, field="stackup." + layer_id)
    for shape in shapes:
        shape["sheet_z_mm"] = surface
    validate_native_contacts(shapes, {**port, "start_mm": start, "stop_mm": stop, "axis": "xy"[axis]},
                             TOLERANCE_MM, polygons)
    identity = port["positive_geometry_id"]
    signal = [_polygon(poly, "geometry") for poly in polygons[identity]]
    neighbors = {key for key, parts in polygons.items() if key != identity
                 and any(_polygons_too_close(a, _polygon(b, "geometry"), CONTACT_EPSILON_MM)
                         for a in signal for b in parts)}
    return next(shape for shape in shapes if shape["id"] == identity), polygons[identity], neighbors


def _move_feed(document, candidate, anchors, old, destination):
    """! @brief 끝점의 접촉을 따라 선의 가까운 끝 또는 패드를 이동한다."""
    port = next(row for row in candidate["ports"] if row["id"] == anchors["ids"][0])
    moving = next(row for row in candidate["geometry"] if row["id"] == port["positive_geometry_id"])
    old_shape, _, prior = _contact_geometry(document, port, moving["layer_id"], old)
    shift = [b - a for a, b in zip(old[1], destination)]
    if moving["kind"] == "pad":
        field = "center"
    else:
        direction = port["direction"]
        radius = old_shape["width_mm"] / 2
        cap = [old[1][i] + radius * direction[i] for i in (0, 1)]
        matches = [key for key in ("start", "end") if math.dist(cap, point(candidate, moving[key])) <= EPSILON_MM]
        if len(matches) != 1:
            fail("신호 단자 길이는 급전과 맞닿는 선의 끝에서만 구동할 수 있습니다.", "anchors", "E_CONFLICT")
        field = matches[0]
    coordinates = point(candidate, moving[field])
    moving[field] = [replace_literal(candidate, original, value + delta, "mm", "geometry." + field)
                     for original, value, delta in zip(moving[field], coordinates, shift)]
    port["excitation_box"]["stop"] = [replace_literal(candidate, original, value, "mm", "port.stop")
                                     for original, value in zip(port["excitation_box"]["stop"], destination)]
    if moving["kind"] == "line_path" and math.dist(point(candidate, moving["start"]), point(candidate, moving["end"])) <= EPSILON_MM:
        fail("선의 구동 끝과 고정 끝이 겹칩니다.", "target_mm", "E_CONFLICT")
    updated = positions(candidate, anchors)
    shape, polygons, later = _contact_geometry(candidate, port, moving["layer_id"], updated)
    if not _inside_board(project_board(candidate), shape, TOLERANCE_MM):
        fail("이동한 신호 단자가 기판을 벗어납니다.", "target_mm", "E_CONFLICT")
    if prior != later:
        fail("새 급전 길이가 신호 단자의 기존 도체 접촉을 바꿉니다.", "target_mm", "E_CONFLICT")
    for void in _voids(candidate):
        if _overlap(polygons, [void]) or _segment_hits_polygon(updated[0][:2], updated[1][:2], _polygon(void, "geometry")):
            fail("이동한 급전 또는 신호 단자가 홀이나 절삭과 겹칩니다.", "target_mm", "E_CONFLICT")


def drive(document, anchors, target):
    """! @brief 기존 방향에서 거리만 바꾼 검토 후보를 계산한다."""
    reason = drive_reason(document, anchors)
    if reason:
        fail(reason, "anchors", "E_CONFLICT")
    old = positions(document, anchors)
    distance = math.dist(*old)
    if distance <= EPSILON_MM:
        fail("같은 위치에 있는 기준점에서 구동 방향을 정할 수 없습니다.", "anchors", "E_CONFLICT")
    destination = [b if math.isclose(distance, target, abs_tol=EPSILON_MM, rel_tol=0)
                   else a + (b - a) * target / distance for a, b in zip(*old)]
    candidate = deepcopy(document)
    if anchors["kind"] == "holes":
        _move_hole(candidate, anchors, destination)
    else:
        _move_feed(document, candidate, anchors, old, destination)
    return candidate
