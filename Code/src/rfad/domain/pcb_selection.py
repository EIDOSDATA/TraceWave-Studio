"""! @brief 적용 당시의 PCB 선택 출처와 사용자 채택값을 프로젝트 확장에 보존한다."""

import hashlib
import math
import re

from rfad.domain.pcb_evidence_pool import expand_selection

from rfad.domain.design import _uuid, resolve_scalar
from rfad.domain.material_models import MATERIAL_MODELS
from rfad.domain.pcb_selection_evidence import MAX_EVIDENCE_BYTES, decode, encoded, fail, fields, pointer, read_pointer, sha256, text, validate_evidence


EXTENSION_KEY = "rfad.pcb-selection"
SELECTION_SCHEMA = "rfad.pcb-selection/0.1"
QUANTITY_FIELDS = {
    "materials": {"epsilon_r": "dimensionless", "tan_delta": "dimensionless", "conductivity": "conductivity",
                  "validity_hz.min": "frequency", "validity_hz.max": "frequency"},
    "stackup": {"thickness": "length", "z_min": "length"},
}
TARGET_FIELDS = {"materials": set(QUANTITY_FIELDS["materials"]) | {"model"},
                 "stackup": {"thickness", "z_min", "role", "material_id", "name"}, "ports": {"excitation_box"}}


def state_hash(document: dict) -> str:
    """! @brief 채택값과 이후 직접 편집의 비교를 위해 재료/층/포트 상태만 해시한다."""
    payload = {key: document[key] for key in ("materials", "stackup", "ports")}
    return hashlib.sha256(b"rfad.pcb-selection.applied/0.1\n" + encoded(payload).encode("utf-8")).hexdigest()


def _catalog(value: object) -> None:
    """! @brief 과거 변환 개정을 현재 설치 카탈로그와 무관하게 보존한다."""
    if value is None:
        return
    fields(value, {"catalog_id", "import_version", "source_canonical_sha256", "source_index_sha256"}, "selection.catalog")
    if type(value["catalog_id"]) is not str or re.fullmatch(r"catalog:[0-9a-f]{64}", value["catalog_id"]) is None:
        fail("E_SCHEMA", "카탈로그 개정 식별자가 올바르지 않습니다.", "selection.catalog.catalog_id")
    text(value["import_version"], "selection.catalog.import_version", characters=128)
    if re.fullmatch(r"rfad\.catalog\.import/[1-9][0-9]*", value["import_version"]) is None:
        fail("E_VERSION", "카탈로그 변환 개정 표기가 올바르지 않습니다.", "selection.catalog.import_version")
    for key in ("source_canonical_sha256", "source_index_sha256"):
        sha256(value[key], "selection.catalog." + key)


def _adopted_value(target: dict, value: object, field: str) -> bool:
    """! @brief 채택 당시 값의 차원과 미정 상태를 현재 프로젝트 참조 없이 검사한다."""
    collection, name = target["collection"], target["field"]
    if collection == "materials" and name == "model":
        if type(value) is not str or value not in MATERIAL_MODELS:
            fail("E_SCHEMA", "채택한 재료 손실 모델이 올바르지 않습니다.", field)
        return False
    dimension = QUANTITY_FIELDS.get(collection, {}).get(name)
    if value is None:
        return True
    if dimension is not None:
        quantity = resolve_scalar({"parameters": {}}, value, dimension, field)
        if name in ("epsilon_r", "thickness", "validity_hz.min", "validity_hz.max"):
            if quantity.value_si is not None and quantity.value_si <= 0:
                fail("E_SCHEMA", "PCB 채택값은 양수여야 합니다.", field)
        if name in ("tan_delta", "conductivity") and quantity.value_si is not None and quantity.value_si < 0:
            fail("E_SCHEMA", "PCB 채택값은 음수일 수 없습니다.", field)
        return quantity.value_si is None
    if collection == "ports":
        fields(value, {"start", "stop"}, field)
        missing = False
        for endpoint in ("start", "stop"):
            if type(value[endpoint]) is not list or len(value[endpoint]) != 3:
                fail("E_SCHEMA", "포트 채택 좌표는 길이 수량 3개여야 합니다.", field)
            for item in value[endpoint]:
                missing |= resolve_scalar({"parameters": {}}, item, "length", field).value_si is None
        return missing
    if name == "material_id":
        _uuid(value, field)
    elif name == "role":
        if type(value) is not str or value not in ("conductor", "dielectric", "coating", "adhesive", "air"):
            fail("E_SCHEMA", "층 채택 역할이 올바르지 않습니다.", field)
    else:
        text(value, field, characters=256)
    return False


