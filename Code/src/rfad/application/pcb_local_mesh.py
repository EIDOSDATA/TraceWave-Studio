"""! @brief 급전/비아/지정 간극의 국부 Cartesian 격자 조건과 적용 구간을 계산한다."""

from bisect import bisect_left

from rfad.application.pcb_geometry import fail
from rfad.domain.design import _text, _uuid

FIELD = "settings.local_mesh"
AXES = "xyz"
MAX_RULES = 16
MIN_CELL_MM = 0.0001


def validate_rules(rules):
    """! @brief 원본과 독립적인 조건 형식을 검사한다. 실제 객체와 범위는 계획에서 검증한다."""
    if type(rules) is not list or not 1 <= len(rules) <= MAX_RULES:
        fail("E_RESOURCE", "국부 격자 조건은 1~16개를 지원합니다.", FIELD)
    for index, rule in enumerate(rules):
        field = f"{FIELD}[{index}]"
        kind = rule.get("kind") if type(rule) is dict else None
        keys = {"kind", "priority", "max_cell_mm"}
        if kind not in ("port", "via", "gap") or set(rule) != keys | ({"name", "bounds_mm"} if kind == "gap" else {"object_id"}):
            fail("E_SCHEMA", "국부 격자 대상은 급전, 비아 또는 좌표로 지정한 간극이어야 합니다.", field)
        if type(rule["priority"]) is not int or not 0 <= rule["priority"] <= 100:
            fail("E_SCHEMA", "국부 격자 우선순위는 0~100의 정수여야 합니다.", field + ".priority")
        widths = rule["max_cell_mm"]
        if (type(widths) is not dict or not widths or not widths.keys() <= set(AXES)
                or any(type(width) not in (int, float) or not 0.001 <= width <= 5 for width in widths.values())):
            fail("E_SCHEMA", "한 축 이상에서 목표 최대 셀 폭을 0.001~5 mm로 지정하십시오.", field + ".max_cell_mm")
        if kind != "gap":
            _uuid(rule["object_id"], field + ".object_id")
            continue
        name = _text(rule["name"], field + ".name", limit=64)
        if name != name.strip() or any(ord(character) < 32 for character in name):
            fail("E_SCHEMA", "간극 이름은 양끝 공백이나 줄바꿈 없이 입력하십시오.", field + ".name")
        bounds = rule["bounds_mm"]
        if (type(bounds) is not list or len(bounds) != 3
                or any(type(interval) is not list or len(interval) != 2
                       or any(type(value) not in (int, float) for value in interval)
                       or not -1000 <= interval[0] < interval[1] <= 1000 for interval in bounds)):
            fail("E_SCHEMA", "간극은 X/Y/Z 각각 시작 좌표가 끝 좌표보다 작은 mm 범위여야 합니다.", field + ".bounds_mm")


def _target_bounds(rule, port, vias, field):
    """! @brief 도체의 실제 소비 위치로부터 격자의 대상 범위를 구한다."""
    if rule["kind"] == "gap":
        return rule["bounds_mm"]
    if rule["kind"] == "port" and rule["object_id"] == port["id"]:
        return [sorted(pair) for pair in zip(port["start_mm"], port["stop_mm"])]
    via = vias.get(rule["object_id"]) if rule["kind"] == "via" else None
    if via is not None:
        radius = via["outer_radius_mm"]
        return [[center - radius, center + radius] for center in via["center_mm"]] + [[via["z_min_mm"], via["z_max_mm"]]]
    fail("E_GEOMETRY", "국부 격자 대상이 현재 개정의 해석 형상에 없습니다. 대상을 다시 지정하십시오.", field + ".object_id")


def _insert_anchor(anchors, coordinate):
    """! @brief 최소 셀 간격보다 가까운 기존 임계선을 그대로 사용한다."""
    position = bisect_left(anchors, coordinate)
    candidates = anchors[max(position - 1, 0):position + 1]
    if candidates:
        nearest = min(candidates, key=lambda anchor: abs(anchor - coordinate))
        if abs(nearest - coordinate) < MIN_CELL_MM:
            return nearest
    anchors.insert(position, coordinate)
    return coordinate


