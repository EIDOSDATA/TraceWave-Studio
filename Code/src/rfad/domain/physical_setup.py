"""! @brief 기존 PCB와 독립된 표면층 및 설치 환경 원본의 계약이다."""

import base64
import binascii
from copy import deepcopy
import hashlib
import math
import re

from rfad.domain.design import _fail, _fields, _indexes, _number, _reference, _strings, _text, _uuid, resolve_scalar

KEY = "rfad.physical_setup"
PROFILE = "rfad.physical-setup/0.1"
MAX_STEP_BYTES = 48 * 1024
MAX_STEP_INSTANCE_OFFSETS = 16
SURFACE_KINDS = ("solder_mask", "coverlay", "adhesive", "bondply", "finish", "ferrite", "plating", "coating")
FLAGS = {"visible", "include_in_em", "include_in_export"}
SURFACE_NUMBERS = ("offset", "thickness", "x", "y", "width", "height")
PART_NUMBERS = ("x", "y", "z", "yaw", "width", "height", "depth")
PART_KINDS = ("box", "step", "dielectric_case", "isolated_pec_box", "grounded_pec_box")
EM_PART_KINDS = {"dielectric_case", "isolated_pec_box", "grounded_pec_box"}
EM_SURFACE_KINDS = {"solder_mask", "coverlay", "adhesive", "bondply", "coating"}
ROW_FIELDS = {
    "surface": {"id", "name", "kind", "side", "coverage", "material_id", "openings", "source_refs", *FLAGS, *SURFACE_NUMBERS},
    "scenario": {"id", "name", "source_refs"},
    "part": {"id", "name", "scenario_id", "kind", "material_id", "step", "source_refs", *FLAGS, *PART_NUMBERS},
}
COLLECTIONS = {"surface": "surfaces", "scenario": "scenarios", "part": "parts"}
COMMAND = "physical_setup.edit"


def record_fields(section, record):
    """! @brief 종류에 한정한 수량을 허용하고 해당 키가 없는 과거 원본을 읽는다."""
    fields = ROW_FIELDS[section]
    if section == "part" and isinstance(record, dict) and record.get("kind") == "dielectric_case":
        return fields | {"case_thickness"}
    if section == "part" and isinstance(record, dict) and record.get("kind") == "step" and "instance_offsets" in record:
        return fields | {"instance_offsets"}
    if section == "surface" and isinstance(record, dict) and record.get("kind") == "bondply" and "supply_thickness" in record:
        return fields | {"supply_thickness"}
    return fields


def setup(document):
    """! @brief 이전 원본에 없는 구성은 비어 있는 기준 상태로 조회한다."""
    return document["extensions"].get(KEY, {"schema": PROFILE, "stack": None, "active_scenario_id": None,
                                           "surfaces": [], "scenarios": [], "parts": []})


def step_bytes(source):
    """! @brief 상대/외부 참조 없는 단일 DATA의 ASCII STEP 원본을 hash와 대조한다."""
    field = "step"
    _fields(source, {"name", "chunks", "sha256"}, field)
    name = _text(source["name"], "step.name", limit=128)
    if any(char in name for char in '/\\:') or not name.lower().endswith((".step", ".stp")):
        _fail("E_SCHEMA", "STEP 파일 이름만 전달하십시오.", "step.name")
    chunks = source["chunks"]
    if type(chunks) is not list or not 1 <= len(chunks) <= 16 or any(type(item) is not str or len(item) > 4096 for item in chunks):
        _fail("E_RESOURCE", "STEP 원본 인코딩 크기가 상한을 초과했습니다.", field)
    try:
        raw = base64.b64decode("".join(chunks), validate=True)
        plain = raw.decode("ascii")
    except (ValueError, UnicodeError, binascii.Error):
        _fail("E_SCHEMA", "ASCII STEP 바이트가 필요합니다.", field)
    if not 0 < len(raw) <= MAX_STEP_BYTES:
        _fail("E_RESOURCE", "외부 STEP 한 파일은 최대 48 KiB입니다.", field)
    digest = hashlib.sha256(raw).hexdigest()
    if source["sha256"] != digest:
        _fail("E_HASH", "STEP 원본 hash가 일치하지 않습니다.", field)
    data = re.sub(r"/\*.*?\*/|'(?:''|[^'])*'", "", plain, flags=re.S).strip().upper()
    if (not data.startswith("ISO-10303-21;") or not data.endswith("END-ISO-10303-21;")
            or len(re.findall(r"\bDATA\s*;", data)) != 1 or "@" in data
            or re.search(r"\b(ANCHOR|REFERENCE|SIGNATURE)\s*;|\b(?:EXTERNAL[A-Z_]*|DOCUMENT_FILE|DRAUGHTING_MODEL)\s*\(", data)):
        _fail("E_UNSUPPORTED", "단일 DATA의 자체 포함 STEP 파일만 지원합니다.", field)
    return raw


