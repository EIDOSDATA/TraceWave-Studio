"""! @brief 생성 객체와 출처 사본만 한 개정에서 적용/복원하는 내부 명령을 제공한다."""

from copy import deepcopy

from rfad.domain.design import _fail, _fields, _uuid
from rfad.domain.template_geometry import all_ids
from rfad.domain.template_instance import (EXTENSION_KEY, ORIGIN_SCHEMA, OBJECT_COLLECTIONS,
                                           validate_record, validate_template_origins)


INTERNAL_COMMANDS = ("template_instance.apply",)


def apply_template_command(document: dict, payload: dict) -> tuple[list[str], list[str], dict]:
    """! @brief 정확한 사본을 역명령에 보존하고 현재 라이브러리로 다시 생성하지 않는다."""
    _fields(payload, {"instance_id", "expected_instance_hash", "replacement"}, "command.payload")
    identity = _uuid(payload["instance_id"], "command.payload.instance_id")
    instances = document["extensions"].get(EXTENSION_KEY, {"instances": []})["instances"]
    previous = next((item for item in instances if item["id"] == identity), None)
    expected = None if previous is None else previous["record_hash"]
    if payload["expected_instance_hash"] != expected:
        _fail("E_CONFLICT", "복원할 템플릿 출처 사본이 현재 상태와 다릅니다.", "command.payload.expected_instance_hash")
    replacement = payload["replacement"]
    if replacement is not None:
        validate_record(replacement)
        if replacement["id"] != identity:
            _fail("E_CONFLICT", "템플릿 인스턴스 ID가 사본과 다릅니다.", "command.payload.instance_id")
    elif previous is None:
        _fail("E_CONFLICT", "제거할 템플릿 인스턴스가 없습니다.", "command.payload.instance_id")
    candidate = deepcopy(document)
    changed = []
    if previous is not None:
        for name in OBJECT_COLLECTIONS:
            source = previous["objects"][name]
            objects = source if name == "parameters" else {item["id"]: item for item in source}
            current = candidate[name] if name == "parameters" else {item["id"]: item for item in candidate[name]}
            for object_id, original in objects.items():
                if current.get(object_id) != original:
                    _fail("E_CONFLICT", "생성 후 편집한 객체를 먼저 undo해야 템플릿을 복원할 수 있습니다.", name + "." + object_id)
            changed.extend(objects)
            if name == "parameters":
                candidate[name] = {key: value for key, value in candidate[name].items() if key not in objects}
            else:
                candidate[name] = [item for item in candidate[name] if item["id"] not in objects]
    if replacement is not None:
        used = all_ids(candidate)
        if identity in used:
            _fail("E_CONFLICT", "템플릿 인스턴스 UUID가 현재 객체와 충돌합니다.", "instance_id")
        for name in OBJECT_COLLECTIONS:
            source = replacement["objects"][name]
            ids = set(source if name == "parameters" else (item["id"] for item in source))
            if ids & used:
                _fail("E_CONFLICT", "생성 객체 UUID가 기존 객체와 충돌합니다.", name)
            used.update(ids)
            changed.extend(sorted(ids))
            if name == "parameters":
                candidate[name].update(deepcopy(source))
            else:
                candidate[name] = sorted([*candidate[name], *deepcopy(source)], key=lambda item: item["id"])
    remaining = [deepcopy(item) for item in instances if item["id"] != identity]
    if replacement is not None:
        remaining.append(deepcopy(replacement))
    if remaining:
        candidate["extensions"][EXTENSION_KEY] = {"schema": ORIGIN_SCHEMA, "instances": sorted(remaining, key=lambda item: item["id"])}
    else:
        candidate["extensions"].pop(EXTENSION_KEY, None)
    validate_template_origins(candidate)
    document.clear()
    document.update(candidate)
    inverse = {"type": "template_instance.apply", "payload": {"instance_id": identity,
               "expected_instance_hash": None if replacement is None else replacement["record_hash"], "replacement": deepcopy(previous)}}
    return list(dict.fromkeys(changed)), ["revision", "geometry", "physics", "network", "metrics", "assessment", "exports"], inverse
