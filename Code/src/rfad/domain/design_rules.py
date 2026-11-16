"""! @brief 기대 연결과 사용자 제조 규칙을 물리 형상 및 미정값과 분리해 보존한다."""

from copy import deepcopy

from rfad.domain.design import _fields, _fail, _strings, _text, _uuid, resolve_scalar


RULES = {
    "minimum_width": ("최소 도체 폭", "length"),
    "minimum_clearance": ("다른 net의 최소 간격", "length"),
    "minimum_edge_clearance": ("도체-기판 외곽 최소 거리", "length"),
    "minimum_tool_hole": ("최소 공구 드릴 지름", "length"),
    "minimum_annular_ring": ("공구 드릴 기준 최소 환형 링", "length"),
    "maximum_via_aspect_ratio": ("최대 관통 비아 종횡비", "dimensionless"),
}
CONNECTION_KINDS = ("connected", "isolated", "parasitic")
COMMANDS = tuple(f"{kind}.{action}" for kind in ("connection", "manufacturing_profile") for action in ("set", "remove"))
MAX_CONNECTIONS = 64
MAX_PROFILES = 8


def validate_rules(document):
    """! @brief 전역 UUID/참조와 닫힌 규칙 schema를 검사하되 위반 설계의 편집은 허용한다."""
    used = {document["project_id"], document["revision_id"], *document["parent_revision_ids"], *document["parameters"]}
    used.update(row["id"] for row in document["frames"].values())
    if document["board"] is not None:
        used.add(document["board"]["id"])
    for collection in ("geometry", "ports", "materials", "stackup", "nets", "targets"):
        used.update(row["id"] for row in document[collection])
    used.update(row["revision_id"] for row in document["targets"])
    geometry = {row["id"] for row in document["geometry"]}
    for collection, maximum in (("connections", MAX_CONNECTIONS), ("manufacturing_profiles", MAX_PROFILES)):
        rows = document[collection]
        if type(rows) is not list or len(rows) > maximum:
            _fail("E_RESOURCE", "설계 규칙 collection 상한을 초과했습니다.", collection)
        ids = []
        for index, row in enumerate(rows):
            field = f"{collection}[{index}]"
            keys = {"id", "name", "source_refs"} | ({"kind", "object_ids"} if collection == "connections" else {"version", "rules"})
            _fields(row, keys, field)
            identity = _uuid(row["id"], field + ".id")
            if identity in used:
                _fail("E_CONFLICT", "설계 규칙 UUID가 다른 객체와 충돌합니다.", field + ".id")
            used.add(identity)
            ids.append(identity)
            _text(row["name"], field + ".name", limit=256)
            _strings(row["source_refs"], field + ".source_refs")
            if collection == "connections":
                if row["kind"] not in CONNECTION_KINDS:
                    _fail("E_UNSUPPORTED", "지원하지 않는 연결 의도입니다.", field + ".kind")
                objects = row["object_ids"]
                if type(objects) is not list or len(objects) != 2:
                    _fail("E_SCHEMA", "연결 의도는 두 객체 또는 미정 참조를 지정합니다.", field + ".object_ids")
                for obj in objects:
                    if obj is not None and _uuid(obj, field + ".object_ids") not in geometry:
                        _fail("E_CONFLICT", "기대 연결이 없는 도체를 참조합니다.", field + ".object_ids")
                if objects[0] is not None and objects[0] == objects[1]:
                    _fail("E_CONFLICT", "서로 다른 도체를 지정하십시오.", field + ".object_ids")
            else:
                _text(row["version"], field + ".version", limit=128)
                _fields(row["rules"], set(RULES), field + ".rules")
                for key, (_, dimension) in RULES.items():
                    raw = row["rules"][key]
                    if type(raw) is not dict or "parameter_id" in raw:
                        _fail("E_SCHEMA", "제조 규칙에는 출처를 가진 literal Quantity가 필요합니다.", field + ".rules." + key)
                    value = resolve_scalar(document, raw, dimension, field + ".rules." + key).value_si
                    if value is not None and (value < 0 or (key in ("minimum_width", "minimum_tool_hole", "maximum_via_aspect_ratio") and value == 0)):
                        _fail("E_UNIT", "제조 규칙의 수치 범위가 유효하지 않습니다.", field + ".rules." + key)
                    if dimension == "length" and value is not None and value > 2000:
                        _fail("E_RESOURCE", "기본 DRC의 거리 한계를 초과했습니다.", field + ".rules." + key)
        if ids != sorted(ids):
            _fail("E_SCHEMA", "설계 규칙은 UUID 오름차순이어야 합니다.", collection)


def apply_rule_command(document, kind, payload):
    """! @brief 한 객체의 원본과 출처를 원자 교체하고 의미상 역명령을 만든다."""
    prefix, action = kind.split(".")
    collection = "connections" if prefix == "connection" else "manufacturing_profiles"
    _fields(payload, {"record"} if action == "set" else {"id"}, "command.payload")
    identity = _uuid(payload["record"].get("id") if action == "set" and type(payload["record"]) is dict else payload.get("id"), "command.payload.id")
    previous = next((row for row in document[collection] if row["id"] == identity), None)
    inverse = {"type": prefix + ".remove", "payload": {"id": identity}}
    if previous is not None:
        inverse = {"type": prefix + ".set", "payload": {"record": deepcopy(previous)}}
    remaining = [row for row in document[collection] if row["id"] != identity]
    if action == "set":
        remaining.append(deepcopy(payload["record"]))
    elif previous is None:
        _fail("E_CONFLICT", "제거할 설계 규칙이 없습니다.", "command.payload.id")
    document[collection] = sorted(remaining, key=lambda row: row["id"])
    return [identity], ["revision", "design_checks", "assessment", "exports"], inverse
