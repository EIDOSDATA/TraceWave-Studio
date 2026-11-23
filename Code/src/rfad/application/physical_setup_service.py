"""! @brief 적층/환경 화면의 revision 조회, 부분 편집과 STEP 미리보기를 연결한다."""

import base64
import binascii
from collections import OrderedDict
from copy import deepcopy
import hashlib
from threading import Lock
from uuid import uuid4

from rfad.application.project_contract import _fields, _uuid
from rfad.application.target_editor_values import fail, number, sources
from rfad.domain.design import _text, resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.physical_setup import (KEY, PROFILE, COMMAND, COLLECTIONS, FLAGS, SURFACE_KINDS,
                                        SURFACE_NUMBERS, PART_NUMBERS, PART_KINDS, EM_SURFACE_KINDS, setup, stack_review, step_bytes, em_exclusions)
from rfad.domain.units import Quantity, QuantityError

READS = {"physical.setup.get", "physical.step.preview"}
MUTATION = "physical.setup.apply"
SECTIONS = {"stack", "activation", *COLLECTIONS}
LABELS = {
    "solder_mask": "솔더마스크", "coverlay": "커버레이", "adhesive": "접착층", "bondply": "본드플라이",
    "finish": "표면처리", "ferrite": "페라이트", "plating": "도금층", "coating": "코팅",
    "top": "상면", "bottom": "하면", "board": "기판 전체", "rectangle": "사각 범위",
    "base": "기본 적층", "with_surfaces": "표면층 포함", "box": "간이 상자", "step": "외부 STEP",
    "dielectric_case": "유전체 케이스 (하부 개방)",
    "isolated_pec_box": "비접촉 금속 상자 (PEC)",
    "grounded_pec_box": "급전 기준 패드에 접지한 금속 (PEC)",
}
FIELDS = {
    "name": "이름", "kind": "종류", "side": "면", "coverage": "피복 범위", "material_id": "재료",
    "scenario_id": "설치 시나리오", "visible": "3D 표시", "include_in_em": "해석 포함",
    "include_in_export": "STEP 출력 포함", "nominal": "명목 총두께", "scope": "총두께 범위",
    "offset": "외면에서 간격", "thickness": "최종 두께", "supply_thickness": "공급 두께 (본드플라이용)",
    "x": "X", "y": "Y", "z": "Z",
    "width": "폭", "height": "길이", "depth": "높이", "yaw": "Z축 회전",
    "case_thickness": "벽과 덮개 두께 (케이스용)",
    "instance_replacements": "말단 교체 / 원본과 새 면 대응",
    "instance_offsets": "STEP 말단 배치와 원점, 평면, 축 맞춤",
    "openings": "개구 (mm, 줄마다 X Y 폭 길이)", "active_scenario_id": "활성 시나리오",
}


def _part_path(text):
    """! @brief 점으로 구분한 원본 조립 경로를 읽는다."""
    tokens = text.split(".")
    if not all(token.isascii() and token.isdecimal() and len(token) <= 2 for token in tokens):
        fail("원본 경로는 점으로 구분한 번호입니다. 예시 1.1.2", "instance_offsets")
    return [int(token) for token in tokens]


def _placement_text(item):
    """! @brief 면과 축 메이트, 위치 배치를 저장된 값에서 편집 구문으로 복원한다."""
    path = ".".join(map(str, item["path"]))
    if "mate" in item:
        mate = item["mate"]
        target = ".".join(map(str, mate["target_path"]))
        return f"{path} {mate['kind']} {mate['face']} = {target} {mate['target_face']} {mate['sense']}"
    values = [*item.get("target_origin_mm", item.get("translation_mm")), *item.get("rotation_deg", [])]
    separator = " = " if "target_origin_mm" in item else " "
    return path + separator + " ".join(format(value, ".17g") for value in values)