def validate_instance_offsets(rows):
    """! @brief 원본 STEP의 경로별 조립 이동 또는 기판 원점 맞춤과 회전을 검사한다."""
    field = "part.instance_offsets"
    if type(rows) is not list or not 1 <= len(rows) <= MAX_STEP_INSTANCE_OFFSETS:
        _fail("E_RESOURCE", "STEP 조립 말단 배치는 최대 16개입니다.", field)
    paths = []
    for row in rows:
        point_mate = isinstance(row, dict) and "target_origin_mm" in row
        position_key = "target_origin_mm" if point_mate else "translation_mm"
        keys = {"path", position_key}
        if isinstance(row, dict) and "rotation_deg" in row:
            keys.add("rotation_deg")
        _fields(row, keys, field)
        path, position = row["path"], row[position_key]
        if (type(path) is not list or not 2 <= len(path) <= 8 or path[0] != 1
                or any(type(index) is not int or not 1 <= index <= 32 for index in path)):
            _fail("E_SCHEMA", "STEP 원본의 말단 경로를 입력하십시오.", field)
        if (type(position) is not list or len(position) != 3
                or any(type(value) not in (float, int) or not -1e6 <= value <= 1e6 or not math.isfinite(value)
                       for value in position)):
            _fail("E_GEOMETRY", "유한한 X Y Z 위치 또는 이동량을 mm로 입력하십시오.", field)
        rotation = row.get("rotation_deg", [0, 0, 0])
        if (type(rotation) is not list or len(rotation) != 3
                or any(type(value) not in (float, int) or not -360 <= value <= 360 or not math.isfinite(value)
                       for value in rotation)):
            _fail("E_GEOMETRY", "X Y Z 회전은 각 축 -360~360도로 입력하십시오.", field)
        if not (point_mate or any(position) or any(value % 360 for value in rotation)):
            _fail("E_GEOMETRY", "조립 말단의 실제 위치나 방향이 바뀌는 값을 입력하십시오.", field)
        paths.append(tuple(path))
    if paths != sorted(set(paths)):
        _fail("E_CONFLICT", "같은 STEP 부품 경로를 중복 지정할 수 없습니다.", field)


def _rect(document, data, field):
    """! @brief 알려진 치수의 정의역을 검증하고 미정 좌표는 유지한다."""
    _fields(data, {"x", "y", "width", "height"}, field)
    for key, value in data.items():
        _number(document, value, "length", field + "." + key, positive=key in ("width", "height"))


