"""! @brief 명시적인 층 선택과 사용자 두께로 프로젝트 적층을 구성한다."""

from copy import deepcopy

from rfad.application.project_contract import _fields, _uuid
from rfad.application.pcb_selection_contract import local_id, number, text
from rfad.catalog.models import canonical_json
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity


def decision(identity, field, value, basis, reason, *, collection="stackup", evidence_id=None, pointer=None):
    """! @brief 실제 채택 값과 원문 근거를 별도의 적용 당시 기록으로 남긴다."""
    return {"target": {"collection": collection, "id": identity, "field": field}, "basis": basis,
            "evidence_id": evidence_id, "source_pointer": pointer, "value_json": canonical_json(value), "reason": reason}


def length(value, *, status="user_entered", references=()):
    """! @brief mm 입력을 SI로 한 번만 환산하며 미정값은 유지한다."""
    if value is None:
        return Quantity(None, "length", "mm", "missing", references).to_dict()
    return Quantity.from_value(value, "mm", status=status, source_refs=references).to_dict()


def manual_layers(values, reason):
    """! @brief 사용자가 완전히 지정한 아래에서 위 방향의 층 목록을 검증한다."""
    text(reason, "layout_reason", maximum=1024)
    if type(values) is not list or not 1 <= len(values) <= 32:
        raise ProjectError("E_RESOURCE", "직접 정의한 적층은 1~32개 층이어야 합니다.")
    rows = []
    for item in values:
        _fields(item, {"key", "name", "role", "thickness_mm"})
        key = text(item["key"], "layers.key", maximum=128)
        text(item["name"], "layers.name")
        if item["role"] not in ("conductor", "dielectric", "coating", "adhesive", "air"):
            raise ProjectError("E_UNSUPPORTED", "지원하지 않는 층 역할입니다.")
        thickness = number(item["thickness_mm"], "layers.thickness_mm", positive=True, nullable=True)
        rows.append({**item, "key": key, "thickness_mm": thickness, "status": "user_entered",
                     "thickness_basis": reason, "evidence_ids": [], "thickness_source_pointer": None,
                     "thickness_evidence_id": None})
    return rows


def assign_materials(layers, assignments, material_keys, materials):
    """! @brief 새 재료 key 또는 명시적 기존 UUID만 층에 연결한다."""
    keys = {key for key, _ in layers}
    if assignments.keys() - keys:
        raise ProjectError("E_SCHEMA", "존재하지 않는 층에 재료를 지정했습니다.")
    valid = {item["id"] for item in materials}
    for key, layer in layers:
        if key not in assignments:
            continue
        target = assignments[key]
        if target is not None:
            text(target, "material_assignments")
            target = material_keys.get(target, target)
            if target not in valid:
                raise ProjectError("E_SCHEMA", "재료 대응에 존재하지 않는 ID가 있습니다.")
        layer["material_id"] = target


def assemble_layers(document, selection_id, spec, draft, material_keys, materials):
    """! @brief 기존 외형/패턴을 유지하고 명시적으로 대응한 층 UUID만 재사용한다."""
    decisions = []
    overrides = spec.get("thickness_overrides", {})
    mapping = spec.get("layer_ids", {})
    existing = {item["id"]: item for item in document["stackup"]}
    if "layers" in spec:
        rows = manual_layers(spec["layers"], spec.get("layout_reason"))
    elif draft is not None:
        rows = deepcopy(draft["layers"])
    else:
        if overrides or mapping or "z_origin_mm" in spec:
            raise ProjectError("E_SCHEMA", "기존 적층의 두께/원점을 바꾸려면 전체 층 목록을 명시하십시오.")
        layers = [(item["id"], deepcopy(item)) for item in document["stackup"]]
        assign_materials(layers, spec.get("material_assignments", {}), material_keys, materials)
        for _, layer in layers:
            old = existing[layer["id"]]
            if old["material_id"] != layer["material_id"]:
                decisions.append(decision(layer["id"], "material_id", layer["material_id"],
                                          "missing" if layer["material_id"] is None else "user_override",
                                          "기존 층의 재료를 명시적으로 선택함"))
        return [layer for _, layer in layers], decisions
    keys = [text(item["key"], "layer.key", maximum=128) for item in rows]
    if len(keys) != len(set(keys)):
        raise ProjectError("E_SCHEMA", "적층 key가 중복됩니다.")
    if overrides.keys() - set(keys) or mapping.keys() - set(keys):
        raise ProjectError("E_SCHEMA", "두께 또는 UUID 대응의 층 key가 없습니다.")
    for identity in mapping.values():
        _uuid(identity)
    if len(set(mapping.values())) != len(mapping):
        raise ProjectError("E_SCHEMA", "하나의 기존 층을 여러 층에 대응시킬 수 없습니다.")
    z = length(number(spec.get("z_origin_mm", 0), "z_origin_mm"))["value_si"]
    result = []
    for order, item in enumerate(rows):
        key = item["key"]
        identity = mapping.get(key, local_id(selection_id, "layer", key))
        if key in mapping:
            _uuid(identity)
            if identity not in existing or existing[identity]["role"] != item["role"]:
                raise ProjectError("E_SCHEMA", "기존 층 UUID는 같은 역할의 층에 명시적으로 대응해야 합니다.")
        elif identity in existing:
            raise ProjectError("E_CONFLICT", "이 선택 ID로 이미 만든 층입니다. 새 선택 ID 또는 명시적 대응을 사용하십시오.")
        value = number(item["thickness_mm"], "thickness_mm", positive=True, nullable=True)
        evidence = item.get("thickness_evidence_id")
        pointer = item.get("thickness_source_pointer")
        basis = "published" if item["status"] == "source_value" else "user_assumption"
        reason = item["thickness_basis"]
        status = "source_default" if basis == "published" else "user_entered"
        if key in overrides:
            override = _fields(overrides[key], {"value_mm", "reason"})
            value = number(override["value_mm"], "thickness_overrides.value_mm", positive=True, nullable=True)
            reason = text(override["reason"], "thickness_overrides.reason", maximum=1024)
            basis, status = "user_override", "user_entered"
        if value is None:
            basis = "missing"
        thickness = length(value, status=status, references=() if evidence is None else (evidence,))
        layer = {"id": identity, "name": item["name"], "role": item["role"], "order": order,
                 "z_min": Quantity(z, "length", "mm", "missing" if z is None else "user_entered").to_dict(),
                 "thickness": thickness,
                 "material_id": existing[identity]["material_id"] if identity in existing else None}
        decisions.append(decision(identity, "thickness", thickness, basis, reason,
                                  evidence_id=evidence, pointer=pointer))
        decisions.append(decision(identity, "z_min", layer["z_min"], "missing" if z is None else "user_assumption",
                                  "명시한 아래쪽 원점과 아래 층 두께의 누적 합. 미정 두께 이후 위치는 미정."))
        result.append((key, layer))
        # @brief 접면은 원본 SI 두께로 누적하여 mm 왕복 환산의 가짜 층 중첩을 막는다.
        z = None if z is None or value is None else number(z + thickness["value_si"], "accumulated_z_si")
    assign_materials(result, spec.get("material_assignments", {}), material_keys, materials)
    for _, layer in result:
        decisions.append(decision(layer["id"], "material_id", layer["material_id"],
                                  "missing" if layer["material_id"] is None else "user_assumption", "층별 재료를 명시적으로 대응함"))
    return [layer for _, layer in result], decisions
