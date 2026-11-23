"""! @brief 선택 도체에서 시작하는 다구간 PCB 배선을 층, 넷, 간격 규칙과 함께 적용한다."""

from copy import deepcopy
from uuid import UUID, uuid5

from rfad.application.pcb_exchange_projection import _footprint_from_loops, mechanical_projection, shape_projection
from rfad.domain.boundary_distance import point_distance
from rfad.domain.check_geometry import board_clearance, footprint, separation
from rfad.domain.drawing_layout import mechanical_loops
from rfad.domain.object_names import allocate_name
from rfad.domain.pcb_features import COMMAND, make_patch
from rfad.domain.precision_transform import fail, number


def forbidden_areas(document, layer, flag):
    """! @brief 해당 도체층의 금지 영역과 기계 가공 외곽을 배선 또는 구리 채움에서 제외한다."""
    result = []
    for item in document.get("pcb", {}).get("keepouts", []):
        if item["prohibit"][flag] and (item.get("all_conductor_layers") or layer in item["layer_ids"]):
            if item["frame_id"] != document["board"]["frame_id"]:
                fail("기판과 다른 좌표계의 금지 영역 위치를 먼저 확인하세요.", "frame_id", "E_CONFLICT")
            loops = mechanical_loops(shape_projection(document, item["shape"]))
            result.append((item, loops))
    mechanical_rows = [*document["board"].get("cutouts", []), *document.get("pcb", {}).get("holes", [])]
    if any(row["frame_id"] != document["board"]["frame_id"] for row in mechanical_rows):
        fail("기판과 다른 좌표계의 기계 가공 위치를 먼저 확인하세요.", "frame_id", "E_CONFLICT")
    mechanical = mechanical_projection(document)
    for records in mechanical.values():
        for item in records:
            result.append((item, mechanical_loops(item["shape"])))
    return result


def on_layer(row, layer, orders):
    """! @brief 도금 비아는 시작층과 끝층 사이에서 지나가는 도체층까지 대상으로 삼는다."""
    if row["kind"] != "via":
        return row["layer_id"] == layer
    lo, hi = sorted((orders[row["layer_id"]], orders[row["end_layer_id"]]))
    return lo <= orders[layer] <= hi


def command(document, values):
    """! @brief 경유점을 이은 원본 선들을 함께 검사하고 한 번의 실행 취소로 복원한다."""
    from rfad.application.canvas import _point, _quantity, _uuid
    geometry = {row["id"]: row for row in document["geometry"]}
    seed = geometry.get(_uuid(values["source_id"], "source_id"))
    layer = values["layer_id"]
    if seed is None or seed["net_id"] is None or seed["layer_id"] != layer:
        fail("배선 시작점으로 현재 층에 넷이 지정된 도체를 선택하세요.", "source_id", "E_CONFLICT")
    points = values["points"]
    if type(points) is not list or not 2 <= len(points) <= 33:
        fail("배선에는 시작점을 포함한 경유점 2~33개가 필요합니다.", "points", "E_RESOURCE")
    path = [_point(value, "points") for value in points]
    width = _quantity(values["width_mm"], "mm", "width_mm")
    clearance = number(values["clearance_mm"], "clearance_mm")
    if clearance < 0 or clearance > 1e6 or width["value_si"] <= 0:
        fail("선폭은 양수이고 간격은 0~1000000 mm여야 합니다.", "clearance_mm", "E_SCHEMA")
    if seed["frame_id"] != document["board"]["frame_id"]:
        fail("기판 좌표계의 시작 도체를 선택하세요.", "source_id", "E_CONFLICT")
    source = footprint(document, seed)
    start = tuple(points[0])
    if not source.contains(start) and min(point_distance(start, edge)[0] for edge in source.edges) > source.guard:
        fail("첫 배선점을 선택 도체 위에 지정하세요.", "points", "E_CONFLICT")
    orders = {row["id"]: row["order"] for row in document["stackup"]}
    from rfad.application import copper_pour
    live_pours = copper_pour.active(document)
    obstacles = [(row, footprint(document, row)) for row in document["geometry"]
                 if row["id"] not in live_pours and row["net_id"] != seed["net_id"] and on_layer(row, layer, orders)]
    if any(row["frame_id"] != seed["frame_id"] for row, _ in obstacles):
        fail("다른 넷의 도체를 기판 좌표계에 배치한 뒤 간격을 검사하세요.", "frame_id", "E_CONFLICT")
    forbidden = [(row, _footprint_from_loops(row, loops)) for row, loops in forbidden_areas(document, layer, "tracks")]
    candidate = deepcopy(document)
    budget = [200000]
    for index, (a, b) in enumerate(zip(path, path[1:])):
        line = {key: deepcopy(seed[key]) for key in
                ("frame_id", "layer_id", "net_id", "material_ref", "include_in_em", "include_in_export")}
        identity = values["id"] if index == 0 else str(uuid5(UUID(values["id"]), "route:" + str(index)))
        if identity in geometry:
            fail("배선 구간 ID가 기존 도체와 겹칩니다.", "id", "E_CONFLICT")
        line.update(id=identity, kind="line_path", role="conductor", source_ref=None, start=a, end=b, width=width)
        line["name"] = allocate_name(candidate, line)
        shape = footprint(document, line)
        margin, _ = board_clearance(document, shape)
        if margin < -shape.guard:
            fail(f"배선 {index + 1}구간이 기판 외곽을 벗어납니다.", "points", "E_GEOMETRY")
        for row, obstacle in obstacles + forbidden:
            distance, _, _ = separation(shape, obstacle, budget)
            guard = max(shape.guard, obstacle.guard)
            if distance <= guard or distance + guard < clearance:
                name = row.get("name", row["id"])
                fail(f"배선 {index + 1}구간과 {name}의 실제 간격 {distance:.6g} mm를 확인하세요.",
                     "points", "E_CONFLICT")
        candidate["geometry"].append(line)
    stricter = [key for key, state in live_pours.items() if state["values"]["clearance_mm"] < clearance
                and geometry[key]["net_id"] != seed["net_id"] and geometry[key]["layer_id"] == layer]
    if stricter:
        projected = deepcopy(candidate)
        copper_pour.propagate(document, projected)
        fills = [footprint(projected, row) for row in projected["geometry"] if row["id"] in stricter]
        for row in candidate["geometry"][len(document["geometry"]):]:
            segment = footprint(candidate, row)
            if any(separation(segment, fill, budget)[0] + segment.guard < clearance for fill in fills):
                fail("구리면 채움 간격을 현재 배선의 요구 간격까지 늘리세요.", "clearance_mm", "E_CONFLICT")
    return {"type": COMMAND, "payload": make_patch(document, candidate, "trace.route", "선택한 넷의 대화식 다구간 배선")}
