"""! @brief 적층 초안과 같은 출처의 물성 제안을 읽기 전용 DTO로 조립한다."""

from copy import deepcopy

from rfad.catalog.models import CatalogError, canonical_json, stable_id
from rfad.catalog.stackup_match import resolve_layer_records
from rfad.catalog.suggested_properties import missing_property, property_choice, propose_property
from rfad.domain.material_models import TOTAL_TAN_DELTA_MODEL


SUGGESTION_SCHEMA = "rfad.pcb-stackup-suggestions/0.1"
MAX_RESULT_BYTES = 48 * 1024
MAX_PAGE_SIZE = 8


def _material(source, layer, properties):
    """! @brief 유전체 제안은 미정 적용 대역과 총 Df 모델을 명시하며 기존 재료를 대체하지 않는다."""
    return {
        "key": stable_id("suggested", source["catalog_id"], source["id"], layer["key"]),
        "name": (layer["name"] + " - 적층 물성 제안")[:256],
        "model": TOTAL_TAN_DELTA_MODEL,
        "model_reason": "총 Df 유전체 모델: 독립 전도도는 소비하지 않습니다.",
        "properties": {"epsilon_r": property_choice(properties["epsilon_r"]),
                       "tan_delta": property_choice(properties["tan_delta"]),
                       "conductivity": {"mode": "missing", "reason": "미정 전도도 보존, 총 Df 모델에서 미소비."}},
        "validity_hz": {"min": None, "max": None,
                        "reason": "모델 적용 대역은 미정입니다. 사용자가 별도로 지정해야 합니다."},
    }


def build_stackup_suggestions(reader, source, draft, *, offset=0, limit=MAX_PAGE_SIZE):
    """! @brief 조회는 프로젝트를 바꾸지 않으며 수용 가능한 공개값만 선택 초안으로 제공한다."""
    if type(offset) is not int or not 0 <= offset <= len(draft["layers"]):
        raise CatalogError("E_SCHEMA", "물성 제안의 페이지 시작 위치가 올바르지 않습니다.")
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise CatalogError("E_SCHEMA", "물성 제안은 한 페이지에 1~8개 층을 요청할 수 있습니다.")
    matches = resolve_layer_records(reader, source, draft)
    rows = []
    for layer in draft["layers"][offset:offset + limit]:
        if layer["role"] == "dielectric":
            match = matches[layer["key"]]
            properties = {"epsilon_r": propose_property(reader, match, "dk"),
                          "tan_delta": propose_property(reader, match, "df")}
            material = _material(source, layer, properties)
        else:
            properties = {key: missing_property("유전체 제안 대상 아님.", state="unsupported")
                          for key in ("epsilon_r", "tan_delta")}
            material = None
        notes = [item["message"] for item in draft["issues"] if layer["key"] in item.get("layer_keys", [])]
        rows.append({"layer_key": layer["key"], "name": layer["name"], "role": layer["role"],
                     "thickness_mm": layer["thickness_mm"], "thickness_state": layer["status"],
                     "thickness_basis": layer["thickness_basis"], "properties": properties,
                     "material_spec": material, "notes": notes})
    result = {"schema": SUGGESTION_SCHEMA, "source": deepcopy(source), "draft": deepcopy(draft),
              "layers": rows, "issues": deepcopy(draft["issues"]), "readiness": "not_assessed",
              "offset": offset, "total_count": len(draft["layers"]), "returned_count": len(rows),
              "next_offset": None,
              "limited_by_bytes": False}
    while True:
        end = offset + len(rows)
        result["returned_count"] = len(rows)
        result["next_offset"] = end if end < len(draft["layers"]) else None
        if len(canonical_json(result).encode("utf-8")) <= MAX_RESULT_BYTES:
            return result
        if len(rows) <= 1:
            raise CatalogError("E_RESOURCE", "적층과 한 층의 물성 제안이 응답 크기 상한을 초과했습니다.")
        rows.pop()
        result["limited_by_bytes"] = True
