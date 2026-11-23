"""! @brief 지정 넷의 구리면을 원래 외곽, 실 도체 간격과 금지 영역에서 다시 계산한다."""

from copy import deepcopy
import math

from rfad.adapters.exchange.pcb_geometry import CHORD_MM, polygonize
from rfad.adapters.planar_backend import _canonical_loop, runtime
from rfad.application.interactive_route import forbidden_areas, on_layer
from rfad.application.pcb_exchange_projection import geometry_projection
from rfad.domain.boundary_distance import point_distance
from rfad.domain.check_geometry import board_clearance, footprint
from rfad.domain.drawing_layout import shape_loops
from rfad.domain.planar import validate_region
from rfad.domain.precision_command import EXTENSION_KEY
from rfad.domain.precision_transform import fail, number, point
from rfad.domain.units import Quantity


FILL = "copper_pour"
RESTORE = "restore_copper_outline"


def active(document):
    """! @brief 최초 경계와 이후 변경 기록에서 현재 자동 채움 설정을 복원한다."""
    records = document["extensions"].get(EXTENSION_KEY, {}).get("records", [])
    fills = [row for row in records if row["operation"] in (FILL, RESTORE)]
    replaced = {row["engine"]["pour_parent"] for row in fills if type(row["engine"].get("pour_parent")) is str}
    return {row["selection_ids"][0]: row for row in fills if row["id"] not in replaced and row["operation"] == FILL}


def reason(document, rows, operation):
    """! @brief 활성 채움의 원래 경계 복원과 새 규칙을 선택할 수 있는지 확인한다."""
    if len(rows) != 1 or rows[0]["kind"] != "planar_region" or rows[0]["net_id"] is None:
        return "넷이 지정된 다각형 구리 영역을 하나 선택하세요."
    if operation == RESTORE:
        return "" if rows[0]["id"] in active(document) else "활성 구리면 채움이 없습니다."
    return runtime()[1]["reason"]


def _fill(document, source, outline, values, zones):
    """! @brief 저장할 다각형이 지정 간격과 원래 경계를 만족하는지 실제 도체와 재대조한다."""
    shapely, engine = runtime()
    if shapely is None:
        fail(engine["reason"], "operation", "E_UNSUPPORTED")
    gap = number(values["clearance_mm"], "clearance_mm")
    tolerance = number(values["tolerance_mm"], "tolerance_mm")
    if not 0 < tolerance <= gap / 4 or gap > 1e6:
        fail("양수인 간격과 간격의 1/4 이하인 곡선 근사 허용값을 입력하세요.", "tolerance_mm", "E_GEOMETRY")
    if source["frame_id"] != document["board"]["frame_id"]:
        fail("기판 좌표계의 구리 영역을 선택하세요.", "frame_id", "E_CONFLICT")
    original = {**source, **outline}
    shape = footprint(document, original)
    if board_clearance(document, shape)[0] < -shape.guard:
        fail("구리면 원래 외곽을 기판 안에 지정하세요.", "selection_ids", "E_GEOMETRY")
    if any("parameter_id" in value for loop in [original["outer"], *original["holes"]] for xy in loop for value in xy):
        fail("원래 외곽 좌표에 연결된 매개변수를 먼저 확인하세요.", "selection_ids", "E_CONFLICT")
    body = polygonize(shape_loops(geometry_projection(document, original)))
    layer = source["layer_id"]
    order = {row["id"]: row["order"] for row in document["stackup"]}
    obstacles = []
    for row in document["geometry"]:
        if row["net_id"] == source["net_id"] or not on_layer(row, layer, order):
            continue
        if row["frame_id"] != source["frame_id"]:
            fail("다른 넷의 도체를 기판 좌표계에 배치한 뒤 다시 채우세요.", "frame_id", "E_CONFLICT")
        if row["id"] in zones:
            row = {**row, **zones[row["id"]]["engine"]["outline"]}
        obstacle = polygonize(shape_loops(geometry_projection(document, row)))
        if row["kind"] == "via":
            obstacle = shapely.Polygon(obstacle.exterior)
        if body.distance(obstacle) <= gap + tolerance * 4:
            obstacles.append(obstacle)
    for _, loops in forbidden_areas(document, layer, "copper_pours"):
        obstacle = polygonize(loops)
        if body.distance(obstacle) <= gap + tolerance * 4:
            obstacles.append(obstacle)
    if not obstacles:
        return original
    try:
        blocked = shapely.union_all(obstacles)
        offset = (gap + CHORD_MM + 2 * tolerance) / math.cos(math.pi / 32)
        removed = blocked.simplify(tolerance, preserve_topology=True).buffer(offset, quad_segs=8)
        cut = body.difference(removed)
        if cut.is_empty or cut.geom_type != "Polygon":
            fail("채움이 사라지거나 여러 섬으로 나뉩니다. 영역을 나누어 지정하세요.", "selection_ids", "E_GEOMETRY")
        filled = cut.simplify(tolerance, preserve_topology=True)
        if not body.covers(filled) or filled.distance(blocked) < gap + CHORD_MM:
            filled = cut
        if not body.covers(filled) or filled.distance(blocked) < gap + CHORD_MM:
            fail("실제 도체와의 요구 간격을 확인할 수 없습니다.", "clearance_mm", "E_GEOMETRY")
    except shapely.errors.GEOSException:
        fail("구리면 차집합 형상을 계산할 수 없습니다.", "selection_ids", "E_GEOMETRY")
    outer = _canonical_loop(filled.exterior.coords, clockwise=False)
    holes = sorted((_canonical_loop(ring.coords, clockwise=True) for ring in filled.interiors), key=lambda row: row[0])
    validate_region(outer, holes)
    raw = {tuple(point(document, xy, "geometry")): xy for loop in [original["outer"], *original["holes"]] for xy in loop}
    sources = list(dict.fromkeys(ref for xy in raw.values() for value in xy for ref in value.get("source_refs", [])))

    def quantity(xy):
        """! @brief 원래 꼭짓점의 단위와 출처를 재사용한다."""
        return deepcopy(raw.get(tuple(xy))) or [Quantity.from_value(v, "mm", source_refs=sources).to_dict() for v in xy]

    output = {**source, "outer": [quantity(xy) for xy in outer],
              "holes": [[quantity(xy) for xy in loop] for loop in holes]}
    copper = footprint(document, output)
    for port in document["ports"]:
        for field, side in (("reference_geometry_id", "start"), ("positive_geometry_id", "stop")):
            if port[field] != source["id"]:
                continue
            if "excitation_box" not in port:
                fail("구리면을 참조하는 급전 위치를 먼저 지정하세요.", "ports", "E_CONFLICT")
            xy = tuple(point(document, port["excitation_box"][side][:2], "ports"))
            if not copper.contains(xy) and min(point_distance(xy, edge)[0] for edge in copper.edges) > copper.guard:
                fail("구리면 채움이 기존 급전 단자의 동박을 제거합니다.", "ports", "E_CONFLICT")
    return output


