"""! @brief 정규 관측의 타입과 수치 및 출처 연결을 전수 검사한다."""

import math
from typing import Any

from dataset_io import canonical_digest, iter_records, load_json


POSITIVE_FIELDS = {"dk", "frequency_ghz", "df_frequency_ghz", "thickness_mm"}
NONNEGATIVE_FIELDS = {
    "dk_min", "dk_max", "dk_tolerance", "df", "df_min", "df_max", "df_tolerance",
    "frequency_min_ghz", "frequency_max_ghz", "thickness_min_mm", "thickness_max_mm",
    "thickness_tolerance_mm", "resin_content_pct",
}
RANGE_FIELDS = [
    ("dk_min", "dk_max"), ("df_min", "df_max"),
    ("frequency_min_ghz", "frequency_max_ghz"), ("thickness_min_mm", "thickness_max_mm"),
]


def finite_values(value: Any) -> bool:
    """! @brief 원시 근거를 포함한 중첩 수치의 비유한 값을 검사한다."""
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(finite_values(item) for item in value.values())
    if isinstance(value, list):
        return all(finite_values(item) for item in value)
    return True


def verify_record(audit, record: dict[str, Any], definitions: dict[str, Any], source_ids: set[str]) -> None:
    """! @brief 출처 관측을 수정하지 않고 선언된 스키마와 수치 경계를 확인한다."""
    label = record["record_id"]
    audit.require(not set(record) - definitions.keys(), f"{label}: fields outside schema")
    audit.require(record.get("source_id") in source_ids, f"{label}: unknown source_id")
    audit.require(finite_values(record), f"{label}: non-finite value")
    for field, value in record.items():
        if value is None or field not in definitions:
            continue
        types = definitions[field]["observed_types"].split(",")
        audit.require(type(value).__name__ in types, f"{label}: unexpected type for {field}")
    for field in POSITIVE_FIELDS | NONNEGATIVE_FIELDS:
        value = record.get(field)
        if value is None:
            continue
        valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
        audit.require(valid_type, f"{label}: invalid numeric field {field}")
        if not valid_type:
            continue
        if field in POSITIVE_FIELDS:
            audit.require(value > 0, f"{label}: nonpositive {field}")
        else:
            audit.require(value >= 0, f"{label}: negative {field}")
    for field in ("df", "df_min", "df_max"):
        value = record.get(field)
        if isinstance(value, (int, float)):
            audit.require(value <= 1, f"{label}: {field} exceeds one")
    resin = record.get("resin_content_pct")
    if isinstance(resin, (int, float)):
        audit.require(resin <= 100, f"{label}: resin content exceeds 100 percent")
    for lower, upper in RANGE_FIELDS:
        minimum = record.get(lower)
        maximum = record.get(upper)
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)):
            audit.require(minimum <= maximum, f"{label}: reversed {lower}/{upper}")
    for field in ("source_file", "source_manifest_file"):
        if record.get(field):
            audit.file(record[field], f"{label} {field}")


def verify_observations(audit, source_ids: set[str]) -> None:
    """! @brief 모든 분할과 필드 및 정규 관측 해시를 검사한다."""
    schema = load_json(audit.base / "catalog/schema.json")
    definitions = {field["field"]: field for field in schema["fields"]}
    audit.require(len(definitions) == len(schema["fields"]), "Duplicate field names in schema")
    records = list(iter_records(base=audit.base))
    used_fields = set()
    for record in records:
        used_fields.update(record)
        verify_record(audit, record, definitions, source_ids)
    audit.require(used_fields == definitions.keys(), "Observed fields and schema field list differ")
    index = load_json(audit.base / "data/observations/index.json")
    audit.require(canonical_digest(records) == index["canonical_sha256"], "Canonical observation SHA-256 mismatch")
    audit.counts["observations"] = len(records)
    audit.counts["observation_fields"] = len(definitions)
    audit.counts["partitions"] = len(index["partitions"])
