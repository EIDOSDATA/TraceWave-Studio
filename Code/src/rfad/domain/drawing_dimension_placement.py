"""! @brief 종이 좌표의 치수선, 화살표, 문자 충돌을 결정론적으로 배치한다."""

import math


TEXT_HEIGHT = 2.5
CLEARANCE = 0.45
TOLERANCE = 1e-7
OFFSETS = sorted(((dx, dy) for dx in range(-8, 9) for dy in range(-8, 9)),
                 key=lambda item: (item[0] ** 2 + item[1] ** 2, abs(item[0]), item[1] < 0, item[0] < 0))


def _shift(point, direction, amount):
    """! @brief 원본 기준점과 독립된 종이 좌표를 구한다."""
    return [point[0] + direction[0] * amount, point[1] + direction[1] * amount]


def _direction(a, b):
    """! @brief 치수의 표시 방향만 정규화한다."""
    distance = math.dist(a, b)
    return [(b[0] - a[0]) / distance, (b[1] - a[1]) / distance] if distance > TOLERANCE else [1, 0]


def _label_box(point, label):
    """! @brief 한글과 숫자의 보수적인 폭으로 읽을 공간을 확보한다."""
    half = TEXT_HEIGHT * sum(0.65 if ord(char) < 128 else 1.05 for char in label) / 2
    x, y = point
    return [x - half, y - TEXT_HEIGHT * 0.27, x + half, y + TEXT_HEIGHT]


def _segment_box(segment):
    """! @brief 두 끝점에서 교차 검사의 빠른 경계를 만든다."""
    _, a, b = segment
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]


def _overlap(a, b, margin=CLEARANCE):
    """! @brief 종이 mm 간격까지 포함해 두 범위가 만나는지 확인한다."""
    return a[0] <= b[2] + margin and b[0] <= a[2] + margin and a[1] <= b[3] + margin and b[1] <= a[3] + margin


def _inside(box, bounds):
    """! @brief 치수와 화살표가 표제란 또는 용지 여백으로 나가지 않게 한다."""
    return bounds[0] <= box[0] and bounds[1] <= box[1] and box[2] <= bounds[2] and box[3] <= bounds[3]


