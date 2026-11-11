"""! @brief 원시 적층의 공개 표기를 기존 DB 연결로 조회하는 GUI 검색 계약을 검사한다."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from rfad.catalog.models import canonical_json
from rfad.catalog.query import MAX_RESULT_BYTES
from rfad.catalog.service import CatalogService
import test_catalog_query as query_fixture


class CatalogNativeLabelTests(unittest.TestCase):
    """! @brief 스키마 재생성 없이 작은 표본의 연결, 검색, 제한과 원문 보존을 확인한다."""

    def setUp(self):
        """! @brief 기존 조회 표본을 공유하되 시험 상태와 정리를 독립적으로 소유한다."""
        self.fixture = query_fixture.CatalogQueryTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.connection = self.fixture.connection
        self.service = self.fixture.service
        self.label = "JLC04061H-3313 (공개 4층, 1.6 mm)"
        self.connection.execute("UPDATE stackups SET label=? WHERE stackup_id='stackup1'", (self.label,))
        self.add_template("template2")
        self.add_template("template3")
        self.connection.commit()

    def add_template(self, identity):
        """! @brief 원시의 큰 정수는 원문에 두고 목록 식별자는 문자열로 보존한다."""
        self.fixture.insert("native_templates", template_id=identity, template_key="4200000000000000001",
                            stackup_id="stackup1", publisher="Fabricator", source_id="source1", kind="jlc_named_template",
                            source_path="native.json", source_pointer="/templates/1", source_sha256="c" * 64,
                            flags_json='["reference_only"]', raw={"id": 4200000000000000001, "missing": None})

    def search(self, **values):
        """! @brief 목록의 기존 공개 계약에 query만 추가해 호출한다."""
        return self.service.search({"entity": "native_templates", **values})

    def test_linked_summary_and_unlinked_templates_preserve_existing_contract(self):
        """! @brief 공개 표기는 보조 요약이며 미연결 원자료를 제외하거나 물리 적층으로 승격하지 않는다."""
        result = self.search()
        self.assertEqual([item["id"] for item in result["items"]], ["template1", "template2", "template3"])
        self.assertEqual(result["readiness"], "not_assessed")
        unlinked, linked = result["items"][:2]
        for field in ("stackup_label", "layer_count", "nominal_thickness_mm"):
            self.assertIsNone(unlinked[field])
        self.assertEqual(linked["stackup_label"], self.label)
        self.assertEqual(linked["layer_count"], 4)
        self.assertEqual(linked["nominal_thickness_mm"], 1.6)
        self.assertEqual(linked["template_key"], "4200000000000000001")
        self.assertEqual(linked["review_flags"], ["reference_only"])
        self.assertNotIn("raw_json", linked)
        detail = self.service.get({"entity": "native_templates", "id": "template2"})
        self.assertEqual(detail["item"], linked)
        self.assertEqual(json.loads(detail["raw"]["text"]), {"id": 4200000000000000001, "missing": None})

    def test_query_searches_full_linked_label_with_literal_sql_wildcards(self):
        """! @brief hash 키를 몰라도 공개 적층 표기로 찾으며 와일드카드와 SQL은 실행하지 않는다."""
        found = self.search(query="JLC04061H")
        self.assertEqual([item["id"] for item in found["items"]], ["template2", "template3"])
        literal = "한글 %_\\' 끝표기"
        self.connection.execute("UPDATE stackups SET label=?", ("앞" * 600 + literal,))
        self.connection.commit()
        found = self.search(query=literal)
        self.assertEqual(len(found["items"]), 2)
        self.assertEqual(len(found["items"][0]["stackup_label"]), 512)
        self.assertIn("stackup_label", found["items"][0]["truncated_fields"])
        self.assertEqual(self.search(query="' OR 1=1 --")["items"], [])
        self.assertEqual(self.search(query="user-defined")["items"][0]["id"], "template1")

    def test_query_is_one_page_sql_with_stable_ids_and_no_raw_json(self):
        """! @brief 행마다 추가 조회하지 않고 PK 왼쪽 결합 한 번으로 같은 순서의 페이지를 만든다."""
        statements = []
        original = self.service.repository.connection

        @contextmanager
        def traced_connection():
            """! @brief 스키마 검증 이후의 실제 목록 조회만 기록한다."""
            with original() as (connection, metadata):
                connection.set_trace_callback(statements.append)
                yield connection, metadata

        with patch.object(self.service.repository, "connection", traced_connection):
            first = self.search(query="JLC04061H", limit=1)
        self.assertEqual(len(statements), 1)
        self.assertIn("LEFT JOIN stackups", statements[0])
        self.assertNotIn("raw_json", statements[0])
        second = self.search(query="JLC04061H", limit=1, offset=first["next_offset"], catalog_id=first["catalog_id"])
        self.assertEqual([first["items"][0]["id"], second["items"][0]["id"]], ["template2", "template3"])
        self.assertFalse(second["has_more"])

    def test_long_joined_labels_keep_byte_bound_and_all_page_rows(self):
        """! @brief 새 표시 열도 기존 축약 및 48 KiB 페이지 제한을 따라 후속 행을 잃지 않는다."""
        self.connection.execute("UPDATE stackups SET label=?", ("공개 적층 " * 200,))
        for number in range(100):
            self.add_template(f"wide{number:03d}")
        self.connection.commit()
        offset, identities, limited = 0, [], False
        while offset is not None:
            result = self.search(limit=100, offset=offset, catalog_id="test:revision1")
            self.assertLessEqual(len(canonical_json(result).encode("utf-8")), MAX_RESULT_BYTES)
            limited |= result["limited_by_bytes"]
            identities.extend(item["id"] for item in result["items"])
            offset = result["next_offset"]
        self.assertTrue(limited)
        self.assertEqual(len(identities), 103)
        self.assertEqual(len(set(identities)), 103)


@unittest.skipUnless(os.environ.get("RFAD_CATALOG_TEST_DB"), "실제 DB 경로를 지정한 조회 검증에서 실행")
class CatalogNativeLabelRealDatabaseTests(unittest.TestCase):
    """! @brief 보관된 전체 DB도 재생성 없이 JLC 공개 표기로 조회되는지 검사한다."""

    def test_real_jlc_label_search_and_unlinked_identity(self):
        """! @brief 실제 연결 요약을 원래 SQL 값과 대조하고 사용자 정의 템플릿도 유지한다."""
        database = Path(os.environ["RFAD_CATALOG_TEST_DB"]).absolute()
        before = database.stat()
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        linked = dict(connection.execute(
            "SELECT c.template_id,s.label,s.layer_count,s.nominal_thickness_mm FROM native_templates c "
            "JOIN stackups s ON s.stackup_id=c.stackup_id WHERE c.publisher='JLCPCB' AND s.layer_count=4 "
            "ORDER BY c.template_id LIMIT 1").fetchone())
        unlinked = connection.execute(
            "SELECT template_id FROM native_templates WHERE publisher='JLCPCB' AND stackup_id IS NULL LIMIT 1").fetchone()[0]
        service = CatalogService(database)
        result = service.search({"entity": "native_templates", "filters": {"publisher": "JLCPCB"}, "query": linked["label"]})
        self.assertLessEqual(len(canonical_json(result).encode("utf-8")), MAX_RESULT_BYTES)
        item = next(item for item in result["items"] if item["id"] == linked["template_id"])
        self.assertEqual(item["stackup_label"], linked["label"])
        self.assertEqual(item["layer_count"], linked["layer_count"])
        self.assertEqual(item["nominal_thickness_mm"], linked["nominal_thickness_mm"])
        unknown = service.get({"entity": "native_templates", "id": unlinked, "raw_limit": 1})
        self.assertIsNone(unknown["item"]["stackup_label"])
        self.assertIsNone(unknown["item"]["layer_count"])
        self.assertIsNone(unknown["item"]["nominal_thickness_mm"])
        self.assertEqual(service.search({"entity": "native_templates", "query": "no such linked label 12345"})["items"], [])
        after = database.stat()
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))


if __name__ == "__main__":
    unittest.main()