def edited(document, rows, operation, values):
    """! @brief 원래 다각형과 규칙을 봉인한 기록에 이어서 실제 채움 형상을 제시한다."""
    message = reason(document, rows, operation)
    if message:
        fail(message, "selection_ids", "E_CONFLICT")
    source, = rows
    zones = active(document)
    previous = zones.get(source["id"])
    outline = previous["engine"]["outline"] if previous else {key: deepcopy(source[key]) for key in ("outer", "holes")}
    engine = {"name": "rfad.copper-pour", "version": "0.1", "outline": outline,
              "pour_parent": previous["id"] if previous else None}
    if operation == RESTORE:
        return [{**source, **outline}], engine
    if previous and previous["values"] == values:
        fail("현재 구리면의 간격과 근사 허용값이 같습니다.", "values", "E_CONFLICT")
    return [_fill(document, source, outline, values, zones)], {**engine, "backend": runtime()[1]}


def propagate(before, after):
    """! @brief 배선, 도체층, 기계 형상 또는 금지 영역 변경 뒤 같은 개정에서 구리면을 재생성한다."""
    if EXTENSION_KEY not in before["extensions"]:
        return []
    blobs = ("geometry", "parameters", "board", "stackup", "pcb")
    if all(before.get(key) == after.get(key) for key in blobs):
        return []
    previous, zones = active(before), active(after)
    if not previous or not zones:
        return []
    old = {row["id"]: row for row in before["geometry"]}
    indices = {row["id"]: i for i, row in enumerate(after["geometry"])}
    changed = []
    for key, feature in zones.items():
        if key not in previous or previous[key]["id"] != feature["id"]:
            continue
        if key not in indices:
            fail("원래 경계를 복원한 뒤 자동 채움 영역을 삭제하세요.", "selection_ids", "E_CONFLICT")
        source = after["geometry"][indices[key]]
        if any(source[name] != old[key][name] for name in ("outer", "holes", "net_id", "layer_id")):
            fail("원래 경계를 복원한 뒤 구리면 외곽, 넷과 층을 편집하세요.", "selection_ids", "E_CONFLICT")
        output = _fill(after, source, feature["engine"]["outline"], feature["values"], zones)
        if output != source:
            after["geometry"][indices[key]] = output
            changed.append(key)
    return changed
