"""! @brief 두 기준점의 참조 및 구동 치수를 프로젝트 개정과 함께 보존한다."""

from copy import deepcopy
import math

from rfad.domain.design import _fields, _uuid
from rfad.domain.object_names import validate_name
from rfad.domain.pcb_features import apply_pcb_command, records
from rfad.domain.precision_transform import MAX_COORDINATE_MM, fail, number, point


KEY = "rfad.smart-dimensions"
PROFILE = "rfad.smart-dimensions/0.1"
COMMAND = "dimension.smart.replace"
LIMIT = 64
EPSILON_MM = 1e-7


def dimensions(document):
    """! @brief 기존 원본에 새 컬렉션을 자동 삽입하지 않는다."""
    return document["extensions"].get(KEY, {}).get("items", [])


def validate_anchors(anchors):
    """! @brief 두 홀 또는 같은 급전의 시작/끝 중 하나를 안정 UUID로 고정한다."""
    _fields(anchors, {"kind", "ids"}, "anchors")
    kind, ids = anchors["kind"], anchors["ids"]
    if (kind not in ("holes", "feed") or type(ids) is not list
            or len(ids) != (2 if kind == "holes" else 1)):
        fail("두 홀 또는 하나의 급전 양단을 선택하세요.", "anchors", "E_SCHEMA")
    for identity in ids:
        _uuid(identity, "anchors.ids")
    if len(set(ids)) != len(ids):
        fail("서로 다른 두 홀을 선택하세요.", "anchors", "E_CONFLICT")


def hole_sources(document):
    """! @brief 중심점이 있는 원형 홀, 슬롯과 도금 비아를 안정 ID로 내놓는다."""
    holes = {row["id"]: row for row in records(document, "pcb.holes")}
    vias = {row["id"]: row for row in document["geometry"] if row["kind"] == "via"}
    return holes | vias


def hole_center(document, row):
    """! @brief 기판 좌표의 명시 중심만 읽고 자유형 홀의 중심을 추정하지 않는다."""
    if document["board"] is None or row["frame_id"] != document["board"]["frame_id"]:
        fail("같은 기판 좌표계에 있는 홀 중심을 선택하세요.", "anchors", "E_CONFLICT")
    shape = row.get("shape", row)
    if "center" not in shape:
        fail("명시 중심이 없는 홀입니다.", "anchors", "E_CONFLICT")
    return [*point(document, shape["center"], "hole.center"), 0.0]


def positions(document, anchors):
    """! @brief 쌍의 순서와 원본 좌표를 보존하여 두 기준점 수치를 반환한다."""
    if anchors["kind"] == "holes":
        holes = hole_sources(document)
        rows = [holes.get(identity) for identity in anchors["ids"]]
        if any(row is None for row in rows):
            fail("기록한 홀이 현재 개정에 없습니다.", "anchors", "E_CONFLICT")
        return [hole_center(document, row) for row in rows]
    port = next((row for row in document["ports"] if row["id"] == anchors["ids"][0]), None)
    if port is None or "excitation_box" not in port:
        fail("급전 양단의 실제 좌표를 먼저 지정하세요.", "anchors", "E_CONFLICT")
    return [point(document, port["excitation_box"][key], "port." + key) for key in ("start", "stop")]


def measurement(points):
    """! @brief A에서 B로 향하는 실제 거리, 부호 있는 성분과 방향각을 구한다."""
    delta = [b - a for a, b in zip(*points)]
    planar = math.hypot(*delta[:2])
    distance = math.hypot(*delta)
    return {"points_mm": points, "delta_mm": delta, "distance_mm": distance,
            "azimuth_deg": None if planar <= EPSILON_MM else math.degrees(math.atan2(delta[1], delta[0])),
            "elevation_deg": None if distance <= EPSILON_MM else math.degrees(math.atan2(delta[2], planar))}


def key_for(anchors):
    """! @brief 순서가 뒤집힌 같은 물리 쌍이 중복 저장되는 것을 막는다."""
    return anchors["kind"], tuple(sorted(anchors["ids"]))


