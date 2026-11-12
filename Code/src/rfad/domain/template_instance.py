"""! @brief 생성 당시 카드/입력/객체 사본을 현재 편집 원본과 분리해 보존한다."""

from copy import deepcopy

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.design import _fail, _fields, _uuid
from rfad.domain.template_geometry import object_id, parameter_roles
from rfad.domain.template_inputs import normalize_inputs
from rfad.templates.cards import validate_card_snapshot
from rfad.domain.template_provenance import generation_report


EXTENSION_KEY = "rfad.template-origin"
ORIGIN_SCHEMA = "rfad.template-origin/0.1"
MAX_INSTANCES = 8
MAX_ORIGIN_BYTES = 256 * 1024
OBJECT_COLLECTIONS = ("parameters", "nets", "geometry", "ports")
_RECORD_FIELDS = {"id", "card", "base_revision", "base_content_hash", "binding", "inputs", "port_recipe",
                  "target_snapshots", "objects", "record_hash", "source_document", "source_document_hash", "requested_inputs"}


def record_hash(record: dict) -> str:
    """! @brief 원본 사본 해시 필드를 제외한 전체 의미에 정규 해시를 계산한다."""
    return canonical_hash({key: value for key, value in record.items() if key != "record_hash"})


def object_ids(record: dict) -> dict[str, list[str]]:
    """! @brief 저장 당시 사본에서 객체 대응을 재구성하며 별도 덮어쓰기 맵을 두지 않는다."""
    return {name: sorted(record["objects"][name] if name == "parameters" else (item["id"] for item in record["objects"][name]))
            for name in OBJECT_COLLECTIONS}


def validate_record(record: object) -> None:
    """! @brief 카드가 외부 라이브러리에 없어도 과거 입력/객체 사본을 검증한다."""
    _fields(record, _RECORD_FIELDS, "template_origin.instance")
    instance_id = _uuid(record["id"], "template_origin.instance.id")
    _uuid(record["base_revision"], "template_origin.base_revision")
    digest = record["base_content_hash"]
    if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        _fail("E_HASH", "템플릿 기준 원본 해시가 올바르지 않습니다.", "template_origin.base_content_hash")
    validate_card_snapshot(record["card"])
    _fields(record["binding"], {"board_id", "frame_id", "layer_id", "material_id"}, "template_origin.binding")
    for key, identity in record["binding"].items():
        if key != "material_id" or identity is not None:
            _uuid(identity, "template_origin.binding." + key)
    if normalize_inputs(record["card"], record["requested_inputs"]) != record["inputs"]:
        _fail("E_HASH", "템플릿 표시 원문과 저장 Quantity가 다릅니다.", "template_origin.inputs")
    if type(record["target_snapshots"]) is not list or len(record["target_snapshots"]) > 32:
        _fail("E_SCHEMA", "과거 템플릿 입력/목표 사본 형식이 다릅니다.", "template_origin.inputs")
    target_ids = set()
    for target in record["target_snapshots"]:
        if type(target) is not dict:
            _fail("E_SCHEMA", "과거 목표 사본이 object가 아닙니다.", "template_origin.target_snapshots")
        _uuid(target.get("id"), "template_origin.target_snapshots.id")
        _uuid(target.get("revision_id"), "template_origin.target_snapshots.revision_id")
        if target["id"] in target_ids:
            _fail("E_CONFLICT", "과거 목표 사본 ID가 중복됩니다.", "template_origin.target_snapshots")
        target_ids.add(target["id"])
    _fields(record["objects"], set(OBJECT_COLLECTIONS), "template_origin.objects")
    parameters = record["objects"]["parameters"]
    if type(parameters) is not dict or len(parameters) > 32:
        _fail("E_RESOURCE", "템플릿 매개변수 사본의 상한을 초과했습니다.", "template_origin.objects.parameters")
    if set(parameters) != {object_id(instance_id, "parameter:" + role) for role in parameter_roles(record["card"])}:
        _fail("E_HASH", "과거 매개변수의 안정 역할 ID 목록이 다릅니다.", "template_origin.objects.parameters")
    ids = {instance_id}
    for key, parameter in parameters.items():
        if type(parameter) is not dict or key != parameter.get("id"):
            _fail("E_SCHEMA", "과거 매개변수의 key/ID가 다릅니다.", "template_origin.objects.parameters")
        ids.add(_uuid(key, "template_origin.objects.parameters.id"))
    roles = {object_id(instance_id, name) for name in ("net", "radiator", "feed", "ground", "short", "pad", "port")}
    for name in ("nets", "geometry", "ports"):
        collection = record["objects"][name]
        if type(collection) is not list or len(collection) > 8:
            _fail("E_RESOURCE", "템플릿 객체 사본이 제한된 목록이 아닙니다.", "template_origin.objects." + name)
        for item in collection:
            if type(item) is not dict:
                _fail("E_SCHEMA", "과거 템플릿 객체는 object여야 합니다.", "template_origin.objects." + name)
            identity = _uuid(item.get("id"), "template_origin.objects." + name + ".id")
            if identity in ids or identity not in roles:
                _fail("E_HASH", "과거 템플릿 객체의 안정 ID 대응이 다릅니다.", "template_origin.objects." + name)
            ids.add(identity)
    if record["record_hash"] != record_hash(record):
        _fail("E_HASH", "템플릿의 입력/출처/객체 사본 해시가 다릅니다.", "template_origin.record_hash")
    _validate_original_design(record)


