"""! @brief PCB 적층과 채택 출처를 하나의 검증된 원자 명령으로 교체한다."""

from copy import deepcopy

from rfad.domain.design import _normalize_quantities, validate_design
from rfad.domain.pcb_selection import EXTENSION_KEY, validate_project_selection
from rfad.domain.pcb_selection_evidence import encoded, fail, fields


def _ports(original: list, replacement: list) -> None:
    """! @brief 기존 포트의 ID와 의미는 보존하고 명시적 급전 좌표만 바꾼다."""
    before = {item["id"]: item for item in original}
    after = {item["id"]: item for item in replacement}
    if before.keys() != after.keys():
        fail("E_PORT", "적층 적용에서 포트를 생성하거나 제거할 수 없습니다.", "command.payload.ports")
    for identity, port in before.items():
        old = {key: value for key, value in port.items() if key != "excitation_box"}
        new = {key: value for key, value in after[identity].items() if key != "excitation_box"}
        if encoded(old) != encoded(new):
            fail("E_PORT", "적층 적용은 기존 포트의 급전 좌표만 변경할 수 있습니다.", "ports." + identity)


def apply_stackup_command(document: dict, payload: object) -> tuple[list[str], list[str], dict]:
    """! @brief 전체 후보 검증에 성공한 경우에만 전달된 복사본을 바꾸고 역명령을 만든다."""
    fields(payload, {"materials", "stackup", "ports", "selection"}, "command.payload")
    candidate = deepcopy(document)
    previous = {key: deepcopy(document[key]) for key in ("materials", "stackup", "ports")}
    previous["selection"] = deepcopy(document["extensions"].get(EXTENSION_KEY))
    for key in ("materials", "stackup", "ports"):
        candidate[key] = _normalize_quantities(payload[key])
    if payload["selection"] is None:
        candidate["extensions"].pop(EXTENSION_KEY, None)
    else:
        candidate["extensions"][EXTENSION_KEY] = deepcopy(payload["selection"])
    validate_design(candidate)
    validate_project_selection(candidate)
    _ports(document["ports"], candidate["ports"])
    changed = []
    for collection in ("materials", "stackup", "ports"):
        old = {item["id"]: item for item in document[collection]}
        new = {item["id"]: item for item in candidate[collection]}
        changed.extend(identity for identity in sorted(old.keys() | new.keys()) if old.get(identity) != new.get(identity))
    if document["extensions"].get(EXTENSION_KEY) != candidate["extensions"].get(EXTENSION_KEY):
        changed.append(document["project_id"])
    document.clear()
    document.update(candidate)
    return changed, ["revision", "geometry", "physics", "network", "metrics", "assessment", "exports"], {
        "type": "pcb_stackup.apply", "payload": previous,
    }
