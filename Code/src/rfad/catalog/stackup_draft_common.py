"""! @brief 제조업체 원문을 추정 없이 보존하는 적층 초안 도구를 정의한다."""

import math
import re

from rfad.catalog.models import CatalogError, stable_id


DRAFT_SCHEMA = "rfad.pcb-stackup-draft/0.1"
MAX_DRAFT_LAYERS = 256


def positive(value: object) -> float | None:
    """! @brief 불리언, 문자열, 비유한값과 비양수를 길이로 채택하지 않는다."""
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def object_raw(row: dict) -> dict:
    """! @brief 구조 변환 대상의 원문이 JSON object인지 확인한다."""
    if type(row.get("raw")) is not dict:
        raise CatalogError("E_SCHEMA", "적층 원문은 JSON object여야 합니다.")
    return row["raw"]


def decimal_mm(value: object) -> float | None:
    """! @brief mm 열의 단일 십진수만 읽고 oz나 복합 문구를 변환하지 않는다."""
    if type(value) is not str or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value.strip()) is None:
        return None
    return positive(float(value))


def issue(draft: dict, code: str, message: str, keys: list[str] | None = None, *, blocker: bool = False) -> None:
    """! @brief 미정 물성과 층 구성 오류를 구분한 진단을 추가한다."""
    draft["issues"].append({"code": code, "severity": "blocker" if blocker else "warning",
                            "message": message, "layer_keys": [] if keys is None else keys})


def new_draft(reader, row: dict, entity: str) -> dict:
    """! @brief 카탈로그 개정과 원문 개체 해시를 초안 식별에 포함한다."""
    catalog_id = reader.catalog()["catalog_id"]
    item_id = row["template_id"] if entity == "native_templates" else row["record_id"]
    source = reader.source_evidence(row["source_id"])
    return {
        "schema": DRAFT_SCHEMA,
        "id": stable_id("draft", DRAFT_SCHEMA, catalog_id, entity, item_id, row["raw_sha256"]),
        "catalog_id": catalog_id, "publisher": row["publisher"],
        "template_id": item_id if entity == "native_templates" else None,
        "record_id": item_id if entity == "observations" else None,
        "source_order": "top_to_bottom", "layer_order": "bottom_to_top",
        "nominal_thickness_mm": None, "thickness_convention": "source_nominal_unverified",
        "layers": [], "issues": [], "evidence_ids": [source["id"]],
    }


def capture(reader, draft: dict, entity: str, item_id: str, pointers: list[str] | None = None) -> str:
    """! @brief 선택 필드의 타입과 큰 정수 원문을 reader의 증거 사본에 보존한다."""
    evidence = reader.capture(entity, item_id, pointers=pointers)
    if evidence["id"] not in draft["evidence_ids"]:
        draft["evidence_ids"].append(evidence["id"])
    return evidence["id"]


def layer(draft: dict, key: str, name: str, role: str, thickness: float | None,
          basis: str, evidence: str, source_order: int, *, thickness_pointer: str | None = None,
          thickness_evidence: str | None = None) -> None:
    """! @brief 원문 위에서 아래 순서로 층을 적재하며 아직 z 좌표를 만들지 않는다."""
    if len(draft["layers"]) >= MAX_DRAFT_LAYERS:
        raise CatalogError("E_RESOURCE", "적층 초안의 층 수가 허용 범위를 초과했습니다.")
    draft["layers"].append({"key": key, "name": name[:240], "role": role,
                            "thickness_mm": thickness,
                            "status": "source_value" if thickness is not None else "unresolved",
                            "thickness_basis": basis, "evidence_ids": [evidence],
                            "thickness_source_pointer": thickness_pointer if thickness is not None else None,
                            "thickness_evidence_id": (thickness_evidence or evidence) if thickness is not None else None,
                            "source_order": source_order})


def finish(draft: dict, expected_copper: object = None, *, require_count: bool = False) -> dict:
    """! @brief 물성 자동 채택을 금지하고 완성 두께 및 층수의 한계를 명시한다."""
    if type(expected_copper) is int and expected_copper > 0:
        actual = sum(item["role"] == "conductor" for item in draft["layers"])
        if actual != expected_copper:
            issue(draft, "copper_layer_count_mismatch", "원문 동박 층수와 변환한 도체 층수가 다릅니다.", blocker=True)
        else:
            names = [item["name"].removesuffix("-CU") for item in draft["layers"] if item["role"] == "conductor"]
            if names != ["L" + str(index + 1) for index in range(expected_copper)]:
                issue(draft, "conductor_order_unverified", "원문 도체 이름이 위에서 아래로 연속하지 않습니다. 층 순서를 직접 확인하십시오.", blocker=True)
    elif require_count:
        issue(draft, "copper_layer_count_unverified", "원문 전체 동박 층수를 확인할 수 없습니다. 층 구성을 직접 정의하십시오.", blocker=True)
    issue(draft, "material_properties_unselected", "Dk, Df와 전도도는 자동 채택하지 않았습니다. 재료 조건을 별도로 선택하십시오.")
    issue(draft, "finished_thickness_unverified", "원문 공칭 두께를 완성 기판 두께로 확정하지 않았습니다. 제조 조건을 확인하십시오.")
    draft["layers"].reverse()
    return draft