def _validate_original_design(record: dict) -> None:
    """! @brief 현재 객체와 분리된 적용 당시 core 원본에 기존 전체 의미 검증을 수행한다."""
    from rfad.domain.project import validate_project
    from rfad.domain.template_geometry import validate_binding
    from rfad.domain.template_ports import generate_port

    source = record["source_document"]
    if type(source) is not dict or source.get("extensions") != {}:
        _fail("E_SCHEMA", "템플릿 core 원본 사본에는 중첩 extension을 넣을 수 없습니다.", "template_origin.source_document")
    if record["source_document_hash"] != canonical_hash(source):
        _fail("E_HASH", "확장을 제외한 core 원본 사본 해시가 다릅니다.", "template_origin.source_document_hash")
    validate_project(source)
    if source["revision_id"] != record["base_revision"]:
        _fail("E_HASH", "템플릿 원본 사본의 기준 개정이 다릅니다.", "template_origin.base_revision")
    validate_binding(source, record["binding"], record["card"])
    targets = {item["id"]: item for item in source["targets"]}
    for target in record["target_snapshots"]:
        if targets.get(target["id"]) != target:
            _fail("E_HASH", "템플릿 목표 사본이 적용 당시 core 원본과 다릅니다.", "template_origin.target_snapshots")
    probe = deepcopy(source)
    for name in OBJECT_COLLECTIONS:
        additions = record["objects"][name]
        if name == "parameters":
            if set(probe[name]) & set(additions):
                _fail("E_CONFLICT", "과거 매개변수 UUID가 기준 원본과 충돌합니다.", "template_origin.objects.parameters")
            probe[name].update(deepcopy(additions))
        else:
            probe[name] = sorted([*probe[name], *deepcopy(additions)], key=lambda item: item["id"])
    validate_project(probe)
    if record["card"]["schema"] == "rfad.template-card/0.2":
        from rfad.domain.template_geometry import generate_geometry
        generated = generate_geometry(source, record["id"], record["binding"], record["card"], record["inputs"])
        if generated != record["objects"]:
            _fail("E_HASH", "문헌 카드의 최초 생성 사본이 원문/입력/배치와 다릅니다.", "template_origin.objects")
    port_probe = deepcopy(record["objects"])
    port_probe["ports"] = []
    generate_port(source, port_probe, record["id"], record["binding"], record["card"], record["port_recipe"])
    if port_probe["ports"] != record["objects"]["ports"]:
        _fail("E_HASH", "과거 포트 recipe와 생성 포트가 다릅니다.", "template_origin.port_recipe")


def validate_template_origins(document: dict) -> None:
    """! @brief 과거 사본의 무결성만 검사하고 이후 사용자 편집/삭제를 막지 않는다."""
    value = document["extensions"].get(EXTENSION_KEY)
    if value is None:
        return
    _fields(value, {"schema", "instances"}, "extensions." + EXTENSION_KEY)
    if value["schema"] != ORIGIN_SCHEMA:
        _fail("E_VERSION", "지원하지 않는 템플릿 출처 profile입니다.", "extensions." + EXTENSION_KEY)
    if type(value["instances"]) is not list or not 1 <= len(value["instances"]) <= MAX_INSTANCES:
        _fail("E_RESOURCE", "템플릿 출처 사본은 1~8개여야 합니다.", "template_origin.instances")
    ids = []
    for record in value["instances"]:
        validate_record(record)
        ids.append(record["id"])
    if ids != sorted(set(ids)):
        _fail("E_CONFLICT", "템플릿 출처 인스턴스는 중복 없는 UUID 순서여야 합니다.", "template_origin.instances")
    if len(canonical_bytes(value)) > MAX_ORIGIN_BYTES:
        _fail("E_RESOURCE", "템플릿 출처 사본이 256 KiB를 초과했습니다.", "template_origin")


def instance_status(document: dict, record: dict) -> dict:
    """! @brief 현재 객체의 직접 편집/삭제 차이를 과거 출처를 수정하지 않고 반환한다."""
    changes = []
    for name in OBJECT_COLLECTIONS:
        original = record["objects"][name]
        before = original if name == "parameters" else {item["id"]: item for item in original}
        current = document[name] if name == "parameters" else {item["id"]: item for item in document[name]}
        for identity, value in before.items():
            if current.get(identity) != value:
                changes.append({"collection": name, "id": identity, "status": "removed" if identity not in current else "modified"})
    return {"instance_id": record["id"], "template_id": record["card"]["template_id"], "version": record["card"]["version"],
            "record_hash": record["record_hash"], "changes": changes, "support": deepcopy(record["card"]["support"]),
            "generation": generation_report(record["card"], record["inputs"]),
            "evaluation_status": "not_evaluated"}
