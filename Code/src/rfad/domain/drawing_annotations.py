"""! @brief 도면의 참조 치수 설정과 고정 개정에서 평가한 주석을 관리한다."""

from copy import deepcopy
import math

from rfad.domain.design import _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import display_names
from rfad.domain.precision_dimensions import dimensions
from rfad.domain import smart_dimensions


KEY = "rfad.drawing-annotations"
PROFILE = "rfad.drawing-annotations/0.1"
COMMAND = "drawing.annotations.set"
CATEGORIES = {"board": "기판 외곽", "holes": "홀 중심", "arcs": "원호 반경", "feeds": "급전 간극"}
STYLES = {"baseline": "기준선식", "chain": "연쇄식", "ordinate": "좌표식"}
FIELD = "drawing.annotations"
LIMIT = 128
EPSILON = 1e-7


def _fail(message, code="E_SCHEMA"):
    """! @brief 잘못된 치수 설정에 해당 필드 진단을 붙인다."""
    raise ProjectError(code, message, details={"field_path": FIELD})


def recipe(document):
    """! @brief 기존 프로젝트에는 명시적으로 저장한 설정만 반환한다."""
    return document["extensions"].get(KEY, {}).get("recipe")


def validate_recipe(value):
    """! @brief 저장 가능한 2D 뷰, 기준점, 스타일과 참조 키를 확인한다."""
    _fields(value, {"view", "datum", "style", "categories", "model_dimensions", "hole_table"}, FIELD)
    view, datum = value["view"], value["datum"]
    if type(view) is dict and view.get("kind") == "layer":
        _fields(view, {"kind", "layer_id"}, FIELD + ".view")
        _uuid(view["layer_id"], FIELD + ".view.layer_id")
    else:
        _fields(view, {"kind"}, FIELD + ".view")
        if view["kind"] != "outline":
            _fail("자동 치수에는 기판 외곽 또는 도체층 뷰를 선택하세요.")
    _fields(datum, {"kind", "id"}, FIELD + ".datum")
    if datum["kind"] == "hole":
        _uuid(datum["id"], FIELD + ".datum.id")
    elif datum["kind"] not in ("board_origin", "board_min") or datum["id"] is not None:
        _fail("기판 원점, 외곽 최소점 또는 홀 중심을 기준으로 선택하세요.")
    if type(value["style"]) is not str or value["style"] not in STYLES or type(value["hole_table"]) is not bool:
        _fail("치수 기입 방식과 홀 표 옵션을 확인하세요.")
    selected = value["categories"]
    if (type(selected) is not list or len(selected) > len(CATEGORIES)
            or any(type(item) is not str or item not in CATEGORIES for item in selected)
            or len(set(selected)) != len(selected)):
        _fail("자동 치수 대상을 확인하세요.")
    model = value["model_dimensions"]
    if type(model) is not list or len(model) > LIMIT:
        _fail("모델 치수는 한 뷰에 최대 128개를 선택할 수 있습니다.", "E_RESOURCE")
    seen = set()
    for item in model:
        _fields(item, {"source_id", "key"}, FIELD + ".model_dimensions")
        _uuid(item["source_id"], FIELD + ".model_dimensions.source_id")
        if type(item["key"]) is not str or not 1 <= len(item["key"]) <= 80 or not all(
                char.isascii() and (char.isalnum() or char in "._-") for char in item["key"]):
            _fail("모델 치수 키가 유효하지 않습니다.")
        key = item["source_id"], item["key"]
        if key in seen:
            _fail("같은 모델 치수를 중복 선택했습니다.", "E_CONFLICT")
        seen.add(key)
    if not (selected or model or value["hole_table"]):
        _fail("자동 치수, 모델 치수 또는 홀 표를 선택하세요.")


def validate(document):
    """! @brief 사라진 도면 참조도 검사할 수 있도록 기존 ID를 그대로 보존한다."""
    if KEY not in document["extensions"]:
        return
    stored = document["extensions"][KEY]
    _fields(stored, {"profile", "recipe"}, FIELD)
    if stored["profile"] != PROFILE:
        _fail("지원하지 않는 도면 치수 설정 버전입니다.", "E_VERSION")
    validate_recipe(stored["recipe"])


