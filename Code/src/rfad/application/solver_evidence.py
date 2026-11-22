"""! @brief 완료된 PCB 해석에서 봉인 개정, 조건, 입력과 출처를 읽는다."""

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import PROFILE as PCB_PROFILE, validate_settings
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import display_names
from rfad.domain.pcb_evidence_pool import POOL_SCHEMA
from rfad.domain.pcb_selection import EXTENSION_KEY
from rfad.domain.pcb_selection_evidence import encoded


METHOD = "result.solver_evidence"


def pcb_result_plan(service, state, project_id, result_id):
    """! @brief 결과의 소유 범위와 원래 계획 및 개정의 해시를 대조한다."""
    result = state["solver_results"].get(result_id)
    if result is None or result["project_id"] != project_id or result["metadata"]["profile"] != PCB_PROFILE:
        raise ProjectError("E_MISSING_ARTIFACT", "이 프로젝트의 사용자 PCB 해석 결과를 찾지 못했습니다.")
    plan_id = result["analysis_plan_id"]
    row = state["analysis_plans"].get(plan_id)
    if row is None or row["project_id"] != project_id:
        raise ProjectError("E_MISSING_ARTIFACT", "결과의 원래 해석 계획을 찾지 못했습니다.")
    reference = row["reference"]
    _, plan = service.solver._record(state, "analysis_plans", reference, "plan_id", project_id)
    snapshot, document = plan["snapshot"], plan["source_semantics"]
    if (plan["plan_id"] != plan_id or plan["analysis_profile"] != PCB_PROFILE
            or snapshot != result["snapshot"] or snapshot["project_id"] != project_id
            or any(document[key] != snapshot[key] for key in ("project_id", "revision_id", "schema_version"))
            or canonical_hash(document) != snapshot["content_hash"]):
        raise ProjectError("E_HASH", "결과와 원래 해석 계획의 개정 또는 해시가 다릅니다.")
    validate_settings(plan["case"]["settings"])
    return reference, plan


def _recorded_objects(document, case):
    """! @brief 실제 계획에 포함한 재료, 급전, 양단과 적층을 원본 ID로 연결한다."""
    groups = {}
    for kind, collection, items in (
        ("material", "materials", case["materials"]),
        ("port", "ports", [case["port"]]),
        ("terminal", "geometry", [item for item in case["shapes"] if item["id"] in
                                 (case["port"]["positive_geometry_id"], case["port"]["reference_geometry_id"])]),
        ("layer", "stackup", case["layers"]),
    ):
        names = display_names(document, collection)
        by_id = {item["id"]: item for item in document[collection]}
        for computed in items:
            identity = computed["id"]
            if identity not in by_id:
                raise ProjectError("E_HASH", "계획의 계산 입력 ID에 해당하는 봉인 원본이 없습니다.")
            groups[kind, identity] = (names[identity], by_id[identity], computed)
    return groups


def _quantity_sources(document, original):
    """! @brief 원본 수량 및 참조 매개변수의 필드별 출처와 당시 평가 값을 찾는다."""
    refs = {}
    parameters = {}

    def parameter_sources(identity, field):
        """! @brief 같은 매개변수는 한 번만 읽고 당시 표현식의 의존 출처도 따라간다."""
        pending = [(identity, field)]
        while pending:
            key, path = pending.pop()
            if key in parameters:
                if path not in parameters[key]["fields"]:
                    parameters[key]["fields"].append(path)
                continue
            parameter = document["parameters"][key]
            parameters[key] = {"fields": [path], "original": parameter}
            location = f'parameters.{key}'
            walk(parameter["quantity"], location + ".quantity")
            bindings = parameter.get("expression", {}).get("bindings", {})
            pending.extend((target, f"{location}.expression.bindings.{name}")
                           for name, target in reversed(tuple(bindings.items())))

    def walk(value, field):
        """! @brief 중첩 수량을 원래 경로와 함께 보존한다."""
        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{field}[{index}]")
        if not isinstance(value, dict):
            return
        if "parameter_id" in value:
            parameter_sources(value["parameter_id"], field)
            return
        for reference in value.get("source_refs", []):
            refs.setdefault(reference, []).append(field + ".source_refs" if field else "source_refs")
        if isinstance(value.get("source_ref"), str):
            refs.setdefault(value["source_ref"], []).append(field + ".source_ref" if field else "source_ref")
        for name, child in value.items():
            if name not in ("source_refs", "source_ref"):
                walk(child, f"{field}.{name}" if field else name)

    walk(original, "")
    return refs, parameters