def _instance_offsets(text):
    """! @brief 경로별 상대 이동, 기판 원점 또는 두 부품의 면과 축 맞춤을 읽는다."""
    from rfad.domain.physical_setup import validate_instance_offsets

    result = []
    for line in text.splitlines():
        columns = line.split()
        if not columns:
            continue
        if len(columns) >= 2 and columns[1] in ("plane", "axis"):
            if (len(columns) != 7 or columns[3] != "="
                    or not all(token.isascii() and token.isdecimal() and len(token) <= 3
                               for token in (columns[2], columns[5]))):
                fail("메이트는 경로 plane/axis 면번호 = 상대경로 상대면번호 same/opposed 순서입니다.", "instance_offsets")
            result.append({"path": _part_path(columns[0]), "mate": {"kind": columns[1], "face": int(columns[2]),
                           "target_path": _part_path(columns[4]), "target_face": int(columns[5]), "sense": columns[6]}})
            continue
        point_mate = len(columns) > 1 and columns[1] == "="
        values = columns[2:] if point_mate else columns[1:]
        if len(values) not in (3, 6):
            fail("경로 뒤에 X Y Z 이동 또는 = X Y Z 기판 목표점(mm)을 입력하십시오. 마지막에 회전 세 축(deg)을 추가할 수 있습니다.",
                 "instance_offsets")
        position_key = "target_origin_mm" if point_mate else "translation_mm"
        row = {"path": _part_path(columns[0]),
               position_key: [number(value, "instance_offsets") for value in values[:3]]}
        if len(values) == 6:
            row["rotation_deg"] = [number(value, "instance_offsets") for value in values[3:]]
        result.append(row)
    result.sort(key=lambda row: row["path"])
    if result:
        validate_instance_offsets(result)
    return result


def _replacement_text(item):
    """! @brief 원본 경로와 독립 STEP 객체 ID 및 면 재대응을 편집 문자열로 돌린다."""
    parts = [".".join(map(str, item["path"])), item["source_part_id"]]
    return " ".join([*parts, *(f"{original}={new}" for original, new in item["faces"])])


def _replacements(text, model):
    """! @brief 저장된 STEP의 SHA를 고정하고 원래 면에서 새 면으로 가는 명시 대응을 읽는다."""
    from rfad.domain.physical_setup import validate_replacements

    available = {part["id"]: part["step"] for part in model["parts"] if part["kind"] == "step"}
    rows = []
    for line in text.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if len(tokens) < 2 or tokens[1] not in available:
            fail("대상 말단 경로와 저장된 교체 STEP 객체 ID를 입력하십시오.", "instance_replacements")
        pairs = [token.split("=") for token in tokens[2:]]
        if any(len(pair) != 2 or any(not n.isascii() or not n.isdecimal() or len(n) > 3 for n in pair) for pair in pairs):
            fail("면 대응은 원래면=새면 형식으로 지정하십시오.", "instance_replacements")
        rows.append({"path": _part_path(tokens[0]), "source_part_id": tokens[1],
                     "source_sha256": available[tokens[1]]["sha256"], "faces": [[int(a), int(b)] for a, b in pairs]})
    rows.sort(key=lambda row: row["path"])
    if rows:
        validate_replacements(rows)
    return rows


def _missing(key):
    """! @brief 입력하지 않은 치수에는 단위와 미정 상태만 부여한다."""
    return Quantity(None, "angle" if key == "yaw" else "length", "deg" if key == "yaw" else "mm", "missing", []).to_dict()


def _empty(section):
    """! @brief 새 양식에는 RF 물성이나 치수 기본값을 공급하지 않는다."""
    if section == "stack":
        return {"nominal": _missing("nominal"), "scope": None, "source_refs": []}
    result = {"name": "", "source_refs": []}
    if section != "scenario":
        dimensions = SURFACE_NUMBERS if section == "surface" else PART_NUMBERS
        result.update({key: _missing(key) for key in dimensions})
        result.update({key: key == "visible" for key in FLAGS})
        result.update(material_id=None)
        if section == "surface":
            result.update(kind="solder_mask", side="top", coverage="board", openings=[])
        else:
            result.update(kind="box", scenario_id=None, step=None)
    return result


def _record(model, section, identity):
    """! @brief 명시 ID 조회와 신규 양식을 구분한다."""
    if section == "activation":
        return {"active_scenario_id": model["active_scenario_id"]}
    if section == "stack":
        return model["stack"]
    if identity is None:
        return None
    row = next((row for row in model[COLLECTIONS[section]] if row["id"] == identity), None)
    if row is None:
        fail("선택한 물리 구성 항목이 현재 개정에 없습니다.", "record_id", "E_CONFLICT")
    return row


def _value(document, item, key, unit):
    """! @brief 수량 표시 반올림을 원본 값에 되먹임하지 않는다."""
    quantity = resolve_scalar(document, item, "angle" if key == "yaw" else "length")
    return "" if quantity.value_si is None else format(quantity.as_unit(unit), ".15g")


