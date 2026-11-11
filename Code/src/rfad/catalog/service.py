"""! @brief 프로젝트와 독립된 카탈로그 조회 및 크기가 제한된 DTO를 제공한다."""

import hashlib
from pathlib import Path

from .models import CATALOG_SCHEMA, CatalogError, canonical_json
from .query import ENTITIES, MAX_PAGE_SIZE, MAX_RAW_CHARACTERS, MAX_RESULT_BYTES, parse_detail, parse_search
from .repository import CatalogRepository


def _size(value: dict) -> int:
    """! @brief RPC의 UTF-8 프레임과 같은 기준으로 응답 크기를 계산한다."""
    try:
        return len(canonical_json(value).encode("utf-8"))
    except (ValueError, TypeError, UnicodeError) as error:
        raise CatalogError("E_SCHEMA", "카탈로그 결과에 유한 JSON으로 표현할 수 없는 값이 있습니다.") from error


def _summary(item: dict) -> dict:
    """! @brief 비정상적으로 긴 요약도 명시적인 축약 표시와 함께 제한한다."""
    item = dict(item)
    item["truncated_fields"] = list(item["truncated_fields"])
    for maximum in (256, 128, 64):
        if _size(item) <= 12 * 1024:
            break
        for field, value in tuple(item.items()):
            if (type(value) is str and field != "id" and not field.endswith("_id")
                    and not field.endswith("_sha256") and len(value) > maximum):
                item[field] = value[:maximum]
                if field not in item["truncated_fields"]:
                    item["truncated_fields"].append(field)
        flags = item["review_flags"]
        if len(flags) > 8 or any(len(flag) > maximum for flag in flags):
            item["review_flags"] = [flag[:maximum] for flag in flags[:8]]
            if "review_flags" not in item["truncated_fields"]:
                item["truncated_fields"].append("review_flags")
    if _size(item) > 12 * 1024:
        raise CatalogError("E_SCHEMA", "카탈로그 식별자와 요약이 허용 크기를 초과했습니다.")
    return item


class CatalogService:
    """! @brief 선택 자료는 검색 가능 여부만 알리며 해석 준비 완료로 승인하지 않는다."""

    def __init__(self, database: Path | None = None):
        """! @brief 선택적 서버 설정만 보관하고 프로젝트나 CAD 모듈을 불러오지 않는다."""
        self.repository = CatalogRepository(database)

    def status(self) -> dict:
        """! @brief 미설정, 파일 누락, 잘못된 DB도 작은 상태 DTO로 반환한다."""
        result = {"schema": CATALOG_SCHEMA, "configured": self.repository.database is not None,
                  "available": False, "state": "unconfigured", "readiness": "not_assessed"}
        try:
            metadata = self.repository.status()
        except CatalogError as error:
            result["state"] = error.details.get("state", "invalid")
            result["diagnostic"] = error.to_dict()
            return result
        result.update({"available": True, "state": "ready", "catalog_id": metadata["catalog_id"],
                       "import_version": metadata["import_version"],
                       "counts": {key: value for key, value in metadata.get("counts", {}).items()
                                  if key in ENTITIES and type(value) is int and value >= 0},
                       "limits": {"page_size": MAX_PAGE_SIZE, "result_bytes": MAX_RESULT_BYTES,
                                  "raw_characters": MAX_RAW_CHARACTERS}, "entities": list(ENTITIES)})
        for field in ("created_at", "source_index_sha256", "source_canonical_sha256"):
            value = metadata.get(field)
            if type(value) is str and len(value) <= 256:
                result[field] = value
        return result

    def search(self, value: dict) -> dict:
        """! @brief 정확 필터와 리터럴 부분 문자열 검색을 안정 순서로 페이지화한다."""
        request = parse_search(value)
        metadata, rows = self.repository.search(request)
        result = {"catalog_id": metadata["catalog_id"], "entity": request.entity, "readiness": "not_assessed",
                  "offset": request.offset, "limit": request.limit, "items": [], "returned_count": 0,
                  "has_more": False, "next_offset": None, "limited_by_bytes": False}
        if "frequency_ghz" in request.filters:
            prop = request.filters["frequency_property"]
            result["frequency_scope"] = {
                "property": prop, "mode": request.filters.get("frequency_mode", "exact"),
                "meaning": "explicit_df_point_only" if prop == "df" else (
                    "record_frequency_not_property_assignment" if prop == "record" else "dk_present_record_frequency"),
                "interpolated": False,
            }
        for row in rows[:request.limit]:
            item = _summary(row)
            result["items"].append(item)
            if _size(result) > MAX_RESULT_BYTES - 256:
                result["items"].pop()
                result["limited_by_bytes"] = True
                break
        result["returned_count"] = len(result["items"])
        result["has_more"] = len(rows) > len(result["items"])
        if result["has_more"]:
            result["next_offset"] = request.offset + result["returned_count"]
        if _size(result) > MAX_RESULT_BYTES:
            raise CatalogError("E_RESOURCE", "카탈로그 응답의 크기가 허용 범위를 초과했습니다.")
        return result

    def get(self, value: dict) -> dict:
        """! @brief 원래 JSON 타입을 유지한 문자열 조각과 재구성용 해시를 제공한다."""
        request = parse_detail(value)
        metadata, item, raw = self.repository.get(request)
        item = _summary(item)
        digest = item["raw_sha256"]
        if type(digest) is not str or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise CatalogError("E_HASH", "카탈로그 원문 해시가 올바르지 않습니다.")
        result = {"catalog_id": metadata["catalog_id"], "entity": request.entity, "readiness": "not_assessed",
                  "item": item, "raw": {"format": "json", "encoding": "utf-8", "offset_unit": "unicode_codepoints",
                                        "offset": request.raw_offset, "text": raw["text"],
                                        "total_characters": raw["length"], "sha256": digest,
                                        "next_offset": None, "complete": False}}
        if raw["properties"] is not None:
            result["properties"] = raw["properties"]
        while _size(result) > MAX_RESULT_BYTES - 128:
            length = len(result["raw"]["text"])
            if length <= 1:
                raise CatalogError("E_RESOURCE", "카탈로그 상세 요약이 커서 원문 페이지를 반환할 수 없습니다.")
            result["raw"]["text"] = result["raw"]["text"][:length // 2]
        end = request.raw_offset + len(result["raw"]["text"])
        result["raw"]["next_offset"] = end if end < raw["length"] else None
        result["raw"]["complete"] = end == raw["length"]
        if _size(result) > MAX_RESULT_BYTES:
            raise CatalogError("E_RESOURCE", "카탈로그 상세 응답의 크기가 허용 범위를 초과했습니다.")
        if request.raw_offset == 0 and result["raw"]["complete"]:
            actual = hashlib.sha256(result["raw"]["text"].encode("utf-8")).hexdigest()
            if actual != digest:
                raise CatalogError("E_HASH", "카탈로그 원문과 저장된 해시가 일치하지 않습니다.")
        return result