def compile_rules(case, anchors, model_bounds):
    """! @brief 축별 국부 규칙을 기존 모델 내부선에 고정하고 원래 범위와 적용 범위를 분리한다."""
    vias = {via["id"]: via for via in case.get("vias", [])}
    rows = []
    for index, rule in enumerate(case["settings"]["local_mesh"]):
        field = f"{FIELD}[{index}]"
        bounds = _target_bounds(rule, case["port"], vias, field)
        if rule["kind"] == "gap" and any(a < low - 1e-9 or b > high + 1e-9
                                         for (a, b), (low, high) in zip(bounds, model_bounds)):
            fail("E_GEOMETRY", "간극 좌표는 해석 모델의 X/Y/Z 내부 범위에 있어야 합니다.", field + ".bounds_mm")
        row = {"kind": rule["kind"], "priority": rule["priority"], "bounds_mm": bounds, "axes": {},
               **({"name": rule["name"]} if rule["kind"] == "gap" else {"object_id": rule["object_id"]})}
        for axis, name in enumerate(AXES):
            if name not in rule["max_cell_mm"]:
                continue
            width = rule["max_cell_mm"][name]
            start, stop = bounds[axis]
            if start == stop:
                start, stop = start - width / 2, stop + width / 2
            low, high = model_bounds[axis]
            start = _insert_anchor(anchors[axis], round(max(low, start), 12))
            stop = _insert_anchor(anchors[axis], round(min(high, stop), 12))
            if stop - start < MIN_CELL_MM - 1e-12:
                fail("E_GEOMETRY", "국부 격자 범위가 최소 셀 간격보다 작습니다.", field)
            row["axes"][name] = {"target_cell_mm": width, "effective_bounds_mm": [start, stop], "segments": []}
        rows.append(row)
    return rows


def assign_interval(rules, left, right):
    """! @brief 겹친 구간의 우선순위를 적용하고 같은 상태의 인접 구간을 합친다."""
    active = [(priority, axis) for priority, axis in rules
              if axis["effective_bounds_mm"][0] <= left and right <= axis["effective_bounds_mm"][1]]
    if not active:
        return None
    winner = max((priority, -axis["target_cell_mm"]) for priority, axis in active)
    for priority, axis in active:
        applied = (priority, -axis["target_cell_mm"]) == winner
        segments = axis["segments"]
        if segments and segments[-1]["applied"] == applied and segments[-1]["bounds_mm"][1] == left:
            segments[-1]["bounds_mm"][1] = right
        else:
            segments.append({"applied": applied, "bounds_mm": [left, right]})
    return -winner[1]


def finish_report(rules, lines):
    """! @brief 최종 격자선에서 적용/우선순위 제외 구간의 셀 수와 실제 최대 폭을 읽는다."""
    for rule in rules:
        for axis, record in rule["axes"].items():
            values = lines[axis]
            for segment in record["segments"]:
                low, high = segment["bounds_mm"]
                first, last = bisect_left(values, low), bisect_left(values, high)
                segment.update(first_line=first, cells=last - first,
                               max_cell_mm=max(values[index + 1] - values[index] for index in range(first, last)))
    return {"schema": "rfad.pcb-local-mesh/0.1", "rules": rules}


def covers_feed(report, port):
    """! @brief 평면 급전 간극 전체에 두 셀 기준을 만족하는 실제 국부 조건이 있는지 확인한다."""
    axis = port["axis"]
    axis_index = AXES.index(axis)
    low, high = sorted((port["start_mm"][axis_index], port["stop_mm"][axis_index]))
    width = (high - low) / 2
    eligible = []
    for rule in report["rules"]:
        record = rule["axes"].get(axis)
        if record and record["target_cell_mm"] <= width + 1e-12:
            eligible.extend(segment["bounds_mm"] for segment in record["segments"] if segment["applied"])
    for start, stop in sorted(eligible):
        if start <= low + 1e-12:
            low = max(low, stop)
        if low >= high - 1e-12:
            return True
    return False