def _options(values, *, optional=False, unknown="미정"):
    """! @brief 표시 이름과 안정 ID를 분리한다."""
    return ([{"value": "", "label": unknown}] if optional else []) + [
        {"value": value, "label": label} for value, label in values]


def _descriptors(document, model, section, row):
    """! @brief 읽기/변경이 같은 필드 및 선택지 정의를 사용한다."""
    scenarios = [(item["id"], item["name"]) for item in model["scenarios"]]
    choices = {
        "coverage": _options([(key, LABELS[key]) for key in ("board", "rectangle")]),
        "side": _options([(key, LABELS[key]) for key in ("top", "bottom")]),
        "scope": _options([(key, LABELS[key]) for key in ("base", "with_surfaces")], optional=True),
        "kind": _options([(key, LABELS[key]) for key in (SURFACE_KINDS if section == "surface" else PART_KINDS)]),
        "material_id": _options([(item["id"], item["name"]) for item in document["materials"]], optional=True),
        "scenario_id": _options(scenarios, optional=True, unknown="선택 필요"),
        "active_scenario_id": _options(scenarios, optional=True, unknown="기준 PCB"),
    }
    result = []
    keys = {"surface": ("name", "kind", "side", "coverage", "offset", "thickness", "supply_thickness", "x", "y", "width", "height", "openings",
                        "material_id", "visible", "include_in_em", "include_in_export"),
            "part": ("name", "scenario_id", "kind", "x", "y", "z", "yaw", "width", "height", "depth", "case_thickness",
                     "instance_offsets", "instance_replacements", "material_id", "visible", "include_in_em", "include_in_export"),
            "stack": ("nominal", "scope"), "scenario": ("name",), "activation": ("active_scenario_id",)}[section]
    for key in keys:
        entry = {"key": key, "label": FIELDS[key]}
        if key in choices:
            entry.update(kind="choice", choices=choices[key], value=row[key] or "")
        elif key in FLAGS:
            entry.update(kind="bool", value=row[key])
        elif key == "openings":
            entry.update(kind="lines", value="\n".join(" ".join(_value(document, rect[item], item, "mm") or "-" for item in ("x","y","width","height"))
                                                       for rect in row[key]))
        elif key in ("instance_offsets", "instance_replacements"):
            format_item = _placement_text if key == "instance_offsets" else _replacement_text
            entry.update(kind="lines", value="\n".join(format_item(item) for item in row.get(key, [])))
        elif key == "name":
            entry.update(kind="text", value=row[key])
        else:
            unit = "deg" if key == "yaw" else "mm"
            quantity = row.get(key, _missing(key))
            entry.update(kind="quantity", unit=unit, value=_value(document, quantity, key, unit), original=deepcopy(quantity))
        result.append(entry)
    return result


def _quantity(old, key, text, reason):
    """! @brief 수정된 수치만 해석하고 기존 자료 및 결정 사유를 남긴다."""
    unit = "deg" if key == "yaw" else "mm"
    value = None if not text.strip() or text == "-" else number(text, key)
    refs = sources(old.get("source_refs", []), reason)
    if value is None:
        return {**_missing(key), "source_refs": refs}
    try:
        quantity = Quantity.from_value(value, unit, source_refs=refs).to_dict()
    except QuantityError as error:
        fail(str(error), key, "E_UNIT")
    if old.get("value_si") == quantity["value_si"]:
        return deepcopy(old)
    return quantity


def _openings(document, row, value, reason):
    """! @brief 개구 편집에서 수정하지 않은 개별 치수와 출처를 유지한다."""
    result = []
    keys = ("x", "y", "width", "height")
    for index, line in enumerate(line for line in value.splitlines() if line.strip()):
        columns = line.split()
        if len(columns) != 4 or index >= 8:
            fail("줄마다 X Y 폭 길이를 mm로 입력하십시오. 최대 8줄입니다.", "openings")
        old = row["openings"][index] if index < len(row["openings"]) else {key: _missing(key) for key in keys}
        result.append({key: deepcopy(old[key]) if (_value(document, old[key], key, "mm") or "-") == text
                       else _quantity(old[key], key, text, reason) for key, text in zip(keys, columns)})
    return result