def validate_setup(document):
    """! @brief 설치/표면 참조가 다른 원본의 의미를 덮어쓰지 않도록 검증한다."""
    if KEY not in document["extensions"]:
        return
    model = setup(document)
    _fields(model, {"schema", "stack", "active_scenario_id", *COLLECTIONS.values()}, KEY)
    if model["schema"] != PROFILE:
        _fail("E_VERSION", "지원하지 않는 적층/환경 계약입니다.", KEY)
    if model["stack"] is not None:
        _fields(model["stack"], {"nominal", "scope", "source_refs"}, "stack")
        _number(document, model["stack"]["nominal"], "length", "stack.nominal", positive=True)
        if model["stack"]["scope"] not in (None, "base", "with_surfaces"):
            _fail("E_SCHEMA", "명목 두께의 포함 범위를 선택하십시오.", "stack.scope")
        _strings(model["stack"]["source_refs"], "stack.source_refs")
    indexes = _indexes(document)
    used = {identity for index in indexes.values() for identity in index}
    used.update([document["project_id"], document["revision_id"], *document["parent_revision_ids"], *document["parameters"]])
    if document["board"] is not None:
        used.add(document["board"]["id"])
    used.update(row["id"] for key in ("targets", "connections", "manufacturing_profiles") for row in document[key])
    scenarios = {}
    source_total = 0
    for section in ("scenario", "surface", "part"):
        rows = model[COLLECTIONS[section]]
        if type(rows) is not list or len(rows) > 16:
            _fail("E_RESOURCE", "각 설치 구성 목록은 최대 16개입니다.", section)
        for row in rows:
            _fields(row, record_fields(section, row), section)
            identity = _uuid(row["id"], section + ".id")
            if identity in used:
                _fail("E_CONFLICT", "설치/표면 객체 ID가 중복됩니다.", section + ".id")
            used.add(identity)
            _text(row["name"], section + ".name", limit=128)
            _strings(row["source_refs"], section + ".source_refs")
            if section == "scenario":
                scenarios[identity] = row
                continue
            for flag in FLAGS:
                if type(row[flag]) is not bool:
                    _fail("E_SCHEMA", "포함 상태에는 boolean을 사용하십시오.", section + "." + flag)
            _reference(row["material_id"], indexes["materials"], section + ".material_id", optional=True)
            keys = SURFACE_NUMBERS if section == "surface" else PART_NUMBERS
            for key in keys:
                _number(document, row[key], "angle" if key == "yaw" else "length", section + "." + key,
                        positive=key in ("thickness", "width", "height", "depth"), nonnegative=key == "offset")
            if section == "surface":
                if row["kind"] not in SURFACE_KINDS or row["side"] not in ("top", "bottom") or row["coverage"] not in ("board", "rectangle"):
                    _fail("E_SCHEMA", "표면층의 종류/면/범위를 지정하십시오.", "surface")
                if "supply_thickness" in row:
                    _number(document, row["supply_thickness"], "length", "surface.supply_thickness", positive=True)
                if type(row["openings"]) is not list or len(row["openings"]) > 8:
                    _fail("E_RESOURCE", "표면층당 사각 개구는 최대 8개입니다.", "surface.openings")
                for opening in row["openings"]:
                    _rect(document, opening, "surface.openings")
            else:
                _reference(row["scenario_id"], scenarios, "part.scenario_id")
                if row["kind"] == "dielectric_case":
                    _number(document, row["case_thickness"], "length", "part.case_thickness", positive=True)
                if row["kind"] == "step":
                    source_total += len(step_bytes(row["step"]))
                    if "instance_offsets" in row:
                        validate_instance_offsets(row["instance_offsets"])
                elif row["kind"] not in PART_KINDS or row["step"] is not None:
                    _fail("E_SCHEMA", "지원하는 외부 물체 종류를 선택하십시오.", "part.kind")
        if [row["id"] for row in rows] != sorted(row["id"] for row in rows):
            _fail("E_SCHEMA", "설치/표면 객체 목록을 ID 순서로 저장하십시오.", section)
    if source_total > MAX_STEP_BYTES:
        _fail("E_RESOURCE", "프로젝트에 보존할 STEP 원본 합계는 최대 48 KiB입니다.", "parts")
    _reference(model["active_scenario_id"], scenarios, "active_scenario_id", optional=True)


def apply_setup(document, payload):
    """! @brief 하나의 변경으로 구성 교체와 정확한 역명령을 만든다."""
    _fields(payload, {"section", "record_id", "record", "display_only", "restore_absence"}, "command.payload")
    section, identity, record = (payload[key] for key in ("section", "record_id", "record"))
    if section not in {*COLLECTIONS, "stack", "activation"} or any(type(payload[key]) is not bool for key in ("display_only", "restore_absence")):
        _fail("E_SCHEMA", "물리 구성 변경 형식이 유효하지 않습니다.", "command.payload")
    if section in COLLECTIONS:
        _uuid(identity, "command.payload.record_id")
    if section == "activation":
        _fields(record, {"active_scenario_id"}, "command.payload.record")
    absent = KEY not in document["extensions"]
    model = deepcopy(setup(document))
    if section in COLLECTIONS:
        rows = model[COLLECTIONS[section]]
        previous = next((row for row in rows if row["id"] == identity), None)
        rows = [row for row in rows if row["id"] != identity]
        if record is not None:
            record = deepcopy(record)
            # @brief 같은 STEP 바이트를 위치 변경마다 명령 저널에 중복 저장하지 않는다.
            inherit_step = section == "part" and previous is not None and type(record) is dict and "step" not in record
            if inherit_step:
                record["step"] = deepcopy(previous["step"])
            _fields(record, record_fields(section, record), "command.payload.record")
            if record["id"] != identity:
                _fail("E_SCHEMA", "물리 객체 ID와 변경 대상이 다릅니다.", "command.payload.record_id")
            rows.append(record)
            if inherit_step:
                previous = {key: value for key, value in previous.items() if key != "step"}
        model[COLLECTIONS[section]] = sorted(rows, key=lambda row: row["id"])
    elif section == "activation":
        previous = {"active_scenario_id": model["active_scenario_id"]}
        model.update(record)
    else:
        previous = model["stack"]
        model["stack"] = deepcopy(record)
    if payload["restore_absence"]:
        document["extensions"].pop(KEY, None)
    else:
        document["extensions"][KEY] = model
    invalidation = ["revision", "geometry"]
    if not payload["display_only"]:
        invalidation.extend(["physics", "network", "metrics", "assessment", "exports"])
    inverse = {**payload, "record": deepcopy(previous), "restore_absence": absent}
    return [identity] if identity else [], invalidation, {"type": COMMAND, "payload": inverse}


