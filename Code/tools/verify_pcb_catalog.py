"""! @brief 전체 정리 자료와 검색 DB의 보존성, 페이지 및 실제 위험 사례를 대조한다."""

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from rfad.catalog.models import canonical_json
from rfad.catalog.query import MAX_RESULT_BYTES
from rfad.catalog.repository import IDS
from rfad.catalog.service import CatalogService


def require(condition: bool, reason: str) -> None:
    """! @brief Python 최적화 옵션에도 생략되지 않는 수용 조건을 검사한다."""
    if not condition:
        raise ValueError(reason)


def read_json(path: Path):
    """! @brief 검증용 원문 JSON을 명시적 UTF-8로 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def verify_observations(source: Path, connection: sqlite3.Connection) -> dict:
    """! @brief 모든 관측의 원래 키/타입/값과 파티션 해시를 독립적으로 대조한다."""
    index = read_json(source / "data/observations/index.json")
    count = 0
    fields = set()
    roles = Counter()
    for partition in index["partitions"]:
        digest = hashlib.sha256()
        rows = 0
        with (source / partition["path"]).open("rb") as stream:
            for line in stream:
                digest.update(line)
                if not line.strip():
                    continue
                original = json.loads(line)
                stored = connection.execute("SELECT raw_json,raw_sha256 FROM observations WHERE record_id=?",
                                            (original["record_id"],)).fetchone()
                require(stored is not None, "원문 관측 ID 누락: " + original["record_id"])
                raw = canonical_json(original)
                require(stored[0] == raw, "원문 필드/타입/값 불일치: " + original["record_id"])
                require(stored[1] == hashlib.sha256(raw.encode("utf-8")).hexdigest(), "관측 해시 불일치")
                fields.update(original)
                roles[original["dataset_role"]] += 1
                count += 1
                rows += 1
        require(rows == partition["records"] and digest.hexdigest() == partition["sha256"], "JSONL 파티션 불일치")
    require(count == index["record_count"], "관측 전체 수 불일치")
    digest = hashlib.sha256()
    db_count = 0
    for row in connection.execute("SELECT raw_json FROM observations ORDER BY record_id"):
        digest.update(row[0].encode("utf-8") + b"\n")
        db_count += 1
    require(count == db_count and digest.hexdigest() == index["canonical_sha256"], "전체 정규 관측 해시 불일치")
    summary = read_json(source / "catalog/selection_review_summary.json")
    flags = dict(connection.execute("SELECT flag,count(*) FROM observation_flags GROUP BY flag"))
    require(flags == summary["global_flag_counts"], "원문 검토 플래그 수 불일치")
    schema = read_json(source / "catalog/schema.json")
    require(fields == {item["field"] for item in schema["fields"]}, "원문 필드 집합 불일치")
    return {"observations": count, "fields": len(fields), "partitions": len(index["partitions"]),
            "roles": dict(roles), "canonical_sha256": digest.hexdigest(), "review_flags": flags}


def verify_pages(service: CatalogService, connection: sqlite3.Connection, entity: str, filters=None) -> list[str]:
    """! @brief 실제 서비스의 바이트 제한과 다음 offset을 따라 모든 결과를 순회한다."""
    request = {"entity": entity, "limit": 100, "filters": filters or {}}
    identities = []
    while True:
        response = service.search(request)
        require(len(canonical_json(response).encode("utf-8")) <= MAX_RESULT_BYTES, "검색 응답 상한 위반")
        require(response["readiness"] == "not_assessed", "검색 결과가 해석 준비로 승격됨")
        identities.extend(item["id"] for item in response["items"])
        if not response["has_more"]:
            break
        require(response["returned_count"] > 0, "검색 페이지가 진행되지 않음")
        request.update(offset=response["next_offset"], catalog_id=response["catalog_id"])
    require(len(identities) == len(set(identities)), "검색 페이지에 중복 ID 존재")
    if not filters:
        expected = {row[0] for row in connection.execute("SELECT " + IDS[entity] + " FROM " + entity)}
        require(set(identities) == expected, "검색 페이지가 전체 자료를 덮지 못함: " + entity)
    return identities


def verify_details(service: CatalogService, connection: sqlite3.Connection) -> dict:
    """! @brief 각 개체의 가장 큰 JSON을 공개 API 조각만으로 복원한다."""
    results = {}
    for entity, key in IDS.items():
        row = connection.execute("SELECT " + key + ",raw_json,raw_sha256 FROM " + entity
                                 + " ORDER BY length(raw_json) DESC LIMIT 1").fetchone()
        if row is None:
            continue
        pieces = []
        request = {"entity": entity, "id": row[0], "raw_limit": 8192}
        offset = 0
        while True:
            response = service.get(request)
            require(len(canonical_json(response).encode("utf-8")) <= MAX_RESULT_BYTES, "상세 응답 상한 위반")
            raw = response["raw"]
            require(raw["sha256"] == row[2], "공개 상세 SHA-256 불일치")
            require(raw["offset"] == offset and raw["total_characters"] == len(row[1]), "공개 상세 범위 불일치")
            require(raw["offset_unit"] == "unicode_codepoints" and raw["encoding"] == "utf-8"
                    and raw["format"] == "json", "공개 상세 인코딩 계약 불일치")
            pieces.append(raw["text"])
            offset += len(raw["text"])
            if raw["complete"]:
                require(offset == len(row[1]) and raw["next_offset"] is None, "상세 완료 위치 불일치")
                break
            require(raw["text"], "상세 조각이 진행되지 않음")
            require(raw["next_offset"] == offset, "상세 다음 위치 불일치")
            request.update(raw_offset=raw["next_offset"], catalog_id=response["catalog_id"])
        text = "".join(pieces)
        require(text == row[1] and hashlib.sha256(text.encode("utf-8")).hexdigest() == row[2], "상세 재구성 해시 불일치")
        results[entity] = {"id": row[0], "characters": len(text), "chunks": len(pieces)}
    return results


def verify_filters(service: CatalogService, connection: sqlite3.Connection) -> dict:
    """! @brief 실제 검토 수치와 주파수 조건을 공개 검색 결과에 대조한다."""
    cases = {
        "exact_2_4ghz": ({"frequency_property": "record", "frequency_ghz": 2.4}, 0),
        "exact_2_45ghz": ({"frequency_property": "record", "frequency_ghz": 2.45}, 0),
        "exact_2_5ghz": ({"frequency_property": "record", "frequency_ghz": 2.5}, 120),
        "jlc_nonpositive": ({"review_flag": "invalid_nonpositive_source_ply_value"}, 226),
        "pcbway_group_total": ({"review_flag": "group_thickness_not_individual_ply_thickness"}, 999),
        "source_conflicts": ({"review_flag": "published_source_conflict"}, 49),
        "magnetic_material": ({"review_flag": "nonunit_relative_permeability"}, 1),
        "different_dk_df_frequency": ({"review_flag": "dk_df_frequency_not_shared"}, 21),
    }
    results = {}
    for name, (filters, expected) in cases.items():
        actual = len(verify_pages(service, connection, "observations", filters))
        require(actual == expected, "실제 위험/주파수 검색 수 불일치: " + name)
        results[name] = actual
    filters = {"publisher": "Wurth Elektronik", "review_flag": "prefix_cross_layer_fields_present"}
    actual = len(verify_pages(service, connection, "native_components", filters))
    require(actual == 167, "WE 원시 필드 경계 검토 수 불일치")
    results["we_cross_layer_fields"] = actual
    return results


def verify(source: Path, database: Path) -> dict:
    """! @brief 원문 검증과 서비스 성능 측정의 메모리 범위를 분리한다."""
    started = time.perf_counter()
    service = CatalogService(database)
    status = service.status()
    require(status["available"], "카탈로그를 열 수 없음: " + str(status))
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        require(connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite 무결성 오류")
        require(connection.execute("PRAGMA foreign_key_check").fetchone() is None, "SQLite 외래 키 오류")
        observations = verify_observations(source, connection)
        pages = {entity: len(verify_pages(service, connection, entity)) for entity in IDS}
        details = verify_details(service, connection)
        filters = verify_filters(service, connection)
    performance = subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).with_name("pcb_catalog_performance.py")),
                                  "--database", str(database)], capture_output=True, timeout=120)
    require(performance.returncode == 0, "독립 성능 측정 실패: " + performance.stderr.decode("utf-8", errors="replace"))
    return {"schema": "rfad.catalog.verification/1", "checked_at": datetime.now(timezone.utc).isoformat(),
            "catalog_id": status["catalog_id"], "database": str(database), "status": "passed",
            "observations": observations, "paged_counts": pages, "largest_details": details, "filter_cases": filters,
            "performance": json.loads(performance.stdout), "elapsed_seconds": time.perf_counter() - started,
            "scope": "catalog source preservation and read-only search; solver readiness not assessed"}


def main() -> int:
    """! @brief 실제 전체 자료 시험 결과를 로컬 JSON 보고서로 남긴다."""
    parser = argparse.ArgumentParser(description="전체 PCB 카탈로그 검증")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    arguments = parser.parse_args()
    result = verify(arguments.source.resolve(), arguments.database.resolve())
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "observations": result["observations"]["observations"],
                      "elapsed_seconds": result["elapsed_seconds"], "report": str(arguments.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
