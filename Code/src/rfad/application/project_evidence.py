"""! @brief 현재와 보존 개정의 출처, 가정과 변경을 읽기 전용으로 투영한다."""

import json
from itertools import islice

from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import display_names
from rfad.domain.sweep_selection import KEY as SWEEP_KEY
from rfad.domain.template_instance import EXTENSION_KEY, instance_status
from rfad.domain.units import Quantity, QuantityError


METHOD = "project.evidence"

_MAX_RECOVERY_ROWS = 96
_MAX_RECOVERY_BYTES = 128 * 1024
_MISSING = object()
_SECTION_NAMES = {
    "metadata": "프로젝트", "board": "기판", "geometry": "형상", "stackup": "적층", "ports": "급전",
    "targets": "목표", "materials": "재료", "parameters": "매개변수", "nets": "넷", "frames": "좌표계",
    "environment": "외부 환경", "extensions": "확장 데이터", "connections": "연결",
}
_FIELD_NAMES = {
    "name": "이름", "description": "설명", "width": "폭", "height": "높이", "radius": "반지름",
    "diameter": "지름", "thickness": "두께", "start": "시작점", "end": "끝점", "center": "중심",
    "resistance": "저항", "reference_plane": "기준면", "layer_id": "층", "material_id": "재료",
    "source_refs": "출처", "value_si": "값 (SI)", "display_unit": "표시 단위", "order": "순서",
    "value": "값", "include_in_em": "해석 포함", "include_in_export": "출력 포함",
}


def _display(value):
    """! @brief 작은 DTO에 상태와 단위를 보존하며 큰 원문요소는 표시 범위를 명시한다."""
    if value is None:
        return "미정"
    if isinstance(value, dict) and "value_si" in value:
        unit = value.get("display_unit", "")
        try:
            quantity = Quantity(**value)
        except (TypeError, QuantityError):
            pass
        else:
            if quantity.value_si is None:
                return "미정"
            try:
                return f"{quantity.as_unit(unit):.12g} {unit} / {quantity.status.value}"
            except QuantityError:
                return f"{quantity.value_si:.12g} SI / {quantity.status.value}"
    if isinstance(value, list) and len(value) <= 3:
        return " / ".join(_display(item) for item in value)
    text = str(value)
    return text if len(text) <= 320 else text[:320] + " ... (표시 일부)"


def _template(record, document, objects):
    """! @brief 보존한 문헌과 적용 입력, 현재 형상 값을 서로 다른 열로 나눈다."""
    card = record["card"]
    items = []
    for field in card.get("input_fields", []):
        key = field["key"]
        reference = card.get("reference_inputs", {}).get(key, {})
        reference_value = reference.get("quantity")
        items.append([field["label"], _display(reference_value), _display(record["inputs"].get(key)),
                      "아래 생성 객체의 현재 치수 참고"])
    dimensions = {"radius": "반지름", "width": "폭", "diameter": "지름", "start_angle": "시작각",
                  "sweep_angle": "회전각", "start": "시작점", "end": "끝점", "center": "중심"}
    for original in record["objects"]["geometry"][:8]:
        current = objects.get(original["id"])
        label = original.get("name") or original.get("label") or original.get("kind", "형상")
        current_name = "현재 개정에 없음"
        if current:
            current_name = current.get("name") or current.get("label") or label
        items.append([label, "생성 객체 / 표시 이름", label, current_name])
        for key, caption in dimensions.items():
            if key in original:
                items.append([caption, label, _display(original[key]),
                              _display(current.get(key)) if current else "현재 개정에 없음"])
    source = card.get("source", {})
    evidence = card.get("evidence", {})
    status = instance_status(document, record)
    notes = [source.get("scope", ""), *source.get("references", []),
             f"기준 개정 {record['base_revision']}", f"보존 사본 SHA-256 {record['source_document_hash']}",
             f"채택 기록 SHA-256 {record['record_hash']}", status["generation"]["summary"],
             f"생성 뒤 수정 / 삭제 {len(status['changes'])}개"]
    for key, caption in (("archive_path", "원문 경로"), ("archive_sha256", "원문 SHA-256"),
                         ("inner_member", "원문 내부 항목"), ("inner_sha256", "내부 항목 SHA-256")):
        if evidence.get(key):
            notes.append(f"{caption} {evidence[key]}")
    assumptions = [*card.get("assumptions", []), *card.get("limitations", [])]
    if record.get("port_recipe") is None:
        assumptions.append("이 생성에는 급전 정의를 포함하지 않았습니다.")
    assumptions.extend(f"생략: {_display(item)}" for item in evidence.get("omitted", []))
    assumptions.extend(f"미정: {_display(item)}" for item in evidence.get("unknown", []))
    return {"label": card["name"], "values": items, "source": "\n".join(_display(note) for note in notes[:20]),
            "assumptions": "\n".join(_display(item) for item in assumptions[:20])}


