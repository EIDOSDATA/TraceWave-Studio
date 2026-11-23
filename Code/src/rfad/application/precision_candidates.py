"""! @brief 정밀 편집 입력을 검토 가능한 원본 후보와 출처 사본으로 구성한다."""

from copy import deepcopy
import math
from uuid import UUID, uuid5

from rfad.adapters.planar_backend import operate, runtime
from rfad.application.canonical import canonical_hash
from rfad.domain.curve_boolean import _intersections, _piece, TOLERANCE_MM
from rfad.domain.design import _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import allocate_name, object_label
from rfad.domain import pattern_features as patterns
from rfad.domain.precision_fillet import curved_fillet
from rfad.domain.precision_dimensions import bind_dimension, dimensions, set_dimension
from rfad.domain.precision_transform import MAX_SELECTION, fail, number, point, point_fields, replace_literal, scalar, transform
from rfad.domain.sketch_constraints import groups as sketch_groups
from rfad.domain.units import Quantity


OPERATIONS = {
    "rotate": ("회전", {"pivot_x_mm", "pivot_y_mm", "angle_deg"}),
    "mirror": ("미러", {"axis", "offset_mm"}),
    "linear_pattern": ("직선 반복 복사", {"count", "dx_mm", "dy_mm"}),
    "circular_pattern": ("원형 반복 복사", {"count", "pivot_x_mm", "pivot_y_mm", "step_deg"}),
    "edit_linear_pattern": ("직선 반복 설정 편집", {"count", "dx_mm", "dy_mm"}),
    "edit_circular_pattern": ("원형 반복 설정 편집", {"count", "pivot_x_mm", "pivot_y_mm", "step_deg"}),
    "detach_pattern": ("반복 연결 해제", set()),
    "line_fillet": ("두 직선 사이 필렛", {"radius_mm"}),
    "curved_fillet": ("원호에 접하는 필렛", {"radius_mm"}),
    "curve_trim": ("교차점에서 선·원호 자르기", {"target_id", "keep"}),
    "curve_split": ("선·원호 중심선 분할", {"percent"}),
    "curve_extend": ("선·원호 한쪽 끝 연장", {"endpoint", "distance_mm"}),
    "arc_offset": ("원호 중심선 오프셋", {"distance_mm"}),
    "dimension_set": ("치수 변경", {"dimension_key", "value", "unit"}),
    "bind_dimension": ("매개변수 연결", {"dimension_key", "parameter_id"}),
    "union": ("영역 합치기", set()),
    "difference": ("첫 영역에서 빼기", set()),
    "intersection": ("영역 교차", set()),
    "offset": ("영역 오프셋", {"distance_mm", "join", "mitre_limit"}),
}
PLANAR_OPERATIONS = {"union", "difference", "intersection", "offset"}
PATTERNS = patterns.PATTERNS


def selected(document, identities):
    """! @brief 명시 선택 순서를 보존하며 모르는 UUID와 중복을 차단한다."""
    if type(identities) is not list or len(identities) > MAX_SELECTION:
        fail("선택은 최대 16개 UUID 목록이어야 합니다.", "selection_ids", "E_RESOURCE")
    for identity in identities:
        _uuid(identity, "selection_ids")
    if len(set(identities)) != len(identities):
        fail("같은 객체를 중복 선택할 수 없습니다.", "selection_ids", "E_CONFLICT")
    geometry = {row["id"]: row for row in document["geometry"]}
    if any(identity not in geometry for identity in identities):
        fail("선택 객체가 현재 개정에 없습니다.", "selection_ids", "E_CONFLICT")
    return [geometry[identity] for identity in identities]


def _referenced(document, identities):
    """! @brief 객체 교체에서 단자/비아/기대 연결을 자동으로 다른 객체에 넘기지 않는다."""
    ids = set(identities)
    for port in document["ports"]:
        if ids & {port["positive_geometry_id"], port["reference_geometry_id"]}:
            return "포트가 참조한 영역입니다. 급전 의미를 자동으로 새 객체에 넘기지 않습니다."
    for row in document["connections"]:
        if ids & set(row["object_ids"]):
            return "기대 연결이 참조한 영역입니다. 먼저 연결 참조를 명시적으로 정리하십시오."
    for row in document["geometry"]:
        if ids & set(row.get("pad_ids", [])):
            return "비아가 참조한 패드입니다. 참조를 자동 교체하지 않습니다."
    return ""


