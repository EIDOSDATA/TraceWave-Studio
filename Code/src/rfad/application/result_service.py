"""! @brief 결과 조회/표/비교/Smith를 원본 변경 없는 유한 공개 RPC로 제공한다."""

from copy import deepcopy

from rfad.application.canonical import canonical_bytes
from rfad.application.project_contract import _fields, _uuid
from rfad.application.network_records import samples
from rfad.application.result_sources import fail, resolve, validate_pin
from rfad.application import result_catalog, result_complex


PROFILE = "rfad.result-workspace/0.1"
FIELDS = {
    "result.revisions": {"offset", "limit", "catalog_hash"},
    "result.sources": {"kind", "revision_id", "snapshot_id", "study_id", "offset", "limit", "catalog_hash"},
    "result.describe": {"source"},
    "result.page": {"source", "pin", "row", "column", "offset", "limit"},
    "result.marker": {"source", "pin", "row", "column", "frequency_hz"},
    "result.smith": {"source", "pin", "port", "chart", "offset", "limit"},
    "result.export": {"source", "pin", "format"},
    "result.field.describe": {"source", "pin"},
    "result.field.page": {"source", "pin", "monitor_id", "frequency_index", "component", "plane", "roi", "stride"},
    "result.compare": {"left", "right", "right_port_order", "row", "column", "frequency_policy", "offset", "limit"},
    "result.conditions": {"left", "right", "offset", "limit"},
}
READS = {*FIELDS, "result.metrics", "result.radiation"}


def bounded(result):
    """! @brief 원문을 조용히 잘라내지 않고 결과 응답 예산을 검사한다."""
    if len(canonical_bytes(result)) > 256 * 1024:
        fail("결과 응답이 256 KiB를 초과했습니다. 작은 페이지로 조회하십시오.", "E_RESOURCE")
    return result


def _selection(value):
    """! @brief 비교 자료도 source와 고정 pin을 함께 요구한다."""
    _fields(value, {"source", "pin"})
    validate_pin(value["pin"])
    return value


def _identity(value):
    """! @brief 응답 문맥에 필요한 원본 선택과 pin만 복제한다."""
    return {"source": deepcopy(value["source"]), "pin": deepcopy(value["pin"])}


def _describe(value):
    """! @brief 실제 입력 개정/조건과 당시 평가를 작은 조회 DTO로 구분한다."""
    from rfad.application.result_export import available_formats

    current = value["current_document"]["revision_id"]
    source_revision = value["source_revision"]["id"]
    radiation = value["normalized"] is not None and "radiation_summary" in value["normalized"]
    field = value["normalized"] is not None and "loss_recording" in value["normalized"]["provenance"]["analysis_plan"]["case"]
    return {"profile": "rfad.result-view/0.1", **_identity(value), "label": value["label"],
        "source_revision": deepcopy(value["source_revision"]), "current_revision_id": current,
        "source_document_role": value["source_document_role"], "is_current_design": current == source_revision,
        "stale_reasons": [] if current == source_revision else ["design_revision_differs"],
        "descriptor": deepcopy(value["descriptor"]), "states": deepcopy(value["states"]),
        "reference_scope": deepcopy((value["dataset"].get("conditions") or {}).get("reference_scope")),
        "numerical_details": deepcopy(value["numerical_details"]),
        "source_time": value.get("source_time"), "source_time_kind": value.get("source_time_kind"),
        "available_views": {"network": True, "smith": value["dataset"]["parameter_kind"] == "S",
                            "metrics": radiation, "radiation": radiation, "field": field},
        "available_exports": available_formats(value),
        "view_reasons": {"physics": "계산 또는 가져온 자료의 표시이며 독립 물리 검증은 별도입니다."},
        "source_refs": deepcopy(value["dataset"]["source_refs"]),
        "historical_assessments": deepcopy(value["historical_assessments"]),
        "calculated_ordinal": value["calculated_ordinal"], "selection_values": deepcopy(value["selection_values"])}


def read(service, method, params):
    """! @brief 결과를 읽을 뿐 프로젝트 개정/이력/파일이나 과거 평가를 게시하지 않는다."""
    if method == "result.metrics":
        from rfad.application.result_metrics import metrics
        return metrics(service, params)
    if method == "result.radiation":
        from rfad.application.result_radiation import radiation
        return radiation(service, params)
    if method not in FIELDS:
        fail("지원하지 않는 결과 조회입니다.", "E_UNSUPPORTED")
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        fail("지원하지 않는 결과 API 버전입니다.", "E_VERSION")
    context, data = params["context"], params["input"]
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    _fields(data, FIELDS[method])
    if method == "result.revisions":
        return result_catalog.revisions(service, context, data)
    if method == "result.sources":
        return result_catalog.sources(service, context, data)
    if method in ("result.compare", "result.conditions"):
        pair = [_selection(data[key]) for key in ("left", "right")]
        left, right = [resolve(service, context, item["source"], item["pin"]) for item in pair]
        conditions = result_complex.condition_differences(left, right)
        if method == "result.conditions":
            offset, limit = data["offset"], data["limit"]
            if type(offset) is not int or not 0 <= offset < len(conditions) or type(limit) is not int or not 1 <= limit <= 32:
                fail("조건 비교 페이지는 유효한 시작 순번과 1~32개 크기가 필요합니다.", "E_RESOURCE")
            rows = conditions[offset:offset + limit]
            return bounded({"profile": "rfad.result-conditions/0.1", "left": _identity(left), "right": _identity(right),
                "items": rows, "offset": offset, "total": len(conditions),
                "next_offset": offset + len(rows) if offset + len(rows) < len(conditions) else None})
        result = result_complex.compare_data(left["dataset"], right["dataset"], data)
        return bounded({"profile": "rfad.result-comparison/0.1", "left": _identity(left), "right": _identity(right), **result,
            "condition_differences": conditions[:32], "condition_count": len(conditions), "condition_next_offset": 32 if len(conditions) > 32 else None,
            "historical_assessments": {"left": left["historical_assessments"], "right": right["historical_assessments"]}})
    if method != "result.describe":
        validate_pin(data["pin"])
    value = resolve(service, context, data["source"], None if method == "result.describe" else data["pin"])
    if method == "result.describe":
        return bounded(_describe(value))
    if method == "result.export":
        from rfad.application.result_export import exported

        return exported(service, value, data["format"])
    arguments = {key: item for key, item in data.items() if key not in ("source", "pin")}
    if method in ("result.field.describe", "result.field.page"):
        from rfad.application import result_fields

        if method == "result.field.describe":
            return result_fields.describe(service, value)
        return result_fields.page(service, value, arguments)
    if method == "result.page":
        payload = {"page": samples(value["dataset"], **arguments)}
    elif method == "result.marker":
        payload = result_complex.marker(value["dataset"], **arguments)
    else:
        from rfad.application import result_smith

        payload = result_smith.project(value["dataset"], **arguments)
    return bounded({"profile": "rfad." + method.removeprefix("result.") + "-view/0.1", **_identity(value), **payload})
