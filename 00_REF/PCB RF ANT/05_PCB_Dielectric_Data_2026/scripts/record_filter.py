"""! @brief 관측을 보정하거나 보간하지 않는 필터 조건과 CSV 호환 입력을 제공한다."""

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterator

from review_rules import flags


def number(value: Any) -> float | None:
    """! @brief 유한한 수치만 필터 비교에 사용한다."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(result):
        return None
    return result


def keep(record: dict[str, Any], options: Any) -> bool:
    """! @brief 명시적으로 요청한 조건에 해당하는 공개 관측만 선택한다."""
    for query, key in [(options.manufacturer, "manufacturer"), (options.product, "product")]:
        if query and query.casefold() not in str(record.get(key) or "").casefold():
            return False
    for query, key in [
        (options.source_id, "source_id"),
        (options.stackup_id, "stackup_id"),
        (options.dataset_role, "dataset_role"),
    ]:
        if query and record.get(key) != query:
            return False
    if options.scalar_dk_only and number(record.get("dk")) is None:
        return False
    if options.review_flag and options.review_flag not in flags(record):
        return False
    if options.frequency_ghz is not None:
        target = options.frequency_ghz
        frequency = number(record.get("frequency_ghz"))
        low = number(record.get("frequency_min_ghz"))
        high = number(record.get("frequency_max_ghz"))
        matched = False
        if frequency is not None and abs(frequency - target) < max(1e-12, abs(target) * 1e-9):
            matched = True
        if options.include_frequency_ranges and low is not None and high is not None:
            if low <= target <= high:
                matched = True
        if options.allow_missing_frequency and frequency is None and low is None and high is None:
            matched = True
        if not matched:
            return False
    return True


def iter_legacy_csv(path: Path, fields: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """! @brief 기존 CSV를 알려진 필드 타입으로 읽되 누락된 키를 복원했다고 주장하지 않는다."""
    definitions = {field["field"]: field["observed_types"].split(",") for field in fields}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if len(reader.fieldnames or []) != len(set(reader.fieldnames or [])):
            raise ValueError("Duplicate CSV field names")
        if set(reader.fieldnames or []) - definitions.keys():
            raise ValueError("CSV contains fields outside catalog/schema.json")
        for raw in reader:
            if None in raw:
                raise ValueError("CSV row has more values than header fields")
            record = {}
            for field, value in raw.items():
                types = definitions[field]
                if value in (None, ""):
                    record[field] = None
                elif "list" in types or "dict" in types:
                    try:
                        decoded = json.loads(value)
                    except ValueError:
                        if "str" not in types:
                            raise
                        decoded = value
                    if type(decoded).__name__ in types and not isinstance(decoded, str):
                        record[field] = decoded
                    elif "str" in types:
                        record[field] = value
                    else:
                        raise ValueError(f"Invalid CSV compound value: {field}")
                elif types == ["bool"]:
                    if value.casefold() not in ("true", "false"):
                        raise ValueError(f"Invalid CSV boolean: {field}")
                    record[field] = value.casefold() == "true"
                elif "str" not in types and ("int" in types or "float" in types):
                    if types == ["int"]:
                        record[field] = int(value)
                    else:
                        record[field] = float(value)
                    if not math.isfinite(record[field]):
                        raise ValueError(f"Non-finite CSV number: {field}")
                else:
                    record[field] = value
            yield record


def csv_value(value: Any) -> Any:
    """! @brief null은 공란으로, 복합 타입은 JSON으로 CSV에 표시한다."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    return value