def operation_reason(document, rows, operation):
    """! @brief 비활성 사유를 서비스와 GUI가 같은 선택 기준으로 표시한다."""
    if not rows:
        return "도체 객체를 선택하십시오."
    if operation in patterns.REGENERATE or operation == "detach_pattern":
        try:
            patterns.match(document, rows, operation)
        except ProjectError as error:
            return error.message
        return ""
    if operation in ("dimension_set", "bind_dimension", "offset", "arc_offset") and len(rows) != 1:
        return "이 작업에는 객체 한 개를 선택하십시오."
    if operation in {"line_fillet", "curved_fillet"}:
        kinds = {row["kind"] for row in rows}
        if len(rows) != 2 or not kinds <= {"line_path", "arc_path"}:
            return "공통 끝점을 가진 선·원호 도체 두 개를 선택하십시오."
        if operation == "line_fillet" and kinds != {"line_path"}:
            return "공통 끝점을 가진 직선 도체 두 개를 선택하십시오."
        if operation == "curved_fillet" and "arc_path" not in kinds:
            return "하나 이상의 열린 원호를 선택하십시오."
        fields = ("frame_id", "layer_id", "net_id", "material_ref", "role", "include_in_em", "include_in_export")
        if any(rows[0][key] != rows[1][key] for key in fields):
            return "같은 좌표계, 층, 넷, 재료, 역할, 선폭 및 포함 상태인 도체만 필렛으로 연결할 수 있습니다."
        return _referenced(document, [row["id"] for row in rows])
    if operation == "curve_trim":
        if len(rows) != 2 or any(row["kind"] not in {"line_path", "arc_path"} for row in rows):
            return "자르는 도체와 경계 도체를 선 또는 원호로 두 개 선택하십시오."
        if rows[0]["frame_id"] != rows[1]["frame_id"] or rows[0]["layer_id"] != rows[1]["layer_id"]:
            return "같은 좌표계와 층의 도체 두 개를 선택하십시오."
        return ""
    if operation in ("curve_split", "curve_extend"):
        if len(rows) != 1 or rows[0]["kind"] not in {"line_path", "arc_path"}:
            return "분할하거나 연장할 열린 선 또는 원호 하나를 선택하십시오."
        identity = rows[0]["id"]
        for group in sketch_groups(document):
            if any(ref["id"] == identity for relation in (*group["constraints"], *group["protected"])
                   for ref in relation["refs"]):
                return "스케치 구속이 참조하는 도체입니다. 구속을 먼저 편집하십시오."
        return _referenced(document, [identity])
    if operation in PLANAR_OPERATIONS:
        engine = runtime()[1]
        if not engine["available"]:
            return engine["reason"]
        if any(row["kind"] != "planar_region" for row in rows):
            return "현재 평면 연산은 직선 외곽과 구멍을 가진 도체 영역만 지원합니다."
        if operation != "offset" and len(rows) < 2:
            return "집합 연산에는 두 개 이상 영역이 필요합니다."
        fields = ("frame_id", "layer_id", "net_id", "material_ref", "role", "include_in_em", "include_in_export")
        if any(any(row[key] != rows[0][key] for key in fields) for row in rows[1:]):
            return "좌표계/층/net/재료/역할/해석 및 출력 포함 상태가 같은 영역만 연산할 수 있습니다."
        if any("parameter_id" in value or value.get("value_si") is None for row in rows for _, coordinates in point_fields(row) for value in coordinates):
            return "좌표가 미정이거나 매개변수에 결합되어 있습니다. 자동으로 리터럴 영역으로 변환하지 않습니다."
        return _referenced(document, [row["id"] for row in rows])
    if operation in ("dimension_set", "bind_dimension"):
        key = "editable" if operation == "dimension_set" else "binding_supported"
        return "" if any(row[key] for row in dimensions(document, rows[0])) else "선택 객체에 지원하는 직접 치수가 없습니다."
    if operation == "arc_offset":
        row = rows[0]
        if row["kind"] != "arc_path":
            return "원의 중심과 전개각을 유지하면서 이동할 원호를 선택하십시오."
        if "parameter_id" in row["radius"] or row["radius"].get("value_si") is None:
            return "원호 반경이 매개변수에 연결되었거나 미정입니다."
        return _referenced(document, [row["id"]])
    if operation in PATTERNS:
        ids = {row["id"] for row in rows}
        if len(rows) * 2 > MAX_SELECTION:
            return "원본과 복사본을 합쳐 최대 16개까지 지원합니다."
        if any(set(row.get("pad_ids", [])) - ids for row in rows):
            return "비아를 복사할 때 연결한 모든 패드를 함께 선택하십시오."
    for row in rows:
        if any("parameter_id" in value or value.get("value_si") is None for _, coordinates in point_fields(row) for value in coordinates):
            return "위치가 미정이거나 매개변수에 연결되어 있습니다. 해당 속성/매개변수를 편집하십시오."
        if operation == "linear_pattern":
            continue
        angles = [row["start_angle"]] if row["kind"] == "arc_path" else []
        if row["kind"] == "arc_path" and operation == "mirror":
            angles.append(row["sweep_angle"])
        if row["kind"] == "pad" and row["pad_shape"] == "rectangle":
            angles.append(row["rotation"])
        if any("parameter_id" in value or value.get("value_si") is None for value in angles):
            return "변환 각도가 미정이거나 매개변수에 연결되어 있습니다. 해당 매개변수를 편집하십시오."
    return ""