def _target(record):
    """! @brief 저장한 목표의 원 출처와 판정 한계를 현재 개정에서 읽는다."""
    rows = []
    for item in record.get("criteria", [])[:20]:
        limit = item["limit"]
        operator = {"le": "<=", "ge": ">="}.get(item["operator"], item["operator"])
        value = "미정" if limit["value"] is None else f"{operator} {limit['value']} {limit['unit']}"
        rows.append(["성능 기준", item["metric"], "저장한 목표", f"{value} / {limit['status']}"])
    source = list(record.get("source_refs", []))
    for item in record.get("criteria", []):
        source.extend(item["limit"]["source_refs"])
    return {"label": f"목표 / {record['name']}", "values": rows,
            "source": "\n".join(_display(item) for item in list(dict.fromkeys(source))[:15]),
            "assumptions": "목표 입력을 표시합니다. 목표 평가 결과는 결과 작업 영역에서 확인합니다."}


def _sweep(record, parameters):
    """! @brief 채택한 값과 현재 매개변수를 이름과 함께 대조한다."""
    rows = []
    for row in record["values"][:20]:
        current = parameters.get(row["id"], {})
        rows.append([current.get("name", row["id"]), _display(row["before"]), _display(row["after"]),
                     _display(current.get("quantity"))])
    source = (f"원본 개정 {record['source_revision_id']}\n연구 {record['study_id']}\n"
              f"후보 순서 {record['calculated_ordinal']}\n채택 사유 {record['reason']}\n"
              f"채택 기록 SHA-256 {record['record_hash']}")
    return {"label": f"설계 스윕 / 후보 {record['calculated_ordinal']}", "values": rows,
            "source": source, "assumptions": "정해진 후보의 편집 사본입니다. 새 개정의 해석 및 측정은 별도입니다."}


def _recovery_value(value, field):
    """! @brief 빈 문자열, 미정값과 개정에 항목 자체가 없는 상태를 구분한다."""
    if value is _MISSING:
        return "항목 없음"
    if value is None:
        return "미정"
    text = (value or "빈 값") if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    maximum = 4096 if field == ("description",) else 640
    return text if len(text) <= maximum else text[:maximum] + " ... (표시 일부)"


def _recovery_fields(before, after, field=()):
    """! @brief 객체 안의 바뀐 경로만 반환하고 추가·삭제된 값은 한 행으로 유지한다."""
    if before == after:
        return
    if isinstance(before, dict) and isinstance(after, dict):
        quantity_keys = {"value_si", "display_unit", "dimension", "status", "source_refs"}
        quantity = before.keys() == after.keys() == quantity_keys
        display_keys = {"value_si", "display_unit", "dimension"}
        if quantity and any(before[key] != after[key] for key in display_keys):
            yield field + ("value",), _display(before), _display(after)
        for key in dict.fromkeys((*before, *after)):
            if quantity and key in display_keys:
                continue
            yield from _recovery_fields(before.get(key, _MISSING), after.get(key, _MISSING), (*field, key))
    else:
        yield field, _recovery_value(before, field), _recovery_value(after, field)


