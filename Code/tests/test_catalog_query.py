"""! @brief 작은 SQLite 표본으로 카탈로그 조회의 경계와 원문 보존을 검증한다."""

import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rfad.catalog.models import CATALOG_IMPORT_VERSION, CATALOG_SCHEMA, CatalogError, canonical_json
from rfad.catalog.query import MAX_RESULT_BYTES, parse_detail, parse_search
from rfad.catalog.schema import create_indexes, create_schema
from rfad.catalog.service import CatalogService


class CatalogQueryTests(unittest.TestCase):
    """! @brief 프로젝트, CAD 및 원본 폴더와 독립된 읽기 계약을 검사한다."""

    def setUp(self):
        """! @brief 각 시험이 독립된 인덱스와 누락 조건을 갖도록 한다."""
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "자료 & # %.sqlite"
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)
        create_schema(self.connection)
        create_indexes(self.connection)
        metadata = {"schema": CATALOG_SCHEMA, "import_version": CATALOG_IMPORT_VERSION,
                    "catalog_id": "test:revision1", "created_at": "2026-11-11",
                    "source_index_sha256": "a" * 64, "source_canonical_sha256": "b" * 64,
                    "counts": {"observations": 4, "products": 1}, "readiness": "not_assessed"}
        self.connection.executemany("INSERT INTO meta VALUES (?,?)", [(key, canonical_json(value))
                                                                    for key, value in metadata.items()])
        self.insert("sources", source_id="source1", publisher="Fabricator", title="시험 원문", url="https://example.test",
                    local_path="originals/fixture.json", local_available=1)
        self.insert("products", product_id="product1", publisher="Fabricator", product="FR-4",
                    dataset_role="fabricator")
        self.insert("stackups", stackup_id="stackup1", publisher="Fabricator", source_stackup_id="S4",
                    label="공개 4층", layer_count=4, nominal_thickness_mm=1.6, native_available=1)
        base = {"product_id": "product1", "source_id": "source1", "publisher": "Fabricator", "product": "FR-4",
                "dataset_role": "fabricator", "stackup_id": "stackup1", "material_form": "core"}
        self.insert("observations", **base, record_id="r01", dk=4.2, df=0.02, frequency_ghz=2.4,
                    thickness_mm=0.2, raw={"record_id": "r01", "dk": 4.2, "df": 0.02, "missing": None})
        self.insert("observations", **base, record_id="r02", df=0.03, frequency_ghz=1.0, df_frequency_ghz=5.0,
                    thickness_mm=0.4)
        self.insert("observations", **base, record_id="r03", dk_min=4.0, dk_max=4.4,
                    frequency_min_ghz=1.0, frequency_max_ghz=10.0, thickness_mm=0.8)
        self.insert("observations", **(base | {"product": "literal %_\\' text"}), record_id="r04", dk=4.0,
                    frequency_ghz=2.4, df_frequency_ghz=2.4)
        self.connection.execute("INSERT INTO observation_flags VALUES (?,?)", ("r01", "df_frequency_missing"))
        native = {"publisher": "Fabricator", "source_id": "source1", "source_path": "native.json",
                  "source_pointer": "/templates/0", "source_sha256": "c" * 64, "flags_json": '["reference_only"]'}
        self.insert("native_templates", **native, template_id="template1", template_key="user-defined", kind="jlc")
        self.insert("native_components", **native, component_id="component1", template_id="template1",
                    component_order=0, kind="Core", raw={"id": 4200000000000000001, "copper": None})
        self.insert("native_evidence", evidence_id="evidence1", kind="page_metadata", source_path="native.json",
                    source_pointer="/body", source_sha256="d" * 64)
        self.connection.commit()
        self.service = CatalogService(self.database)

    def insert(self, table: str, *, raw: dict | None = None, **fields):
        """! @brief 시험 소유 표에 원문과 정확한 UTF-8 해시를 함께 넣는다."""
        text = canonical_json(fields if raw is None else raw)
        if table == "observations":
            fields["properties_json"] = canonical_json({"readiness": "not_assessed", "fixture": True})
        fields.update(raw_json=text, raw_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
        names = ",".join(fields)
        self.connection.execute("INSERT INTO " + table + " (" + names + ") VALUES ("
                                + ",".join("?" for _ in fields) + ")", tuple(fields.values()))

    def search(self, **filters):
        """! @brief 관측 필터 요청을 짧게 구성한다."""
        return self.service.search({"entity": "observations", "filters": filters})

    def test_status_is_optional_and_invalid_database_is_reported(self):
        """! @brief 미설정과 누락 및 손상된 파일 때문에 서비스 생성이 실패하지 않는다."""
        self.assertEqual(CatalogService().status()["state"], "unconfigured")
        missing = Path(self.temporary.name) / "missing.sqlite"
        self.assertEqual(CatalogService(missing).status()["state"], "missing")
        self.assertFalse(missing.exists())
        broken = Path(self.temporary.name) / "broken.sqlite"
        broken.write_bytes(b"not sqlite")
        self.assertEqual(CatalogService(broken).status()["state"], "invalid")
        status = self.service.status()
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["import_version"], CATALOG_IMPORT_VERSION)
        self.assertEqual(status["readiness"], "not_assessed")
        self.assertLess(len(canonical_json(status).encode("utf-8")), 4096)
        self.connection.execute("UPDATE meta SET value=? WHERE key='counts'", ('[]',))
        self.connection.commit()
        self.assertEqual(self.service.status()["state"], "invalid")

    def test_dk_df_and_record_frequency_are_not_conflated(self):
        """! @brief 공통 주파수를 Df로 전용하거나 Df만 있는 행을 Dk로 표시하지 않는다."""
        self.assertEqual([item["id"] for item in self.search(frequency_ghz=2.4, frequency_property="dk")["items"]],
                         ["r01", "r04"])
        self.assertEqual(self.search(frequency_ghz=2.4, frequency_property="df")["items"], [])
        self.assertEqual([item["id"] for item in self.search(frequency_ghz=5.0, frequency_property="df")["items"]], ["r02"])
        self.assertEqual(self.search(frequency_ghz=1.0, frequency_property="dk")["items"], [])
        record = self.search(frequency_ghz=1.0, frequency_property="record")
        self.assertEqual([item["id"] for item in record["items"]], ["r02"])
        self.assertEqual(record["frequency_scope"]["meaning"], "record_frequency_not_property_assignment")

    def test_explicit_ranges_are_searchable_without_interpolation(self):
        """! @brief 공개 주파수 범위 포함은 점주파수 보간 및 Df 범위 확정과 다르다."""
        self.assertEqual(self.search(frequency_ghz=7.0, frequency_property="dk")["items"], [])
        result = self.search(frequency_ghz=7.0, frequency_property="dk", frequency_mode="contains")
        self.assertEqual([item["id"] for item in result["items"]], ["r03"])
        self.assertIsNone(result["items"][0]["dk"])
        self.assertFalse(result["frequency_scope"]["interpolated"])
        self.assertEqual(self.search(frequency_ghz=7.0, frequency_property="df", frequency_mode="contains")["items"], [])

    def test_filters_escape_like_and_bind_sql_values(self):
        """! @brief SQL 조각과 LIKE 와일드카드는 리터럴 검색값으로 취급한다."""
        result = self.service.search({"entity": "observations", "query": "%_\\'"})
        self.assertEqual([item["id"] for item in result["items"]], ["r04"])
        self.assertEqual(self.search(publisher="' OR 1=1 --")["items"], [])
        self.assertEqual([item["id"] for item in self.search(layer_count=4, thickness_min_mm=0.3,
                                                            thickness_max_mm=0.8)["items"]], ["r02", "r03"])
        self.assertEqual([item["id"] for item in self.search(review_flag="df_frequency_missing")["items"]], ["r01"])

    def test_page_revision_and_stable_order(self):
        """! @brief 중간 개정 교체는 같은 페이지 흐름으로 이어 붙일 수 없다."""
        first = self.service.search({"entity": "observations", "limit": 2})
        self.assertEqual([item["id"] for item in first["items"]], ["r01", "r02"])
        self.assertEqual(first["next_offset"], 2)
        request = {"entity": "observations", "limit": 2, "offset": first["next_offset"], "catalog_id": first["catalog_id"]}
        second = self.service.search(request)
        self.assertEqual([item["id"] for item in second["items"]], ["r03", "r04"])
        self.assertIsNone(second["next_offset"])
        self.connection.execute("UPDATE meta SET value=? WHERE key='catalog_id'", ('"test:revision2"',))
        self.connection.commit()
        with self.assertRaises(CatalogError) as caught:
            self.service.search(request)
        self.assertEqual(caught.exception.code, "E_CONFLICT")

    def test_native_templates_without_normalized_stackup_remain_visible(self):
        """! @brief 원자료 구성행과 사용자 정의 템플릿도 정규 물리층으로 승격하지 않는다."""
        template = self.service.search({"entity": "native_templates", "filters": {"review_flag": "reference_only"}})
        self.assertEqual(template["items"][0]["id"], "template1")
        self.assertIsNone(template["items"][0]["stackup_id"])
        self.assertEqual(template["readiness"], "not_assessed")
        detail = self.service.get({"entity": "native_components", "id": "component1"})
        self.assertEqual(json.loads(detail["raw"]["text"])["id"], 4200000000000000001)
        self.assertNotIn("raw_json", detail["item"])
        self.assertEqual(len(self.service.search({"entity": "native_evidence"})["items"]), 1)

    def test_raw_unicode_fragments_reconstruct_all_types_and_hash(self):
        """! @brief 큰 JSON도 문자 경계와 전체 해시를 보존하며 여러 응답으로 읽는다."""
        original = {"text": "가😀\"\\" * 20000, "integer": 4200000000000000001, "null": None, "bool": False}
        raw = canonical_json(original)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.connection.execute("UPDATE observations SET raw_json=?,raw_sha256=? WHERE record_id='r01'", (raw, digest))
        self.connection.commit()
        chunks, offset, revision = [], 0, "test:revision1"
        while offset is not None:
            result = self.service.get({"entity": "observations", "id": "r01", "raw_offset": offset,
                                       "raw_limit": 8192, "catalog_id": revision})
            self.assertLessEqual(len(canonical_json(result).encode("utf-8")), MAX_RESULT_BYTES)
            self.assertEqual(result["raw"]["offset_unit"], "unicode_codepoints")
            self.assertEqual(result["raw"]["sha256"], digest)
            self.assertEqual(result["properties"], {"readiness": "not_assessed", "fixture": True})
            chunks.append(result["raw"]["text"])
            offset = result["raw"]["next_offset"]
        restored = "".join(chunks)
        self.assertEqual(restored, raw)
        self.assertEqual(json.loads(restored), original)
        self.assertEqual(hashlib.sha256(restored.encode("utf-8")).hexdigest(), digest)

    def test_search_byte_budget_does_not_drop_following_rows(self):
        """! @brief 긴 표시 문자열이 있으면 페이지를 줄이고 다음 실제 행부터 이어 읽는다."""
        for number in range(100):
            self.insert("products", product_id=f"long{number:03d}", publisher="회사" * 300,
                        product="재질" * 300, dataset_role="role", laminate_manufacturer="소재" * 300)
        self.connection.commit()
        identifiers, offset = [], 0
        byte_limited = False
        while offset is not None:
            result = self.service.search({"entity": "products", "limit": 100, "offset": offset,
                                          "catalog_id": "test:revision1"})
            self.assertLessEqual(len(canonical_json(result).encode("utf-8")), MAX_RESULT_BYTES)
            byte_limited |= result["limited_by_bytes"]
            identifiers.extend(item["id"] for item in result["items"])
            offset = result["next_offset"]
        self.assertTrue(byte_limited)
        self.assertEqual(len(identifiers), 101)
        self.assertEqual(len(set(identifiers)), 101)

    def test_readonly_connections_do_not_write_or_import_cad(self):
        """! @brief 조회 연결의 쓰기 차단과 DB 및 외부 원문 비접근을 확인한다."""
        before = self.database.read_bytes()
        self.service.search({"entity": "observations"})
        self.service.get({"entity": "sources", "id": "source1"})
        with self.assertRaises(CatalogError):
            with self.service.repository.connection() as (connection, _):
                self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA trusted_schema").fetchone()[0], 0)
                connection.execute("DELETE FROM observations")
        self.assertEqual(self.database.read_bytes(), before)
        self.assertFalse(self.database.with_name(self.database.name + "-journal").exists())

    def test_bad_inputs_and_unknown_filters_are_rejected(self):
        """! @brief bool 수치, 비유한 수, 필터 오타 및 임의 SQL과 경로 입력을 거부한다."""
        invalid = [{"entity": "observations", "limit": True}, {"entity": "observations", "limit": 101},
                   {"entity": "observations", "offset": 1}, {"entity": "observations", "sql": "SELECT 1"},
                   {"entity": "sources; DROP TABLE products"}, {"entity": "products", "filters": {"frequency_ghz": 2.4}},
                   {"entity": "observations", "filters": {"frequency_ghz": float("nan"), "frequency_property": "dk"}},
                   {"entity": "observations", "filters": {"frequency_ghz": 10**1000, "frequency_property": "dk"}},
                   {"entity": "observations", "filters": {"frequency_ghz": 2.4}},
                   {"entity": "observations", "filters": {"thickness_min_mm": 2, "thickness_max_mm": 1}},
                   {"entity": "observations", "filters": {"layer_count": True}},
                   {"entity": "sources", "filters": {"local_available": 1}},
                   {"entity": "observations", "query": "\x00"}]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(CatalogError):
                parse_search(request)
        for request in ({"entity": "observations", "id": "r01", "raw_offset": 1},
                        {"entity": "observations", "id": "r01", "raw_limit": 8193},
                        {"entity": "sources", "id": "source1", "path": "outside.json"}):
            with self.subTest(request=request), self.assertRaises(CatalogError):
                parse_detail(request)

    def test_wrong_schema_missing_row_and_tampered_small_raw_are_explicit(self):
        """! @brief 누락 및 해시 오류를 빈 정상 결과나 물성 기본값으로 바꾸지 않는다."""
        with self.assertRaises(CatalogError) as caught:
            self.service.get({"entity": "observations", "id": "missing"})
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        self.connection.execute("UPDATE observations SET raw_json='{}' WHERE record_id='r01'")
        self.connection.commit()
        with self.assertRaises(CatalogError) as caught:
            self.service.get({"entity": "observations", "id": "r01"})
        self.assertEqual(caught.exception.code, "E_HASH")
        self.connection.execute("PRAGMA user_version=999")
        self.connection.commit()
        self.assertEqual(self.service.status()["diagnostic"]["code"], "E_VERSION")

    def test_missing_tables_and_oversized_derived_property_are_rejected(self):
        """! @brief 필수 스키마와 파생 표시 DTO의 크기 계약도 조회 시 검사한다."""
        self.connection.execute("UPDATE observations SET properties_json=? WHERE record_id='r01'",
                                (canonical_json({"text": "한" * 3000}),))
        self.connection.commit()
        with self.assertRaises(CatalogError):
            self.service.get({"entity": "observations", "id": "r01"})
        self.connection.execute("DROP TABLE native_evidence")
        self.connection.commit()
        self.assertEqual(self.service.status()["state"], "invalid")

    def test_missing_or_unknown_import_version_requires_rebuild(self):
        """! @brief 같은 SQL 구조라도 변환 의미가 다른 인덱스는 읽기를 거부한다."""
        for value in (None, "rfad.catalog.import/999"):
            with self.subTest(value=value):
                self.connection.execute("DELETE FROM meta WHERE key='import_version'")
                if value is not None:
                    self.connection.execute("INSERT INTO meta VALUES (?,?)", ("import_version", canonical_json(value)))
                self.connection.commit()
                status = self.service.status()
                self.assertEqual(status["state"], "invalid")
                self.assertEqual(status["diagnostic"]["code"], "E_VERSION")
                with self.assertRaises(CatalogError) as caught:
                    self.service.search({"entity": "observations"})
                self.assertEqual(caught.exception.code, "E_VERSION")

    def test_detail_stops_when_even_one_character_exceeds_budget(self):
        """! @brief 요약만으로 예산을 넘으면 같은 한 글자를 무한히 축약하지 않는다."""
        with patch("rfad.catalog.service.MAX_RESULT_BYTES", 256), self.assertRaises(CatalogError) as caught:
            self.service.get({"entity": "observations", "id": "r01"})
        self.assertEqual(caught.exception.code, "E_RESOURCE")


if __name__ == "__main__":
    unittest.main()
