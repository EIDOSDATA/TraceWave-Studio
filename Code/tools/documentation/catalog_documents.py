"""! @brief 승인/개발/원문/추출/검증 자료의 전수 파일 목록을 분류한다.

@details 파일 읽기/해시/텍스트 구조 확인은 전문 내용의 재검증과 구분한다.
승인 원문과 외부 자료, 과거 runtime profile은 수정하지 않는다.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import argparse
from pathlib import Path
import hashlib
import json
import os
import subprocess

CODE = Path(__file__).resolve().parents[2]
ROOT = CODE.parent
DOCS = ROOT / "01_개발문서"
CATALOG = DOCS / "10_문서목록"
EXCLUDED = {"02_문서목록.json", "03_문서집계.md"}


def category(path):
    """! @brief 파일 종류와 위치로 문서 목적 및 검토 수준을 구분한다."""
    relative = path.relative_to(ROOT).as_posix()
    if relative.startswith("01_개발문서/12_보관이력/01_승인기준선/"):
        if path.name == "README.md":
            return "document_navigation", "승인 원문과 현행 편집본의 보관/탐색 안내; 승인 원문 아님"
        return "approved_baseline_archive", "승인 당시 원문/manifest 보존; 현행 편집본과 구분"
    if relative.startswith("00_참고자료/"):
        if path.suffix.lower() == ".pdf":
            return "reference_original_pdf", "파일 목록/해시; 전 페이지 내용 재검증 아님"
        if path.suffix.lower() == ".md" or path.name.lower().startswith("readme"):
            return "reference_guide", "안내/분류/사용 조건 내용 검토"
        if "search_text" in relative or path.suffix.lower() == ".txt":
            return "reference_extracted_text", "전체 파일 텍스트 읽기/구조 목록; 개별 수식 재검증 아님"
        if path.suffix.lower() in {".csv", ".json", ".jsonl", ".xlsx"}:
            return "reference_index_or_data", "파일 목록/근거 연결; 상세 검사 범위는 analysis_review"
        if path.suffix.lower() in {".py", ".ps1", ".sh", ".js"}:
            return "reference_support_tool", "자료 묶음의 지원 도구; 파일 목록/해시"
        return "reference_original_or_asset", "파일 목록/해시; 원문 내용 재검증 아님"
    if relative.startswith("Code/runtime_profiles/"):
        if path.name in {"python-exchange-windows-x64.json", "python-exchange-windows-x64.txt",
                         "windows-internal-bundle-x64.json"}:
            return "runtime_definition", "내부 배포와 도면 교환의 고정 의존성 및 고지 정의"
        return "historical_verification", "당시 실행 기록 보존; 새 실행/합격 아님"
    if relative.startswith("01_개발문서/"):
        suffix = path.suffix.lower()
        folder = path.relative_to(DOCS).parts[0]
        if path.is_relative_to(DOCS / "07_검증/01_구현감사"):
            return "current_traceability", "기계 생성/구조 대조; AC 합격 아님"
        if folder == "10_문서목록":
            return "document_catalog", "분류/경로 대응"
        if folder == "04_화면설계" and suffix in {".png", ".svg", ".drawio"}:
            return "screen_design_asset", "화면 근거 또는 설계 그림; 실제 GUI 시험과 별도"
        if folder == "12_보관이력":
            if path.name == "README.md":
                return "document_navigation", "최초 제안과 현재 계약의 연결 안내"
            return "historical_proposal", "제안 본문/현재 계약의 권위 관계 검토"
        if folder == "11_검토기록" and suffix == ".json":
            return "documentation_validation_record", "문서 링크/그림 구조 검수; 제품 수용 아님"
        if suffix == ".md":
            return "current_" + folder if folder != path.name else "document_navigation", "본문/현재 설명/담당 기능 관계 검토"
        return "documentation_asset", "문서/시안 자산 보존"
    return "repository_guide", "개발 문서 진입/현재 상태 검토"


def digest_file(path):
    """! @brief 큰 PDF도 스트리밍하여 작업트리 바이트 해시를 기록한다."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def relative_link(path, folder=CATALOG):
    """! @brief 공백이 있는 저장소 경로도 Markdown 링크로 표현한다."""
    value = Path(os.path.relpath(path, folder)).as_posix()
    return "<" + value + ">" if " " in value else value


