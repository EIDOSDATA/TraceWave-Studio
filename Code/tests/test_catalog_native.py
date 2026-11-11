"""! @brief 원시 적층의 타입, 출처, 위험 표시와 원자적 가져오기를 검증한다."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rfad.catalog.models import CatalogError, canonical_json, stable_id
from rfad.catalog.native import import_native
from rfad.catalog.schema import create_schema
from rfad.catalog.source import PackageSource


class CatalogNativeTests(unittest.TestCase):
    """! @brief 복합 코어, 압착 합계와 접두어 중첩을 작고 독립적인 자료로 검사한다."""

    def setUp(self):
        """! @brief 원래 값과 형식을 직접 판별할 수 있는 세 업체 자료를 만든다."""
        self.temporary = TemporaryDirectory(prefix="rfad native catalog ")
        self.root = Path(self.temporary.name)
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        create_schema(self.connection)
        for source_id in ("FB240", "FB198", "FB020", "FB021"):
            self.connection.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
                                    (source_id, "test", "", "", None, 0, "{}", "0" * 64))
        for publisher, label in (("JLCPCB", "named__id1"), ("PCBWay", "published"),
                                 ("Wurth Elektronik", "same")):
            self.connection.execute("INSERT INTO stackups VALUES (?,?,?,?,?,?,?,?,?)",
                                    (stable_id("stackup", publisher, label), publisher, label,
                                     label, None, None, 0, "{}", "0" * 64))
        core = {"material": "Core", "dielectricConstant": 3.99, "dielectricThick": 0.075,
                "topConductorThick": 0.03, "botConductorThick": 0.03,
                "plateContainCopper": False, "sortId": None,
                "impedanceDefaultTemplateBasicDataBizKey": 603088778047963138}
        self.documents = {
            "fab_jlc_stackup_audit.json": [
                {"source_id": "FB240", "stackup_id": "named__id1", "public_template_id": "id1",
                 "public_ui_named_template": True, "template_json_index": 0,
                 "response_path": "raw/FAB/JLC_public_API/board_type_1_page_001.json"},
                {"source_id": "FB240", "stackup_id": "custom__id2", "public_template_id": "id2",
                 "public_ui_named_template": False, "template_json_index": 1,
                 "response_path": "raw/FAB/JLC_public_API/board_type_1_page_001.json"},
            ],
            "board_type_1_page_001.json": {
                "success": True, "message": None,
                "body": {"pageNum": 1, "list": [
                    {"impedanceDefaultTemplateAccessId": "id1", "basicDataList": [core]},
                    {"impedanceDefaultTemplateAccessId": "id2", "basicDataList": [
                        {"material": "Prepreg", "dielectricThick": 0, "dielectricConstant": 0},
                    ]},
                ]},
            },
            "fab_jlc_material_definitions.json": {"materialKey": 603088778047963138, "optional": None},
            "fab_nonpositive_thickness_audit.json": [{"original": -0.01, "confirmed": False}],
            "fab_pcbway_stackups.json": [{
                "stackup_id": "published", "source_id": "FB198", "published_index": "1",
                "rows": [["L2-CU", "Inner Copper", "0.035", "1.1 (Core with Cu)"],
                         ["CORE", "Core DK:4.6", "1.030"], ["L3-CU", "Inner Copper", "0.035"]],
                "post_lamination_groups": {
                    str(index): {"value": 1.1, "rows": 3, "start": 0, "label": "1.1 (Core with Cu)"}
                    for index in range(3)
                },
            }],
            "fab_we_audit.json": [
                {"source_id": "FB020", "file": "same.stackup", "native_file_sha256": "a" * 64},
                {"source_id": "FB021", "file": "same.stackup", "native_file_sha256": "b" * 64},
            ],
            "fab_we_raw_fields.json": [
                {"source_id": "FB020", "stackup_id": "same.stackup", "layer_index": 1,
                 "raw_fields": {"NAME": "Top Solder", "DIELCONST": "3.5", "0NAME": "Other layer",
                                "0DIELCONST": "4.3", "COPTHICK": "0.6693mil"}},
                {"source_id": "FB021", "stackup_id": "same.stackup", "layer_index": 1,
                 "raw_fields": {"NAME": "Core", "DIELCONST": "-4.2"}},
            ],
        }

    def tearDown(self):
        """! @brief 임시 DB와 출처 파일을 닫는다."""
        self.connection.close()
        self.temporary.cleanup()

    def package(self):
        """! @brief 파일별 해시 명세를 포함한 실제 읽기 전용 패키지를 준비한다."""
        files = []
        for filename, value in self.documents.items():
            relative = "data/fabricator_native_metadata/" + filename
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
            path.write_bytes(raw)
            files.append({"path": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        manifest = self.root / "catalog/file_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"schema": "rfad.reference.file-manifest/1", "files": files}), encoding="utf-8")
        return PackageSource(self.root)

    def assert_original_objects(self, table):
        """! @brief 저장된 객체가 JSON Pointer의 원본 값 및 두 해시와 일치하는지 확인한다."""
        for row in self.connection.execute("SELECT * FROM " + table):
            path = self.root / row["source_path"]
            raw_bytes = path.read_bytes()
            original = json.loads(raw_bytes)
            for token in row["source_pointer"].split("/")[1:]:
                original = original[int(token)] if isinstance(original, list) else original[token]
            self.assertEqual(row["raw_json"], canonical_json(original))
            self.assertEqual(row["raw_sha256"], hashlib.sha256(row["raw_json"].encode("utf-8")).hexdigest())
            self.assertEqual(row["source_sha256"], hashlib.sha256(raw_bytes).hexdigest())

    def test_preserves_types_locations_and_source_scoped_identity(self):
        """! @brief 큰 정수, 빈값, 부호, 타입과 같은 이름의 다른 출처를 유지한다."""
        package = self.package()
        result = import_native(self.connection, self.root, package)
        self.assertEqual((result["templates"], result["components"], result["evidence"]), (5, 7, 4))
        self.assertEqual(result["links"], 4)
        self.assertEqual(result["physical_layers_created"], 0)
        self.assertEqual(result["publishers"]["JLCPCB"]["user_defined_templates"], 1)
        self.assertEqual(result["publishers"]["Wurth Elektronik"]["prefix_cross_layer_rows"], 1)
        for table in ("native_templates", "native_components"):
            self.assert_original_objects(table)
        core = json.loads(self.connection.execute(
            "SELECT c.raw_json FROM native_components c JOIN native_templates t USING(template_id) "
            "WHERE t.kind='jlc_named_template' ORDER BY c.component_order LIMIT 1"
        ).fetchone()[0])
        self.assertEqual(core["impedanceDefaultTemplateBasicDataBizKey"], 603088778047963138)
        self.assertIs(type(core["impedanceDefaultTemplateBasicDataBizKey"]), int)
        self.assertIs(core["plateContainCopper"], False)
        self.assertIsNone(core["sortId"])
        self.assertNotIn("materialName", core)
        custom = self.connection.execute("SELECT stackup_id FROM native_templates WHERE kind='jlc_user_defined_template'").fetchone()
        self.assertIsNone(custom[0])
        self.assertEqual(self.connection.execute("SELECT COUNT(DISTINCT template_id) FROM native_templates WHERE publisher='Wurth Elektronik'").fetchone()[0], 2)
        self.assertEqual(self.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_group_totals_and_cross_layer_fields_stay_uninterpreted(self):
        """! @brief 합계와 다른 층 필드를 유전체 단일값으로 조용히 바꾸지 않는다."""
        result = import_native(self.connection, self.root, self.package())
        self.assertEqual(result["publishers"]["PCBWay"]["shared_post_lamination_group_rows"], 3)
        for row in self.connection.execute("SELECT flags_json FROM native_components WHERE publisher='PCBWay'"):
            self.assertIn("shared_post_lamination_group_total_not_layer_thickness", json.loads(row[0]))
        row = self.connection.execute("SELECT raw_json,flags_json FROM native_components WHERE source_id='FB020'").fetchone()
        self.assertEqual(json.loads(row[0])["raw_fields"]["0DIELCONST"], "4.3")
        self.assertIn("prefix_cross_layer_fields_present", json.loads(row[1]))
        self.assertIn("native_component_not_physical_layer", json.loads(row[1]))
        evidence = self.connection.execute("SELECT raw_json FROM native_evidence WHERE kind='jlc_page_envelope_without_templates'").fetchone()
        self.assertEqual(json.loads(evidence[0]), {"success": True, "message": None, "body": {"pageNum": 1}})

    def test_invalid_late_group_rolls_back_prior_templates_and_links(self):
        """! @brief 후속 업체의 실패가 앞 업체의 일부 저장을 남기지 않는다."""
        self.documents["fab_pcbway_stackups.json"][0]["post_lamination_groups"]["0"]["rows"] = 99
        with self.assertRaises(CatalogError):
            import_native(self.connection, self.root, self.package())
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM native_templates").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT SUM(native_available) FROM stackups").fetchone()[0], 0)

    def test_rejects_missing_source(self):
        """! @brief 출처 FK가 없는 원시 자료를 저장하지 않는다."""
        self.connection.execute("DELETE FROM sources WHERE source_id='FB240'")
        with self.assertRaises(sqlite3.IntegrityError):
            import_native(self.connection, self.root, self.package())
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM native_evidence").fetchone()[0], 0)

    def test_rejects_duplicate_native_order(self):
        """! @brief 같은 출처 파일의 원시 순번 충돌을 덮어쓰기하지 않는다."""
        self.documents["fab_we_raw_fields.json"].append(deepcopy(self.documents["fab_we_raw_fields.json"][0]))
        with self.assertRaises(CatalogError):
            import_native(self.connection, self.root, self.package())
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM native_templates").fetchone()[0], 0)

    def test_jlc_page_envelope_and_templates_reconstruct_original(self):
        """! @brief 분리된 페이지 메타데이터와 배열을 합치면 원래 모든 필드가 복원된다."""
        import_native(self.connection, self.root, self.package())
        restored = json.loads(self.connection.execute(
            "SELECT raw_json FROM native_evidence WHERE kind='jlc_page_envelope_without_templates'"
        ).fetchone()[0])
        restored["body"]["list"] = [json.loads(row[0]) for row in self.connection.execute(
            "SELECT raw_json FROM native_templates WHERE publisher='JLCPCB' ORDER BY source_pointer"
        )]
        self.assertEqual(canonical_json(restored), canonical_json(self.documents["board_type_1_page_001.json"]))

    def test_unknown_metadata_file_fails_coverage(self):
        """! @brief 새 원문 파일을 가져오지 않은 상태를 성공으로 보고하지 않는다."""
        self.documents["new_unknown_metadata.json"] = {"unhandled": True}
        with self.assertRaises(CatalogError) as raised:
            import_native(self.connection, self.root, self.package())
        self.assertEqual(raised.exception.code, "catalog_native_coverage")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM native_components").fetchone()[0], 0)

    def test_audit_identity_and_paths_are_checked(self):
        """! @brief 감사 순번과 API 템플릿 ID가 다르거나 경로가 이탈하면 거부한다."""
        self.documents["fab_jlc_stackup_audit.json"][0]["public_template_id"] = "wrong"
        with self.assertRaises(CatalogError):
            import_native(self.connection, self.root, self.package())
        self.documents["fab_jlc_stackup_audit.json"][0]["response_path"] = "../../outside.json"
        with self.assertRaises(CatalogError) as raised:
            import_native(self.connection, self.root, self.package())
        self.assertEqual(raised.exception.code, "catalog_native_path")

    def test_file_budget_and_absent_native_package(self):
        """! @brief 원문 파일별 메모리 상한을 지키며 native 없는 패키지도 지원한다."""
        result = import_native(self.connection, self.root, SimpleNamespace(files={}))
        self.assertEqual(result["templates"], 0)
        with patch("rfad.catalog.native_common.MAX_NATIVE_FILE_BYTES", 1):
            with self.assertRaises(CatalogError) as raised:
                import_native(self.connection, self.root, self.package())
        self.assertEqual(raised.exception.code, "E_RESOURCE")

    def test_existing_native_directory_cannot_be_omitted_from_manifest(self):
        """! @brief 자료 폴더가 있는데 명세에서 빠진 경우 빈 카탈로그로 숨기지 않는다."""
        self.package()
        with self.assertRaises(CatalogError) as raised:
            import_native(self.connection, self.root, SimpleNamespace(files={}))
        self.assertEqual(raised.exception.code, "catalog_native_coverage")

    def verifier(self):
        """! @brief 독립 표준 라이브러리 검증 도구를 부작용 없이 불러온다."""
        tool = Path(__file__).resolve().parents[1] / "tools" / "verify_pcb_catalog_native.py"
        return runpy.run_path(str(tool))["verify_native_catalog"]

    def save_database(self):
        """! @brief 읽기 전용 검증에 사용할 임시 DB 복사본을 만든다."""
        self.connection.commit()
        target = self.root / "catalog.sqlite"
        destination = sqlite3.connect(target)
        try:
            self.connection.backup(destination)
        finally:
            destination.close()
        return target

    def test_independent_verifier_reconstructs_all_source_documents(self):
        """! @brief 별도 검증 도구가 모든 파일과 구성행을 확인하고 DB를 수정하지 않는다."""
        import_native(self.connection, self.root, self.package())
        database = self.save_database()
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        result = self.verifier()(self.root, database)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["source_files_checked"], len(self.documents))
        self.assertEqual(result["records_checked"]["native_components"], 7)
        self.assertEqual(result["component_parent_links_checked"], 7)
        self.assertEqual(result["database_sha256"], before)
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)

    def test_independent_verifier_detects_type_change_and_missing_component(self):
        """! @brief 자체 해시가 일치하더라도 bool 타입 변경이나 구성행 누락을 발견한다."""
        import_native(self.connection, self.root, self.package())
        row = self.connection.execute(
            "SELECT c.component_id,c.raw_json FROM native_components c JOIN native_templates t USING(template_id) "
            "WHERE t.kind='jlc_named_template'"
        ).fetchone()
        changed = json.loads(row[1])
        changed["plateContainCopper"] = 0
        raw = canonical_json(changed)
        self.connection.execute("UPDATE native_components SET raw_json=?,raw_sha256=? WHERE component_id=?",
                                (raw, hashlib.sha256(raw.encode("utf-8")).hexdigest(), row[0]))
        self.connection.execute("DELETE FROM native_components WHERE template_id IN "
                                "(SELECT template_id FROM native_templates WHERE kind='jlc_user_defined_template')")
        result = self.verifier()(self.root, self.save_database())
        self.assertFalse(result["ok"])
        codes = {error["code"] for error in result["errors"]}
        self.assertIn("value_or_type", codes)
        self.assertIn("missing_or_extra_records", codes)


if __name__ == "__main__":
    unittest.main()
