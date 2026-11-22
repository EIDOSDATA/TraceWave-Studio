"""! @brief 현재와 보존 개정의 출처, 가정과 변경을 읽기 전용으로 투영한다."""

from rfad.application.project_contract import _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.sweep_selection import KEY as SWEEP_KEY
from rfad.domain.template_instance import EXTENSION_KEY, instance_status
from rfad.domain.units import Quantity, QuantityError


METHOD = "project.evidence"


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
    return {"project_id": document["project_id"], "revision_id": revision, "records": adopted, "history": history[:24],
            "history_total": len(history) if target_id else len(undo), "redo_count": len(project["history"]["redo"]), "recovery": recovery,
            "saved_revision": saved["revision_id"]}
