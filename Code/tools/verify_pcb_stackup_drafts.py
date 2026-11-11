"""! @brief 원문 DB를 수정하지 않고 모든 제조업체 적층 초안과 도메인 근거를 검증한다."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.catalog.models import CatalogError, canonical_json
from rfad.catalog.selection_reader import SelectionReader
from rfad.catalog.stackup_draft import build_stackup_draft
from rfad.domain.pcb_selection_evidence import MAX_EVIDENCE_BYTES, validate_evidence


STATES = ("converted_draft", "manual_blocker", "resource_limit", "unexpected_error")


def file_hash(path: Path) -> str:
    """! @brief 큰 DB를 메모리에 모두 적재하지 않고 SHA-256을 구한다."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_one(database: Path, catalog_id: str, row: sqlite3.Row) -> dict:
    """! @brief 변환기의 명시적 한도와 반환 후 도메인 검증 실패를 구분한다."""
    result = {"template_id": row["template_id"], "publisher": row["publisher"], "kind": row["kind"],
              "published_copper_layer_count": row["layer_count"]}
    stage = "conversion"
    try:
        with SelectionReader(database, catalog_id) as reader:
            draft = build_stackup_draft(reader, row["template_id"])
            stage = "domain_evidence_validation"
            evidence = reader.evidence
            checked = validate_evidence(evidence, reader.catalog())
            size = len(canonical_json(evidence).encode("utf-8"))
            if size > MAX_EVIDENCE_BYTES:
                raise ValueError("도메인 근거 예산을 초과한 결과가 반환되었습니다.")
            references = set(draft["evidence_ids"])
            for layer in draft["layers"]:
                references.update(layer["evidence_ids"])
                if layer["thickness_evidence_id"] is not None:
                    references.add(layer["thickness_evidence_id"])
            if not references <= checked.keys():
                raise ValueError("초안의 근거 ID가 도메인에서 검증한 사본 목록에 없습니다.")
            blockers = [issue["code"] for issue in draft["issues"] if issue["severity"] == "blocker"]
            result.update({
                "state": "manual_blocker" if blockers else "converted_draft", "blockers": blockers,
                "layer_count": len(draft["layers"]),
                "unresolved_thickness_count": sum(layer["thickness_mm"] is None for layer in draft["layers"]),
                "evidence_count": len(evidence), "evidence_bytes": size,
                "domain_evidence_validated": True,
                "native_origins_validated": sum(item["entity"].startswith("native_") for item in evidence),
            })
    except Exception as error:
        expected_limit = stage == "conversion" and isinstance(error, CatalogError) and error.code == "E_RESOURCE"
        result.update({"state": "resource_limit" if expected_limit else "unexpected_error", "stage": stage,
                       "code": getattr(error, "code", None), "error_type": type(error).__name__, "message": str(error)})
    return result


def verify(database: Path) -> dict:
    """! @brief 읽기 전용 연결로 모든 템플릿을 순회하고 DB 전후 해시와 집계를 남긴다."""
    started = time.monotonic()
    before_stat = database.stat()
    before_hash = file_hash(database)
    counts = Counter({state: 0 for state in STATES})
    publishers = defaultdict(Counter)
    by_layer = defaultdict(Counter)
    max_evidence = defaultdict(int)
    results, errors = [], []
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("BEGIN")
        metadata = {row["key"]: json.loads(row["value"]) for row in connection.execute(
            "SELECT key,value FROM meta WHERE key IN ('catalog_id','counts')")}
        catalog_id = metadata["catalog_id"]
        expected_count = metadata["counts"]["native_templates"]
        if type(expected_count) is not int or expected_count < 0:
            raise ValueError("카탈로그 템플릿 개수 메타데이터가 올바르지 않습니다.")
        cursor = connection.execute(
            "SELECT t.template_id,t.publisher,t.kind,s.layer_count FROM native_templates t "
            "LEFT JOIN stackups s USING(stackup_id) ORDER BY t.template_id")
        for row in cursor:
            result = verify_one(database, catalog_id, row)
            results.append(result)
            state = result["state"]
            counts[state] += 1
            publishers[row["publisher"]][state] += 1
            key = (row["publisher"], row["layer_count"])
            by_layer[key][state] += 1
            max_evidence[key] = max(max_evidence[key], result.get("evidence_bytes", 0))
            if len(results) % 1000 == 0:
                print("검증 진행: " + str(len(results)) + "개", file=sys.stderr, flush=True)
        if len(results) != expected_count:
            errors.append("템플릿 전수 개수가 카탈로그 메타데이터와 다릅니다.")
    finally:
        connection.close()
    after_hash = file_hash(database)
    after_stat = database.stat()
    unchanged = before_hash == after_hash and (before_stat.st_size, before_stat.st_mtime_ns) == (after_stat.st_size, after_stat.st_mtime_ns)
    if not unchanged:
        errors.append("검증 도중 DB의 해시, 크기 또는 수정 시간이 변경되었습니다.")
    return {
        "schema": "rfad.pcb-stackup-draft-verification/0.1",
        "ok": not errors and counts["unexpected_error"] == 0, "database": str(database), "catalog_id": catalog_id,
        "scope": "원문 기반 초안 변환과 도메인 근거 검증이며 제작 가능성, 완성 두께 또는 CAD/EM 준비 승인 검사가 아닙니다.",
        "database_sha256_before": before_hash, "database_sha256_after": after_hash, "database_unchanged": unchanged,
        "expected_template_count": expected_count, "template_count": len(results), "counts": dict(counts),
        "domain_evidence_limit_bytes": MAX_EVIDENCE_BYTES,
        "domain_evidence_validated_count": sum(result.get("domain_evidence_validated", False) for result in results),
        "publishers": {publisher: dict(values) for publisher, values in sorted(publishers.items())},
        "counts_by_publisher_layer": [
            {"publisher": publisher, "layer_count": layer_count, "counts": dict(values),
             "max_success_evidence_bytes": max_evidence[(publisher, layer_count)]}
            for (publisher, layer_count), values in sorted(by_layer.items(), key=lambda item: (item[0][0], str(item[0][1])))
        ],
        "errors": errors, "elapsed_seconds": round(time.monotonic() - started, 3), "results": results,
    }


def write_report(report: Path, result: dict) -> None:
    """! @brief 임시 파일을 완성한 뒤 배타적 hard link로 공개하여 기존 보고서를 덮어쓰지 않는다."""
    report.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=report.parent,
                                         prefix=".stackup-verification-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, report)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    """! @brief 명시한 DB를 검증하고 새 보고서 경로에만 저장한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    database = arguments.database.resolve()
    report = arguments.report.absolute()
    if os.path.lexists(report):
        print("기존 보고서는 덮어쓰지 않습니다: " + str(report), file=sys.stderr)
        return 2
    if database == report.resolve():
        print("DB와 보고서 경로가 같을 수 없습니다.", file=sys.stderr)
        return 2
    try:
        result = verify(database)
    except Exception as error:
        result = {"ok": False, "database": str(database), "error_type": type(error).__name__, "error": str(error)}
    try:
        write_report(report, result)
    except OSError as error:
        print("새 보고서를 저장할 수 없습니다: " + str(error), file=sys.stderr)
        return 2
    summary = {key: value for key, value in result.items() if key not in ("results", "counts_by_publisher_layer")}
    summary["report"] = str(report)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
