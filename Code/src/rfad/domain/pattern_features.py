"""! @brief 반복 배치의 원본, 배치 순번과 사본 UUID를 영속 편집 이력으로 연결한다."""

from uuid import UUID, uuid5

from rfad.application.canonical import canonical_hash
from rfad.domain.object_names import allocate_name
from rfad.domain.precision_command import EXTENSION_KEY
from rfad.domain.precision_transform import MAX_SELECTION, fail, number, transform


PATTERNS = {"linear_pattern", "circular_pattern"}
REGENERATE = {"edit_linear_pattern": "linear_pattern", "edit_circular_pattern": "circular_pattern"}


def generate(document, rows, operation, values, origin_id, names=None):
    """! @brief 원본을 유지하면서 각 배치의 복사 ID와 비아 패드 대응을 함께 만든다."""
    count = number(values["count"], "count")
    if not count.is_integer() or not 2 <= count <= MAX_SELECTION // len(rows):
        fail("반복 수는 원본을 포함한 정수이며, 결과 객체는 전체 16개 이하여야 합니다.", "count", "E_RESOURCE")
    count = int(count)
    linear = operation == "linear_pattern"
    if linear:
        x, y = (number(values[key], key) for key in ("dx_mm", "dy_mm"))
        if x == y == 0:
            fail("반복 피치를 지정하십시오.", "dx_mm", "E_CONFLICT")
    else:
        step = number(values["step_deg"], "step_deg")
        if not 0 < abs(step) < 360:
            fail("원형 반복 간격의 절댓값은 0보다 크고 360도보다 작아야 합니다.", "step_deg", "E_SCHEMA")
        angles = sorted((step * index) % 360 for index in range(count))
        if any(b - a <= 1e-10 for a, b in zip(angles, angles[1:] + [angles[0] + 360])):
            fail("반복한 회전 위치가 겹칩니다. 개수나 간격을 조정하십시오.", "step_deg", "E_CONFLICT")
    output = list(rows)
    used_names = [row["name"] for row in document["geometry"] if "name" in row]
    by_source = {row["id"]: {canonical_hash(row)} for row in rows}
    for index in range(1, count):
        copied_ids = {row["id"]: str(uuid5(UUID(origin_id), f"pattern:{index}:{row['id']}")) for row in rows}
        transform_values = ({"dx_mm": x * index, "dy_mm": y * index} if linear else
                            {"pivot_x_mm": values["pivot_x_mm"], "pivot_y_mm": values["pivot_y_mm"], "angle_deg": step * index})
        for row in rows:
            copied = transform(document, row, "translate" if linear else "rotate", transform_values)
            digest = canonical_hash(copied)
            if digest in by_source[row["id"]]:
                fail("반복해도 기존과 같은 위치와 형상이 있습니다.", "selection_ids", "E_CONFLICT")
            by_source[row["id"]].add(digest)
            copied["id"] = copied_ids[row["id"]]
            if "pad_ids" in copied:
                copied["pad_ids"] = [copied_ids[key] for key in copied["pad_ids"]]
            copied["name"] = (names or {}).get(copied["id"]) or allocate_name(document, copied, reserved=used_names)
            used_names.append(copied["name"])
            output.append(copied)
    return output


def features(document):
    """! @brief 생성 기록과 이어진 편집 기록에서 마지막 반복 설정을 복원한다."""
    records = document["extensions"].get(EXTENSION_KEY, {}).get("records", [])
    successors = {}
    for row in records:
        parent = row["engine"].get("pattern_parent")
        if row["operation"] in {*REGENERATE, "detach_pattern"} and parent is not None:
            if type(parent) is not str or parent in successors:
                fail("반복 편집 이력에서 이전 설정을 하나로 정할 수 없습니다.", "precision_origin", "E_CONFLICT")
            successors[parent] = row
    active = {}
    for root in records:
        if root["operation"] not in PATTERNS:
            continue
        current = root
        seen = set()
        while current["id"] in successors:
            if current["id"] in seen:
                fail("반복 편집 이력에 순환 참조가 있습니다.", "precision_origin", "E_CONFLICT")
            seen.add(current["id"])
            current = successors[current["id"]]
        if current["operation"] == "detach_pattern":
            continue
        active[root["id"]] = {"root": root, "head": current, "kind": root["operation"],
                              "linked": current["engine"].get("linked_pattern") is True}
    return active


def match(document, rows, operation):
    """! @brief 한 반복에 속한 선택만 받으며 중복 소속이면 고유한 사본을 요구한다."""
    chosen = {row["id"] for row in rows}
    candidates = [feature for feature in features(document).values()
                  if (operation == "detach_pattern" or feature["kind"] == REGENERATE[operation])
                  and chosen <= {row["id"] for row in feature["head"]["after"]}]
    if len(candidates) != 1:
        fail("편집할 반복에 속한 고유한 사본을 선택하세요.", "selection_ids", "E_CONFLICT")
    return candidates[0]


