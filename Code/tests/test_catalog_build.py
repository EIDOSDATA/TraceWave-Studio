"""! @brief 카탈로그 원문 보존과 실패 시 기존 인덱스 보호를 검증한다."""

from copy import deepcopy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from rfad.catalog.build import build_catalog
from rfad.catalog.models import CatalogError, stable_id
from rfad.catalog.review import flags


def write_json(path: Path, value: object) -> None:
    """! @brief 시험 패키지의 JSON을 실제 UTF-8 파일로 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def manifest(package: Path) -> None:
    """! @brief 시험 입력의 변경을 의도적으로 승인할 때 파일 명세를 다시 만든다."""
    entries = []
    for path in sorted(package.rglob("*")):
        if not path.is_file() or path.name == "file_manifest.json":
            continue
        raw = path.read_bytes()
        entries.append({"path": path.relative_to(package).as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    write_json(package / "catalog/file_manifest.json", {"schema": "rfad.reference.file-manifest/1", "files": entries})


def make_package(package: Path, records: list[dict] | None = None) -> list[dict]:
    """! @brief 미제공/null/숫자/배열/객체를 가진 작고 완결된 공개 관측을 구성한다."""
    if records is None:
        records = [
            {"record_id": "PCB000002", "source_id": "S1", "manufacturer": "Example",
             "product": "Board material", "dataset_role": "fabricator_published_parameter",
             "laminate_manufacturer": "Actual supplier", "dk": 4.2, "df": None,
             "frequency_ghz": 1, "stackup_id": "STACK-A", "copper_layer_count": 2,
             "nominal_board_thickness_mm": 1.0, "thickness_mm": 0.93,
             "source_file": "originals/source.txt", "value_type": "fabricator_calculator",
             "raw_fields": {"boolean": False, "items": [1, "1", None]}},
            {"record_id": "PCB000001", "source_id": "S1", "manufacturer": "Example",
             "product": "Board material", "dataset_role": "material_published_parameter",
             "dk": 4, "frequency_ghz": 10, "df_frequency_ghz": 1,
             "source_file": "originals/source.txt", "value_type": "design"},
        ]
    original = package / "originals/source.txt"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"Published source bytes.\n")
    write_json(package / "catalog/sources.json", [{
        "source_id": "S1", "organization": "Example", "title": "Published data", "url": "https://example.com/data",
        "local_path": "originals/source.txt", "archived": True, "bytes": original.stat().st_size,
        "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
    }])
    definitions = {}
    for record in records:
        for field, value in record.items():
            definitions.setdefault(field, set())
            if value is not None:
                definitions[field].add(type(value).__name__)
    write_json(package / "catalog/schema.json", {"fields": [
        {"field": field, "observed_types": ",".join(sorted(types))} for field, types in definitions.items()
    ]})
    partitions = []
    for publisher in sorted({record["manufacturer"] for record in records}):
        path = package / "data/observations" / (publisher + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        group = [record for record in records if record["manufacturer"] == publisher]
        raw = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in group).encode("utf-8")
        path.write_bytes(raw)
        partitions.append({"publisher": publisher, "path": path.relative_to(package).as_posix(),
                           "records": len(group), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    canonical = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                        for record in sorted(records, key=lambda record: record["record_id"])).encode("utf-8")
    write_json(package / "data/observations/index.json", {
        "schema": "rfad.reference.observations/1", "record_count": len(records),
        "canonical_sha256": hashlib.sha256(canonical).hexdigest(), "partitions": partitions,
    })
    manifest(package)
    return records


class CatalogBuildTests(unittest.TestCase):
    """! @brief 임시 실제 파일과 SQLite로 원자 발행과 입력 계약을 확인한다."""

    def setUp(self):
        """! @brief 사용자 자료와 분리된 시험 패키지와 출력 경로를 만든다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.package = self.directory / "source"
        self.output = self.directory / "catalog.sqlite"
        self.records = make_package(self.package)

    def tearDown(self):
        """! @brief 생성한 시험 파일만 정리한다."""
        self.temporary.cleanup()

    def assert_failure_preserves_existing(self, code: str | None = None):
        """! @brief 실패한 생성이 기존 DB 바이트와 임시 파일 상태를 보존하는지 확인한다."""
        before = self.output.read_bytes()
        with self.assertRaises(CatalogError) as raised:
            build_catalog(self.package, self.output, overwrite=True)
        if code is not None:
            self.assertEqual(raised.exception.code, code)
        self.assertEqual(before, self.output.read_bytes())
        self.assertEqual(list(self.directory.glob(".catalog-*")), [])

    def test_raw_records_types_omitted_keys_and_foreign_keys_survive(self):
        before = {path.relative_to(self.package): path.read_bytes() for path in self.package.rglob("*") if path.is_file()}
        result = build_catalog(self.package, self.output)
        with closing(sqlite3.connect(self.output)) as database:
            rows = {identity: json.loads(raw) for identity, raw in database.execute("SELECT record_id,raw_json FROM observations")}
            self.assertEqual(rows, {record["record_id"]: record for record in self.records})
            self.assertNotIn("df", rows["PCB000001"])
            self.assertIsNone(rows["PCB000002"]["df"])
            self.assertIs(type(rows["PCB000001"]["dk"]), int)
            self.assertIs(type(rows["PCB000002"]["dk"]), float)
            self.assertEqual(database.execute("SELECT count(*) FROM products").fetchone()[0], 2)
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
            for raw, digest in database.execute("SELECT raw_json,raw_sha256 FROM observations"):
                self.assertEqual(hashlib.sha256(raw.encode("utf-8")).hexdigest(), digest)
        self.assertEqual(result["counts"]["observations"], 2)
        self.assertEqual(result["readiness"], "not_assessed")
        self.assertEqual(before, {path.relative_to(self.package): path.read_bytes() for path in self.package.rglob("*") if path.is_file()})

    def test_product_and_stackup_ids_are_independent_of_package_location(self):
        first = build_catalog(self.package, self.output)
        other = self.directory / "elsewhere"
        make_package(other, deepcopy(self.records))
        second_path = self.directory / "second.sqlite"
        second = build_catalog(other, second_path)
        with closing(sqlite3.connect(self.output)) as left, closing(sqlite3.connect(second_path)) as right:
            self.assertEqual(left.execute("SELECT product_id FROM products ORDER BY product_id").fetchall(),
                             right.execute("SELECT product_id FROM products ORDER BY product_id").fetchall())
            self.assertEqual(left.execute("SELECT stackup_id FROM stackups").fetchone()[0], stable_id("stackup", "Example", "STACK-A"))
        self.assertEqual(first["catalog_id"], second["catalog_id"])

    def test_bad_partition_hash_preserves_previous_database(self):
        build_catalog(self.package, self.output)
        with (self.package / "data/observations/Example.jsonl").open("ab") as handle:
            handle.write(b" ")
        self.assert_failure_preserves_existing("E_HASH")

    def test_bad_original_source_hash_preserves_previous_database(self):
        build_catalog(self.package, self.output)
        (self.package / "originals/source.txt").write_bytes(b"Changed source.\n")
        manifest(self.package)
        self.assert_failure_preserves_existing("E_HASH")

    def test_wrong_canonical_hash_preserves_previous_database(self):
        build_catalog(self.package, self.output)
        path = self.package / "data/observations/index.json"
        index = json.loads(path.read_text(encoding="utf-8"))
        index["canonical_sha256"] = "0" * 64
        write_json(path, index)
        manifest(self.package)
        self.assert_failure_preserves_existing("E_HASH")

    def test_duplicate_ids_and_unknown_sources_are_rejected(self):
        build_catalog(self.package, self.output)
        duplicate = deepcopy(self.records)
        duplicate[1]["record_id"] = duplicate[0]["record_id"]
        make_package(self.package, duplicate)
        self.assert_failure_preserves_existing("E_SCHEMA")
        missing_source = deepcopy(self.records)
        missing_source[0]["source_id"] = "unknown"
        make_package(self.package, missing_source)
        self.assert_failure_preserves_existing("E_SCHEMA")

    def test_nonfinite_numbers_and_nonpositive_normalized_thickness_are_rejected(self):
        build_catalog(self.package, self.output)
        for value, code in ((float("nan"), "E_SCHEMA"), (float("inf"), "E_SCHEMA"), (-0.1, "E_RANGE")):
            records = deepcopy(self.records)
            records[0]["thickness_mm"] = value
            make_package(self.package, records)
            self.assert_failure_preserves_existing(code)

    def test_input_path_escape_and_output_inside_package_are_rejected(self):
        build_catalog(self.package, self.output)
        records = deepcopy(self.records)
        records[0]["source_file"] = "../outside.txt"
        make_package(self.package, records)
        self.assert_failure_preserves_existing("E_PATH")
        with self.assertRaises(CatalogError):
            build_catalog(self.package, self.package / "catalog.sqlite")

    def test_source_hardlink_cannot_be_overwritten(self):
        build_catalog(self.package, self.output)
        linked = self.package / "originals/linked.sqlite"
        os.link(self.output, linked)
        manifest(self.package)
        self.assert_failure_preserves_existing("E_PATH")

    def test_overwrite_is_explicit_and_only_for_catalog_databases(self):
        self.output.write_bytes(b"A user document")
        self.assert_failure_preserves_existing("E_VERSION")
        self.output.unlink()
        with closing(sqlite3.connect(self.output)) as database:
            database.execute("CREATE TABLE unrelated (value TEXT)")
        self.assert_failure_preserves_existing("E_VERSION")
        self.output.unlink()
        build_catalog(self.package, self.output)
        with self.assertRaises(CatalogError) as raised:
            build_catalog(self.package, self.output)
        self.assertEqual(raised.exception.code, "E_EXISTS")
        second = build_catalog(self.package, self.output, overwrite=True)
        self.assertEqual(second["counts"]["observations"], 2)

    def test_review_flags_preserve_dangerous_raw_evidence(self):
        records = deepcopy(self.records)
        records[0].update({"thickness_mm": None, "thickness_status": "invalid_nonpositive_source_ply_value",
                           "raw_reported_thickness_mm": -0.0185, "relative_permeability": 6})
        make_package(self.package, records)
        build_catalog(self.package, self.output)
        with closing(sqlite3.connect(self.output)) as database:
            actual = {row[0] for row in database.execute("SELECT flag FROM observation_flags WHERE record_id=?", (records[0]["record_id"],))}
            self.assertEqual(actual, set(flags(records[0])))
            self.assertIn("invalid_nonpositive_source_ply_value", actual)
            self.assertIn("nonunit_relative_permeability", actual)
            self.assertIsNone(database.execute("SELECT thickness_mm FROM observations WHERE record_id=?", (records[0]["record_id"],)).fetchone()[0])

    def test_stackup_conflicting_thickness_remains_a_set_of_candidates(self):
        records = deepcopy(self.records)
        extra = deepcopy(records[0])
        extra["record_id"] = "PCB000003"
        extra["nominal_board_thickness_mm"] = 1.6
        records.append(extra)
        make_package(self.package, records)
        build_catalog(self.package, self.output)
        with closing(sqlite3.connect(self.output)) as database:
            thickness, raw = database.execute("SELECT nominal_thickness_mm,raw_json FROM stackups").fetchone()
            self.assertIsNone(thickness)
            self.assertEqual(json.loads(raw)["nominal_thicknesses_mm"], [1.0, 1.6])

    def test_cached_source_change_before_publication_is_detected(self):
        """! @brief 검증 캐시 이후 바뀐 원문을 마지막 확인에서 차단한다."""
        build_catalog(self.package, self.output)

        def change_source(connection, source_root, package):
            """! @brief 관측을 읽은 뒤 원문 변경 경쟁을 시험한다."""
            (source_root / "originals/source.txt").write_bytes(b"Changed after cached verification.\n")
            return {"readiness": "not_assessed"}

        with patch("rfad.catalog.native.import_native", side_effect=change_source):
            self.assert_failure_preserves_existing("E_CONFLICT")

    def test_import_version_changes_catalog_revision_but_preserves_source_ids(self):
        """! @brief 변환 규칙의 개정으로 페이지 혼합을 막고 원문 개체 ID는 유지한다."""
        first = build_catalog(self.package, self.output)
        second_path = self.directory / "new-import.sqlite"
        with patch("rfad.catalog.build.CATALOG_IMPORT_VERSION", "rfad.catalog.import/test-next"):
            second = build_catalog(self.package, second_path)
        self.assertNotEqual(first["catalog_id"], second["catalog_id"])
        self.assertNotEqual(first["import_version"], second["import_version"])
        with closing(sqlite3.connect(self.output)) as left, closing(sqlite3.connect(second_path)) as right:
            self.assertEqual(left.execute("SELECT product_id FROM products ORDER BY product_id").fetchall(),
                             right.execute("SELECT product_id FROM products ORDER BY product_id").fetchall())

    def test_malformed_metadata_containers_return_schema_errors(self):
        """! @brief 유효한 해시라도 잘못된 메타데이터 구조는 명시적인 진단으로 거부한다."""
        build_catalog(self.package, self.output)
        cases = (
            ("catalog/products.json", ["not an object"]),
            ("catalog/products.json", {"unexpected": []}),
            ("catalog/products.json", [{"organization": [], "product": "X"}]),
            ("catalog/schema.json", {"fields": ["not an object"]}),
            ("catalog/schema.json", {"fields": [{"field": "dk", "observed_types": []}]}),
        )
        for relative, value in cases:
            with self.subTest(relative=relative, value=value):
                make_package(self.package, self.records)
                products = self.package / "catalog/products.json"
                if products.exists():
                    products.unlink()
                write_json(self.package / relative, value)
                manifest(self.package)
                self.assert_failure_preserves_existing("E_SCHEMA")
        for partitions in (["not an object"], {"path": "wrong container"}, [{"path": []}]):
            with self.subTest(partitions=partitions):
                make_package(self.package, self.records)
                products = self.package / "catalog/products.json"
                if products.exists():
                    products.unlink()
                path = self.package / "data/observations/index.json"
                index = json.loads(path.read_text(encoding="utf-8"))
                index["partitions"] = partitions
                write_json(path, index)
                manifest(self.package)
                self.assert_failure_preserves_existing("E_SCHEMA")


if __name__ == "__main__":
    unittest.main()