def apply(document, payload):
    """! @brief 참조 주석 설정만 바꾸고 같은 명령으로 실행 취소할 수 있게 한다."""
    _fields(payload, {"recipe"}, FIELD)
    previous, selected = recipe(document), payload["recipe"]
    if selected is not None:
        validate_recipe(selected)
    if selected == previous:
        _fail("현재 도면 치수 설정과 같습니다.", "E_CONFLICT")
    if selected is None:
        document["extensions"].pop(KEY)
    else:
        document["extensions"][KEY] = {"profile": PROFILE, "recipe": deepcopy(selected)}
    return [], ["revision", "exports"], {"type": COMMAND, "payload": {"recipe": deepcopy(previous)}}


def _feed_points(document, port):
    """! @brief 평면 급전의 실제 지정 양단만 참조 치수로 사용한다."""
    points = smart_dimensions.positions(document, {"kind": "feed", "ids": [port["id"]]})
    if abs(points[1][2] - points[0][2]) > EPSILON or math.dist(points[0][:2], points[1][:2]) <= EPSILON:
        _fail("같은 높이에서 서로 다른 실제 급전 양단이 필요합니다.", "E_GEOMETRY")
    return [point[:2] for point in points]


def _view_key(view):
    """! @brief 선택 목록과 도면 뷰의 안정 층 식별자를 대응한다."""
    return view.get("layer_id", view["kind"])


def _smart_row(document, item):
    """! @brief 스마트 치수의 방식과 물리 참조를 유지하며 현재값을 읽는다."""
    locations, value = [], None
    try:
        points = smart_dimensions.positions(document, item["anchors"])
        value = smart_dimensions.measurement(points)["distance_mm"]
        if abs(points[0][2] - points[1][2]) <= EPSILON:
            locations = [point[:2] for point in points]
    except ProjectError:
        pass
    return {"key": "smart.distance", "label": item["name"], "value": value, "unit": "mm",
            "anchors_mm": locations, "mode": item["mode"], "anchors": item["anchors"]}


def catalog(document):
    """! @brief 현재 선택한 스냅샷에서 조회할 기준점과 모델 치수 원본을 나열한다."""
    names = display_names(document)
    board = document["board"]
    if board is None:
        return {"datums": [], "model_dimensions": []}
    holes = smart_dimensions.hole_sources(document)
    hole_rows = []
    for identity, row in holes.items():
        try:
            smart_dimensions.hole_center(document, row)
        except ProjectError:
            continue
        if row.get("include_in_export", True):
            hole_rows.append({"id": identity, "name": names.get(identity, row.get("name", "홀"))})
    geometry = {row["id"]: row for row in document["geometry"] if row["include_in_export"]}
    layers = [row["id"] for row in document["stackup"]]
    layer_indexes = {identity: index for index, identity in enumerate(layers)}
    ports = {row["id"]: row for row in document["ports"]}
    records = []
    for row in geometry.values():
        view_ids = [row["layer_id"]]
        if row["kind"] == "via":
            first, last = sorted((layer_indexes[row["layer_id"]], layer_indexes[row["end_layer_id"]]))
            view_ids = layers[first:last + 1]
        for item in dimensions(document, row):
            records.append({"source_id": row["id"], "key": item["key"], "name": names[row["id"]],
                            "label": item["label"], "value": item["value"], "unit": item["unit"], "views": view_ids})
    hole_ids = {row["id"] for row in hole_rows}
    for item in smart_dimensions.dimensions(document):
        anchor = item["anchors"]
        view_ids = []
        if anchor["kind"] == "holes":
            if all(identity in hole_ids for identity in anchor["ids"]):
                view_ids = ["outline", *layers]
        else:
            port = ports.get(anchor["ids"][0], {})
            endpoints = [geometry.get(port.get(key)) for key in ("positive_geometry_id", "reference_geometry_id")]
            if all(endpoints) and endpoints[0]["layer_id"] == endpoints[1]["layer_id"]:
                view_ids = [endpoints[0]["layer_id"]]
        if view_ids:
            row = _smart_row(document, item)
            records.append({"source_id": item["id"], "key": row["key"], "name": "스마트 치수", "label": row["label"],
                            "value": row["value"], "unit": row["unit"], "views": view_ids})
    return {"datums": sorted(hole_rows, key=lambda row: (row["name"], row["id"])), "model_dimensions": records}