def parameter_copies(document, objects):
    """! @brief 선택 객체가 참조한 매개변수와 표현식 의존 사본만 추출한다."""
    pending = []

    def visit(value):
        """! @brief 기하 원본의 제한 JSON 트리에서 참조를 읽는다."""
        if type(value) is dict:
            if set(value) == {"parameter_id"}:
                pending.append(value["parameter_id"])
            else:
                for child in value.values():
                    visit(child)
        elif type(value) is list:
            for child in value:
                visit(child)

    visit(objects)
    result = {}
    while pending:
        identity = pending.pop()
        if identity in result:
            continue
        record = document["parameters"].get(identity)
        if record is None:
            fail("의존 매개변수가 없습니다.", "selection_ids", "E_CONFLICT")
        result[identity] = deepcopy(record)
        pending.extend(record.get("expression", {}).get("dependencies", []))
    return result


def _planar_objects(document, rows, operation, values, origin_id):
    """! @brief 명시 연산 결과에 새 UUID를 주고 모든 입력의 출처 사본을 따로 보존한다."""
    operands = [{"outer": [point(document, item) for item in row["outer"]],
                 "holes": [[point(document, item) for item in hole] for hole in row["holes"]]} for row in rows]
    shapes, engine = operate(operands, operation, values)
    sources = []
    for row in rows:
        for _, coordinates in point_fields(row):
            for quantity in coordinates:
                sources.extend(quantity.get("source_refs", []))
    sources = list(dict.fromkeys(sources))
    if len(sources) > 128:
        fail("결과 좌표의 합친 출처가 128개 상한을 초과했습니다.", "selection_ids", "E_RESOURCE")
    result = []
    for index, shape in enumerate(shapes):
        output = deepcopy(rows[0])
        output["id"] = str(uuid5(UUID(origin_id), "geometry:" + str(index)))
        output["outer"] = [[Quantity.from_value(value, "mm", source_refs=sources).to_dict() for value in point] for point in shape["outer"]]
        output["holes"] = [[[Quantity.from_value(value, "mm", source_refs=sources).to_dict() for value in point] for point in loop] for loop in shape["holes"]]
        output["name"] = allocate_name(document, output, reserved=[item["name"] for item in result])
        result.append(output)
    return result, engine