def _distance_to_segment(point, a, b):
    """! @brief 끝점과 선분의 간격으로 평행한 선과 화살표까지 검사한다."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= TOLERANCE ** 2:
        return math.dist(point, a)
    factor = min(1, max(0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq))
    return math.hypot(point[0] - a[0] - factor * dx, point[1] - a[1] - factor * dy)


def _segments_close(a, b, c, d, margin):
    """! @brief 교차와 근접을 구분 없이 선분 간 간섭으로 처리한다."""
    def cross(p, q, r):
        """! @brief 세 점의 방향을 계산한다."""
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    if cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0:
        return True
    return min(_distance_to_segment(a, c, d), _distance_to_segment(b, c, d),
               _distance_to_segment(c, a, b), _distance_to_segment(d, a, b)) <= margin


def _box_hits(box, segment, segment_box):
    """! @brief 치수 문자가 실제 선분을 가리는지 검사한다."""
    if not _overlap(box, segment_box):
        return False
    _, a, b = segment
    if any(box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3] for p in (a, b)):
        return True
    x0, y0, x1, y1 = box
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return any(_segments_close(a, b, c, d, CLEARANCE) for c, d in zip(corners, corners[1:] + corners[:1]))


def _collision(a, b):
    """! @brief 치수 본체끼리, 또는 다른 치수의 문자와 각 선분이 겹치는지 확인한다."""
    if not _overlap(a["extent"], b["extent"]):
        return False
    if (_overlap(a["label_box"], b["label_box"])
            or any(_box_hits(a["label_box"], item, area) for item, area in b["checked_segments"])
            or any(_box_hits(b["label_box"], item, area) for item, area in a["checked_segments"])):
        return True
    for first, first_box in a["checked_segments"]:
        for second, second_box in b["checked_segments"]:
            if not _overlap(first_box, second_box):
                continue
            if _segments_close(first[1], first[2], second[1], second[2], CLEARANCE):
                return True
    return False


def _arrow(segments, tip, back, size):
    """! @brief 치수 끝 실제 좌표에서 종이 크기의 열린 화살표를 만든다."""
    normal = [-back[1], back[0]]
    end = _shift(tip, back, size)
    for sign in (-1, 1):
        segments.append(("arrow", tip, _shift(end, normal, sign * size * 0.37)))


def _size_line(segments, a, b, point, box):
    """! @brief 양 끝을 연장해 이동한 평행 치수선과 짧은 구간의 바깥 화살표를 만든다."""
    span = math.dist(a, b)
    if span <= TOLERANCE:
        return
    unit = _direction(a, b)
    normal = [-unit[1], unit[0]]
    distance = sum((coordinate - origin) * direction for coordinate, origin, direction in zip(point, a, normal))
    half_width = (box[2] - box[0]) / 2
    height = TEXT_HEIGHT if normal[1] * distance < 0 else TEXT_HEIGHT * 0.27
    margin = abs(normal[0]) * half_width + abs(normal[1]) * height + 1.55
    offset = distance - math.copysign(margin, distance)
    p, q = _shift(a, normal, offset), _shift(b, normal, offset)
    if abs(offset) > TOLERANCE:
        segments.extend((("extension", a, p), ("extension", b, q)))
    size = 1.55
    outside = span < 2 * size + 1.25
    sign = -1 if outside else 1
    _arrow(segments, p, unit, sign * size)
    _arrow(segments, q, unit, -sign * size)
    start, end = (_shift(p, unit, -size - 0.45), _shift(q, unit, size + 0.45)) if outside else (p, q)
    lead = sum((coordinate - origin) * direction for coordinate, origin, direction in zip(point, start, unit))
    if lead < 0 or lead > math.dist(start, end):
        projected = _shift(start, unit, lead)
        if lead < 0:
            start = projected
        else:
            end = projected
    segments.append(("line", start, end))


def _leader(segments, tip, point, box):
    """! @brief 리더 화살표를 출처에 남기고 글자 상자 밖에서 선을 끝낸다."""
    direction = _direction(tip, point)
    normal = [-direction[0], -direction[1]]
    edges = [box[axis + 2] if component > 0 else box[axis] for axis, component in enumerate(normal)]
    distance = min((edge - coordinate) / component for edge, coordinate, component in zip(edges, point, normal)
                   if abs(component) > TOLERANCE)
    if math.dist(tip, point) <= distance + 0.9:
        return
    end = _shift(point, normal, distance + 0.8)
    if math.dist(tip, end) > 0.3:
        segments.append(("line", tip, end))
        _arrow(segments, tip, direction, min(1.45, math.dist(tip, end)))


def _candidate(group, point):
    """! @brief 같은 위치로 미리보기와 출력에 쓸 실제 주석 벡터를 구성한다."""
    point = [round(value, 6) for value in point]
    box = _label_box(point, group["label"])
    kind, anchors = group["kind"], group["anchors"]
    segments = []
    if kind in ("linear", "board_x", "board_y"):
        _size_line(segments, *anchors, point, box)
    elif kind == "hole" and group["projected"]:
        a, b = anchors
        _size_line(segments, a, [b[0], a[1]], [point[0], point[1] - 0.6], box)
        _size_line(segments, [b[0], a[1]], b, [point[0] - 0.6, point[1]], box)
        if not segments:
            _leader(segments, b, point, box)
    else:
        _leader(segments, anchors[-1], point, box)
    ends = [_segment_box(segment) for segment in segments]
    boxes = [box, *ends]
    checked = [(segment, area) for segment, area in zip(segments, ends) if segment[0] != "extension"]
    extent = [min(item[0] for item in boxes), min(item[1] for item in boxes), max(item[2] for item in boxes),
              max(item[3] for item in boxes)]
    return {"point_mm": point, "label_box": box, "extent": extent, "segments": segments,
            "checked_segments": checked, "self_overlap": not segments or any(_box_hits(box, item, area) for item, area in checked)}


def _candidates(group, bounds):
    """! @brief 가까운 안쪽 위치부터 유한 격자 후보를 검사한다."""
    x0, y0, x1, y1 = bounds
    x, y = group["preferred"]
    box = _label_box([0, 0], group["label"])
    keep = set()
    for dx, dy in OFFSETS:
        px = min(max(x + dx * 6, x0 - box[0] + 0.1), x1 - box[2] - 0.1)
        py = min(max(y + dy * 6, y0 - box[1] + 0.1), y1 - box[3] - 0.1)
        point = round(px, 6), round(py, 6)
        if point not in keep:
            keep.add(point)
            yield point


def _visible_parts(segment, labels):
    """! @brief 문자 공간을 가로지르는 보조선만 끊어 원래 끝점과 읽기 쉬운 문자를 보존한다."""
    if segment[0] != "extension":
        yield segment
        return
    _, a, b = segment
    start, end = 0.0, 1.0
    delta = [b[0] - a[0], b[1] - a[1]]
    gaps = []
    for box in labels:
        if not _overlap(_segment_box(segment), box):
            continue
        low, high = start, end
        for axis in (0, 1):
            left, right = box[axis] - CLEARANCE, box[axis + 2] + CLEARANCE
            if abs(delta[axis]) <= TOLERANCE:
                if not left <= a[axis] <= right:
                    low, high = 1, 0
                continue
            entry, exit_at = sorted(((left - a[axis]) / delta[axis], (right - a[axis]) / delta[axis]))
            low, high = max(low, entry), min(high, exit_at)
        if low < high:
            gaps.append((low, high))
    for low, high in sorted(gaps) + [(end, end)]:
        if low - start > TOLERANCE:
            yield "extension", _shift(a, delta, start), _shift(a, delta, low)
        start = max(start, high)


def fixed_label(point, label):
    """! @brief 사용자가 옮기지 않는 기준 문자를 충돌 검사에 포함한다."""
    box = _label_box(point, label)
    return {"label_box": box, "extent": box, "segments": [], "checked_segments": []}


def arrange(groups, bounds, pins, obstacles=()):
    """! @brief 수동 위치를 먼저 확보한 뒤 자동 치수의 간섭을 검사하며 배치한다."""
    positions = {(row["source_id"], row["key"]): row["point_mm"] for row in pins}
    indexed = {(row["source_id"], row["key"]): row for row in groups}
    placed, unavailable = {}, []
    for key, point in positions.items():
        group = indexed.get(key)
        if group is None:
            unavailable.append({"source_id": key[0], "key": key[1], "reason": "현재 뷰에 기입할 치수가 없습니다."})
            continue
        candidate = _candidate(group, point)
        if not _inside(candidate["label_box"], bounds):
            unavailable.append({"source_id": key[0], "key": key[1], "reason": "수동 위치가 현재 도면 영역을 벗어납니다."})
            continue
        placed[key] = {**candidate, "pinned": True}

    def cost(choice, others, cutoff=math.inf):
        """! @brief 화면 범위와 자기 문자 충돌을 우선하며 개선이 불가능한 후보는 중단한다."""
        outside = not _inside(choice["extent"], bounds) or choice["self_overlap"]
        result = len(others) + 1 if outside else 0
        for other in others:
            if result >= cutoff:
                break
            result += _collision(choice, other)
        return result

    def best_choice(group, others, first):
        """! @brief 현재보다 나은 위치를 가까운 후보에서 찾는다."""
        best, score = first, cost(first, others)
        for point in _candidates(group, bounds):
            if score == 0:
                break
            choice = _candidate(group, point)
            next_score = cost(choice, others, score)
            if next_score < score:
                best, score = choice, next_score
        return {**best, "pinned": False}

    for key, group in indexed.items():
        if key not in placed:
            first = _candidate(group, next(_candidates(group, bounds)))
            placed[key] = best_choice(group, [*placed.values(), *obstacles], first)

    for key in reversed(indexed):
        if placed[key]["pinned"]:
            continue
        peers = [item for peer, item in placed.items() if peer != key]
        placed[key] = best_choice(indexed[key], [*peers, *obstacles], placed[key])

    collisions = []
    items = []
    for key, group in indexed.items():
        candidate = placed[key]
        if (candidate["self_overlap"] or not _inside(candidate["extent"], bounds)
                or any(_collision(candidate, other) for peer, other in placed.items() if peer != key)
                or any(_collision(candidate, obstacle) for obstacle in obstacles)):
            collisions.append({"source_id": key[0], "key": key[1], "title": group["title"]})
        items.append({**group, **candidate})
    labels = [item["label_box"] for item in (*items, *obstacles)]
    for item in items:
        item["segments"] = [part for segment in item["segments"] for part in _visible_parts(segment, labels)]
    moved = sum(not item["pinned"] and math.dist(item["point_mm"], item["preferred"]) > 1e-5 for item in items)
    return items, {"moved": moved, "pinned": sum(item["pinned"] for item in items), "collisions": collisions,
                   "unavailable": unavailable}
