"""! @brief 전체 카탈로그 적층의 읽기 전용 제안을 검사하고 미정/근사/제한 범위를 집계한다."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.application.catalog_api import query
from rfad.application.canonical import canonical_bytes
from rfad.catalog.service import CatalogService
from rfad.domain.errors import ProjectError


STATES = frozenset({"published", "missing", "ambiguous", "approximation_required", "unsupported"})


def require(condition, message):
    """! @brief 최적화 옵션과 무관하게 검증 실패를 보고한다."""
    if not condition:
        raise RuntimeError(message)


def digest(path):
    """! @brief 전체 자료를 메모리에 적재하지 않고 파일 보존을 확인한다."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sources(database, catalog_id):
    """! @brief 모든 원시 template과 관측 기반 적층 후보를 읽기 전용 연결에서 열거한다."""
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        total_observations = connection.execute("SELECT count(*) FROM observations").fetchone()[0]
        rows = [("native_templates", identity, publisher, kind) for identity, publisher, kind in connection.execute(
            "SELECT template_id,publisher,kind FROM native_templates ORDER BY publisher,template_id")]
        rows.extend(("observations", identity, publisher, "observation") for identity, publisher in connection.execute(
            "SELECT record_id,publisher FROM observations WHERE publisher='OSH Park' ORDER BY record_id"))
    return total_observations, [(dict(catalog_id=catalog_id, entity=entity, id=identity), publisher, kind)
                                for entity, identity, publisher, kind in rows]


def check_result(result, source):
    """! @brief 제안이 원문 두께를 유지하고 미정/근사 숫자를 자동 입력하지 않는지 검사한다."""
    require(result["schema"] == "rfad.pcb-stackup-suggestions/0.1", "제안 schema 불일치")
    require(result["source"] == source, "요청과 제안 출처 불일치")
    require(result["readiness"] == "not_assessed", "제안을 해석 준비 완료로 승격함")
    require(len(canonical_bytes(result)) <= 48 * 1024, "제안 응답 예산 초과")
    require(result["returned_count"] == len(result["layers"]), "페이지 반환 행수 불일치")
    require(result["total_count"] == len(result["draft"]["layers"]), "전체 층수 불일치")
    draft = {item["key"]: item for item in result["draft"]["layers"]}
    counts = Counter()
    for layer in result["layers"]:
        require(layer["layer_key"] in draft, "원래 적층에 없는 층 제안")
        require(layer["thickness_mm"] == draft[layer["layer_key"]]["thickness_mm"], "두께 추정 또는 덮어쓰기")
        counts["layers"] += 1
        for field in ("epsilon_r", "tan_delta"):
            item = layer["properties"][field]
            require(item["state"] in STATES, "알 수 없는 물성 상태")
            counts[field + ":" + item["state"]] += 1
            if item["state"] != "published":
                require(item["value"] is None, "미정/근사 후보를 기본 수치로 승격함")
        material = layer["material_spec"]
        if material is not None:
            require(material["properties"]["conductivity"]["mode"] == "missing", "전도도를 임의 기본값으로 생성함")
            require(material["validity_hz"]["min"] is None and material["validity_hz"]["max"] is None,
                    "시험 주파수를 해석 모델 적용 대역으로 자동 복사함")
            for field in ("epsilon_r", "tan_delta"):
                require(material["properties"][field]["mode"] in ("catalog", "missing"), "사용자 입력을 자동 생성함")
    return counts


def all_pages(catalog, source):
    """! @brief 모든 페이지를 이어가며 중복/누락과 페이지 사이 원문 변화가 없는지 검사한다."""
    offset, seen, keys, counts, original_draft = 0, set(), [], Counter(), None
    while offset is not None:
        require(offset not in seen and len(seen) <= 256, "페이지 오프셋 순환 또는 상한 초과")
        seen.add(offset)
        result = query("catalog.stackup_suggestions", {
            "contract_version": "rfad.api/2.0", "context": {}, "input": {"source": source, "offset": offset}}, catalog)
        require(result["offset"] == offset, "요청과 응답 오프셋 불일치")
        if original_draft is None:
            original_draft = result["draft"]
        require(result["draft"] == original_draft, "페이지 사이 원문 적층 변경")
        counts.update(check_result(result, source))
        keys.extend(layer["layer_key"] for layer in result["layers"])
        next_offset = result["next_offset"]
        if next_offset is not None:
            require(next_offset == offset + len(result["layers"]) and next_offset > offset,
                    "다음 페이지 오프셋이 실제 반환 범위와 다름")
        offset = next_offset
    require(keys == [layer["key"] for layer in original_draft["layers"]], "전체 제안의 층 누락 또는 중복")
    counts["pages"] = len(seen)
    return counts, not keys


def run(database, report_path):
    """! @brief 실제 프로젝트를 만들지 않고 전체 적층의 제안 범위와 자료 불변을 확인한다."""
    database, report_path = Path(database), Path(report_path)
    require(not report_path.exists(), "보고서는 새 파일 경로를 사용하십시오.")
    started = time.monotonic()
    before = digest(database)
    catalog = CatalogService(database)
    status = catalog.status()
    require(status["available"], "전체 카탈로그를 읽을 수 없습니다.")
    observations, inputs = sources(database, status["catalog_id"])
    by_kind = defaultdict(Counter)
    limits, failures = [], []
    for source, publisher, kind in inputs:
        counter = by_kind[publisher + ":" + kind]
        counter["inspected"] += 1
        try:
            counts, empty = all_pages(catalog, source)
            counter.update(counts)
            counter["returned"] += 1
            if empty:
                counter["no_supported_physical_layers"] += 1
        except ProjectError as error:
            entry = {"source": source, "code": error.code, "message": error.message}
            if error.code == "E_RESOURCE":
                try:
                    query("catalog.stackup_draft", {"contract_version": "rfad.api/2.0", "context": {}, "input": source}, catalog)
                except ProjectError as legacy_error:
                    entry["legacy_draft_rejected"] = legacy_error.code == "E_RESOURCE"
                    entry["legacy_message"] = legacy_error.message
                else:
                    entry["legacy_draft_rejected"] = False
                if entry["legacy_draft_rejected"]:
                    counter["resource_limit"] += 1
                    limits.append(entry)
                else:
                    counter["failed"] += 1
                    failures.append(entry)
            else:
                counter["failed"] += 1
                failures.append(entry)
        except Exception as error:
            counter["failed"] += 1
            failures.append({"source": source, "type": type(error).__name__, "message": str(error)})
    after = digest(database)
    require(before == after, "검증 중 원본 카탈로그가 변경되었습니다.")
    report = {
        "schema": "rfad.stackup-suggestions-verification/0.1",
        "status": "failed" if failures else "completed_with_explicit_limits" if limits else "passed",
        "catalog_id": status["catalog_id"], "database_sha256": after, "database_unchanged": True,
        "observation_count": observations, "inspected_count": len(inputs),
        "scope": "all_native_templates_and_OSH_Park_observation_stackup_candidates",
        "by_kind": {key: dict(value) for key, value in sorted(by_kind.items())},
        "resource_limits": limits, "failures": failures,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "manufacturing_validated": False, "physics_validated": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return report


def main():
    """! @brief 자료 경로와 덮어쓰지 않는 새 보고서만 입력받는다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    options = parser.parse_args()
    report = run(options.database, options.report)
    print(json.dumps({"status": report["status"], "inspected": report["inspected_count"],
                      "limits": len(report["resource_limits"]), "failures": len(report["failures"]),
                      "elapsed_seconds": report["elapsed_seconds"], "report": str(options.report)}, ensure_ascii=False))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
