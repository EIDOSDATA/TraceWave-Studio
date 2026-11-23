"""! @brief 지정 넷의 구리면을 원래 외곽, 실 도체 간격과 금지 영역에서 다시 계산한다."""

from copy import deepcopy
import math

from rfad.adapters.exchange.pcb_geometry import CHORD_MM, polygonize
from rfad.adapters.planar_backend import _canonical_loop, runtime
from rfad.application.interactive_route import forbidden_areas, on_layer
from rfad.application.pcb_exchange_projection import geometry_projection
from rfad.application.canonical import canonical_hash
from rfad.domain import copper_islands as islands
from rfad.domain.object_names import allocate_name
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
        return "" if islands.owner_of(document, rows[0]["id"]) in active(document) else "활성 구리면 채움이 없습니다."
    return runtime()[1]["reason"]


def _fill(document, old, outline, values, zones):
    """! @brief 저장할 다각형이 지정 간격과 원래 경계를 만족하는지 실제 도체와 재대조한다."""
    source = old[0]
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
        owner = islands.owner_of(document, row["id"])
        if owner != row["id"] and owner in zones:
            continue
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
        _guard_members(document, old, [original])
        return [original]
    try:
        blocked = shapely.union_all(obstacles)
        offset = (gap + CHORD_MM + 2 * tolerance) / math.cos(math.pi / 32)
        removed = blocked.simplify(tolerance, preserve_topology=True).buffer(offset, quad_segs=8)
        cut = body.difference(removed)
        if cut.is_empty or cut.geom_type not in ("Polygon", "MultiPolygon"):
            fail("채울 동박 면적이 남지 않았습니다.", "selection_ids", "E_GEOMETRY")
        filled = cut.simplify(tolerance, preserve_topology=True)
        if not body.covers(filled) or filled.distance(blocked) < gap + CHORD_MM:
            filled = cut
        if not body.covers(filled) or filled.distance(blocked) < gap + CHORD_MM:
            fail("실제 도체와의 요구 간격을 확인할 수 없습니다.", "clearance_mm", "E_GEOMETRY")
    except shapely.errors.GEOSException:
        fail("구리면 차집합 형상을 계산할 수 없습니다.", "selection_ids", "E_GEOMETRY")
    parts = [filled] if filled.geom_type == "Polygon" else sorted(filled.geoms, key=lambda shape: shape.bounds)
    if not 1 <= len(parts) <= len(islands.slots(source["id"])):
        fail("한 구리면은 서로 떨어진 섬을 16개까지 지원합니다.", "selection_ids", "E_RESOURCE")
    raw = {tuple(point(document, xy, "geometry")): xy for loop in [original["outer"], *original["holes"]] for xy in loop}
    sources = list(dict.fromkeys(ref for xy in raw.values() for value in xy for ref in value.get("source_refs", [])))

    def quantity(xy):
        """! @brief 원래 꼭짓점의 단위와 출처를 재사용한다."""
        return deepcopy(raw.get(tuple(xy))) or [Quantity.from_value(v, "mm", source_refs=sources).to_dict() for v in xy]

    mapping = _assign(document, old, parts, shapely)
    outputs = []
    previous = {row["id"]: row for row in old}
    for index, part in enumerate(parts):
        outer = _canonical_loop(part.exterior.coords, clockwise=False)
        holes = sorted((_canonical_loop(ring.coords, clockwise=True) for ring in part.interiors), key=lambda row: row[0])
        validate_region(outer, holes)
        key = mapping[index]
        output = {**source, "id": key, "outer": [quantity(xy) for xy in outer],
                  "holes": [[quantity(xy) for xy in loop] for loop in holes]}
        if key in previous and "name" in previous[key]:
            output["name"] = previous[key]["name"]
        elif key != source["id"]:
            output["name"] = allocate_name(document, output, reserved=[row["name"] for row in outputs if "name" in row])
        outputs.append(output)
    order = islands.slots(source["id"])
    outputs.sort(key=lambda row: order.index(row["id"]))
    _guard_members(document, old, outputs)
    return outputs


