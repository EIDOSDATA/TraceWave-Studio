"""! @brief 원문과 검색 텍스트 및 ZIP 내부 문서의 바이트 연결을 검사한다."""

import hashlib
from collections import defaultdict
from zipfile import ZipFile

from dataset_io import load_json


def verify_sources(audit) -> set[str]:
    """! @brief 출처 ID와 보관된 원문 및 현행 검색 텍스트를 확인한다."""
    sources = load_json(audit.base / "catalog/sources.json")
    identifiers = set()
    for source in sources:
        source_id = source["source_id"]
        audit.require(source_id not in identifiers, f"Duplicate source_id: {source_id}")
        identifiers.add(source_id)
        audit.require(bool(source.get("url")), f"{source_id}: source URL missing")
        if source.get("local_path"):
            audit.file(source["local_path"], source_id, source.get("sha256"), source.get("bytes"))
        elif source.get("archived"):
            audit.require(False, f"{source_id}: archived source has no local_path")
        if source.get("search_text_file"):
            audit.file(source["search_text_file"], f"{source_id} search text")
    audit.counts["sources"] = len(sources)
    return identifiers


def verify_search_index(audit, source_ids: set[str]) -> None:
    """! @brief PDF 검색 색인의 원문과 추출 텍스트 해시를 확인한다."""
    entries = load_json(audit.base / "catalog/pdf_search_index.json")
    for entry in entries:
        source_id = entry["source_id"]
        audit.require(source_id in source_ids, f"Search index: unknown source {source_id}")
        audit.file(entry["local_path"], f"{source_id} PDF index", entry.get("sha256"))
        if entry.get("text_path"):
            audit.file(
                entry["text_path"], f"{source_id} PDF text",
                entry.get("text_sha256"), entry.get("text_bytes"),
            )
    audit.counts["pdf_search_entries"] = len(entries)
    extras = load_json(audit.base / "audit/collection/fab_extra_files.json")
    for extra in extras:
        audit.file(
            extra["package_path"], "Fabricator metadata",
            extra.get("sha256"), extra.get("bytes"),
        )
    audit.counts["fabricator_extra_files"] = len(extras)


def verify_archive_members(audit, source_ids: set[str]) -> None:
    """! @brief 압축을 풀어 쓰지 않고 ZIP 구성원과 검색 텍스트를 검증한다."""
    index = load_json(audit.base / "catalog/archive_members.json")
    archives = defaultdict(list)
    for entry in index["members"]:
        archives[entry["archive_path"]].append(entry)
    for relative, entries in archives.items():
        path = audit.file(relative, "ZIP archive", entries[0]["archive_sha256"])
        if path is None:
            continue
        with ZipFile(path) as archive:
            seen = set()
            actual = {item.filename for item in archive.infolist() if not item.is_dir()}
            for entry in entries:
                member = entry["member_path"]
                audit.require(member not in seen, f"Duplicate archive index member: {relative}:{member}")
                seen.add(member)
                audit.require(
                    entry["archive_sha256"] == entries[0]["archive_sha256"],
                    f"Archive hashes disagree in member index: {relative}",
                )
                for source_id in entry["archive_source_ids"]:
                    audit.require(source_id in source_ids, f"Archive member: unknown source {source_id}")
                if member not in actual:
                    audit.require(False, f"Missing archive member: {relative}:{member}")
                    continue
                data = archive.read(member)
                audit.require(len(data) == entry["bytes"], f"Member byte count mismatch: {relative}:{member}")
                audit.require(
                    hashlib.sha256(data).hexdigest() == entry["sha256"],
                    f"Member SHA-256 mismatch: {relative}:{member}",
                )
                if entry.get("text_path"):
                    audit.file(entry["text_path"], f"{relative}:{member} text", entry.get("text_sha256"))
            audit.require(seen == actual, f"Archive index does not cover every member: {relative}")
    audit.counts["archives"] = len(archives)
    audit.counts["archive_members"] = len(index["members"])