def _hole_rows(data, visible):
    """! @brief 드릴 원본의 중심, 완성 치수, 공구와 도금 상태를 개별 홀 단위로 보존한다."""
    projection = data["projection"]
    rows = []
    for item in projection.get("mechanical", {}).get("holes", []):
        shape = item["shape"]
        rows.append({"id": item["id"], "center": shape.get("center_mm"), "kind": shape["kind"],
                     "finished": shape.get("diameter_mm", shape.get("finished_width_mm")),
                     "length": shape.get("finished_length_mm"), "tool": item["tool_diameter_mm"],
                     "plating": item["plating"]["state"]})
    for item in projection["shapes"]:
        if item["kind"] == "via" and (visible is None or item["id"] in visible):
            rows.append({"id": item["id"], "center": item["center_mm"], "kind": "via",
                         "finished": item["finished_hole_diameter_mm"], "length": None,
                         "tool": item["tool_hole_diameter_mm"], "plating": "plated"})
    for row in rows:
        row["name"] = data["names"].get(row["id"], "홀")
    rows.sort(key=lambda row: (tuple(row["center"] or (math.inf, math.inf)), row["id"]))
    for index, row in enumerate(rows, 1):
        row["mark"] = f"H{index}"
    return rows


def evaluation(data, option, bounds, visible):
    """! @brief 한 뷰에서 참조 치수와 중복·누락 목록을 읽기 전용으로 계산한다."""
    from rfad.domain.drawing_layout import polar

    settings = data["options"]["annotations"]
    document = data["projection"]["source_semantics"]
    board = data["projection"]["board"]
    categories = settings["categories"]
    holes = _hole_rows(data, None if option["kind"] == "outline" else visible)
    hole_index = {row["id"]: row for row in holes}
    datum = settings["datum"]
    datum_point = ([0.0, 0.0] if datum["kind"] == "board_origin" else bounds[:2] if datum["kind"] == "board_min"
                   else hole_index.get(datum["id"], {}).get("center"))
    report = {"style": settings["style"], "datum_mm": datum_point, "missing": [], "duplicates": [],
              "not_applicable": [], "dimension_count": 0, "hole_count": len(holes) if settings["hole_table"] else 0}
    rows, keys = [], {}

    def issue(status, source_id, title, reason):
        """! @brief 검토 목록에 원본 ID와 화면 명칭을 함께 둔다."""
        report[status].append({"source_id": source_id, "title": title, "reason": reason})

    def emit(source_id, key, title, value, anchors, kind, *, unit="mm", origin="automatic", model_mode=None):
        """! @brief 같은 물리 출처의 자동/모델 주석을 하나만 남기고 양쪽 기원을 기록한다."""
        if key in keys:
            existing = keys[key]
            existing["origins"].append({"source_id": source_id, "kind": origin, "mode": model_mode})
            issue("duplicates", source_id, title, "이미 기입한 같은 참조 치수에 합쳤습니다.")
            return
        row = {"source_id": source_id, "dimension_key": key[1], "title": title, "kind": kind,
               "value": value, "unit": unit, "anchors_mm": anchors,
               "origins": [{"source_id": source_id, "kind": origin, "mode": model_mode}]}
        keys[key] = row
        rows.append(row)

    x0, y0, x1, y1 = bounds
    if datum_point is None:
        issue("missing", datum["id"], "기준점", "선택한 홀 중심을 이 뷰에서 확인할 수 없습니다.")
    if "board" in categories:
        corners = board.get("outer_mm", [[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
        if board.get("kind") == "circle":
            cx, cy = board["center_mm"]
            corners = [[x0, cy], [x1, cy], [cx, y0], [cx, y1]]
        for index, axis in enumerate(("x", "y")):
            anchors = [min(corners, key=lambda point: point[index]), max(corners, key=lambda point: point[index])]
            emit(board["id"], (board["id"], "board." + axis), "외곽 " + axis.upper(),
                 anchors[1][index] - anchors[0][index], anchors, "board_" + axis)
    if "holes" in categories:
        if not holes:
            issue("not_applicable", None, CATEGORIES["holes"], "이 뷰에 표시할 홀이 없습니다.")
        prior, prior_label = datum_point, "기준점"
        ordered = sorted(holes, key=lambda row: row["id"] != datum["id"]) if datum["id"] else holes
        for row in ordered:
            center = row["center"]
            if center is None:
                issue("missing", row["id"], row["name"], "명시 홀 중심 좌표가 없습니다.")
                continue
            if datum_point is None:
                continue
            origin = prior if settings["style"] == "chain" else datum_point
            deltas = [coordinate - base for coordinate, base in zip(center, origin)]
            title = row["mark"] + (" / " + prior_label + " 기준" if settings["style"] == "chain" else "")
            emit(row["id"], (row["id"], "hole.center"), title, deltas, [origin, center], "hole")
            if settings["style"] == "chain":
                prior, prior_label = center, row["mark"]
    if "arcs" in categories:
        arcs = [row for row in data["projection"]["shapes"] if row["id"] in visible and row["kind"] == "arc_path"]
        if not arcs:
            issue("not_applicable", None, CATEGORIES["arcs"], "이 뷰에 표시할 원호 도체가 없습니다.")
        for row in arcs:
            center, radius = row["center_mm"], row["radius_mm"]
            tip = polar(center, radius, row["start_angle_deg"] + row["sweep_angle_deg"] / 2)
            emit(row["id"], (row["id"], "arc.radius"), data["names"][row["id"]] + " 반경", radius, [center, tip], "radial")
    if "feeds" in categories:
        ports = [row for row in document["ports"] if option["kind"] == "layer" and
                 (None in (row["positive_geometry_id"], row["reference_geometry_id"])
                  or {row["positive_geometry_id"], row["reference_geometry_id"]} & visible)]
        if not ports:
            issue("not_applicable", None, CATEGORIES["feeds"], "이 뷰에 연결된 급전이 없습니다.")
        for port in ports:
            try:
                if not {port["positive_geometry_id"], port["reference_geometry_id"]} <= visible:
                    _fail("선택 뷰에 급전 양쪽 도체가 함께 표시되지 않습니다.", "E_REFERENCE")
                anchors = _feed_points(document, port)
            except ProjectError as error:
                issue("missing", port["id"], port["name"], error.message)
                continue
            emit(port["id"], (port["id"], "feed.gap"), port["name"] + " 간극", math.dist(*anchors), anchors, "linear")

    known = {(group["entity_id"], item["key"]): {**item, "label": group["label"] + " / " + item["label"]}
             for group in data["dimensions"] for item in group["items"] if group["entity_id"] in visible or group["entity_id"] in hole_index}
    ports = {port["id"]: port for port in document["ports"]}
    for smart in smart_dimensions.dimensions(document):
        anchor = smart["anchors"]
        if anchor["kind"] == "holes":
            shown = set(anchor["ids"]) <= hole_index.keys()
        else:
            port = ports.get(anchor["ids"][0])
            shown = port is not None and {port["positive_geometry_id"], port["reference_geometry_id"]} <= visible
        if shown:
            known[smart["id"], "smart.distance"] = _smart_row(document, smart)
    for reference in settings["model_dimensions"]:
        source_id, key = reference["source_id"], reference["key"]
        item = known.get((source_id, key))
        if item is None or item["value"] is None:
            issue("missing", source_id, item["label"] if item else data["names"].get(source_id, key),
                  "선택한 모델 치수의 값이 미정이거나 이 뷰에서 원본을 찾을 수 없습니다.")
            continue
        anchor = item.get("anchors")
        physical = (anchor["ids"][0], "feed.gap") if anchor and anchor["kind"] == "feed" and item["anchors_mm"] else (source_id, key)
        points = item["anchors_mm"]
        kind = "value"
        if len(points) == 2 and key in ("line.length", "arc.radius", "smart.distance"):
            kind = "radial" if key == "arc.radius" else "linear"
        emit(source_id, physical, item["label"], item["value"], points, kind, unit=item["unit"], origin="model",
             model_mode=item.get("mode"))

    report["dimension_count"] = len(rows)
    return rows, holes, report