def _port_points(document, key):
    """! @brief 기존 남은 급전 단자의 기판 좌표만 해당 도체에 연결한다."""
    points = []
    for port in document["ports"]:
        for field, side in (("reference_geometry_id", "start"), ("positive_geometry_id", "stop")):
            if port[field] == key:
                if "excitation_box" not in port:
                    fail("구리면을 참조하는 급전 위치를 먼저 지정하세요.", "ports", "E_CONFLICT")
                points.append(tuple(point(document, port["excitation_box"][side][:2], "ports")))
    return points


def _assign(document, old, parts, shapely):
    """! @brief 급전 위치, 이전 면적과의 겹침, 예약 슬롯 순서로 섬의 영속 ID를 대응한다."""
    owner = old[0]["id"]
    mapping, used = {}, set()
    overlap = []
    for row in old:
        key = row["id"]
        xy = _port_points(document, key)
        if xy:
            matches = [i for i, part in enumerate(parts) if all(part.distance(shapely.Point(p)) < 1e-10 for p in xy)]
            if len(matches) != 1 or matches[0] in mapping:
                fail("구리면 분할 또는 병합으로 기존 급전 단자의 소유 도체를 유지할 수 없습니다.", "ports", "E_CONFLICT")
            mapping[matches[0]], used = key, used | {key}
        original = polygonize(shape_loops(geometry_projection(document, row)))
        for i, part in enumerate(parts):
            area = original.intersection(part).area
            if area > 0:
                overlap.append((-area, key, i))
    for _, key, index in sorted(overlap, key=lambda entry: (entry[1] != owner, *entry)):
        if key not in used and index not in mapping:
            mapping[index] = key
            used.add(key)
    if owner not in used:
        unused = [i for i in range(len(parts)) if i not in mapping]
        if not unused:
            freeable = [i for i, key in mapping.items() if not _port_points(document, key)]
            if not freeable:
                fail("급전이 연결된 섬의 원본 ID를 유지할 수 없습니다.", "ports", "E_CONFLICT")
            index = max(freeable, key=lambda i: parts[i].area)
            used.remove(mapping[index])
        else:
            index = max(unused, key=lambda i: parts[i].area)
        mapping[index] = owner
        used.add(owner)
    available = iter(key for key in islands.slots(owner) if key not in used)
    occupied = {row["id"] for row in document["geometry"]} - {row["id"] for row in old}
    for index in range(len(parts)):
        if index not in mapping:
            key = next(available)
            if key in occupied:
                fail("구리 섬에 필요한 ID를 다른 도체가 사용합니다.", "selection_ids", "E_CONFLICT")
            mapping[index] = key
    return mapping


def _guard_members(document, old, outputs):
    """! @brief 사라지는 섬을 외부 단자나 기대 연결의 다른 도체로 대체하지 않는다."""
    keep = {row["id"] for row in outputs}
    removed = {row["id"] for row in old} - keep
    if any(removed & set(row["object_ids"]) for row in document["connections"]) or any(_port_points(document, key) for key in removed):
        fail("급전 또는 기대 연결이 참조한 동박 섬이 사라집니다.", "selection_ids", "E_CONFLICT")
    for row in outputs:
        points = _port_points(document, row["id"])
        if points:
            copper = footprint(document, row)
            for xy in points:
                if not copper.contains(xy) and min(point_distance(xy, edge)[0] for edge in copper.edges) > copper.guard:
                    fail("구리면 채움이 기존 급전 단자의 동박을 제거합니다.", "ports", "E_CONFLICT")