def _published(entry: tuple[dict, object], location: str, adopted: object, field: str) -> None:
    """! @brief 직접 채택 근거의 존재와 명확한 단위 수치의 일치를 검사한다."""
    evidence, snapshot = entry
    if evidence["scope"] == "complete":
        present, original = read_pointer(snapshot, location)
    else:
        present, original = location in snapshot["values"], snapshot["values"].get(location)
        if not present:
            prefixes = [item for item in snapshot["values"] if location.startswith(item + "/")]
            if prefixes:
                prefix = max(prefixes, key=len)
                present, original = read_pointer(snapshot["values"][prefix], location[len(prefix):])
    if not present or original is None:
        fail("E_SCHEMA", "직접 채택할 공개값이 출처 사본에 없습니다.", field)
    if type(adopted) is dict and "value_si" in adopted and type(original) in (int, float):
        token = location.rsplit("/", 1)[-1]
        dimension = adopted["dimension"]
        jlc_thickness = (
            evidence["entity"] == "native_components" and location == "/dielectricThick"
        ) or (
            evidence["entity"] == "native_templates"
            and re.fullmatch(r"/basicDataList/(0|[1-9][0-9]*)/dielectricThick", location) is not None
        )
        millimetres = token.endswith("_mm") or jlc_thickness or (
            location.startswith("/post_lamination_groups/") and token == "value")
        scale = None
        if dimension == "dimensionless":
            scale = 1.0
        elif dimension == "length" and millimetres:
            scale = 1e-3
        elif dimension == "frequency" and token.endswith("_ghz"):
            scale = 1e9
        elif dimension == "frequency" and token.endswith("_hz"):
            scale = 1.0
        elif dimension == "conductivity" and token in ("conductivity", "conductivity_s_per_m"):
            scale = 1.0
        if scale is None:
            fail("E_SCHEMA", "출처 수치의 단위 변환은 명시적인 사용자 가정으로 기록해야 합니다.", field)
        try:
            expected = float(original) * scale
        except OverflowError:
            fail("E_SCHEMA", "출처 수치를 float64로 채택할 수 없습니다.", field)
        if not math.isfinite(expected) or adopted["value_si"] != expected:
            fail("E_HASH", "직접 채택값이 출처의 명시적 수치와 다릅니다.", field)
    elif encoded(original) != encoded(adopted):
        fail("E_HASH", "직접 채택값이 출처 원문과 다릅니다.", field)


