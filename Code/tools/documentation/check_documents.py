"""! @brief 현재 개발 Markdown 링크와 화면 그림의 구조/동일성을 검사한다."""

from pathlib import Path
import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

CODE = Path(__file__).resolve().parents[2]
ROOT = CODE.parent
DOCS = ROOT / "01_개발문서"
BASELINE = DOCS / "12_보관이력/01_승인기준선/01_삼점사"
SCREEN_NAMES = {"05_설계와_이차원편집", "06_해석준비", "07_결과조회", "08_결과비교",
                "09_출력과_검수", "04_시작과_복구", "10_설정과_이름변경", "01_스튜디오_전체전환",
                "02_편집초안과_저장흐름", "03_객체이름과_식별자", "11_기판교환과_원문수입"}
SCREEN_ASSETS = {"11_기판교환과_원문수입": ("17_기판교환과_원문수입", 1420, 800)}


def check_link(path, destination):
    """! @brief 네트워크에 접근하지 않고 로컬 파일 링크의 존재를 검사한다."""
    target = destination.strip().strip("<>")
    if target.startswith(("https:", "http:", "mailto:", "#")):
        return None
    target = unquote(target.split("#", 1)[0])
    if not target:
        return None
    target = target.split(' "', 1)[0]
    location = (path.parent / target).resolve()
    if not location.exists():
        return {"document": path.relative_to(ROOT).as_posix(), "target": destination}
    return None


def main():
    """! @brief 문서 링크와 DrawIO/SVG/PNG 파일을 실제 파일에서 대조한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    base = DOCS / "04_화면설계" if args.screen_only else DOCS
    assert (base / "README.md").is_file(), "문서 진입점이 없습니다: " + str(base)
    assert (DOCS / "04_화면설계/README.md").is_file(), "화면 문서가 없습니다."
    drawings = sorted((DOCS / "04_화면설계/02_전환도원본").glob("*.drawio"))
    assert {path.stem for path in drawings} == SCREEN_NAMES, "화면 그림의 누락 또는 미등록 그림이 있습니다."
    documents = sorted(path for path in base.rglob("*.md")
                       if not path.is_relative_to(BASELINE) or path.name == "README.md")
    if not args.screen_only:
        documents += [CODE / "README.md", CODE / "ui/wxwidgets/README.md", ROOT / "README.md"]
    failures = []
    links = 0
    for document in documents:
        text = re.sub(r"```.*?```", "", document.read_text(encoding="utf-8"), flags=re.S)
        for match in re.finditer(r"\]\(([^\n]+?)\)", text):
            links += 1
            problem = check_link(document, match.group(1))
            if problem:
                failures.append(problem)
    diagrams = []
    for drawing in drawings:
        model = ET.parse(drawing).getroot()
        cells = model.findall(".//mxCell")
        ids = [cell.attrib["id"] for cell in cells]
        assert len(ids) == len(set(ids))
        assert {"0", "1"} <= set(ids)
        labels = []
        edges = 0
        for cell in cells:
            if cell.get("vertex") == "1":
                assert cell.find("mxGeometry") is not None
                labels.extend(line for line in cell.get("value", "").splitlines() if line)
            if cell.get("edge") == "1":
                edges += 1
                geo = cell.find("mxGeometry")
                assert geo.find("mxPoint[@as='sourcePoint']") is not None
                assert geo.find("mxPoint[@as='targetPoint']") is not None
                if drawing.stem in {"01_스튜디오_전체전환", "02_편집초안과_저장흐름", "03_객체이름과_식별자", "11_기판교환과_원문수입"}:
                    assert cell.get("source") in ids, (drawing.name, cell.attrib)
                    assert cell.get("target") in ids, (drawing.name, cell.attrib)
        image_name, expected_width, expected_height = SCREEN_ASSETS.get(drawing.stem, (drawing.stem, 1600, 1000))
        image = DOCS / "04_화면설계/01_그림자료" / (image_name + ".svg")
        svg = ET.parse(image).getroot()
        texts = [element.text for element in svg.findall("{http://www.w3.org/2000/svg}text")]
        assert labels == texts, drawing.name
        png = image.with_suffix(".png")
        data = png.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert int.from_bytes(data[16:20], "big") == expected_width
        assert int.from_bytes(data[20:24], "big") == expected_height
        diagrams.append({"name": drawing.stem, "cells": len(cells), "edges": edges,
                         "drawio_sha256": hashlib.sha256(drawing.read_bytes()).hexdigest(),
                         "svg_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                         "png_sha256": hashlib.sha256(data).hexdigest()})
    baseline_files = 0
    folder_names = []
    named_files = []
    if not args.screen_only:
        folder_names = [folder for folder in [DOCS, *DOCS.rglob("*")] if folder.is_dir()]
        assert all(re.fullmatch(r"\d{2,}_[가-힣0-9_]+", folder.name) for folder in folder_names), "개발 문서 폴더 이름 규칙 위반"
        named_files = [path for path in DOCS.rglob("*") if path.is_file() and path.name != "README.md"]
        assert all(re.fullmatch(r"\d{2,}_[가-힣0-9_]+\.[a-z]+", path.name) for path in named_files), "개발 문서 파일 이름 규칙 위반"
        for folder in folder_names:
            numbers = {int(path.name.split("_", 1)[0]) for path in named_files if path.parent == folder}
            assert numbers == set(range(1, len(numbers) + 1)), "폴더별 문서 번호의 누락: " + str(folder)
        mapping = json.loads((DOCS / "10_문서목록/01_이전경로대응.json").read_text(encoding="utf-8"))
        manifest = json.loads((BASELINE / "01_승인기록/02_승인반영목록.json").read_text(encoding="utf-8"))
        assert len(manifest["files"]) == manifest["document_count"] == 27
        for original, expected in manifest["files"].items():
            archived = (ROOT / mapping["approved_baseline_paths"][original]).resolve()
            assert archived.is_relative_to(BASELINE) and archived.is_file(), original
            normalized = archived.read_text(encoding="utf-8-sig").encode("utf-8")
            assert hashlib.sha256(normalized).hexdigest() == expected, original
            baseline_files += 1
    report = {"scope": "screen" if args.screen_only else "current_development_docs",
              "approved_baseline_files_verified": baseline_files,
              "folder_names_verified": len(folder_names),
              "numbered_files_verified": len(named_files),
              "archive_link_scope": "original_relative_context_preserved_not_current_links",
              "documents": len(documents), "links_checked": links,
              "broken_links": failures, "diagrams": diagrams,
              "native_gui_test": "not_run", "native_drawio_roundtrip": "not_run"}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "diagrams"}, ensure_ascii=False))
    print(f"DrawIO/SVG/PNG structural checks: {len(diagrams)}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
