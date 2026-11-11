"""! @brief 최종 배포 파일 목록과 자체 안내 HTML의 로컬 링크를 검사한다."""

from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from dataset_io import load_json, package_path


def verify_manifest(audit) -> None:
    """! @brief 파일 목록의 크기와 해시 및 누락을 확인한다."""
    manifest = load_json(audit.base / "catalog/file_manifest.json")
    entries = manifest["files"] if isinstance(manifest, dict) else manifest
    listed = set()
    for entry in entries:
        relative = entry["path"]
        audit.require(relative not in listed, f"Duplicate manifest path: {relative}")
        listed.add(relative)
        audit.file(relative, "Manifest", entry["sha256"], entry["bytes"])
    unlisted = []
    excluded = 0
    for path in audit.base.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(audit.base)
        if relative.parts[0] == "exports" or "__pycache__" in relative.parts:
            excluded += 1
            continue
        if relative.as_posix() == "catalog/file_manifest.json":
            continue
        if relative.as_posix() not in listed:
            unlisted.append(relative.as_posix())
    for relative in unlisted:
        audit.require(False, f"File missing from manifest: {relative}")
    audit.counts["manifest_files"] = len(entries)
    audit.counts["excluded_export_or_cache_files"] = excluded


class GuideLinks(HTMLParser):
    """! @brief 수집 원문이 아닌 자체 안내 화면의 파일 링크를 수집한다."""

    def __init__(self):
        """! @brief 링크와 문서 내부 위치 목록을 초기화한다."""
        super().__init__(convert_charrefs=True)
        self.links = []
        self.anchors = set()

    def handle_starttag(self, tag, attributes):
        """! @brief href 및 src와 내부 anchor를 읽는다."""
        for name, value in attributes:
            if name in ("href", "src") and value:
                self.links.append(value)
            if name == "id" and value:
                self.anchors.add(value)


def verify_guide(audit) -> None:
    """! @brief START_HERE_ko.html의 로컬 링크만 패키지 내부 파일과 대조한다."""
    path = audit.file("START_HERE_ko.html", "Guide")
    if path is None:
        return
    parser = GuideLinks()
    parser.feed(path.read_text(encoding="utf-8-sig"))
    local_count = 0
    for link in parser.links:
        parts = urlsplit(link)
        if parts.scheme or parts.netloc:
            continue
        if not parts.path:
            if parts.fragment:
                audit.require(unquote(parts.fragment) in parser.anchors, f"Guide anchor missing: {link}")
            continue
        relative = unquote(parts.path)
        if relative.endswith("/"):
            directory = package_path(relative, audit.base)
            audit.require(directory.is_dir(), f"Guide directory missing: {link}")
        else:
            audit.file(relative, "Guide link")
        local_count += 1
    audit.counts["guide_local_links"] = local_count
