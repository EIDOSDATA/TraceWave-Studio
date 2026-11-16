"""! @brief 단일 관측 원본에서 선택 검토용 JSON과 CSV 색인을 재생성한다."""

import argparse
import csv
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dataset_io import iter_records, load_json
from review_rules import FLAG_DESCRIPTIONS, REVIEW_MEANING, flags


def new_group() -> dict[str, Any]:
    """! @brief 관측 원본을 복제하지 않는 집계 상태를 만든다."""
    return {"count": 0, "products": set(), "sources": set(), "flags": Counter()}


def accumulate(group: dict[str, Any], record: dict[str, Any], record_flags: list[str]) -> None:
    """! @brief 공개 관측의 식별자와 검토 조건만 그룹에 집계한다."""
    group["count"] += 1
    group["products"].add(record["product"])
    group["sources"].add(record["source_id"])
    group["flags"].update(record_flags)


def group_summary(group: dict[str, Any]) -> dict[str, Any]:
    """! @brief 내부 집계 상태를 결정적 순서의 JSON 값으로 바꾼다."""
    return {
        "observation_count": group["count"],
        "distinct_product_labels": len(group["products"]),
        "source_ids": sorted(group["sources"]),
        "flag_counts": dict(sorted(group["flags"].items())),
    }


def build_review(base: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """! @brief 전체 관측을 검사하고 중첩 가능한 검토 조건을 집계한다."""
    index = load_json(base / "data/observations/index.json")
    if index.get("schema") != "rfad.reference.observations/1":
        raise ValueError("Unsupported observation index schema")
    publishers = defaultdict(new_group)
    stackups = defaultdict(new_group)
    global_flags = Counter()
    frequencies = Counter()
    total = 0
    for record in iter_records(base=base):
        record_flags = flags(record)
        publisher = record["manufacturer"]
        accumulate(publishers[publisher], record, record_flags)
        if record.get("stackup_id"):
            accumulate(stackups[(publisher, record["stackup_id"])], record, record_flags)
        global_flags.update(record_flags)
        frequencies[record.get("frequency_ghz")] += 1
        total += 1
    review = {
        "schema": "rfad.reference.selection-review/0.1",
        "meaning": REVIEW_MEANING,
        "publishers": [],
        "stackups": [],
    }
    for publisher, group in sorted(publishers.items()):
        review["publishers"].append({"publisher": publisher, **group_summary(group)})
    for (publisher, stackup_id), group in sorted(stackups.items()):
        review["stackups"].append(
            {"publisher": publisher, "stackup_id": stackup_id, **group_summary(group)}
        )
    jlc_audit = load_json(base / "data/fabricator_native_metadata/fab_jlc_stackup_audit.json")
    named_templates = 0
    for template in jlc_audit:
        if template.get("public_ui_named_template") is True:
            named_templates += 1
    jlc_stackups = 0
    for publisher, stackup_id in stackups:
        if publisher == "JLCPCB":
            jlc_stackups += 1
    summary = {
        "schema": "rfad.reference.selection-review-summary/1",
        "meaning": REVIEW_MEANING,
        "observation_index": "data/observations/index.json",
        "observation_canonical_sha256": index["canonical_sha256"],
        "all_observations": total,
        "publisher_count": len(publishers),
        "stackup_label_count": len(stackups),
        "global_flag_counts": dict(sorted(global_flags.items())),
        "flag_descriptions_ko": FLAG_DESCRIPTIONS,
        "jlc_templates_in_raw_api": len(jlc_audit),
        "jlc_named_templates": named_templates,
        "jlc_unnamed_templates": len(jlc_audit) - named_templates,
        "jlc_named_stackup_labels": jlc_stackups,
        "jlc_unnamed_template_note": "Custom or placeholder templates are retained only in raw API metadata, not inserted as observations.",
        "rows_at_2_4ghz": frequencies[2.4],
        "rows_at_2_45ghz": frequencies[2.45],
        "rows_at_2_5ghz": frequencies[2.5],
    }
    return review, summary


def csv_text(groups: list[dict[str, Any]], include_stackup: bool) -> str:
    """! @brief 검토 그룹을 0을 명시한 고정 플래그 열의 CSV로 바꾼다."""
    fields = ["publisher"]
    if include_stackup:
        fields.append("stackup_id")
    fields.extend(["observation_count", "distinct_product_labels", "source_ids"])
    fields.extend(sorted(FLAG_DESCRIPTIONS))
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for group in groups:
        row = {
            "publisher": group["publisher"],
            "observation_count": group["observation_count"],
            "distinct_product_labels": group["distinct_product_labels"],
            "source_ids": json.dumps(group["source_ids"], ensure_ascii=False),
        }
        if include_stackup:
            row["stackup_id"] = group["stackup_id"]
        for flag in sorted(FLAG_DESCRIPTIONS):
            row[flag] = group["flag_counts"].get(flag, 0)
        writer.writerow(row)
    return buffer.getvalue()


def write_outputs(base: Path, review: dict[str, Any], summary: dict[str, Any]) -> None:
    """! @brief 검증이 끝난 파생 색인 네 개만 임시 파일을 거쳐 교체한다."""
    catalog = base / "catalog"
    outputs = [
        ("selection_review.json", json.dumps(review, ensure_ascii=False, indent=2) + "\n", "utf-8"),
        ("selection_review_summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8"),
        ("review_publishers.csv", csv_text(review["publishers"], False), "utf-8-sig"),
        ("review_stackups.csv", csv_text(review["stackups"], True), "utf-8-sig"),
    ]
    for filename, content, encoding in outputs:
        destination = catalog / filename
        temporary = catalog / (filename + ".tmp")
        try:
            temporary.write_text(content, encoding=encoding, newline="\n")
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()


def main() -> int:
    """! @brief 지정한 자료 폴더의 검토 색인을 재생성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-root", type=Path, default=Path(__file__).resolve().parents[1],
        help="Root of the curated reference package; defaults to this script's package.",
    )
    arguments = parser.parse_args()
    base = arguments.package_root.resolve()
    try:
        review, summary = build_review(base)
        write_outputs(base, review, summary)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Review index generation failed: {error}", file=sys.stderr)
        return 1
    print(
        f"Reviewed {summary['all_observations']} observations, "
        f"{summary['publisher_count']} publishers and "
        f"{summary['stackup_label_count']} stackup labels. No solver readiness is granted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
