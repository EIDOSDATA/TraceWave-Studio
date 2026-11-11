"""! @brief 제조업체 적층 제안의 정확한 대응, 미정 보존과 공개 적용 경계를 검증한다."""

from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from rfad.application.catalog_api import query
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.catalog.build import build_catalog
from rfad.catalog.models import canonical_json
from rfad.catalog.service import CatalogService
from rfad.domain.errors import ProjectError
from rfad.domain.material_models import TOTAL_TAN_DELTA_MODEL
from rfad.domain.pcb_selection import EXTENSION_KEY
from test_catalog_build import make_package
import test_pcb_selection_service as service_fixture


NATIVE_PATH = "originals/native_fixture.json"


def observation(identifier="PCB000010", **changes):
    """! @brief 실제 업체 관측과 혼동하지 않는 정확한 시험용 층 대응을 만든다."""
    value = {
        "record_id": identifier, "source_id": "S1", "manufacturer": "JLCPCB",
        "product": "시험 Core-X", "dataset_role": "fabricator_published_parameter",
        "record_kind": "published_stackup_layer", "stackup_id": "JLC-TEST",
        "public_template_id": "T1", "layer_index": 0, "layer": "L1/L2",
        "material_form": "core", "material_name": "Core-X", "thickness_mm": 1.0,
        "copper_layer_count": 2, "nominal_board_thickness_mm": 1.07,
        "dk": 4.2, "df": 0.015, "frequency_ghz": 1.0, "df_frequency_ghz": 2.5,
        "method": "시험 Dk 방법", "df_method": "시험 Df 방법", "axis": "Z",
        "source_file": NATIVE_PATH,
        "source_location": "fixture.json; body.list[0].basicDataList[0]",
        "value_type": "fabricator_calculator",
    }
    value.update(changes)
    return value


def install_catalog(root, *, records=None, component_changes=None, custom=False):
    """! @brief 원본 출처와 행 해시가 있는 작은 SQLite를 공개 생성기와 명시적 native 행으로 만든다."""
    records = [observation()] if records is None else records
    package, database = root / "suggestion-source", root / "suggestion-catalog.sqlite"
    component = {
        "material": "Core", "materialName": "Core-X", "layerName": "L1/L2",
        "dielectricThick": 1.0, "dielectricConstant": 4.2, "plateContainCopper": False,
        "topConductorThick": 0.035, "botConductorThick": 0.035,
    }
    component.update(component_changes or {})
    template = {"impedanceDefaultTemplateAccessId": "T1", "plateThickness": 1.07,
                "plateLayerNumber": 2, "basicDataList": [component]}
    native_path = package / NATIVE_PATH
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(canonical_json({"body": {"list": [template]}}), encoding="utf-8")
    for record in records:
        source_path = package / record["source_file"]
        if not source_path.exists():
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("다른 시험 출처", encoding="utf-8")
    make_package(package, records)
    report = build_catalog(package, database, overwrite=database.exists())
    with closing(sqlite3.connect(database)) as connection:
        stackup = connection.execute("SELECT stackup_id FROM observations WHERE record_id=?", (records[0]["record_id"],)).fetchone()[0]
        common = {"stackup_id": None if custom else stackup, "publisher": "JLCPCB", "source_id": "S1",
                  "source_path": NATIVE_PATH, "source_sha256": hashlib.sha256(native_path.read_bytes()).hexdigest(), "flags_json": "[]"}
        for table, value, fields in (
            ("native_templates", template, {"template_id": "template-jlc", "template_key": "T1",
                                           "kind": "jlc_user_defined_template" if custom else "jlc_named_template",
                                           "source_pointer": "/body/list/0"}),
            ("native_components", component, {"component_id": "component-jlc", "template_id": "template-jlc",
                                             "component_order": 0, "kind": "jlc_api_component",
                                             "source_pointer": "/body/list/0/basicDataList/0"}),
        ):
            raw = canonical_json(value)
            row = {**common, **fields, "raw_json": raw, "raw_sha256": hashlib.sha256(raw.encode()).hexdigest()}
            connection.execute("INSERT INTO " + table + " (" + ",".join(row) + ") VALUES ("
                               + ",".join("?" for _ in row) + ")", tuple(row.values()))
        connection.commit()
    source = {"catalog_id": report["catalog_id"], "entity": "native_templates", "id": "template-jlc"}
    return database, source


def envelope(source, **paging):
    """! @brief 프로젝트 변경 context가 없는 공개 읽기 요청을 만든다."""
    return {"contract_version": "rfad.api/2.0", "context": {}, "input": {"source": source, **paging}}