def _recovery_rows(saved, current):
    """! @brief 같은 안정 ID의 항목을 대응시키고 실제 변경된 값과 경로를 표시한다."""
    names = {**display_names(saved), **display_names(current)}
    sections = tuple(_SECTION_NAMES) + tuple(key for key in dict.fromkeys((*saved, *current)) if key not in _SECTION_NAMES and key not in {
        "schema_version", "project_id", "revision_id", "parent_revision_ids",
    })
    for section in sections:
        caption = _SECTION_NAMES.get(section, section)
        before, after = saved.get(section, _MISSING), current.get(section, _MISSING)
        if before == after:
            continue
        if section == "metadata":
            before = {key: before[key] for key in ("name", "description")}
            after = {key: after[key] for key in ("name", "description")}
        items = [("", before, after)]
        if section == "parameters":
            items = [(key, before.get(key, _MISSING), after.get(key, _MISSING))
                     for key in dict.fromkeys((*before, *after))]
        elif isinstance(before, list) and isinstance(after, list) and all(
                isinstance(row, dict) and isinstance(row.get("id"), str) for row in (*before, *after)):
            prior, recent = ({row["id"]: row for row in side} for side in (before, after))
            items = [(key, prior.get(key, _MISSING), recent.get(key, _MISSING))
                     for key in dict.fromkeys((*prior, *recent))]
            common = prior.keys() & recent.keys()
            old_order, new_order = ([key for key in side if key in common] for side in (prior, recent))
            if old_order != new_order:
                yield [caption, "", "목록 순서", _recovery_value(old_order, ()), _recovery_value(new_order, ())]
        for key, old, new in items:
            item = new if new is not _MISSING else old
            label = names.get(key) or (item.get("name") if isinstance(item, dict) else None) or key
            for field, original, edited in _recovery_fields(old, new):
                path = " / ".join(_FIELD_NAMES.get(part, part) for part in field)
                status = "추가" if old is _MISSING else "삭제" if new is _MISSING else "값"
                yield [caption, label, path or status, original, edited]


def read(service, params):
    """! @brief 조회 한 번에 최대 24개 출처와 현재 이력의 최근 24개 변경을 반환한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    data = _fields(params["input"], {"expected_revision"}, {"target_id"})
    expected = _uuid(data["expected_revision"])
    target_id = _uuid(data["target_id"]) if "target_id" in data else None
    state = service.journal.read()
    project = service._project(state, params["context"])
    document = service._load(project)
    revision = document["revision_id"]
    service._check_history_head(project, revision)
    if expected != revision:
        raise ProjectError("E_CONFLICT", "출처 조회의 기준 개정이 변경됐습니다.")
    saved = document if project["current"] == project["saved"] else service.repository.read(project["saved"])[1]
    objects = {item["id"]: item for item in document["geometry"]}
    parameters = document["parameters"]
    ext = document["extensions"]
    if target_id is None:
        adopted = [_template(row, document, objects)
                   for row in ext.get(EXTENSION_KEY, {}).get("instances", [])[-8:]]
        adopted.extend(_sweep(row, parameters) for row in ext.get(SWEEP_KEY, {}).get("records", [])[-8:])
        adopted.extend(_target(row) for row in document["targets"][:8])
    else:
        target = next((item for item in document["targets"] if item["id"] == target_id), None)
        if target is None:
            raise ProjectError("E_SCHEMA", "현재 개정에서 목표를 찾지 못했습니다.")
        adopted = [_target(target)]
    history = []
    undo = project["history"]["undo"]
    for key in reversed(undo if target_id else undo[-24:]):
        record = state["commands"].get(key)
        if record and record["project_id"] == document["project_id"]:
            cmd = record.get("command", {})
            payload = cmd.get("payload", {})
            target = payload.get("target")
            target_key = target.get("id", "") if isinstance(target, dict) else ""
            identity = payload.get("id", payload.get("instance_id", target_key))
            if not isinstance(identity, str):
                identity = ""
            if target_id is not None and (cmd.get("type") not in {"target.set", "target.remove", "target.constraints.set"}
                                          or identity != target_id):
                continue
            history.append([record["old_revision"], record["new_revision"], cmd.get("type", "기록 없음"),
                            _display(objects.get(identity, {}).get("name") or identity)])
    recovery = [["개정", saved["revision_id"], revision],
                ["프로젝트 이름", saved["metadata"]["name"], document["metadata"]["name"]]]
    collections = {"geometry": "형상", "stackup": "적층", "ports": "급전", "targets": "목표"}
    for key, caption in collections.items():
        before, after = saved[key], document[key]
        recovery.append([caption, str(len(before)), f"{len(after)} / {'동일' if before == after else '내용 변경'}"])
    details = []
    size = 0
    has_more = False
    for row in islice(_recovery_rows(saved, document), _MAX_RECOVERY_ROWS + 1):
        size += len(canonical_bytes(row)) + 1
        if len(details) == _MAX_RECOVERY_ROWS or size > _MAX_RECOVERY_BYTES:
            has_more = True
            break
        details.append(row)
    return {"project_id": document["project_id"], "revision_id": revision, "records": adopted, "history": history[:24],
            "recovery_details": {"rows": details, "has_more": has_more},
            "history_total": len(history) if target_id else len(undo), "redo_count": len(project["history"]["redo"]), "recovery": recovery,
            "saved_revision": saved["revision_id"]}
