"""! @brief 구리면 정의와 파생 섬의 소유권 및 정확한 취소용 기하 목록을 관리한다."""

from copy import deepcopy
from uuid import UUID, uuid5

from rfad.application.canonical import canonical_hash
from rfad.domain.precision_transform import MAX_SELECTION, fail


KEY = "rfad.copper-islands"
SCHEMA = "rfad.copper-islands/0.1"
REPLAY = "pcb.copper-pour.replay"


def slots(owner):
    """! @brief 원본을 포함해 한 채움 정의에 예약된 최대 16개 슬롯 ID를 반환한다."""
    return [owner, *(str(uuid5(UUID(owner), "copper-island:" + str(index))) for index in range(1, MAX_SELECTION))]


def members(document, owner):
    """! @brief 과거 단일 섬 문서에서는 원래 영역 ID만 반환한다."""
    return document["extensions"].get(KEY, {}).get("owners", {}).get(owner, [owner])


def owner_of(document, identity):
    """! @brief 파생된 동박 조각을 선택해도 해당 채움 정의를 찾는다."""
    for owner, ids in document["extensions"].get(KEY, {}).get("owners", {}).items():
        if identity in ids:
            return owner
    return identity


def store(document, owner, ids):
    """! @brief 소유권을 기록하고 마지막 정의의 해제 때 확장을 제거한다."""
    owners = dict(document["extensions"].get(KEY, {}).get("owners", {}))
    if ids is None:
        owners.pop(owner, None)
    else:
        owners[owner] = ids
    if owners:
        document["extensions"][KEY] = {"schema": SCHEMA, "owners": owners}
    else:
        document["extensions"].pop(KEY, None)


def validate(document, active):
    """! @brief 저장 시 엔진을 실행하지 않고 정의, 결정적 슬롯과 넷/층 소유권을 대조한다."""
    data = document["extensions"].get(KEY)
    expected = {key for key, row in active.items() if row["engine"].get("island_scheme") == 1}
    if data is None and not expected:
        return
    if type(data) is not dict or set(data) != {"schema", "owners"} or data["schema"] != SCHEMA or type(data["owners"]) is not dict:
        fail("구리 섬 소유권 기록을 확인하세요.", KEY, "E_SCHEMA")
    owners = data["owners"]
    if not expected <= owners.keys() or not owners.keys() <= active.keys():
        fail("구리 섬에 연결된 채움 정의가 다릅니다.", KEY, "E_CONFLICT")
    geometry = {row["id"]: row for row in document["geometry"]}
    claimed = set()
    for owner, ids in owners.items():
        if (type(ids) is not list or not 1 <= len(ids) <= MAX_SELECTION or any(type(key) is not str for key in ids)
                or ids[0] != owner or len(ids) != len(set(ids)) or claimed.intersection(ids)
                or not set(ids) <= set(slots(owner)) or not set(ids) <= geometry.keys()):
            fail("구리 섬 ID 또는 소유권이 현재 도체와 다릅니다.", KEY, "E_CONFLICT")
        claimed.update(ids)
        base = geometry[owner]
        for key in ids:
            if geometry[key]["kind"] != "planar_region" or any(geometry[key][p] != base[p] for p in ("frame_id", "layer_id", "net_id", "role", "material_ref", "include_in_em", "include_in_export")):
                fail("구리 섬의 넷, 층, 기준면 또는 속성이 채움 정의와 다릅니다.", KEY, "E_CONFLICT")


def snapshot(document, owner):
    """! @brief 위상 변경 이력에는 실제 저장된 섬과 소유권 상태를 정확히 보존한다."""
    by_id = {row["id"]: row for row in document["geometry"]}
    ids = members(document, owner)
    defined = owner in document["extensions"].get(KEY, {}).get("owners", {})
    return {"registered": defined, "rows": [deepcopy(by_id[key]) for key in ids]}


def restore(before, after, patches):
    """! @brief 검증된 내부 역명령의 원본과 목표를 비교한 뒤 과거 슬롯 배치를 복원한다."""
    ids = []
    inverse = []
    for patch in patches:
        owner = patch["owner"]
        old = snapshot(before, owner)
        if canonical_hash(old) != patch["expected"]:
            fail("구리면 재생성 이력이 현재 형상과 다릅니다.", KEY, "E_CONFLICT")
        desired = patch["desired"]
        rows = desired["rows"]
        old_ids = {row["id"] for row in old["rows"]}
        new_ids = [row["id"] for row in rows]
        if not new_ids or new_ids[0] != owner or not set(new_ids) <= set(slots(owner)) or len(set(new_ids)) != len(new_ids):
            fail("다른 정의의 동박을 복원할 수 없습니다.", KEY, "E_CONFLICT")
        keep = [row for row in after["geometry"] if row["id"] not in old_ids]
        if {row["id"] for row in keep} & set(new_ids):
            fail("복원할 구리 섬 ID가 다른 객체와 겹칩니다.", KEY, "E_CONFLICT")
        after["geometry"] = sorted([*keep, *deepcopy(rows)], key=lambda row: row["id"])
        store(after, owner, new_ids if desired["registered"] else None)
        ids.extend(sorted(old_ids | set(new_ids)))
        inverse.append({"owner": owner, "expected": canonical_hash(desired), "desired": old})
    return ids, inverse