def candidates(document):
    """! @brief 기준 PCB에 선택된 시나리오의 delta만 겹친다."""
    model = setup(document)
    return model["surfaces"], [row for row in model["parts"] if row["scenario_id"] == model["active_scenario_id"]]


def read_scalar(document, value, dimension="length"):
    """! @brief 알려지지 않은 치수는 계산에 맞춰 보정하지 않는다."""
    return resolve_scalar(document, value, dimension).value_si


def stack_review(document):
    """! @brief 개별 두께, 절대 z, 두께 합과 명목의 차이를 SI로 제공한다."""
    model = setup(document)
    rows = []
    for layer in document["stackup"]:
        lower, thickness = (read_scalar(document, layer[key]) for key in ("z_min", "thickness"))
        rows.append({"id": layer["id"], "name": layer["name"], "role": layer["role"], "material_id": layer["material_id"],
                     "z_min": lower, "z_max": None if lower is None or thickness is None else lower + thickness,
                     "thickness": thickness, "thickness_input": deepcopy(layer["thickness"])})
    base = None
    gaps = []
    if rows and all(row["z_min"] is not None and row["z_max"] is not None for row in rows):
        base = [rows[0]["z_min"], rows[-1]["z_max"]]
        for before, after in zip(rows, rows[1:]):
            gap = after["z_min"] - before["z_max"]
            if gap > 8 * max(math.ulp(after["z_min"]), math.ulp(before["z_max"])):
                gaps.append({"from": before["id"], "to": after["id"], "length_si": gap})
    extent = None if base is None else list(base)
    surfaces = []
    for row in model["surfaces"]:
        offset, thickness = (read_scalar(document, row[key]) for key in ("offset", "thickness"))
        interval = None
        if base is not None and offset is not None and thickness is not None:
            outer = base[1] + offset if row["side"] == "top" else base[0] - offset
            ends = [outer, outer + thickness] if row["side"] == "top" else [outer - thickness, outer]
            if all(math.isfinite(value) for value in ends) and ends[1] > ends[0]:
                interval = ends
        if interval is None:
            extent = None
        if extent is not None:
            extent = [min(extent[0], interval[0]), max(extent[1], interval[1])]
        surfaces.append({"id": row["id"], "name": row["name"], "side": row["side"], "thickness_si": thickness, "interval_si": interval})
    spec = model["stack"]
    total = None if extent is None else extent[1] - extent[0]
    base_extent = None if base is None else base[1] - base[0]
    base_sum = None if not rows or any(row["thickness"] is None for row in rows) else math.fsum(row["thickness"] for row in rows)
    nominal = None if spec is None else read_scalar(document, spec["nominal"])
    measured = None if spec is None or spec["scope"] is None else base_extent if spec["scope"] == "base" else total
    return {"rows": rows, "base_si": base, "base_sum_si": base_sum, "base_extent_si": base_extent,
            "gaps": gaps, "surfaces": surfaces, "full_extent_si": total,
            "nominal_difference_si": None if nominal is None or measured is None else measured - nominal}


def em_exclusions(document):
    """! @brief 지원하지 않는 해석 포함 요청은 모델에서 조용히 버리지 않는다."""
    surfaces, parts = candidates(document)
    return [{"id": row["id"], "section": section, "reason": "unsupported_in_profile" if row["include_in_em"] else "excluded_by_user"}
            for section, rows, supported in (("surface", surfaces, EM_SURFACE_KINDS), ("part", parts, EM_PART_KINDS))
            for row in rows if not (row["include_in_em"] and row["kind"] in supported)]
