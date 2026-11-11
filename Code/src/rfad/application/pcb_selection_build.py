"""! @brief 출처 선택과 명시적 입력을 한 번에 적용할 프로젝트 후보로 조립한다."""

from contextlib import nullcontext
from copy import deepcopy

from rfad.application.pcb_selection_contract import local_id, text
from rfad.application.pcb_selection_layers import assemble_layers
from rfad.application.pcb_selection_review import issue, update_ports
from rfad.application.project_contract import _fields, _uuid
from rfad.catalog.material_selection import build_material
from rfad.catalog.selection_reader import SelectionReader
from rfad.catalog.stackup_draft import build_observation_draft, build_stackup_draft
from rfad.domain.errors import ProjectError
from rfad.domain.material_models import LEGACY_MODEL
from rfad.domain.pcb_selection import EXTENSION_KEY, SELECTION_SCHEMA, state_hash
from rfad.domain.pcb_selection_history import preserve_selection_history
from rfad.domain.project import SCHEMA_VERSION


def source_draft(reader, source):
    """! @brief 원시 적층과 명시적 2층 관측의 서로 다른 변환 경로를 구분한다."""
    if source is None:
        return None
    if source["entity"] == "native_templates":
        return build_stackup_draft(reader, source["id"])
    return build_observation_draft(reader, source["id"])


def materials_from_specs(document, selection_id, spec, reader):
    """! @brief 기존 재료를 보존하고 명시한 기존 ID 또는 새 안정 ID에 선택을 적용한다."""
    materials = {item["id"]: deepcopy(item) for item in document["materials"]}
    mapping = spec.get("material_ids", {})
    keys, used, decisions, issues = {}, set(), [], []
    for item in spec["materials"]:
        _fields(item, {"key", "name", "properties", "validity_hz"}, {"model", "model_reason"})
        key = text(item["key"], "materials.key", maximum=128)
        if key in keys:
            raise ProjectError("E_SCHEMA", "선택 재료 key가 중복됩니다.")
        identity = mapping.get(key, local_id(selection_id, "material", key))
        if key in mapping:
            _uuid(identity)
            if identity not in materials:
                raise ProjectError("E_SCHEMA", "기존 재료 대응 ID가 없습니다.")
        elif identity in materials:
            raise ProjectError("E_CONFLICT", "이미 사용한 선택 ID입니다. 새 ID 또는 기존 재료 대응을 명시하십시오.")
        if identity in used:
            raise ProjectError("E_SCHEMA", "하나의 재료를 여러 선택에 대응할 수 없습니다.")
        if identity in materials and materials[identity]["model"] != LEGACY_MODEL and "model" not in item:
            raise ProjectError("E_SCHEMA", "기존 재료의 손실 모델과 선택 이유를 명시하십시오. 기본 모델로 자동 변경하지 않습니다.")
        selected = build_material({**item, "id": identity}, reader)
        materials[identity] = selected["material"]
        decisions.extend(selected["decisions"])
        issues.extend(selected["issues"])
        keys[key] = identity
        used.add(identity)
    if mapping.keys() - keys.keys():
        raise ProjectError("E_SCHEMA", "재료 UUID 대응에 선택하지 않은 key가 있습니다.")
    return sorted(materials.values(), key=lambda item: item["id"]), keys, decisions, issues


def compose(document, data, database):
    """! @brief 단일 카탈로그 읽기 개정에서 출처 사본과 후보 상태를 결정적으로 만든다."""
    spec, selection_id = data["specification"], data["selection_id"]
    source = spec["source"]
    catalog_id = spec.get("catalog_id") if source is None else source["catalog_id"]
    context = nullcontext(None) if catalog_id is None else SelectionReader(database, catalog_id)
    with context as reader:
        draft = source_draft(reader, source)
        materials, keys, decisions, issues = materials_from_specs(document, selection_id, spec, reader)
        stackup, layer_decisions = assemble_layers(document, selection_id, spec, draft, keys, materials)
        decisions.extend(layer_decisions)
        ports, port_decisions, updated_ports = update_ports(document, spec.get("port_updates", []))
        decisions.extend(port_decisions)
        notes = list(spec.get("notes", []))
        if "layers" in spec:
            notes.append(spec["layout_reason"])
        if draft is not None:
            for source_issue in draft["issues"]:
                copied = dict(source_issue)
                if "layers" in spec and copied["severity"] == "blocker":
                    copied.update(severity="warning", resolution="explicit_user_layout")
                issues.append(copied)
            if not stackup:
                issues.append(issue("layer_layout_required", "자동 변환할 전체 층 구성이 없습니다. layers와 layout_reason을 명시하십시오.", blocker=True))
        candidate = deepcopy(document)
        candidate.update(schema_version=SCHEMA_VERSION, materials=materials, stackup=stackup, ports=ports)
        selection = {"schema": SELECTION_SCHEMA, "id": selection_id,
                     "catalog": None if reader is None else reader.catalog(),
                     "evidence": [] if reader is None else reader.evidence,
                     "decisions": decisions, "applied_state_sha256": state_hash(candidate), "notes": notes}
        selection = preserve_selection_history(document, candidate, selection)
        candidate["extensions"][EXTENSION_KEY] = selection
        payload = {key: candidate[key] for key in ("materials", "stackup", "ports")}
        payload["selection"] = selection
        return {"candidate": candidate, "payload": payload, "source_draft": draft, "issues": issues,
                "updated_ports": updated_ports}
