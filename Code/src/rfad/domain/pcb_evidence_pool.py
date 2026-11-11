"""! @brief 여러 선택이 공유하는 출처를 프로젝트 내부의 한 사본으로 보존한다."""

from copy import deepcopy

from rfad.domain.pcb_selection_evidence import encoded, fail
from rfad.domain.resource_limits import MAX_EVIDENCE_BYTES, MAX_EVIDENCE_ITEMS


POOL_SCHEMA = "rfad.pcb-selection/0.2"
LEGACY_SCHEMA = "rfad.pcb-selection/0.1"


def expand_selection(value):
    """! @brief 저장된 공유 근거를 검증용 독립 사본으로 복원하며 원본은 변경하지 않는다."""
    if type(value) is not dict or value.get("schema") != POOL_SCHEMA:
        return deepcopy(value)
    pool = value.get("evidence_pool")
    if type(pool) is not list or len(pool) > MAX_EVIDENCE_ITEMS:
        fail("E_RESOURCE", "공유 출처 목록의 상한을 초과했습니다.", "selection.evidence_pool")
    if len(encoded(pool).encode("utf-8")) > MAX_EVIDENCE_BYTES:
        fail("E_RESOURCE", "공유 출처의 128 KiB 예산을 초과했습니다.", "selection.evidence_pool")
    entries = {}
    for entry in pool:
        if type(entry) is not dict or type(entry.get("id")) is not str or entry["id"] in entries:
            fail("E_HASH", "공유 출처 ID가 없거나 중복됩니다.", "selection.evidence_pool")
        entries[entry["id"]] = entry
    history = value.get("history", [])
    if type(history) is not list or len(history) > 32:
        fail("E_RESOURCE", "선택 이력 목록의 상한을 초과했습니다.", "selection.history")
    result = deepcopy(value)
    result.pop("evidence_pool")
    records = [result, *result.get("history", [])]
    used = set()
    for index, record in enumerate(records):
        if type(record) is not dict or (index and record.get("schema") != LEGACY_SCHEMA):
            fail("E_VERSION", "공유 근거 선택 이력의 버전이 올바르지 않습니다.", "selection.history")
        identities = record.get("evidence")
        if type(identities) is not list or len(identities) > MAX_EVIDENCE_ITEMS:
            fail("E_RESOURCE", "공유 출처 참조의 상한을 초과했습니다.", "selection.evidence")
        if any(type(identity) is not str or identity not in entries for identity in identities):
            fail("E_HASH", "프로젝트 안에 참조한 출처 사본이 없습니다.", "selection.evidence")
        if len(identities) != len(set(identities)):
            fail("E_HASH", "선택의 공유 출처 참조가 중복됩니다.", "selection.evidence")
        used.update(identities)
        record["schema"] = LEGACY_SCHEMA
        record["evidence"] = [deepcopy(entries[identity]) for identity in identities]
    if used != entries.keys():
        fail("E_SCHEMA", "사용하지 않는 공유 출처 사본이 있습니다.", "selection.evidence_pool")
    return result


def pool_selection(value):
    """! @brief 큰 선택에서 실제 중복이 있을 때만 0.2 공유 저장 형식으로 전환한다."""
    if len(encoded(value).encode("utf-8")) <= 32 * 1024:
        return value
    result = expand_selection(value)
    entries = {}
    for record in [result, *result.get("history", [])]:
        identities = []
        for entry in record["evidence"]:
            identity = entry["id"]
            if identity in entries and entries[identity] != entry:
                fail("E_HASH", "같은 ID의 출처 사본이 서로 다릅니다.", "selection.evidence")
            entries[identity] = entry
            identities.append(identity)
        record["evidence"] = identities
    result["schema"] = POOL_SCHEMA
    result["evidence_pool"] = list(entries.values())
    return result if len(encoded(result)) < len(encoded(value)) else value