def _parse_changes(document, model, section, row, changes, reason):
    """! @brief 전송된 변경 범위만 저장 가능한 수량 또는 참조로 변환한다."""
    entries = {entry["key"]: entry for entry in _descriptors(document, model, section, row)}
    result = deepcopy(row)
    for key, value in changes.items():
        entry = entries.get(key)
        if entry is None or type(value) is not type(entry["value"]):
            fail("편집 필드 값의 형식이 다릅니다.", key)
        if value == entry["value"]:
            continue
        if entry["kind"] == "choice":
            if value not in {item["value"] for item in entry["choices"]}:
                fail("목록에 있는 값을 선택하십시오.", key)
            result[key] = value or None
        elif entry["kind"] == "quantity":
            result[key] = _quantity(entry["original"], key, value, reason)
        elif key in ("instance_offsets", "instance_replacements"):
            offsets = _instance_offsets(value) if key == "instance_offsets" else _replacements(value, model)
            if offsets:
                result[key] = offsets
            else:
                result.pop(key, None)
        elif entry["kind"] == "lines":
            result[key] = _openings(document, row, value, reason)
        else:
            result[key] = value
    return result


def validate_input(context, data):
    """! @brief 영수증 접수 전에 요청 범위와 변경 사유를 검사한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    _fields(data, {"expected_revision", "command_id", "section", "record_id", "operation", "changes", "reason", "step_token"})
    for key in ("expected_revision", "command_id"):
        _uuid(data[key])
    _selection(data)
    if data["operation"] not in ("set", "remove") or type(data["changes"]) is not dict:
        fail("설치/적층 변경 형식이 다릅니다.", "operation")
    if data["step_token"] is not None:
        _uuid(data["step_token"])
    if data["operation"] == "remove" and (data["changes"] or data["step_token"] is not None or data["section"] == "activation"):
        fail("제거할 원본과 빈 변경 목록이 필요합니다.", "operation")
    _text(data["reason"], "reason", limit=512)


def _selection(data):
    """! @brief 단일 설정과 목록 행의 ID 계약을 확인한다."""
    if type(data["section"]) is not str or data["section"] not in SECTIONS:
        fail("지원하지 않는 설정 항목입니다.", "section")
    if data["record_id"] is not None:
        if data["section"] not in COLLECTIONS:
            fail("단일 설정에는 목록 ID가 없습니다.", "record_id")
        _uuid(data["record_id"])


class PhysicalSetupService:
    """! @brief 휘발성 STEP 검토 표와 영속 명령 경계를 연결한다."""

    def __init__(self, service):
        self.service = service
        self.previews = OrderedDict()
        self.lock = Lock()

    def _document(self, state, context, data):
        """! @brief 다른 개정에 대한 검토 결과와 명령을 사용하지 않는다."""
        document = self.service._load(self.service._project(state, context))
        if document["revision_id"] != data["expected_revision"]:
            fail("현재 개정에서 물리 구성을 다시 조회하십시오.", "expected_revision", "E_CONFLICT")
        return document

    def read(self, method, params):
        """! @brief 읽기 전용 폼과 실제 CAD STEP 검토를 분리한다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            fail("지원하지 않는 API 버전입니다.", "contract_version", "E_VERSION")
        context, data = params["context"], params["input"]
        _fields(context, {"project_id"})
        _uuid(context["project_id"])
        keys = {"expected_revision", "section", "record_id"} if method == "physical.setup.get" else {"expected_revision", "name", "chunks"}
        if method == "physical.step.preview" and "record_id" in data:
            keys = {"expected_revision", "record_id"}
        _fields(data, keys)
        _uuid(data["expected_revision"])
        document = self._document(self.service.journal.read(), context, data)
        if method == "physical.step.preview":
            if "record_id" in data:
                _uuid(data["record_id"])
                record = _record(setup(document), "part", data["record_id"])
                if record["kind"] != "step" or record["step"] is None:
                    fail("저장된 STEP 원본이 없습니다.", "record_id")
                source = record["step"]
                return {"preview_token": None, "name": source["name"], **self._saved_inspection(document["project_id"], source)}
            return self._preview(document, data)
        _selection(data)
        model = setup(document)
        section, identity = data["section"], data["record_id"]
        original = _record(model, section, identity)
        row = original if original is not None else _empty(section)
        previous_step = row.get("step")
        return {"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
                "section": section, "record_id": identity, "exists": original is not None,
                "records": {key: [{"id": item["id"], "name": item["name"]} for item in model[collection]]
                            for key, collection in COLLECTIONS.items()}, "fields": _descriptors(document, model, section, row),
                "replacement_sources": [{"id": p["id"], "name": p["name"]} for p in model["parts"]
                                        if p["kind"] == "step" and p["id"] != identity],
                "source_refs": row.get("source_refs", []),
                "step": None if previous_step is None else {key: previous_step[key] for key in ("name", "sha256")},
                "cad_configured": self.service.cad.runtime is not None, "active_scenario_id": model["active_scenario_id"],
                "stack_review": stack_review(document), "em_status": em_exclusions(document),
                "condition_status": "project_conditions_unconfirmed"}

    def _saved_inspection(self, project_id, source):
        """! @brief 같은 프로젝트, 실행 환경, 원본 SHA의 읽기 결과가 있으면 재사용한다."""
        with self.lock:
            for entry in reversed(self.previews.values()):
                if entry[0] == project_id and entry[2]["sha256"] == source["sha256"] and entry[4] is self.service.cad.runtime:
                    return deepcopy(entry[3])
        return self.service.cad.inspect_step(source)

    def _check_instance_references(self, project_id, part, model, inspected):
        """! @brief 원래 면과 교체 고체 면의 종류, 모든 메이트의 지정 면 번호를 적용 전에 대조한다."""
        paths = {tuple(item["path"]) for item in inspected["assembly_instances"] if not item["assembly"]}
        original = {(tuple(item["path"]), face["index"]): face["kind"]
                    for item in inspected.get("mate_faces", []) for face in item["faces"]}
        replaced, cache = {}, {}
        sources = {item["id"]: item for item in model["parts"]}
        for item in part.get("instance_replacements", []):
            path = tuple(item["path"])
            if path not in paths:
                fail("교체할 대상 말단 경로가 없습니다.", "instance_replacements")
            identity = item["source_part_id"]
            if identity not in cache:
                cache[identity] = self._saved_inspection(project_id, sources[identity]["step"])
            donor = cache[identity]
            if donor["shape"] != "single_solid":
                fail("교체 원본에는 하나의 닫힌 STEP 고체를 지정하십시오.", "instance_replacements")
            faces = {face["index"]: face["kind"] for leaf in donor["mate_faces"] for face in leaf["faces"]}
            links = {}
            for old, new in item["faces"]:
                if (path, old) not in original or faces.get(new) != original[path, old]:
                    fail("원본과 교체 부품에서 같은 종류의 평면 또는 원통 면을 대응하십시오.", "instance_replacements")
                links[old] = new
            replaced[path] = links
        for offset in part.get("instance_offsets", []):
            path = tuple(offset["path"])
            if path not in paths:
                fail("원본 STEP의 말단 부품 경로를 확인하십시오.", "instance_offsets", "E_CONFLICT")
            if "mate" in offset:
                mate = offset["mate"]
                for source, face in ((path, mate["face"]), (tuple(mate["target_path"]), mate["target_face"])):
                    if original.get((source, face)) != mate["kind"]:
                        fail("지정한 경로와 면 번호의 원본 평면 또는 원통면을 확인하십시오.", "instance_offsets")
                    if source in replaced and face not in replaced[source]:
                        fail("메이트가 참조하는 원본 면을 교체할 면 번호에 대응하십시오.", "instance_replacements")

    def _preview(self, document, data):
        """! @brief 실제 worker로 읽은 바이트만 해당 개정에서 채택할 수 있다."""
        chunks = data["chunks"]
        if type(chunks) is not list or not 1 <= len(chunks) <= 16 or any(type(item) is not str or len(item) > 4096 for item in chunks):
            fail("외부 STEP은 최대 48 KiB입니다.", "chunks", "E_RESOURCE")
        try:
            raw = base64.b64decode("".join(chunks), validate=True)
        except (ValueError, binascii.Error):
            fail("STEP의 base64 인코딩이 유효하지 않습니다.", "chunks")
        source = {"name": data["name"], "chunks": chunks, "sha256": hashlib.sha256(raw).hexdigest()}
        step_bytes(source)
        result = self.service.cad.inspect_step(source)
        if result.get("sha256") != source["sha256"]:
            fail("CAD 미리보기 결과 hash가 다릅니다.", "step", "E_HASH")
        token = str(uuid4())
        with self.lock:
            self.previews[token] = (document["project_id"], document["revision_id"], deepcopy(source), deepcopy(result), self.service.cad.runtime)
            if len(self.previews) > 16:
                self.previews.popitem(last=False)
        return {"preview_token": token, "name": source["name"], **result}

    def admit(self, state, context, data):
        """! @brief 검토한 원본과 물리 배치를 한 번의 undo 가능한 명령으로 보존한다."""
        document = self._document(state, context, data)
        model = setup(document)
        section, identity = data["section"], data["record_id"]
        original = _record(model, section, identity)
        remove = data["operation"] == "remove"
        if remove and original is None:
            fail("제거할 물리 구성 원본이 없습니다.", "record_id", "E_CONFLICT")
        display_only = False
        if remove:
            record = None
        else:
            row = original if original is not None else _empty(section)
            record = _parse_changes(document, model, section, row, data["changes"], data["reason"])
            if section != "part" and data["step_token"] is not None:
                fail("외부 물체에서만 STEP 원본을 적용할 수 있습니다.", "step_token")
            if section == "part" and record["kind"] == "step" and data["step_token"] is not None:
                with self.lock:
                    preview = self.previews.get(data["step_token"])
                if preview is None or preview[:2] != (document["project_id"], document["revision_id"]):
                    fail("현재 개정에서 STEP을 다시 미리 보십시오.", "step_token", "E_CONFLICT")
                record["step"] = deepcopy(preview[2])
            if section == "part":
                if record["kind"] == "step" and record["step"] is None:
                    fail("STEP 파일의 읽기 미리보기가 필요합니다.", "step_token")
                if record["kind"] != "step":
                    for key in ("instance_offsets", "instance_replacements"):
                        if key in data["changes"] and record.get(key):
                            fail("말단 배치와 교체는 외부 STEP 조립에만 적용할 수 있습니다.", key)
                        record.pop(key, None)
                    record["step"] = None
                placements = ("instance_offsets", "instance_replacements")
                changed = any(record.get(key) != (original or {}).get(key) for key in placements)
                if any(record.get(key) for key in placements) and (changed or data["step_token"] is not None):
                    previous_source = (original or {}).get("step")
                    if previous_source and record["step"]["sha256"] != previous_source["sha256"] and any(
                            record.get(key) and (original or {}).get(key) and key not in data["changes"] for key in placements):
                        fail("STEP 원본이 바뀌었습니다. 말단 배치와 교체 참조를 지우거나 새로 입력하십시오.",
                             "instance_offsets", "E_CONFLICT")
                    inspected = preview[3] if data["step_token"] is not None else self._saved_inspection(document["project_id"], record["step"])
                    self._check_instance_references(document["project_id"], record, model, inspected)
                if record["kind"] == "dielectric_case":
                    record.setdefault("case_thickness", _missing("case_thickness"))
                else:
                    if "case_thickness" in data["changes"]:
                        fail("벽 두께는 유전체 케이스에만 지정하십시오.", "case_thickness")
                    record.pop("case_thickness", None)
            if section == "surface":
                if record["kind"] != "bondply":
                    if "supply_thickness" in data["changes"]:
                        fail("공급 두께는 본드플라이에만 지정하십시오.", "supply_thickness")
                    record.pop("supply_thickness", None)
                elif original is None or original["kind"] != "bondply":
                    record.setdefault("supply_thickness", _missing("supply_thickness"))
            if data["step_token"] is not None and record.get("step") is None:
                fail("STEP 미리보기 사용 시 외부 STEP 종류를 선택하십시오.", "step_token")
            if record == original:
                fail("변경할 항목이 없습니다.", "changes", "E_CONFLICT")
            display_only = original is not None and {k for k in original.keys() | record.keys()
                                                      if original.get(k) != record.get(k)} == {"visible"}
            if "source_refs" in record:
                record["source_refs"] = sources(record["source_refs"], data["reason"])
            if section in COLLECTIONS:
                identity = identity or str(uuid4())
                record["id"] = identity
        if section == "part" and original is not None and record is not None and record["step"] == original["step"]:
            del record["step"]
        payload = {"section": section, "record_id": identity, "record": record, "display_only": display_only, "restore_absence": False}
        result = self.service._apply(state, context, {"expected_revision": data["expected_revision"], "command_id": data["command_id"],
                                                     "type": COMMAND, "payload": payload})
        state["commands"][data["command_id"]]["physical_setup_reason"] = data["reason"]
        return {**result, "record_id": None if remove else identity}