def edited(document, rows, operation, values):
    """! @brief 원래 다각형과 규칙을 봉인한 기록에 이어서 실제 채움 형상을 제시한다."""
    message = reason(document, rows, operation)
    if message:
        fail(message, "selection_ids", "E_CONFLICT")
    key = islands.owner_of(document, rows[0]["id"])
    geometry = {row["id"]: row for row in document["geometry"]}
    current = [geometry[m] for m in islands.members(document, key)]
    source = current[0]
    zones = active(document)
    previous = zones.get(key)
    outline = previous["engine"]["outline"] if previous else {k: deepcopy(source[k]) for k in ("outer", "holes")}
    engine = {"name": "rfad.copper-pour", "version": "0.2", "outline": outline, "island_scheme": 1,
              "pour_parent": previous["id"] if previous else None}
    if operation == RESTORE:
        output = [{**source, **outline}]
        _guard_members(document, current, output)
        return current, output, engine
    if previous and previous["values"] == values:
        fail("현재 구리면의 간격과 근사 허용값이 같습니다.", "values", "E_CONFLICT")
    return current, _fill(document, current, outline, values, zones), {**engine, "backend": runtime()[1]}


def propagate(before, after, capture=None, restoring=()):
    """! @brief 명시 채움의 자식 목록과 다른 편집으로 재생성한 섬을 같은 개정에 기록한다."""
    if not any(EXTENSION_KEY in doc["extensions"] for doc in (before, after)):
        return []
    previous, zones = active(before), active(after)
    if not previous and not zones:
        return []
    old_geo = {row["id"]: row for row in before["geometry"]}
    geometry = {row["id"]: row for row in after["geometry"]}
    changed = []
    old_records, new_records = ({row["id"]: row for row in doc["extensions"].get(EXTENSION_KEY, {}).get("records", [])}
                                for doc in (before, after))
    for key in previous.keys() | zones.keys():
        left, right = previous.get(key), zones.get(key)
        if left == right:
            continue
        edited_records = [(new_records[r], "after") for r in new_records.keys() - old_records.keys()]
        edited_records += [(old_records[r], "before") for r in old_records.keys() - new_records.keys()]
        if right is None:
            islands.store(after, key, None)
            continue
        selected = next(((row, end) for row, end in edited_records
                         if row["operation"] in (FILL, RESTORE) and row["selection_ids"][0] == key), None)
        if selected is None:
            fail("구리면 정의의 전후 편집 이력이 연결되지 않았습니다.", "selection_ids", "E_CONFLICT")
        record, end = selected
        ids = [row["id"] for row in record[end]]
        if len(ids) == 1 and right["engine"].get("island_scheme") != 1:
            islands.store(after, key, None)
        else:
            islands.store(after, key, ids)
    if all(before.get(key) == after.get(key) for key in ("geometry", "parameters", "board", "stackup", "pcb")):
        return []
    for key, feature in zones.items():
        if key in restoring or key not in previous or previous[key]["id"] != feature["id"]:
            continue
        members = islands.members(before, key)
        if any(identity not in geometry for identity in members):
            fail("원래 경계를 복원한 뒤 자동 채움 영역을 삭제하세요.", "selection_ids", "E_CONFLICT")
        for identity in members:
            if identity != key and {k: v for k, v in old_geo[identity].items() if k != "name"} != {
                    k: v for k, v in geometry[identity].items() if k != "name"}:
                fail("파생 구리 섬의 속성은 원래 채움 정의에서 변경하세요.", "selection_ids", "E_CONFLICT")
            if any(geometry[identity][name] != old_geo[identity][name] for name in ("outer", "holes", "net_id", "layer_id")):
                fail("원래 경계를 복원한 뒤 구리면 외곽, 넷과 층을 편집하세요.", "selection_ids", "E_CONFLICT")
        old = [geometry[identity] for identity in members]
        result = _fill(after, old, feature["engine"]["outline"], feature["values"], zones)
        if result == old:
            continue
        ids = [row["id"] for row in result]
        for identity in members:
            del geometry[identity]
        geometry.update({row["id"]: row for row in result})
        after["geometry"] = sorted(geometry.values(), key=lambda row: row["id"])
        if len(ids) > 1 or feature["engine"].get("island_scheme") == 1 or len(members) > 1:
            islands.store(after, key, ids)
        changed.extend(sorted(set(members) | set(ids)))
        if capture is not None and max(len(members), len(ids)) > 1:
            current = islands.snapshot(after, key)
            capture.append({"owner": key, "expected": canonical_hash(current), "desired": islands.snapshot(before, key)})
    return list(dict.fromkeys(changed))