def _validate_record(selection: object) -> None:
    """! @brief 비재귀 선택 하나의 채택값을 현재 재료와 무관하게 검증한다."""
    fields(selection, {"schema", "id", "catalog", "evidence", "decisions", "applied_state_sha256", "notes"}, "selection")
    if selection["schema"] != SELECTION_SCHEMA:
        fail("E_VERSION", "지원하지 않는 PCB 선택 확장 버전입니다.", "selection.schema")
    _uuid(selection["id"], "selection.id")
    _catalog(selection["catalog"])
    sha256(selection["applied_state_sha256"], "selection.applied_state_sha256")
    evidence = validate_evidence(selection["evidence"], selection["catalog"])
    if type(selection["notes"]) is not list or len(selection["notes"]) > 32:
        fail("E_RESOURCE", "PCB 선택 설명은 최대 32개 목록이어야 합니다.", "selection.notes")
    for note in selection["notes"]:
        text(note, "selection.notes")
    decisions = selection["decisions"]
    if type(decisions) is not list or len(decisions) > 128:
        fail("E_RESOURCE", "PCB 채택 결정은 최대 128개 목록이어야 합니다.", "selection.decisions")
    targets = set()
    for number, decision in enumerate(decisions):
        field = f"selection.decisions[{number}]"
        fields(decision, {"target", "basis", "evidence_id", "source_pointer", "value_json", "reason"}, field)
        target = decision["target"]
        fields(target, {"collection", "id", "field"}, field + ".target")
        if type(target["collection"]) is not str or target["collection"] not in TARGET_FIELDS:
            fail("E_SCHEMA", "PCB 채택 대상 collection이 올바르지 않습니다.", field)
        if type(target["field"]) is not str or target["field"] not in TARGET_FIELDS[target["collection"]]:
            fail("E_SCHEMA", "PCB 채택 대상 필드가 올바르지 않습니다.", field)
        _uuid(target["id"], field + ".target.id")
        key = (target["collection"], target["id"], target["field"])
        if key in targets:
            fail("E_CONFLICT", "같은 PCB 필드의 채택 기록이 중복됩니다.", field)
        targets.add(key)
        if decision["basis"] not in ("published", "user_override", "user_assumption", "missing"):
            fail("E_SCHEMA", "PCB 채택 근거 종류가 올바르지 않습니다.", field)
        text(decision["reason"], field + ".reason", empty=decision["basis"] in ("published", "missing"))
        identity, location = decision["evidence_id"], decision["source_pointer"]
        if identity is not None and (type(identity) is not str or identity not in evidence):
            fail("E_SCHEMA", "PCB 채택 기록이 없는 출처를 참조합니다.", field)
        if location is not None:
            pointer(location, field + ".source_pointer")
            if identity is None:
                fail("E_SCHEMA", "출처 ID 없는 JSON 포인터를 사용할 수 없습니다.", field)
        adopted = decode(decision["value_json"], field + ".value_json")
        missing = _adopted_value(target, adopted, field + ".value_json")
        if (decision["basis"] == "missing") != missing:
            fail("E_SCHEMA", "PCB 채택 근거와 값의 미정 상태가 다릅니다.", field)
        if decision["basis"] == "published":
            if identity is None or location is None:
                fail("E_SCHEMA", "공개값 직접 채택에는 출처와 JSON 포인터가 필요합니다.", field)
            _published(evidence[identity], location, adopted, field)


def validate_selection(selection: object) -> None:
    """! @brief 필요한 과거 출처도 개별 검증하고 전체 사본 예산을 함께 제한한다."""
    if type(selection) is not dict:
        fail("E_SCHEMA", "PCB 선택은 객체여야 합니다.", "selection")
    selection = expand_selection(selection)
    history = selection.get("history", [])
    if type(history) is not list or len(history) > 32:
        fail("E_RESOURCE", "PCB 선택 이력은 최대 32개 비재귀 목록이어야 합니다.", "selection.history")
    current = {key: value for key, value in selection.items() if key != "history"}
    _validate_record(current)
    identities = {current["id"]}
    evidence = list(current["evidence"])
    for item in history:
        _validate_record(item)
        if item["id"] in identities:
            fail("E_CONFLICT", "PCB 선택 이력의 ID가 중복됩니다.", "selection.history")
        identities.add(item["id"])
        evidence.extend(item["evidence"])
    unique = {}
    for entry in evidence:
        identity = entry["id"]
        if identity in unique and unique[identity] != entry:
            fail("E_HASH", "같은 ID의 출처 사본이 서로 다릅니다.", "selection.history")
        unique[identity] = entry
    if len(unique) > 256 or len(encoded(list(unique.values())).encode("utf-8")) > MAX_EVIDENCE_BYTES:
        fail("E_RESOURCE", "현재와 과거 PCB 출처의 합계가 128 KiB 예산을 초과했습니다.", "selection.history")


def validate_project_selection(document: dict) -> None:
    """! @brief 알려진 선택 확장만 해석하고 다른 확장과 과거 채택 기록은 보존한다."""
    if EXTENSION_KEY in document["extensions"]:
        validate_selection(document["extensions"][EXTENSION_KEY])