def _catalog_sources(document, kind, original):
    """! @brief 봉인된 카탈로그 원문과 이 입력값에 일치하는 채택 포인터를 찾는다."""
    selection = document["extensions"].get(EXTENSION_KEY)
    if selection is None:
        return {}, {}
    collection = {"material": "materials", "port": "ports", "terminal": "geometry", "layer": "stackup"}[kind]
    records = (selection, *selection.get("history", []))
    if selection["schema"] == POOL_SCHEMA:
        entries = selection["evidence_pool"]
    else:
        entries = [row for record in records for row in record["evidence"]]
    citations = {}
    for record in records:
        for decision in record["decisions"]:
            target, reference = decision["target"], decision["evidence_id"]
            if reference is None or target["collection"] != collection or target["id"] != original["id"]:
                continue
            value = original
            for key in target["field"].split("."):
                value = value.get(key) if isinstance(value, dict) else None
            if value is not None and encoded(value) == decision["value_json"]:
                citations.setdefault(reference, []).append({"field": target["field"], "basis": decision["basis"],
                    "pointer": decision["source_pointer"], "reason": decision["reason"], "catalog": record["catalog"]})
    return {row["id"]: row for row in entries}, citations


def read(service, params):
    """! @brief 현재 편집 개정과 독립적으로 선택 결과의 봉인 입력을 조회한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    context = _fields(params["context"], {"project_id"})
    project_id = _uuid(context["project_id"])
    data = _fields(params["input"], {"artifact_id"}, {"page", "kind", "id", "source_index"})
    result_id = _uuid(data["artifact_id"])
    page = data.get("page", "summary")
    page_fields = {"summary": set(), "revision": set(), "object": {"kind", "id"},
                   "source": {"kind", "id", "source_index"}}
    if not isinstance(page, str) or page not in page_fields or set(data) - {"artifact_id", "page"} != page_fields[page]:
        raise ProjectError("E_SCHEMA", "해석 출처 조회의 대상이나 항목이 올바르지 않습니다.")
    state = service.journal.read()
    project = service._project(state, context)
    reference, plan = pcb_result_plan(service, state, project_id, result_id)
    document, snapshot, case = plan["source_semantics"], plan["snapshot"], plan["case"]
    reply = {"artifact_id": result_id, "revision_id": snapshot["revision_id"], "page": page}
    if page == "revision":
        # @brief 계획 속 사본의 의미와 함께 원래 스냅샷 바이트도 대조한다.
        raw, original = service.repository.read(snapshot["artifact"])
        if canonical_hash(original) != snapshot["content_hash"]:
            raise ProjectError("E_HASH", "봉인 스냅샷 파일이 계획 안의 개정과 다릅니다.")
        return {**reply, "document_json": raw.decode("utf-8")}
    objects = _recorded_objects(document, case)
    if page == "summary":
        current = service._load(project)
        return {**reply, "name": document["metadata"]["name"], "description": document["metadata"]["description"],
                "current_revision_id": current["revision_id"], "snapshot": snapshot, "plan": reference,
                "settings": case["settings"], "objects": [{"kind": kind, "id": identity, "name": item[0]}
                                                           for (kind, identity), item in objects.items()],
                "terminals": {key: case["port"][key] for key in ("positive_geometry_id", "reference_geometry_id")}}
    kind, identity = data["kind"], _uuid(data["id"])
    if not isinstance(kind, str) or (kind, identity) not in objects:
        raise ProjectError("E_MISSING_ARTIFACT", "선택 대상은 이 결과의 계산 입력에 없습니다.")
    name, original, computed = objects[kind, identity]
    refs, parameters = _quantity_sources(document, original)
    catalog, citations = _catalog_sources(document, kind, original)
    for reference, decisions in citations.items():
        refs.setdefault(reference, []).extend(decision["field"] for decision in decisions)
    sources = [{"reference": ref, "fields": list(dict.fromkeys(fields))} for ref, fields in refs.items()]
    if page == "source":
        index = data["source_index"]
        if type(index) is not int or not 0 <= index < len(sources):
            raise ProjectError("E_SCHEMA", "선택 입력에 기록된 출처 번호가 아닙니다.")
        entry = sources[index]
        reference = entry["reference"]
        return {**reply, **entry, "record": catalog.get(reference), "citations": citations.get(reference, [])}
    return {**reply, "kind": kind, "id": identity, "name": name, "original": original, "used": computed,
            "parameters": parameters, "sources": sources}