def _centerline(document, row):
    """! @brief 저장된 선과 signed 원호를 교차 계산 형식으로 해석한다."""
    if row["kind"] == "line_path":
        return {"kind": "line", **{key: point(document, row[key], "geometry." + key) for key in ("start", "end")}}
    return {"kind": "arc", "center": point(document, row["center"], "geometry.center"),
            "radius": scalar(document, row["radius"], field="geometry.radius"),
            **{axis: scalar(document, row[key], "angle", "deg", "geometry." + key)
               for axis, key in (("start_deg", "start_angle"), ("sweep_deg", "sweep_angle"))}}


def _trim(document, rows, values):
    """! @brief 선택한 끝에서 첫 교차점까지만 잘라 내고 절삭 경계와 원래 ID를 보존한다."""
    target = _uuid(values["target_id"], "target_id")
    keep = values["keep"]
    if target not in {row["id"] for row in rows} or keep not in ("start", "end"):
        fail("두 도체 중 절삭 대상과 남길 끝을 지정하십시오.", "selection_ids", "E_SCHEMA")
    original = next(row for row in rows if row["id"] == target)
    protected = _referenced(document, [target])
    if protected:
        fail(protected, "target_id", "E_CONFLICT")
    cutter = next(row for row in rows if row["id"] != target)
    subject = _centerline(document, original)
    if subject["kind"] == "arc" and abs(subject["sweep_deg"]) >= 360 - 1e-9:
        fail("접점에서 열린 원호를 만든 후 시작 또는 끝을 자르십시오.", "target_id", "E_UNSUPPORTED")
    try:
        points = _intersections(subject, _centerline(document, cutter))
    except ProjectError as error:
        fail(error.message, "target_id", error.code)
    epsilon = TOLERANCE_MM / _path_span(subject)
    interior = [t for t, _ in points if epsilon < t < 1 - epsilon]
    if not interior:
        fail("대상 내부에서 경계와 만나는 교차점을 찾을 수 없습니다.", "target_id")
    start, end = (0, max(interior)) if keep == "start" else (min(interior), 1)
    result = _resize_path(document, original, subject, start, end)
    return [result if row["id"] == target else deepcopy(row) for row in rows]


def _path_span(curve):
    """! @brief 직선 길이 또는 원호의 중심선 길이를 mm로 계산한다."""
    span = (math.dist(curve["start"], curve["end"]) if curve["kind"] == "line"
            else curve["radius"] * math.radians(abs(curve["sweep_deg"])))
    if not math.isfinite(span) or span <= TOLERANCE_MM:
        fail("유한한 길이를 가진 중심선을 선택하십시오.", "selection_ids")
    return span


def _resize_path(document, original, curve, start, end):
    """! @brief 중심선의 매개 구간에서 한쪽 끝의 위치와 각도만 갱신한다."""
    cut = _piece(curve, start, end)
    result = deepcopy(original)
    if curve["kind"] == "line":
        key = "end" if start == 0 else "start"
        result[key] = [replace_literal(document, old, value, "mm", "geometry." + key)
                       for old, value in zip(original[key], cut[key])]
    else:
        if start != 0:
            result["start_angle"] = replace_literal(document, original["start_angle"], cut["start_deg"], "deg", "geometry.start_angle")
        result["sweep_angle"] = replace_literal(document, original["sweep_angle"], cut["sweep_deg"], "deg", "geometry.sweep_angle")
    return result


def _split_path(document, source, values, origin_id):
    """! @brief 같은 선 또는 원호 위에서 두 조각을 만들고 시작 쪽에 원본 ID를 남긴다."""
    curve = _centerline(document, source)
    if curve["kind"] == "arc" and abs(curve["sweep_deg"]) >= 360 - 1e-9:
        fail("열린 원호를 선택하십시오.", "selection_ids", "E_UNSUPPORTED")
    fraction = number(values["percent"], "percent") / 100
    epsilon = TOLERANCE_MM / _path_span(curve)
    if not epsilon < fraction < 1 - epsilon:
        fail("분할 위치는 중심선의 시작점과 끝점 사이여야 합니다.", "percent")
    first = _resize_path(document, source, curve, 0, fraction)
    second = _resize_path(document, source, curve, fraction, 1)
    second["id"] = str(uuid5(UUID(origin_id), "split-end"))
    second["name"] = allocate_name(document, second)
    return [first, second]


