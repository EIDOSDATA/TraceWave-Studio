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
    base = CODE / "docs/screen_design" if args.screen_only else CODE / "docs"
    documents = sorted(base.rglob("*.md"))
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
    for drawing in sorted((CODE / "docs/screen_design/diagrams").glob("*.drawio")):
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
        image = CODE / "docs/screen_design/assets" / (drawing.stem + ".svg")
        svg = ET.parse(image).getroot()
        texts = [element.text for element in svg.findall("{http://www.w3.org/2000/svg}text")]
        assert labels == texts, drawing.name
        png = image.with_suffix(".png")
        data = png.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert int.from_bytes(data[16:20], "big") == 1600
        assert int.from_bytes(data[20:24], "big") == 1000
        diagrams.append({"name": drawing.stem, "cells": len(cells), "edges": edges,
                         "drawio_sha256": hashlib.sha256(drawing.read_bytes()).hexdigest(),
                         "svg_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                         "png_sha256": hashlib.sha256(data).hexdigest()})
    report = {"scope": "screen" if args.screen_only else "current_development_docs",
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
