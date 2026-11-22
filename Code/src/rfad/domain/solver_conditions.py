"""! @brief 프로젝트 개정에 이름 있는 PCB 해석 조건을 보존한다."""

from copy import deepcopy

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.design import _fail, _fields, _text, _uuid, resolve_scalar
from rfad.domain.network_library import digest
from rfad.domain.physical_setup import candidates, setup

KEY = "rfad.solver-conditions"
PROFILE = "rfad.solver-conditions/0.1"
INSERT = "solver.conditions.insert"
REMOVE = "solver.conditions.remove"
MAX_RECORDS = 32
MAX_BYTES = 32 * 1024


def records(document):
    """! @brief 조건이 없던 프로젝트를 읽을 때 빈 목록을 반환한다."""
    return document["extensions"].get(KEY, {}).get("records", [])


def name(value):
    """! @brief 화면과 저장 원본에서 같은 이름을 사용한다."""
    field = "condition.name"
    value = _text(value, field, limit=96)
    if value != value.strip() or any(ord(ch) < 32 for ch in value):
        _fail("E_SCHEMA", "조건 이름은 양끝 공백이나 줄바꿈 없이 입력하세요.", field)
    return value


def design_context(document):
    """! @brief 해석 조건을 만들 때의 급전과 설치 입력을 표시 이름 및 해시로 남긴다."""
    model = setup(document)
    scenario = next((x for x in model["scenarios"] if x["id"] == model["active_scenario_id"]), None)
    surfaces, parts = candidates(document)
    installation = {"scenario": model["active_scenario_id"],
                    "surfaces": [row for row in surfaces if row["include_in_em"]],
                    "parts": [row for row in parts if row["include_in_em"]]}
    ports = document["ports"]
    labels = []
    resistances = []
    for row in ports:
        resistance = resolve_scalar(document, row["resistance"], "impedance").value_si
        resistances.append(resistance)
        value = "저항 미정" if resistance is None else f"{resistance:.12g} ohm"
        labels.append(f"{row['name']} / {value} / {row['reference_plane']}")
    return {"ports_label": ", ".join(labels)[:256] or "급전 미정",
            "ports_sha256": canonical_hash({"ports": ports, "resistance_ohm": resistances}),
            "installation_label": (scenario["name"] if scenario else "기판 단독")[:256],
            "installation_sha256": canonical_hash(installation)}


def validate(document):
    """! @brief 이름 충돌, 기록 수와 기존 solver 설정 계약을 검사한다."""
    if KEY not in document["extensions"]:
        return
    from rfad.application.pcb_solver import validate_settings

    library = document["extensions"][KEY]
    _fields(library, {"profile", "records"}, KEY)
    rows = library["records"]
    if library["profile"] != PROFILE:
        _fail("E_VERSION", "지원하지 않는 해석 조건 목록입니다.", KEY)
    if type(rows) is not list or not 1 <= len(rows) <= MAX_RECORDS or len(canonical_bytes(library)) > MAX_BYTES:
        _fail("E_RESOURCE", "프로젝트마다 최대 32개와 총 32 KiB까지 해석 조건을 저장할 수 있습니다.", KEY)
    identities, names = set(), set()
    for row in rows:
        _fields(row, {"id", "name", "revision_id", "settings", "design"}, KEY)
        identity = _uuid(row["id"], KEY + ".id")
        normalized = name(row["name"]).casefold()
        if identity in identities or normalized in names:
            _fail("E_CONFLICT", "같은 이름의 해석 조건이 있습니다. 다른 이름을 입력하세요.", "condition.name")
        identities.add(identity)
        names.add(normalized)
        _uuid(row["revision_id"], KEY + ".revision_id")
        validate_settings(row["settings"])
        design = row["design"]
        _fields(design, {"ports_label", "ports_sha256", "installation_label", "installation_sha256"}, KEY + ".design")
        for kind in ("ports", "installation"):
            _text(design[kind + "_label"], KEY + ".design", limit=256)
            digest(design[kind + "_sha256"], KEY + ".design")


def apply(document, command, payload):
    """! @brief 조건 추가와 실행 취소의 역명령에 같은 기록을 보존한다."""
    rows = list(records(document))
    if command == INSERT:
        _fields(payload, {"record"}, "command.payload")
        record = deepcopy(payload["record"])
        identity = record["id"]
        rows.append(record)
        inverse = {"type": REMOVE, "payload": {"id": identity}}
    else:
        _fields(payload, {"id"}, "command.payload")
        identity = payload["id"]
        record = next((row for row in rows if row["id"] == identity), None)
        if record is None:
            _fail("E_CONFLICT", "삭제할 해석 조건을 찾지 못했습니다.", "condition.id")
        rows = [row for row in rows if row["id"] != identity]
        inverse = {"type": INSERT, "payload": {"record": deepcopy(record)}}
    if rows:
        document["extensions"][KEY] = {"profile": PROFILE, "records": rows}
        validate(document)
    else:
        document["extensions"].pop(KEY, None)
    return [identity], ["revision", "solver_conditions"], inverse