def _extend_path(document, source, values):
    """! @brief 지정한 끝을 직선 방향 또는 기존 원의 접선 방향으로 연장한다."""
    end = values["endpoint"]
    if end not in ("start", "end"):
        fail("연장할 시작점 또는 끝점을 지정하십시오.", "endpoint", "E_SCHEMA")
    distance = number(values["distance_mm"], "distance_mm")
    if not TOLERANCE_MM < distance <= 1e6:
        fail("연장 길이는 0.00000001 mm보다 크고 1000000 mm 이하여야 합니다.", "distance_mm")
    curve = _centerline(document, source)
    fraction = distance / _path_span(curve)
    if curve["kind"] == "arc" and abs(curve["sweep_deg"]) * (1 + fraction) >= 360 - 1e-9:
        fail("연장 이후에도 원호의 각도가 한 바퀴 미만이어야 합니다.", "distance_mm")
    start, stop = (-fraction, 1) if end == "start" else (0, 1 + fraction)
    return [_resize_path(document, source, curve, start, stop)]


def _fillet_radius(document, rows, values):
    """! @brief 사용할 반경과 공통 선폭을 검증한다."""
    radius = number(values["radius_mm"], "radius_mm")
    if not 0 < radius <= 1e6:
        fail("필렛 반경은 0보다 크고 1000000 mm 이하여야 합니다.", "radius_mm")
    first_width, second_width = (scalar(document, row["width"], field="geometry.width") for row in rows)
    if abs(first_width - second_width) > TOLERANCE_MM:
        fail("필렛의 두 도체에 같은 폭을 지정하십시오.", "selection_ids")
    return radius


def _fillet_arc(document, source, origin_id, radius, center, start, sweep):
    """! @brief 원래 도체의 의미와 새 중심선 형상을 하나의 원호로 묶는다."""
    arc = {key: deepcopy(value) for key, value in source.items() if key not in {"start", "end"}}
    arc.update(id=str(uuid5(UUID(origin_id), "fillet")), kind="arc_path",
               center=[Quantity.from_value(value, "mm").to_dict() for value in center],
               radius=Quantity.from_value(radius, "mm").to_dict(),
               start_angle=Quantity.from_value(start, "deg").to_dict(),
               sweep_angle=Quantity.from_value(sweep, "deg").to_dict())
    arc["name"] = allocate_name(document, arc)
    return arc


def _curve_fillet(document, rows, values, origin_id):
    """! @brief 접점을 기준으로 기존 중심선을 줄이고 새 필렛을 한 명령으로 작성한다."""
    radius = _fillet_radius(document, rows, values)
    if radius <= scalar(document, rows[0]["width"], field="geometry.width") / 2:
        fail("원호 필렛 반경은 도체 선폭의 절반보다 커야 합니다.", "radius_mm")
    edges = [_centerline(document, row) for row in rows]
    ends, parameters, center, start, sweep = curved_fillet(edges, radius)
    output = []
    for original, edge, endpoint, parameter in zip(rows, edges, ends, parameters):
        low, high = (parameter, 1) if endpoint == 0 else (0, parameter)
        output.append(_resize_path(document, original, edge, low, high))
    return [*output, _fillet_arc(document, rows[0], origin_id, radius, center, start, sweep)]