class StackupSuggestionTests(unittest.TestCase):
    """! @brief 제조업체 이름만 같은 다른 자료를 제안값으로 사용하는 것을 방지한다."""

    def setUp(self):
        """! @brief 시험마다 독립된 원문 및 카탈로그를 준비한다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def suggest(self, **options):
        """! @brief 공개 API를 거쳐 원시 적층과 물성 제안의 결합을 조회한다."""
        self.database, self.source = install_catalog(self.root, **options)
        return query("catalog.stackup_suggestions", envelope(self.source), CatalogService(self.database))

    def dielectric(self, result):
        """! @brief 시험 코어 한 행의 제안만 선택한다."""
        rows = [row for row in result["layers"] if row["role"] == "dielectric"]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_exact_layer_keeps_thickness_and_independent_property_conditions(self):
        """! @brief 같은 물리층의 공개값을 제안하되 주파수/시험법을 서로 복사하지 않는다."""
        result = self.suggest()
        row = self.dielectric(result)
        self.assertEqual(result["schema"], "rfad.pcb-stackup-suggestions/0.1")
        self.assertEqual(result["source"], self.source)
        self.assertEqual(result["readiness"], "not_assessed")
        self.assertEqual(row["thickness_mm"], 1.0)
        self.assertEqual(row["thickness_state"], "source_value")
        dk, df = row["properties"]["epsilon_r"], row["properties"]["tan_delta"]
        self.assertEqual((dk["state"], dk["value"], dk["record_id"]), ("published", 4.2, "PCB000010"))
        self.assertEqual((df["state"], df["value"]), ("published", 0.015))
        self.assertEqual(dk["conditions"]["frequency_ghz"], 1.0)
        self.assertEqual(df["conditions"]["frequency_ghz"], 2.5)
        self.assertNotEqual(dk["conditions"]["method"], df["conditions"]["method"])
        material = row["material_spec"]
        self.assertEqual(material["model"], TOTAL_TAN_DELTA_MODEL)
        self.assertEqual(material["properties"]["conductivity"]["mode"], "missing")
        self.assertIsNone(material["validity_hz"]["min"])
        self.assertIsNone(material["validity_hz"]["max"])
        self.assertTrue(material["model_reason"])

    def test_missing_df_and_copper_thickness_are_not_filled(self):
        """! @brief Dk 관측이나 oz/완성 두께에서 미정 Df와 동박을 추정하지 않는다."""
        result = self.suggest(records=[observation(df=None, df_frequency_ghz=None, df_method=None)])
        row = self.dielectric(result)
        self.assertEqual(row["properties"]["tan_delta"]["state"], "missing")
        self.assertIsNone(row["properties"]["tan_delta"]["value"])
        self.assertEqual(row["material_spec"]["properties"]["tan_delta"]["mode"], "missing")
        for conductor in (item for item in result["layers"] if item["role"] == "conductor"):
            self.assertIsNone(conductor["thickness_mm"])
            self.assertEqual(conductor["thickness_state"], "unresolved")

    def test_copper_including_core_does_not_use_observation_thickness(self):
        """! @brief 관측 수치가 있어도 원문 포함 범위가 불명확한 코어 두께를 복원하지 않는다."""
        result = self.suggest(component_changes={"plateContainCopper": True})
        row = self.dielectric(result)
        self.assertIsNone(row["thickness_mm"])
        self.assertEqual(row["thickness_state"], "unresolved")

    def test_same_publisher_wrong_template_layer_material_and_source_do_not_match(self):
        """! @brief 업체 이름이나 Dk 숫자가 같아도 다른 출처/층/재질은 자동 연결하지 않는다."""
        for changes in ({"public_template_id": "other"}, {"layer_index": 1}, {"material_name": "Other"},
                        {"material_form": "prepreg"}, {"source_file": "other.json"}, {"dk": 4.1},
                        {"source_location": "fixture.json; body.list[1].basicDataList[0]"}):
            with self.subTest(changes=changes):
                row = self.dielectric(self.suggest(records=[observation(**changes)]))
                self.assertNotEqual(row["properties"]["epsilon_r"]["state"], "published")
                self.assertIsNone(row["properties"]["epsilon_r"]["value"])

    def test_duplicate_matching_records_remain_ambiguous(self):
        """! @brief 조건이 다른 복수 후보의 첫 행을 기본값으로 선택하지 않는다."""
        records = [observation(), observation("PCB000011", frequency_ghz=10.0, method="다른 시험법")]
        row = self.dielectric(self.suggest(records=records))
        self.assertEqual(row["properties"]["epsilon_r"]["state"], "ambiguous")
        self.assertIsNone(row["properties"]["epsilon_r"]["value"])

    def test_limits_and_ranges_require_explicit_approximation(self):
        """! @brief 범위 중간값이나 최대 손실값을 자동 상수 모델로 만들지 않는다."""
        row = self.dielectric(self.suggest(records=[observation(dk_min=3.9, dk_max=4.5, df=0.02, df_limit_operator="<=")]))
        for name in ("epsilon_r", "tan_delta"):
            self.assertEqual(row["properties"][name]["state"], "approximation_required")
            self.assertIsNone(row["properties"][name]["value"])
            self.assertEqual(row["material_spec"]["properties"][name]["mode"], "missing")
        df = row["properties"]["tan_delta"]
        self.assertEqual(df["reported_value"], 0.02)
        self.assertEqual(df["reported_limits"]["_limit_operator"], "<=")

    def test_user_defined_template_does_not_borrow_named_stackup_properties(self):
        """! @brief 사용자 정의 template의 같은 이름과 수치를 제조업체 확정 물성으로 올리지 않는다."""
        row = self.dielectric(self.suggest(custom=True))
        self.assertNotEqual(row["properties"]["epsilon_r"]["state"], "published")
        self.assertIsNone(row["properties"]["epsilon_r"]["value"])

    def test_observation_stackup_uses_only_its_own_known_core(self):
        """! @brief 명시적으로 지원하는 OSH 2층 관측은 다른 제품 검색 없이 자체 Dk만 제안한다."""
        record = observation(manufacturer="OSH Park", stackup_id="OSH_2L_1.6", layer="L1-L2",
                             thickness_mm=1.524, dk=4.5, df=None, frequency_ghz=0.01,
                             df_frequency_ghz=None, df_method=None)
        self.database, self.source = install_catalog(self.root, records=[record])
        source = {**self.source, "entity": "observations", "id": record["record_id"]}
        result = query("catalog.stackup_suggestions", envelope(source), CatalogService(self.database))
        row = self.dielectric(result)
        self.assertEqual(row["thickness_mm"], 1.524)
        self.assertEqual(row["properties"]["epsilon_r"]["value"], 4.5)
        self.assertEqual(row["properties"]["tan_delta"]["state"], "missing")

    def test_corrupt_native_hash_is_rejected_before_suggestion(self):
        """! @brief 원문을 바꾼 불일치 native 행을 공식 제안으로 노출하지 않는다."""
        self.database, self.source = install_catalog(self.root)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE native_components SET raw_sha256=?", ("0" * 64,))
            connection.commit()
        with self.assertRaises(ProjectError) as caught:
            query("catalog.stackup_suggestions", envelope(self.source), CatalogService(self.database))
        self.assertEqual(caught.exception.code, "E_HASH")

    def test_paging_preserves_complete_layer_order_and_explicit_unknowns(self):
        """! @brief 작은 페이지를 끝까지 이어도 층 누락/중복 없이 같은 미정 상태를 유지한다."""
        self.database, self.source = install_catalog(self.root)
        catalog = CatalogService(self.database)
        whole = query("catalog.stackup_suggestions", envelope(self.source), catalog)
        collected, offsets = [], []
        offset = 0
        while offset is not None:
            self.assertNotIn(offset, offsets)
            offsets.append(offset)
            result = query("catalog.stackup_suggestions", envelope(self.source, offset=offset, limit=1), catalog)
            self.assertEqual(result["offset"], offset)
            self.assertEqual(result["total_count"], len(whole["draft"]["layers"]))
            self.assertEqual(result["returned_count"], len(result["layers"]))
            self.assertEqual(result["draft"], whole["draft"])
            self.assertLessEqual(len(result["layers"]), 1)
            collected.extend(result["layers"])
            offset = result["next_offset"]
        self.assertEqual(collected, whole["layers"])
        self.assertEqual(offsets, [0, 1, 2])

    def test_invalid_paging_does_not_coerce_boolean_strings_or_unbounded_limits(self):
        """! @brief 페이지 범위가 잘못된 요청을 작게 실패시키며 수치로 강제 변환하지 않는다."""
        self.database, self.source = install_catalog(self.root)
        catalog = CatalogService(self.database)
        for paging in ({"offset": -1}, {"offset": True}, {"offset": "0"},
                       {"limit": 0}, {"limit": 9}, {"limit": True}, {"limit": "1"}):
            with self.subTest(paging=paging):
                with self.assertRaises(ProjectError):
                    query("catalog.stackup_suggestions", envelope(self.source, **paging), catalog)

    def test_public_rpc_is_read_only_and_rejects_stale_catalog_or_extra_input(self):
        """! @brief 조회가 DB 바이트를 바꾸지 않고 잘못된 출처 개정과 임의값 주입을 차단한다."""
        self.database, self.source = install_catalog(self.root)
        before = self.database.read_bytes()
        catalog = CatalogService(self.database)
        request = {"jsonrpc": "2.0", "id": "suggest", "method": "catalog.stackup_suggestions", "params": envelope(deepcopy(self.source))}
        response = handle_frame(json.dumps(request).encode(), catalog=catalog)
        self.assertNotIn("error", response)
        self.assertEqual(self.database.read_bytes(), before)
        request["params"]["input"]["source"]["catalog_id"] = "catalog:" + "0" * 64
        self.assertIn("error", handle_frame(json.dumps(request).encode(), catalog=catalog))
        invalid = envelope(self.source)
        invalid["input"]["epsilon_r"] = 4.4
        with self.assertRaises(ProjectError):
            query("catalog.stackup_suggestions", invalid, catalog)


class StackupSuggestionPersistenceTests(unittest.TestCase):
    """! @brief 제안 수용도 기존 원자 적용/직접 입력/재열기 계약을 사용함을 확인한다."""

    def setUp(self):
        """! @brief 기존 서비스 fixture의 공개 프로젝트 생성 경로를 재사용한다."""
        self.fixture = service_fixture.PcbSelectionServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.database, self.source = install_catalog(self.fixture.root)
        self.fixture.service.close()
        self.fixture.database = self.database
        self.fixture.service = ProjectService(self.fixture.workspace, auto_run=False, catalog_database=self.database)

    def test_suggested_material_apply_undo_redo_snapshot_and_catalog_free_reopen(self):
        """! @brief 명시적으로 수용한 제안의 실제 출처와 미정 대역을 이력/저장에 보존한다."""
        f = self.fixture
        before = f.document()
        journal = f.service.journal.read()
        result = query("catalog.stackup_suggestions", envelope(self.source), CatalogService(self.database))
        self.assertEqual(f.document(), before)
        self.assertEqual(f.service.journal.read(), journal)
        row = next(item for item in result["layers"] if item["role"] == "dielectric")
        material = row["material_spec"]
        specification = {"source": self.source, "materials": [material],
                         "material_assignments": {row["layer_key"]: material["key"]}}
        changed, _ = f.apply(f.selection(specification))
        applied = f.document()
        core = next(item for item in applied["materials"] if item["name"] == material["name"])
        self.assertEqual(core["model"], TOTAL_TAN_DELTA_MODEL)
        self.assertEqual(core["epsilon_r"]["value_si"], 4.2)
        self.assertEqual(core["epsilon_r"]["status"], "source_default")
        self.assertIsNone(core["conductivity"]["value_si"])
        self.assertIsNone(core["validity_hz"]["min"]["value_si"])
        self.assertTrue(core["source_refs"])
        undone = f.service.mutate("project.undo", f.request({"expected_revision": changed["new_revision"], "command_id": str(uuid4())}))
        self.assertEqual(f.document()["materials"], before["materials"])
        redone = f.service.mutate("project.redo", f.request({"expected_revision": undone["new_revision"], "command_id": str(uuid4())}))
        self.assertEqual(f.document()["extensions"], applied["extensions"])
        f.complete("project.save", f.request({"expected_revision": redone["new_revision"]}))
        snapshot = f.complete("snapshot.create", f.request({"expected_revision": redone["new_revision"]}))
        saved = json.loads(f.service.journal.read_artifact(snapshot["artifact"]))
        self.assertEqual(saved["extensions"], applied["extensions"])
        f.service.close()
        f.service = ProjectService(f.workspace, auto_run=False, catalog_database=f.root / "absent.sqlite")
        selected = f.service.pcb_selection.get(f.request({}, read=True))
        self.assertEqual(selected["selection"], applied["extensions"][EXTENSION_KEY])
        core = deepcopy(core)
        core["epsilon_r"] = service_fixture.quantity(4.4, "1")
        f.command("material.set", {"material": core})
        self.assertTrue(f.service.pcb_selection.get(f.request({}, read=True))["modified_since_selection"])


if __name__ == "__main__":
    unittest.main()
