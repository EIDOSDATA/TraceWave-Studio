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
        if path.name.startswith("python-") or path.name in {
            "native-windows-x64.json", "windows-internal-bundle-x64.json",
            "openems-wsl-build.json", "vtk-headless.json", "wsl-development.json"
        }:
            return "runtime_definition", "빌드, 설치 또는 실행에 사용하는 고정 환경과 의존성"
        return "historical_verification", "당시 실행 기록 보존; 새 실행/합격 아님"
    if relative.startswith("01_개발문서/"):
        suffix = path.suffix.lower()
        folder = path.relative_to(DOCS).parts[0]
        if path.is_relative_to(DOCS / "07_검증/01_구현감사"):
            return "current_traceability", "기계 생성/구조 대조; AC 합격 아님"
        if path.parent == DOCS / "07_검증/02_실행화면" and suffix in {".jpg", ".png"}:
            return "native_screen_evidence", "Windows 프로그램을 실행해 캡처한 당시 화면"
        if path.parent == DOCS / "07_검증":
            number = path.stem.split("_")[0]
            if number.isdecimal() and int(number) >= 7:
                return "verification_record", "해당 개정의 실행 근거와 판정 조건"
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
            if path.parent == DOCS or path.name == "README.md":
                return "document_navigation", "해당 분야의 진입점과 담당 계약 연결"
            return "current_" + folder, "본문과 담당 기능 및 이력의 관계 검토"
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
    labels = {
        "approved_baseline_archive": "승인 기준선 원문과 기록",
        "current_traceability": "요구와 구현의 추적 자료",
        "document_catalog": "문서 목록과 이전 경로",
        "document_navigation": "개발 문서 안내",
        "documentation_asset": "개발 문서의 부속 자료",
        "documentation_validation_record": "문서 검사 기록",
        "historical_proposal": "최초 제안",
        "historical_verification": "과거 환경 및 실행 기록",
        "native_screen_evidence": "Windows 앱 실행 캡처",
        "reference_extracted_text": "참고자료에서 추출한 텍스트",
        "reference_guide": "참고자료 사용 안내",
        "reference_index_or_data": "참고자료 색인과 자료표",
        "reference_original_or_asset": "원본 웹페이지, 이미지 및 기타 첨부",
        "reference_original_pdf": "참고자료 PDF",
        "reference_support_tool": "참고자료에 포함된 도구",
        "repository_guide": "저장소 및 빌드 안내",
        "runtime_definition": "빌드 및 실행 환경 정의",
        "screen_design_asset": "화면 설계 그림",
        "verification_record": "개정별 검증 보고서와 실행 자료"
    }
    lines = [
        "# 문서와 참고 자료 전수 파일 집계", "",
        f"{inventory['date_kst']} KST 기준이다. [파일 목록](02_문서목록.json)에서 경로, "
        "용도, 파일 크기, 작업 트리의 SHA-256과 확인 범위를 찾을 수 있다.", "",
        "| 용도 | 파일 수 |", "| --- | ---: |"
    ]
    for role, count in inventory["counts_by_category"].items():
        label = labels.get(role, role.removeprefix("current_"))
        lines.append(f"| {label} | {count:,} |")
    lines.extend([
        "", f"총 {len(inventory['records']):,}개 파일이다. 바이트가 같은 파일은 "
        f"{len(inventory['identical_byte_groups'])}개 그룹이며 원문, 추출본, 실행 기록 등 각 출처를 보존한다.", "",
        "자기 참조를 피하기 위해 이 집계와 기계 목록 두 파일은 수량에서 제외한다. "
        "원문 PDF, 표와 프로그램 예제를 읽고 대조한 결과는 [참고자료 분류](05_참고자료분류.md)에서, "
        "원본 식별값의 알려진 차이는 [출처 검토 기록](../11_검토기록/05_해석과_참고자료_검토.md)에서 확인한다."
    ])
    (CATALOG / "03_문서집계.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"files":len(inventory["records"]), "categories":inventory["counts_by_category"], "identical_groups":len(inventory["identical_byte_groups"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