def _fillet(document, rows, values, origin_id):
    """! @brief 두 유한 직선에 동시에 접하는 정확한 원호를 만들고 접점까지만 줄인다."""
    radius = _fillet_radius(document, rows, values)
    lines = [{end: point(document, row[end], "geometry." + end) for end in ("start", "end")} for row in rows]
    shared = [(left, right) for left in lines[0] for right in lines[1]
              if math.dist(lines[0][left], lines[1][right]) <= TOLERANCE_MM]
    if len(shared) != 1:
        fail("두 직선은 유일한 공통 끝점에서 만나야 합니다.", "selection_ids")
    ends = shared[0]
    corners = [line[end] for line, end in zip(lines, ends)]
    deltas = [[b - a for a, b in zip(corner, line["end" if end == "start" else "start"])]
              for corner, line, end in zip(corners, lines, ends)]
    lengths = [math.hypot(*delta) for delta in deltas]
    if min(lengths) <= TOLERANCE_MM:
        fail("공통 끝점 밖에 길이가 있는 직선이 필요합니다.", "selection_ids")
    first, second = [[value / length for value in delta] for delta, length in zip(deltas, lengths)]
    cross = first[0] * second[1] - first[1] * second[0]
    dot = sum(a * b for a, b in zip(first, second))
    if abs(cross) <= 1e-9:
        fail("같은 직선이나 거의 평행한 직선에는 필렛을 만들 수 없습니다.", "selection_ids")
    half = math.atan2(abs(cross), dot) / 2
    distance = radius / math.tan(half)
    if not TOLERANCE_MM < distance < min(lengths) - TOLERANCE_MM:
        fail("이 반경은 직선 범위 안에 두 접점을 만들지 못합니다.", "radius_mm")
    corner = [(a + b) / 2 for a, b in zip(*corners)]
    bisector = [a + b for a, b in zip(first, second)]
    scale = radius / (math.sin(half) * math.hypot(*bisector))
    center = [value + direction * scale for value, direction in zip(corner, bisector)]
    if max(map(abs, center)) > 1e6:
        fail("필렛 중심이 좌표 범위를 벗어났습니다.", "radius_mm", "E_RESOURCE")
    contacts = [[value + direction * distance for value, direction in zip(corner, tangent)]
                for tangent in (first, second)]
    angles = [math.degrees(math.atan2(y - center[1], x - center[0])) for x, y in contacts]
    output = []
    for row, end, contact in zip(rows, ends, contacts):
        changed = deepcopy(row)
        changed[end] = [replace_literal(document, old, value, "mm", "geometry." + end)
                        for old, value in zip(row[end], contact)]
        output.append(changed)
    sweep = math.remainder(angles[1] - angles[0], 360)
    return [*output, _fillet_arc(document, rows[0], origin_id, radius, center, angles[0], sweep)]


def replacements(document, rows, operation, values, origin_id):
    """! @brief 지원 범위만 실행하고 서비스 검토 전에 원본을 변경하지 않는다."""
    reason = operation_reason(document, rows, operation)
    if reason:
        fail(reason, "selection_ids", "E_CONFLICT")
    engine = {"name": "rfad.precision", "version": "0.1", "available": True, "reason": ""}
    if operation in PLANAR_OPERATIONS:
        return _planar_objects(document, rows, operation, values, origin_id)
    if operation == "dimension_set":
        return [set_dimension(document, rows[0], values["dimension_key"], values["value"], values["unit"])], engine
    if operation == "bind_dimension":
        _uuid(values["parameter_id"], "parameter_id")
        return [bind_dimension(document, rows[0], values["dimension_key"], values["parameter_id"])], engine
    if operation in PATTERNS:
        return patterns.generate(document, rows, operation, values, origin_id), engine
    if operation == "line_fillet":
        return _fillet(document, rows, values, origin_id), engine
    if operation == "curved_fillet":
        return _curve_fillet(document, rows, values, origin_id), engine
    if operation == "curve_trim":
        return _trim(document, rows, values), engine
    if operation == "curve_split":
        return _split_path(document, rows[0], values, origin_id), engine
    if operation == "curve_extend":
        return _extend_path(document, rows[0], values), engine
    if operation == "arc_offset":
        row = deepcopy(rows[0])
        radius = scalar(document, row["radius"], field="geometry.radius")
        distance = number(values["distance_mm"], "distance_mm")
        updated = radius + distance
        if updated <= 0:
            fail("오프셋 이후 원호 반경이 양수여야 합니다.", "distance_mm")
        row["radius"] = replace_literal(document, row["radius"], updated, "mm", "geometry.radius")
        return [row], engine
    return [transform(document, row, operation, values) for row in rows], engine


def item_label(document, item):
    """! @brief 기존 편집기의 객체 표시 이름 규칙을 재사용한다."""
    return object_label(document, item)
