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


def _layer_changes(values, length, metals):
    """! @brief 경유점별 도체층, 완성 홀, 공구, 도금과 랜드 지름을 검증한다."""
    changes = values.get("transitions", [])
    if type(changes) is not list or len(changes) > 8:
        fail("한 배선에는 층 전환을 최대 8개 지정할 수 있습니다.", "transitions", "E_RESOURCE")
    result = {}
    layer = values["layer_id"]
    for row in changes:
        fields = {"index", "layer_id", "pad_diameter_mm", "finished_hole_diameter_mm", "plating_thickness_mm", "tool_hole_diameter_mm"}
        if type(row) is not dict or set(row) != fields or type(row["index"]) is not int or type(row["layer_id"]) is not str:
            fail("비아의 경유점, 층과 네 치수를 입력하세요.", "transitions", "E_SCHEMA")
        index = row["index"]
        if not max(result, default=0) < index < length or row["layer_id"] not in metals or row["layer_id"] == layer:
            fail("오름차순 경유점에서 다른 도체층을 선택하세요.", "transitions", "E_CONFLICT")
        pad, hole, plating, tool = (number(row[key], key) for key in
            ("pad_diameter_mm", "finished_hole_diameter_mm", "plating_thickness_mm", "tool_hole_diameter_mm"))
        if not 0 < hole <= tool < pad or not 0 < plating or hole + 2 * plating >= pad:
            fail("랜드가 공구 및 도금 외경보다 커야 하며 완성 홀과 도금은 양수여야 합니다.", "transitions", "E_GEOMETRY")
        result[index] = row
        layer = row["layer_id"]
    return result


def _via_parts(identity, base, current, step, center, order):
    """! @brief 경유점의 같은 넷에 두 랜드와 상하 정렬된 도금홀을 만든다."""
    from rfad.application.canvas import _quantity
    child = UUID(identity)
    start, end = sorted((current, step["layer_id"]), key=order.get)
    diameter = _quantity(step["pad_diameter_mm"], "mm", "pad_diameter_mm")
    prefix = "transition:" + str(step["index"])
    pads = [{**base, "kind": "pad", "pad_shape": "circle", "center": center, "size": [diameter, diameter],
             "rotation": _quantity(0, "deg", "rotation"), "layer_id": layer,
             "id": str(uuid5(child, prefix + ":pad:" + layer))} for layer in (start, end)]
    via = {**base, "id": str(uuid5(child, prefix + ":via")), "kind": "via", "fill": "none", "center": center,
           "layer_id": start, "end_layer_id": end, "pad_ids": [row["id"] for row in pads]}
    for key in ("finished_hole_diameter", "plating_thickness", "tool_hole_diameter"):
        via[key] = _quantity(step[key + "_mm"], "mm", key)
    return [*pads, via]