def _guard_terminals(document, changed, objects):
    """! @brief 외부 급전과 연결 관계에 쓰이는 사본의 물리 위치를 보호한다."""
    if any(changed & {port["positive_geometry_id"], port["reference_geometry_id"]} for port in document["ports"]):
        fail("변경할 반복 사본에 급전 단자가 연결되어 있습니다. 해당 단자 연결을 먼저 확인하세요.", "ports", "E_CONFLICT")
    if any(changed & set(row["object_ids"]) for row in document["connections"]):
        fail("변경할 반복 사본에 기대 연결이 있습니다. 해당 연결을 먼저 확인하세요.", "connections", "E_CONFLICT")
    if any(row["id"] not in objects and changed & set(row.get("pad_ids", [])) for row in document["geometry"]):
        fail("다른 비아가 사용하는 반복 패드를 변경할 수 없습니다.", "geometry", "E_CONFLICT")


def regenerate(document, feature, values, rows):
    """! @brief 현재 원본에서 같은 순번의 사본 ID와 이름을 유지하며 배치를 다시 만든다."""
    current = {row["id"]: row for row in rows}
    root = feature["root"]
    seeds = root["selection_ids"]
    names = {key: row.get("name") for key, row in current.items() if key not in seeds}
    output = generate(document, [current[key] for key in seeds], feature["kind"], values, root["id"], names)
    by_id = {row["id"]: row for row in output}
    changed = {key for key in current if key not in seeds and by_id.get(key) != current[key]}
    _guard_terminals(document, changed, set(current))
    return output


def editing(document, rows, operation, values):
    """! @brief 현재 반복의 전후 형상과 이전 기록 포인터를 함께 만든다."""
    feature = match(document, rows, operation)
    geometry = {row["id"]: row for row in document["geometry"]}
    old = feature["head"]["after"]
    if any(row["id"] not in geometry for row in old):
        fail("반복에 포함된 원본 또는 사본이 삭제되었습니다.", "selection_ids", "E_CONFLICT")
    expected = [geometry[row["id"]] for row in old]
    if operation == "detach_pattern":
        output = expected
    else:
        if not feature["linked"]:
            seeds = feature["root"]["selection_ids"]
            if any(a["id"] not in seeds and a != b for a, b in zip(expected, old)):
                fail("과거 독립 복사본이 따로 편집되었습니다. 원본 출처를 보존합니다.", "selection_ids", "E_CONFLICT")
        output = regenerate(document, feature, values, expected)
    return expected, output, {"name": "rfad.precision", "version": "0.1", "available": True, "reason": "",
                              "linked_pattern": operation != "detach_pattern", "pattern_parent": feature["head"]["id"]}


def propagate(before, after):
    """! @brief 일반 편집 및 역명령 뒤에 연관 사본을 갱신하고 중첩된 반복은 의존 순서로 평가한다."""
    prior = features(before)
    if not prior:
        return []
    common = {key: value for key, value in features(after).items() if key in prior and value["linked"]
              and value["head"]["id"] == prior[key]["head"]["id"]}
    if not common:
        return []
    old = {row["id"]: row for row in before["geometry"]}
    geometry = {row["id"]: row for row in after["geometry"]}
    changed = []
    pending = dict(common)
    derived = {key: {r["id"] for r in feature["head"]["after"]} - set(feature["root"]["selection_ids"])
               for key, feature in common.items()}
    while pending:
        ready = [key for key, feature in pending.items() if not any(
            parsed != key and set(feature["root"]["selection_ids"]) & derived[parsed] for parsed in pending)]
        if not ready:
            fail("반복 원본 사이에 순환 의존성이 있습니다.", "selection_ids", "E_CONFLICT")
        for key in ready:
            feature = pending.pop(key)
            members = [row["id"] for row in feature["head"]["after"]]
            seeds = feature["root"]["selection_ids"]
            if any(identity not in geometry or identity not in old for identity in members):
                fail("반복의 일부를 삭제하려면 먼저 반복 연결을 해제하세요.", "selection_ids", "E_CONFLICT")
            if any({k: v for k, v in old[identity].items() if k != "name"}
                   != {k: v for k, v in geometry[identity].items() if k != "name"} for identity in derived[key]):
                fail("연결된 사본의 형상은 반복 원본 또는 반복 설정에서 편집하세요.", "selection_ids", "E_CONFLICT")
            if any(old[identity] != geometry[identity] for identity in seeds):
                output = regenerate(after, feature, feature["head"]["values"], [geometry[identity] for identity in members])
                for row in output:
                    if row != geometry[row["id"]]:
                        changed.append(row["id"])
                        geometry[row["id"]] = row
    if changed:
        after["geometry"] = [geometry[row["id"]] for row in after["geometry"]]
    return changed