def build(catalog_date=None):
    """! @brief 현재 존재하는 추적 자료와 새 문서를 빠짐없이 목록에 포함한다."""
    catalog_date = catalog_date or datetime.now(timezone(timedelta(hours=9))).date()
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    paths = set()
    for name in tracked:
        path = ROOT / name
        if name.startswith(("00_참고자료/", "Code/runtime_profiles/")) and path.is_file():
            paths.add(path)
    paths.update(path for path in DOCS.rglob("*") if path.is_file() and path.name not in EXCLUDED)
    paths.update({ROOT / "README.md", CODE / "README.md", CODE / "ui/wxwidgets/README.md"})
    records = []
    for path in sorted(paths):
        role, review = category(path)
        item = {"path": path.relative_to(ROOT).as_posix(), "category": role,
                "review_scope": review, "bytes": path.stat().st_size,
                "working_tree_sha256": digest_file(path)}
        if path.suffix.lower() in {".md", ".txt"}:
            try:
                text = path.read_text(encoding="utf-8-sig")
                item["text_lines"] = len(text.splitlines())
                item["text_status"] = "utf8_read"
            except UnicodeError:
                item["text_status"] = "encoding_requires_source_specific_reader"
        records.append(item)
    duplicates = defaultdict(list)
    for record in records:
        duplicates[record["working_tree_sha256"]].append(record["path"])
    return {"schema": "rfad.documentation-inventory/0.1", "date_kst": catalog_date.isoformat(),
            "scope": "current_development_docs_and_preserved_reference_files",
            "exclusions": ["Git/build/venv/.local", "제품 코드와 테스트 fixture", "이 파일과 생성 요약(자기 해시 순환 제외)"],
            "not_claimed": ["PDF 전 페이지/수식 재검증", "새 GUI/FDTD/실측 시험", "R1 수용 완료"],
            "counts_by_category": dict(sorted(Counter(row["category"] for row in records).items())),
            "records": records,
            "identical_byte_groups": [names for names in duplicates.values() if len(names) > 1]}


def main():
    """! @brief 기계 목록과 사람이 읽는 집계를 함께 갱신한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, help="이번 목록을 작성한 KST 날짜. 과거 개별 기록의 날짜는 변경하지 않음")
    options = parser.parse_args()
    CATALOG.mkdir(parents=True, exist_ok=True)
    inventory = build(options.date)
    (CATALOG / "02_문서목록.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# 문서와 참고 자료 전수 파일 집계", "", f"기준일: {inventory['date_kst']} KST. `catalog_documents.py` 생성 결과다. 분류/파일 읽기와 전문 내용의 검토 수준은 다르며 각 파일의 review_scope를 함께 읽는다.", "", "| 분류 | 파일 수 |", "| --- | --- |"]
    for role, count in inventory["counts_by_category"].items():
        lines.append(f"| {role} | {count} |")
    lines += ["", f"전체 {len(inventory['records'])}개 파일. 동일 작업트리 바이트 그룹 {len(inventory['identical_byte_groups'])}개를 기록했으며 자동 삭제하지 않았다.", "", "전체 경로/분류/검토 수준/바이트/작업트리 SHA256은 [02_문서목록.json](02_문서목록.json)에 있다. PDF 전 페이지 의미 검토, RF 정확도, 외부 링크의 최신 유효성은 이 생성기의 검증 범위가 아니다. 과거 승인/출처 hash와의 실제 비교는 [검토 기록](../11_검토기록/05_해석과_참고자료_검토.md)을 따른다.", "", "02_문서목록.json과 이 요약은 자기 참조 hash를 피하기 위해 목록에서 제외한다. 원문/추출/기존 runtime 파일은 수정하지 않는다."]
    (CATALOG / "03_문서집계.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"files":len(inventory["records"]), "categories":inventory["counts_by_category"], "identical_groups":len(inventory["identical_byte_groups"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
