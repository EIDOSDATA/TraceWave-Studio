"""! @brief 현재 설계가 참조하는 과거 PCB 선택 사본을 중첩 없이 보존한다."""

from copy import deepcopy

from rfad.domain.pcb_selection import EXTENSION_KEY, validate_selection
from rfad.domain.pcb_selection_evidence import fail


def _source_references(candidate: dict) -> set[str]:
    """! @brief 실제 재료/층/포트 안의 증거 참조만 찾으며 원문 문자열은 해석하지 않는다."""
    references = set()
    pending = [candidate[key] for key in ("materials", "stackup", "ports")]
    while pending:
        value = pending.pop()
        if type(value) is dict:
            refs = value.get("source_refs", [])
            if type(refs) is list:
                references.update(item for item in refs if type(item) is str and item.startswith("evidence:"))
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)
    return references


def preserve_selection_history(document: dict, candidate: dict, new_selection: dict) -> dict:
    """! @brief 새 선택이 대체하지 않은 출처를 가진 과거 선택만 독립 사본으로 돌려준다.

    @param document 적용 전 프로젝트이며 기존 선택과 이력을 제공한다.
    @param candidate 적용할 재료/층/포트 목록을 가진 후보 프로젝트이다.
    @param new_selection 이번 적용의 출처와 채택 기록이며 이력은 호출자가 만들지 않는다.
    @return 살아 있는 출처의 과거 선택을 포함한 새 사본이다. 입력 객체는 변경하지 않는다.
    """
    if "history" in new_selection:
        fail("E_SCHEMA", "새 PCB 선택 이력은 기존 프로젝트에서만 구성합니다.", "selection.history")
    validate_selection(new_selection)
    result = deepcopy(new_selection)
    missing = _source_references(candidate) - {item["id"] for item in result["evidence"]}
    previous = document["extensions"].get(EXTENSION_KEY)
    history = []
    if previous is not None:
        validate_selection(previous)
        records = [{key: value for key, value in previous.items() if key != "history"}, *previous.get("history", [])]
        for record in records:
            supplied = {item["id"] for item in record["evidence"]}
            if missing & supplied:
                history.append(deepcopy(record))
                missing -= supplied
    if missing:
        fail("E_SCHEMA", "현재 설계의 PCB 출처 참조에 대응하는 프로젝트 소유 사본이 없습니다.", "selection.history")
    if history:
        result["history"] = history
    validate_selection(result)
    return result
