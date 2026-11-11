"""! @brief 공개 관측을 선택하여 별도 CSV 또는 JSONL 파일로 안전하게 내보낸다."""

import argparse
import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

from dataset_io import BASE, iter_records, load_json
from record_filter import csv_value, iter_legacy_csv, keep
from review_rules import FLAG_DESCRIPTIONS


def output_path(requested: Path, base: Path) -> Path:
    """! @brief 기존 파일 덮어쓰기와 자료 원본 영역으로의 출력을 거부한다."""
    if requested.exists() or requested.is_symlink():
        raise ValueError(f"Output already exists: {requested}")
    destination = requested.resolve()
    if destination.suffix.casefold() not in (".csv", ".jsonl"):
        raise ValueError("Output extension must be .csv or .jsonl")
    try:
        relative = destination.relative_to(base.resolve())
    except ValueError:
        return destination
    if not relative.parts or relative.parts[0] != "exports":
        raise ValueError("Outputs inside the package are allowed only under exports/")
    return destination


def export_records(options: argparse.Namespace) -> int:
    """! @brief 전체 입력 검증을 마친 임시 결과만 새 이름으로 원자적으로 공개한다."""
    base = options.package_root.resolve()
    destination = output_path(options.output, base)
    definitions = load_json(base / "catalog/schema.json")["fields"]
    fieldnames = [field["field"] for field in definitions]
    if options.input is not None:
        if destination.suffix.casefold() != ".csv":
            raise ValueError("Legacy CSV input supports CSV output only; use indexed JSONL to preserve original JSON types.")
        records = iter_legacy_csv(options.input, definitions)
    else:
        records = iter_records(options.manufacturer, base)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    count = 0
    try:
        encoding = "utf-8-sig" if destination.suffix.casefold() == ".csv" else "utf-8"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding=encoding, newline="", dir=destination.parent,
            prefix=".tracewave-export-", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            writer = None
            if destination.suffix.casefold() == ".csv":
                writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
            for record in records:
                if not keep(record, options):
                    continue
                if writer is not None:
                    writer.writerow({key: csv_value(value) for key, value in record.items()})
                else:
                    stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                count += 1
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return count


def main() -> int:
    """! @brief 원 관측의 주파수와 조건을 유지하는 필터 명령을 처리한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=BASE)
    parser.add_argument("--input", type=Path, help="Optional legacy CSV input; exports CSV only.")
    parser.add_argument("--manufacturer", help="Case-insensitive publisher substring.")
    parser.add_argument("--product", help="Case-insensitive product substring.")
    parser.add_argument("--source-id")
    parser.add_argument("--stackup-id")
    parser.add_argument(
        "--dataset-role", choices=["material_published_parameter", "fabricator_published_parameter"]
    )
    parser.add_argument("--review-flag", choices=sorted(FLAG_DESCRIPTIONS))
    parser.add_argument("--frequency-ghz", type=float)
    parser.add_argument("--include-frequency-ranges", action="store_true")
    parser.add_argument("--allow-missing-frequency", action="store_true")
    parser.add_argument("--scalar-dk-only", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    if options.frequency_ghz is not None:
        if not math.isfinite(options.frequency_ghz) or options.frequency_ghz <= 0:
            parser.error("Frequency must be finite and positive.")
    try:
        count = export_records(options)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Export failed: {error}", file=sys.stderr)
        return 1
    print(f"Exported {count} published observations to {options.output}. No solver readiness is granted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