def validate(document):
    """! @brief 구동 거리와 살아 있는 기준을 검사하고 빠진 참조는 계속 보존한다."""
    stored = document["extensions"].get(KEY)
    if stored is None:
        return
    _fields(stored, {"schema", "items"}, KEY)
    rows = stored["items"]
    if stored["schema"] != PROFILE or type(rows) is not list or not 1 <= len(rows) <= LIMIT:
        fail("스마트 치수 버전 또는 최대 64개 보존 범위를 확인하세요.", KEY, "E_RESOURCE")
    keys, ids = set(), []
    for row in rows:
        _fields(row, {"id", "name", "anchors", "mode", "target_mm"}, KEY + ".items")
        identity = _uuid(row["id"], KEY + ".id")
        ids.append(identity)
        validate_name(row["name"], KEY + ".name")
        anchors = row["anchors"]
        validate_anchors(anchors)
        key = key_for(anchors)
        if key in keys:
            fail("이 기준 쌍에 이미 스마트 치수가 있습니다.", "anchors", "E_CONFLICT")
        keys.add(key)
        if row["mode"] == "reference" and row["target_mm"] is None:
            continue
        if row["mode"] != "driving":
            fail("참조 또는 구동 치수 모드가 유효하지 않습니다.", "mode", "E_SCHEMA")
        value = number(row["target_mm"], "target_mm")
        if not EPSILON_MM < value <= MAX_COORDINATE_MM:
            fail("구동 길이 범위를 확인하세요.", "target_mm", "E_UNIT")
        try:
            actual = math.dist(*positions(document, anchors))
        except ProjectError as error:
            fail(f"구동 치수 '{row['name']}'의 기준을 유지하세요. {error.message}", "anchors", "E_CONFLICT")
        if not math.isclose(actual, value, abs_tol=EPSILON_MM, rel_tol=0):
            fail(f"구동 치수 '{row['name']}'과 충돌합니다. 스마트 치수에서 값을 바꾸거나 참조로 전환하세요.",
                 "target_mm", "E_CONFLICT")
    if ids != sorted(set(ids)):
        fail("스마트 치수 ID가 중복되거나 원본 정렬이 바뀌었습니다.", KEY + ".items", "E_HASH")


def apply(document, payload):
    """! @brief 치수와 관련 형상을 한 명령으로 교체하고 정확한 역명령을 만든다."""
    _fields(payload, {"id", "expected", "replacement", "pcb_patch"}, "command.payload")
    identity = _uuid(payload["id"], "id")
    rows = dimensions(document)
    old = next((row for row in rows if row["id"] == identity), None)
    new = payload["replacement"]
    if old != payload["expected"] or (new is None and old is None):
        fail("수정할 치수가 검토 이후 바뀌었습니다.", "id", "E_CONFLICT")
    if new is not None and (type(new) is not dict or new.get("id") != identity):
        fail("치수의 안정 ID가 다릅니다.", "id", "E_HASH")
    affected, invalidated, inverse_patch = [], ["revision", "smart_dimensions"], None
    if payload["pcb_patch"] is not None:
        affected, geometry_invalidated, inverse = apply_pcb_command(document, payload["pcb_patch"])
        invalidated.extend(key for key in geometry_invalidated if key not in invalidated)
        inverse_patch = inverse["payload"]
    remaining = [deepcopy(row) for row in rows if row["id"] != identity]
    if new is not None:
        remaining.append(deepcopy(new))
    if remaining:
        document["extensions"][KEY] = {"schema": PROFILE, "items": sorted(remaining, key=lambda row: row["id"])}
    else:
        document["extensions"].pop(KEY, None)
    validate(document)
    inverse = {"type": COMMAND, "payload": {"id": identity, "expected": deepcopy(new),
               "replacement": deepcopy(old), "pcb_patch": inverse_patch}}
    return [identity, *affected], invalidated, inverse
