"""! @brief 읽기 전용 카탈로그에서 제조업체 원문 JSON의 완전한 보존을 검증한다."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time


PREFIX = "data/fabricator_native_metadata/"
TABLES = ("native_templates", "native_components", "native_evidence")
MAX_FILE_BYTES = 8 * 1024 * 1024
PAGE_NAME = re.compile(r"board_type_[13]_page_[0-9]{3}\.json\Z")
EVIDENCE_KINDS = {
    "fab_jlc_stackup_audit.json": "jlc_stackup_audit",
    "fab_jlc_material_definitions.json": "jlc_material_definitions",
    "fab_nonpositive_thickness_audit.json": "nonpositive_thickness_audit",
}


def canonical(value):
    """! @brief bool과 int, int와 float의 차이도 유지하는 비교 표현을 만든다."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode(value):
    """! @brief 같은 키를 중복해서 쓰는 JSON을 비교 과정에서 덮어쓰지 않는다."""
    def unique_pairs(pairs):
        """! @brief 객체 안의 키 중복을 즉시 거부한다."""
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("JSON 객체의 키가 중복됩니다.")
            result[key] = item
        return result

    result = json.loads(value, object_pairs_hook=unique_pairs)
    canonical(result)
    return result


def digest_text(value):
    """! @brief 저장된 문자열 자체의 해시를 계산한다."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def digest_file(path):
    """! @brief 큰 SQLite 파일을 메모리에 한 번에 적재하지 않는다."""
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_source(root, relative, manifest):
    """! @brief 명세에 있는 내부 경로의 바이트와 파일별 읽기 상한을 확인한다."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or relative not in manifest:
        raise ValueError("원문 경로가 패키지 명세의 범위를 벗어났습니다: " + relative)
    with path.open("rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    entry = manifest[relative]
    if len(raw) > MAX_FILE_BYTES or len(raw) != entry["bytes"]:
        raise ValueError("원문 크기가 명세 또는 읽기 상한과 다릅니다: " + relative)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry["sha256"]:
        raise ValueError("원문 해시가 명세와 다릅니다: " + relative)
    value = decode(raw)
    return value, digest


def resolve_pointer(value, pointer):
    """! @brief RFC 6901 위치를 따라 원문 객체를 찾으며 음수 배열 순번은 거부한다."""
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError("잘못된 JSON Pointer입니다.")
    for part in pointer[1:].split("/"):
        token = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
                raise ValueError("잘못된 JSON 배열 순번입니다.")
            value = value[int(token)]
        else:
            value = value[token]
    return value


def expected_pointers(filename, original):
    """! @brief 원문 구조에서 기대할 템플릿과 구성행 위치를 독립적으로 열거한다."""
    expected = {table: set() for table in TABLES}
    if PAGE_NAME.fullmatch(filename):
        expected["native_evidence"].add("")
        for index, template in enumerate(original["body"]["list"]):
            pointer = f"/body/list/{index}"
            expected["native_templates"].add(pointer)
            expected["native_components"].update(pointer + f"/basicDataList/{order}"
                                                  for order in range(len(template["basicDataList"])))
    elif filename == "fab_pcbway_stackups.json":
        expected["native_templates"] = {f"/{index}" for index in range(len(original))}
        expected["native_components"] = {f"/{index}/rows/{order}" for index, item in enumerate(original)
                                          for order in range(len(item["rows"]))}
    elif filename == "fab_we_audit.json":
        expected["native_templates"] = {f"/{index}" for index in range(len(original))}
    elif filename == "fab_we_raw_fields.json":
        expected["native_components"] = {f"/{index}" for index in range(len(original))}
    elif filename in EVIDENCE_KINDS:
        expected["native_evidence"].add("")
    else:
        raise ValueError("검증 규칙이 없는 원시 메타데이터입니다: " + filename)
    return expected


class Verification:
    """! @brief 오류 출력은 제한하면서 모든 원문 행과 복원 결과를 대조한다."""

    def __init__(self, connection, audit):
        """! @brief 원문 감사 자료로 JLC의 출처와 템플릿 구분을 연결한다."""
        self.connection = connection
        self.audit = {(item["response_path"].split("/")[-1], item["template_json_index"]): item for item in audit}
        self.errors = []
        self.error_count = 0
        self.counts = {table: 0 for table in TABLES}
        self.component_links = 0
        self.locations = {table: defaultdict(list) for table in TABLES}
        for table in TABLES:
            for row in connection.execute("SELECT rowid,source_path FROM " + table):
                self.locations[table][row[1]].append(row[0])

    def check(self, valid, code, relative, pointer=""):
        """! @brief 데이터 내용은 출력하지 않고 오류의 종류와 원문 위치만 남긴다."""
        if not valid:
            self.error_count += 1
            if len(self.errors) < 100:
                self.errors.append({"code": code, "source_path": relative, "source_pointer": pointer})

    def rows(self, table, relative):
        """! @brief 원문 위치별 rowid로 작은 묶음을 읽어 전체 테이블 반복 스캔을 피한다."""
        identities = self.locations[table].get(relative, [])
        for offset in range(0, len(identities), 256):
            batch = identities[offset:offset + 256]
            statement = "SELECT * FROM " + table + " WHERE rowid IN (" + ",".join("?" for _ in batch) + ")"
            yield from self.connection.execute(statement, batch)

    def identity(self, table, row, filename, original, value):
        """! @brief 원문 출처, 템플릿 부모와 순번 및 위험 표시를 별도로 확인한다."""
        relative, pointer = row["source_path"], row["source_pointer"]
        if table == "native_evidence":
            kind = "jlc_page_envelope_without_templates" if PAGE_NAME.fullmatch(filename) else EVIDENCE_KINDS[filename]
            self.check(row["kind"] == kind, "evidence_kind", relative, pointer)
            return
        flags = decode(row["flags_json"])
        self.check("requires_review" in flags and "not_a_verified_physical_stackup" in flags,
                   "review_status", relative, pointer)
        if PAGE_NAME.fullmatch(filename):
            index = int(pointer.split("/")[3])
            audit = self.audit[(filename, index)]
            self.check(row["source_id"] == audit["source_id"] and row["publisher"] == "JLCPCB",
                       "source_identity", relative, pointer)
            if table == "native_templates":
                kind = "jlc_named_template" if audit["public_ui_named_template"] else "jlc_user_defined_template"
                self.check(row["template_key"] == value["impedanceDefaultTemplateAccessId"] == audit["public_template_id"]
                           and row["kind"] == kind, "template_identity", relative, pointer)
            else:
                self.check(row["component_order"] == int(pointer.split("/")[-1]), "component_order", relative, pointer)
                self.check(row["kind"] == "jlc_api_component", "component_kind", relative, pointer)
                if value.get("material") == "Core":
                    self.check("core_row_may_include_top_and_bottom_copper" in flags, "core_copper_warning", relative, pointer)
        elif filename == "fab_pcbway_stackups.json":
            template = original[int(pointer.split("/")[1])]
            self.check(row["source_id"] == template["source_id"] and row["publisher"] == "PCBWay",
                       "source_identity", relative, pointer)
            if table == "native_templates":
                self.check(row["template_key"] == template["stackup_id"] and row["kind"] == "pcbway_published_template",
                           "template_identity", relative, pointer)
            else:
                order = int(pointer.split("/")[-1])
                self.check(row["component_order"] == order, "component_order", relative, pointer)
                self.check(row["kind"] == "pcbway_html_row", "component_kind", relative, pointer)
                group = template["post_lamination_groups"].get(str(order))
                if group is not None and group["rows"] > 1:
                    self.check("shared_post_lamination_group_total_not_layer_thickness" in flags,
                               "lamination_group_warning", relative, pointer)
        else:
            self.check(row["source_id"] == value["source_id"] and row["publisher"] == "Wurth Elektronik",
                       "source_identity", relative, pointer)
            if table == "native_templates":
                self.check(row["template_key"] == value["file"] and row["kind"] == "we_altium_native_file",
                           "template_identity", relative, pointer)
            else:
                self.check(row["component_order"] == value["layer_index"], "component_order", relative, pointer)
                self.check(row["kind"] == "we_raw_field_record", "component_kind", relative, pointer)
                if any(key[:1].isdigit() for key in value["raw_fields"]):
                    self.check("prefix_cross_layer_fields_present" in flags, "cross_layer_warning", relative, pointer)
        if table == "native_components":
            self.check("native_component_not_physical_layer" in flags, "physical_layer_warning", relative, pointer)

    def file(self, relative, original, source_hash):
        """! @brief 포인터별 값과 타입 및 파일 전체를 복원한 결과를 확인한다."""
        filename = relative.split("/")[-1]
        expected = expected_pointers(filename, original)
        objects = {table: {} for table in TABLES}
        template_ids = {}
        for table in TABLES:
            for row in self.rows(table, relative):
                pointer = row["source_pointer"]
                self.counts[table] += 1
                self.check(pointer in expected[table], "unexpected_pointer", relative, pointer)
                self.check(pointer not in objects[table], "duplicate_pointer", relative, pointer)
                self.check(row["source_sha256"] == source_hash, "source_hash", relative, pointer)
                self.check(row["raw_sha256"] == digest_text(row["raw_json"]), "raw_hash", relative, pointer)
                stored = decode(row["raw_json"])
                source_value = resolve_pointer(original, pointer)
                if table == "native_evidence" and PAGE_NAME.fullmatch(filename):
                    source_value = dict(original)
                    source_value["body"] = {key: value for key, value in original["body"].items() if key != "list"}
                self.check(canonical(stored) == canonical(source_value), "value_or_type", relative, pointer)
                self.identity(table, row, filename, original, stored)
                objects[table][pointer] = stored
                if table == "native_templates":
                    template_ids[pointer] = row["template_id"]
                elif table == "native_components" and filename != "fab_we_raw_fields.json":
                    parent = pointer.rsplit("/basicDataList/" if PAGE_NAME.fullmatch(filename) else "/rows/", 1)[0]
                    self.check(row["template_id"] == template_ids.get(parent), "component_parent", relative, pointer)
                    self.component_links += 1
            self.check(set(objects[table]) == expected[table], "missing_or_extra_records", relative, table)
        if PAGE_NAME.fullmatch(filename):
            restored = objects["native_evidence"].get("")
            if restored is None:
                return None
            restored["body"]["list"] = [objects["native_templates"].get(f"/body/list/{index}")
                                          for index in range(len(original["body"]["list"]))]
        elif filename in ("fab_pcbway_stackups.json", "fab_we_audit.json"):
            restored = [objects["native_templates"].get(f"/{index}") for index in range(len(original))]
        elif filename == "fab_we_raw_fields.json":
            restored = [objects["native_components"].get(f"/{index}") for index in range(len(original))]
        else:
            restored = objects["native_evidence"].get("")
        canonical_hash = digest_text(canonical(original))
        self.check(digest_text(canonical(restored)) == canonical_hash, "document_reconstruction", relative)
        return {"path": relative, "source_sha256": source_hash, "canonical_sha256": canonical_hash,
                "records": {table: len(objects[table]) for table in TABLES}}


def verify_native_catalog(source_root, database):
    """! @brief 원문과 SQLite를 수정하지 않고 재실행 가능한 전수 검증 결과를 반환한다."""
    started = time.monotonic()
    source_root, database = Path(source_root).resolve(), Path(database).resolve()
    before = database.stat()
    manifest_path = source_root / "catalog/file_manifest.json"
    with manifest_path.open("rb") as handle:
        raw_manifest = handle.read(MAX_FILE_BYTES + 1)
    if len(raw_manifest) > MAX_FILE_BYTES:
        raise ValueError("파일 명세 크기 상한을 초과했습니다.")
    manifest = {item["path"]: item for item in decode(raw_manifest)["files"]}
    files = {name for name in manifest if name.startswith(PREFIX)}
    actual = {PREFIX + item.name for item in (source_root / PREFIX).iterdir() if item.is_file()}
    if files != actual:
        raise ValueError("실제 원시 메타데이터 파일과 패키지 명세가 다릅니다.")
    audit, _ = load_source(source_root, PREFIX + "fab_jlc_stackup_audit.json", manifest)
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    try:
        verification = Verification(connection, audit)
        for table in TABLES:
            verification.check(set(verification.locations[table]).issubset(files), "unknown_source_file", table)
        results = []
        for relative in sorted(files):
            value, digest = load_source(source_root, relative, manifest)
            results.append(verification.file(relative, value, digest))
        wrong_parents = connection.execute(
            "SELECT COUNT(*) FROM native_components c JOIN native_templates t USING(template_id) "
            "WHERE c.publisher<>t.publisher OR c.source_id<>t.source_id OR c.stackup_id IS NOT t.stackup_id"
        ).fetchone()[0]
        verification.check(wrong_parents == 0, "template_source_link", "native_components")
        for row in connection.execute(
            "SELECT c.raw_json,t.template_key FROM native_components c JOIN native_templates t USING(template_id) "
            "WHERE c.publisher='Wurth Elektronik'"
        ):
            verification.check(decode(row[0])["stackup_id"] == row[1], "we_component_parent", "native_components")
            verification.component_links += 1
        verification.check(connection.execute("PRAGMA foreign_key_check").fetchone() is None,
                           "foreign_key", "database")
        database_hash = digest_file(database)
    finally:
        connection.close()
    after = database.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("검증 중 카탈로그 파일이 변경되었습니다.")
    return {
        "ok": verification.error_count == 0, "database": str(database),
        "database_sha256": database_hash, "source_root": str(source_root),
        "source_files_checked": len(results), "records_checked": verification.counts,
        "component_parent_links_checked": verification.component_links,
        "errors": verification.errors, "error_count": verification.error_count,
        "files": results, "elapsed_seconds": round(time.monotonic() - started, 3),
        "scope": "전체 원시 JSON의 값/타입/배열순서/해시/포인터/위험표시 대조이며 물리층 승인이나 해석 검증은 아닙니다.",
    }


def main():
    """! @brief 명시한 출처와 DB를 검증하여 JSON 결과 및 성공 여부를 반환한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = verify_native_catalog(arguments.source, arguments.database)
    except (OSError, ValueError, KeyError, IndexError, TypeError, RecursionError, sqlite3.Error) as error:
        result = {"ok": False, "error": str(error), "error_type": type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