def command(document, values):
    """! @brief 모든 배선, 패드와 비아를 실제 통과층마다 검사한 뒤 한 번에 적용한다."""
    from rfad.application import copper_pour
    from rfad.application.canvas import _point, _quantity, _uuid
    geometry = {row["id"]: row for row in document["geometry"]}
    seed = geometry.get(_uuid(values["source_id"], "source_id"))
    layer = _uuid(values["layer_id"], "layer_id")
    metals = {row["id"]: row["order"] for row in document["stackup"] if row["role"] == "conductor"}
    if seed is None or seed["net_id"] is None or layer not in metals or not on_layer(seed, layer, metals):
        fail("배선 시작점으로 현재 층에 넷이 지정된 도체를 선택하세요.", "source_id", "E_CONFLICT")
    points = values["points"]
    if type(points) is not list or not 2 <= len(points) <= 33:
        fail("배선에는 시작점을 포함한 경유점 2~33개가 필요합니다.", "points", "E_RESOURCE")
    path = [_point(value, "points") for value in points]
    transitions = _layer_changes(values, len(path), metals)
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
    live_pours = copper_pour.active(document)
    obstacles, prohibited = {}, {}
    candidate = deepcopy(document)
    budget = [200000]
    base = {key: deepcopy(seed[key]) for key in ("frame_id", "net_id", "material_ref", "include_in_em", "include_in_export")}
    base.update(role="conductor", source_ref=None)
    generated = []
    for index, (a, b) in enumerate(zip(path, path[1:]), 1):
        identity = values["id"] if index == 1 else str(uuid5(UUID(values["id"]), "route:" + str(index - 1)))
        pieces = [{**base, "id": identity, "layer_id": layer, "kind": "line_path", "start": a, "end": b, "width": width}]
        if index in transitions:
            step = transitions[index]
            pieces.extend(_via_parts(values["id"], base, layer, step, b, metals))
            layer = step["layer_id"]
        for item in pieces:
            if item["id"] in geometry:
                fail("배선 구간 또는 층 전환 ID가 기존 도체와 겹칩니다.", "id", "E_CONFLICT")
            item["name"] = allocate_name(candidate, item)
            shape = footprint(document, item)
            margin, _ = board_clearance(document, shape)
            if margin < -shape.guard:
                fail(f"배선 {index}구간이 기판 외곽을 벗어납니다.", "points", "E_GEOMETRY")
            flag = {"line_path": "tracks", "pad": "pads", "via": "vias"}[item["kind"]]
            for metal in metals:
                if not on_layer(item, metal, metals):
                    continue
                if metal not in obstacles:
                    others = [row for row in document["geometry"] if row["net_id"] != seed["net_id"]
                              and copper_pour.islands.owner_of(document, row["id"]) not in live_pours and on_layer(row, metal, metals)]
                    if any(row["frame_id"] != seed["frame_id"] for row in others):
                        fail("다른 넷의 도체를 기판 좌표계에 배치한 뒤 간격을 검사하세요.", "frame_id", "E_CONFLICT")
                    obstacles[metal] = [(row, footprint(document, row)) for row in others]
                if (metal, flag) not in prohibited:
                    prohibited[metal, flag] = [(row, _footprint_from_loops(row, loops)) for row, loops in forbidden_areas(document, metal, flag)]
                for row, obstacle in obstacles[metal] + prohibited[metal, flag]:
                    distance, _, _ = separation(shape, obstacle, budget)
                    guard = max(shape.guard, obstacle.guard)
                    if distance <= guard or distance + guard < clearance:
                        name = row.get("name", row["id"])
                        fail(f"배선 {index}구간과 {name}의 실제 간격 {distance:.6g} mm를 확인하세요.", "points", "E_CONFLICT")
            candidate["geometry"].append(item)
            generated.append(item)
    stricter = [key for key, state in live_pours.items() if state["values"]["clearance_mm"] < clearance
                and geometry[key]["net_id"] != seed["net_id"] and geometry[key]["layer_id"] in obstacles]
    if stricter:
        projected = deepcopy(candidate)
        copper_pour.propagate(document, projected)
        fills = [row for row in projected["geometry"] if copper_pour.islands.owner_of(projected, row["id"]) in stricter]
        for row in generated:
            segment = footprint(candidate, row)
            for fill in fills:
                if on_layer(row, fill["layer_id"], metals) and separation(segment, footprint(projected, fill), budget)[0] + segment.guard < clearance:
                    fail("구리면 채움 간격을 현재 배선의 요구 간격까지 늘리세요.", "clearance_mm", "E_CONFLICT")
    return {"type": COMMAND, "payload": make_patch(document, candidate, "trace.route", "선택한 넷의 대화식 다구간 배선")}


def review(service, params):
    """! @brief 커서가 가리키는 경로를 적용과 같은 기하 및 소유권 검증으로 읽기 전용 검사한다."""
    from rfad.application.canvas import canvas_command
    from rfad.application.project_contract import _fields, _uuid
    from rfad.domain.errors import ProjectError
    from rfad.domain.project import apply_command
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 API 버전입니다.", "contract_version", "E_VERSION")
    data = _fields(params["input"], {"expected_revision", "values"})
    _uuid(data["expected_revision"])
    project = service._project(service.journal.read(), params["context"])
    document = service._load(project)
    service._check_history_head(project, document["revision_id"])
    if document["revision_id"] != data["expected_revision"]:
        fail("배선 검토 중 기준 개정이 변경되었습니다.", "expected_revision", "E_CONFLICT")
    try:
        result = canvas_command(document, "create_route", data["values"])
        apply_command(document, {"command_id": data["values"]["id"], **result}, document["revision_id"])
        return {"valid": True, "revision_id": document["revision_id"], "message": "배선의 도체 간격과 금지 영역을 확인했습니다."}
    except ProjectError as problem:
        return {"valid": False, "revision_id": document["revision_id"], "message": problem.message}
