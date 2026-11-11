"""! @brief 카탈로그 선택의 독립 조건, 원문 사본과 제한된 읽기를 검증한다."""

from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.catalog.build import build_catalog
from rfad.catalog.material_selection import build_material
from rfad.catalog.models import CatalogError, canonical_json, stable_id
from rfad.catalog.selection_reader import SelectionReader
from rfad.domain.pcb_selection import state_hash, validate_selection
from rfad.domain.pcb_selection_evidence import validate_evidence
from test_catalog_build import make_package


class CatalogSelectionTests(unittest.TestCase):
    """! @brief 실제 SQLite에서 프로젝트를 수정하지 않는 선택 경계를 확인한다."""

    def setUp(self):
        """! @brief 명시적 Dk/Df 조건과 큰 원시 ID가 있는 시험 자료를 만든다."""
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        records = make_package(self.directory / "source")
        records[0].update(df=0.02, df_frequency_ghz=1, df_method="DF method", axis="Z")
        records[1].update(method="DK method", axis="Z")
        make_package(self.directory / "source", records)
        self.database = self.directory / "catalog.sqlite"
        self.report = build_catalog(self.directory / "source", self.database)
        self.catalog_id = self.report["catalog_id"]
        self.material_id = str(uuid4())
        with closing(sqlite3.connect(self.database)) as connection:
            for table, identity, raw, extras in (
                ("native_templates", "template", {"name": "public template", "id": 4200000000000000001},
                 {"template_id": "template", "template_key": "public", "kind": "fixture"}),
                ("native_components", "component", {"id": 4200000000000000001, "thickness": None, "a/b": {"~x": 1}},
                 {"component_id": "component", "template_id": "template", "component_order": 0, "kind": "Core"}),
            ):
                text = canonical_json(raw)
                fields = {**extras, "publisher": "Example", "source_id": "S1", "source_path": "data/native.json",
                          "source_pointer": "/templates/0" if table == "native_templates" else "/templates/0/rows/0",
                          "source_sha256": "a" * 64, "raw_json": text,
                          "raw_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "flags_json": "[]"}
                connection.execute("INSERT INTO " + table + " (" + ",".join(fields) + ") VALUES ("
                                   + ",".join("?" for _ in fields) + ")", tuple(fields.values()))
            connection.commit()

    def spec(self) -> dict:
        """! @brief 두 물성의 선택과 적용 대역을 각각 명시한다."""
        return {"key": "substrate", "id": self.material_id, "name": "선택한 시험 재료",
                "properties": {
                    "epsilon_r": {"mode": "catalog", "record_id": "PCB000001", "reason": "이 Dk 관측을 선택"},
                    "tan_delta": {"mode": "catalog", "record_id": "PCB000002", "reason": "별도 Df 관측을 선택"},
                    "conductivity": {"mode": "user", "value": 0, "reason": "유전체 전도도 0을 명시적 가정"},
                }, "validity_hz": {"min": 2.4e9, "max": 2.5e9, "reason": "선택값을 이 좁은 대역의 상수 모델로 가정"}}

    def update_record(self, identifier: str, changes: dict) -> None:
        """! @brief 시험 관측의 원문을 수정하고 그 바이트의 유효 해시를 만든다."""
        with closing(sqlite3.connect(self.database)) as connection:
            row = connection.execute("SELECT raw_json FROM observations WHERE record_id=?", (identifier,)).fetchone()
            value = json.loads(row[0])
            value.update(changes)
            raw = canonical_json(value)
            connection.execute("UPDATE observations SET raw_json=?,raw_sha256=? WHERE record_id=?",
                               (raw, hashlib.sha256(raw.encode("utf-8")).hexdigest(), identifier))
            connection.commit()

    def test_independent_choices_preserve_conditions_and_source_snapshots(self):
        """! @brief Dk/Df를 같은 측정 쌍으로 바꾸거나 원문 주파수를 대역으로 확장하지 않는다."""
        with SelectionReader(self.database, self.catalog_id) as reader:
            result = build_material(self.spec(), reader)
            evidence = reader.evidence
            catalog = reader.catalog()
        self.assertEqual(result["material"]["epsilon_r"]["value_si"], 4.0)
        self.assertEqual(result["material"]["tan_delta"]["value_si"], 0.02)
        self.assertEqual(result["material"]["epsilon_r"]["status"], "source_default")
        self.assertEqual(len(evidence), 3)
        self.assertEqual(len(result["decisions"]), 5)
        self.assertIn("W_INDEPENDENT_PROPERTY_CONDITIONS", {item["code"] for item in result["issues"]})
        copies = {item["item_id"]: json.loads(item["raw_json"]) for item in evidence}
        self.assertEqual(copies["PCB000001"]["frequency_ghz"], 10)
        self.assertEqual(copies["PCB000002"]["df_frequency_ghz"], 1)
        self.assertEqual(copies["S1"]["source_id"], "S1")
        for decision in result["decisions"]:
            self.assertIsInstance(json.loads(decision["value_json"]), dict)
        state = {"materials": [result["material"]], "stackup": [], "ports": []}
        validate_selection({"schema": "rfad.pcb-selection/0.1", "id": str(uuid4()), "catalog": catalog,
                            "evidence": evidence, "decisions": result["decisions"],
                            "applied_state_sha256": state_hash(state), "notes": []})

    def test_projection_preserves_large_ids_null_missing_and_native_origin(self):
        """! @brief 큰 정수는 JSON문자열 안에 두고 미제공과 null 및 원문 위치를 보존한다."""
        with SelectionReader(self.database, self.catalog_id) as reader:
            evidence = reader.capture("native_components", "component", ["/id", "/absent", "/thickness", "/a~1b/~0x"])
            duplicate = reader.capture("native_components", "component", ["/thickness", "/a~1b/~0x", "/absent", "/id"])
            self.assertEqual(evidence, duplicate)
            self.assertEqual(len(reader.evidence), 1)
            validate_evidence(reader.evidence, reader.catalog())
        value = json.loads(evidence["raw_json"])
        self.assertEqual(value["values"]["/id"], 4200000000000000001)
        self.assertIsNone(value["values"]["/thickness"])
        self.assertEqual(value["missing"], ["/absent"])
        self.assertEqual(value["values"]["/a~1b/~0x"], 1)
        self.assertEqual(evidence["origin"], {"source_id": "S1", "path": "data/native.json",
                                            "pointer": "/templates/0/rows/0", "sha256": "a" * 64})
        self.assertEqual(evidence["id"], stable_id("evidence", self.catalog_id, "native_components", "component",
                                                  "projection", evidence["pointers"], evidence["snapshot_sha256"], evidence["origin"]))

    def test_cached_snapshots_are_deduplicated_and_cannot_be_mutated_by_callers(self):
        """! @brief 외부 사본 변경이 다음 선택의 권위 원문에 영향을 주지 않는다."""
        with SelectionReader(self.database, self.catalog_id) as reader:
            record, evidence, _ = reader.snapshot_observation("PCB000001")
            record["raw"]["dk"] = 999
            evidence["raw_json"] = "{}"
            second, saved, _ = reader.snapshot_observation("PCB000001")
            self.assertEqual(second["raw"]["dk"], 4)
            self.assertNotEqual(saved["raw_json"], "{}")
            self.assertEqual(len(reader.evidence), 2)
        self.database.unlink()
        self.assertEqual(json.loads(reader.evidence[0]["raw_json"])["record_id"], "PCB000001")

    def test_missing_does_not_become_zero_and_manual_input_needs_no_catalog(self):
        """! @brief 완전 수동 입력과 미정값은 자료 라이브러리 없이도 구성한다."""
        spec = self.spec()
        spec["properties"]["epsilon_r"] = {"mode": "user", "value": 4.1, "reason": "직접 입력"}
        spec["properties"]["tan_delta"] = {"mode": "missing", "reason": "손실 자료 미확정"}
        spec["validity_hz"] = {"min": None, "max": None, "reason": "적용 대역 미확정"}
        result = build_material(spec, None)
        self.assertIsNone(result["material"]["tan_delta"]["value_si"])
        self.assertEqual(result["material"]["tan_delta"]["status"], "missing")
        self.assertEqual(result["material"]["conductivity"]["value_si"], 0)
        self.assertEqual(result["material"]["source_refs"], [])

    def test_unsupported_published_values_require_explicit_user_override(self):
        """! @brief 범위, 한정자와 미지원 물성을 nominal 상수로 조용히 축약하지 않는다."""
        cases = ({"dk_min": 3.8, "dk_max": 4.2}, {"dk_comparison": "<="}, {"data_conflict": True},
                 {"relative_permeability": 6}, {"value_type": "effective_permittivity"},
                 {"anisotropic": True}, {"value_type": "process_and_design"})
        with closing(sqlite3.connect(self.database)) as connection:
            original = connection.execute("SELECT raw_json,raw_sha256 FROM observations WHERE record_id='PCB000001'").fetchone()
        for changes in cases:
            with self.subTest(changes=changes):
                with closing(sqlite3.connect(self.database)) as connection:
                    connection.execute("UPDATE observations SET raw_json=?,raw_sha256=? WHERE record_id='PCB000001'", original)
                    connection.commit()
                self.update_record("PCB000001", changes)
                with SelectionReader(self.database, self.catalog_id) as reader:
                    with self.assertRaises(CatalogError) as caught:
                        build_material(self.spec(), reader)
                self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
                spec = self.spec()
                spec["properties"]["epsilon_r"] = {"mode": "user", "value": 3.9, "record_id": "PCB000001",
                                                     "reason": "한정된 원문을 등방성 상수로 명시적으로 근사"}
                with SelectionReader(self.database, self.catalog_id) as reader:
                    result = build_material(spec, reader)
                self.assertEqual(result["decisions"][0]["basis"], "user_override")
                self.assertEqual(result["material"]["epsilon_r"]["value_si"], 3.9)

    def test_loss_limit_is_not_adopted_as_a_nominal_loss(self):
        """! @brief 명목값처럼 보이는 숫자라도 원문 상한 조건을 무시하지 않는다."""
        self.update_record("PCB000002", {"df_limit_operator": "<=", "value_type": "maximum_loss"})
        with SelectionReader(self.database, self.catalog_id) as reader:
            with self.assertRaises(CatalogError) as caught:
                build_material(self.spec(), reader)
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")

    def test_missing_catalog_scalar_cannot_be_inferred_from_another_field(self):
        """! @brief Dk만 있는 행에서 Df를 얻거나 범위의 중간값을 만들지 않는다."""
        spec = self.spec()
        spec["properties"]["tan_delta"]["record_id"] = "PCB000001"
        with SelectionReader(self.database, self.catalog_id) as reader:
            with self.assertRaises(CatalogError):
                build_material(spec, reader)

    def test_invalid_user_choices_and_frequency_ranges_are_rejected(self):
        """! @brief 명시 이유, 개별 선택 필드와 유한 양수 대역 계약을 확인한다."""
        cases = []
        spec = self.spec()
        spec["properties"]["conductivity"]["reason"] = ""
        cases.append(spec)
        spec = self.spec()
        spec["properties"]["conductivity"]["value"] = True
        cases.append(spec)
        spec = self.spec()
        spec["validity_hz"]["min"] = 3e9
        cases.append(spec)
        spec = self.spec()
        spec["properties"]["epsilon_r"]["value"] = 4.1
        cases.append(spec)
        for spec in cases:
            with self.subTest(spec=spec), SelectionReader(self.database, self.catalog_id) as reader:
                with self.assertRaises(CatalogError):
                    build_material(spec, reader)

    def test_stale_revision_tampered_hash_and_raw_identity_are_rejected(self):
        """! @brief 선택한 개정이나 원문 내용이 바뀌면 사본을 만들지 않는다."""
        with self.assertRaises(CatalogError):
            with SelectionReader(self.database, "catalog:" + "0" * 64):
                pass
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE observations SET raw_sha256=? WHERE record_id='PCB000001'", ("0" * 64,))
            connection.commit()
        with SelectionReader(self.database, self.catalog_id) as reader:
            with self.assertRaises(CatalogError) as caught:
                reader.observation("PCB000001")
        self.assertEqual(caught.exception.code, "E_HASH")
        self.update_record("PCB000001", {"record_id": "different"})
        with SelectionReader(self.database, self.catalog_id) as reader:
            with self.assertRaises(CatalogError) as caught:
                reader.observation("PCB000001")
        self.assertEqual(caught.exception.code, "E_HASH")

    def test_large_raw_or_evidence_is_rejected_without_silent_truncation(self):
        """! @brief 큰 원문은 미리 크기를 검사하고 부분사본도 예산을 넘으면 거부한다."""
        for size in (5000, 300000):
            raw = canonical_json({"payload": "x" * size})
            with closing(sqlite3.connect(self.database)) as connection:
                connection.execute("UPDATE native_templates SET raw_json=?,raw_sha256=? WHERE template_id='template'",
                                   (raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()))
                connection.commit()
            with SelectionReader(self.database, self.catalog_id) as reader:
                with self.assertRaises(CatalogError) as caught:
                    reader.capture("native_templates", "template", ["/payload"])
            self.assertEqual(caught.exception.code, "E_RESOURCE")

    def test_native_rows_are_ordered_and_use_explicit_projection(self):
        """! @brief 원자료 조회가 전체 template를 무조건 프로젝트에 저장하지 않는다."""
        with SelectionReader(self.database, self.catalog_id) as reader:
            rows = reader.native_components("template")
            self.assertEqual([row["component_id"] for row in rows], ["component"])
            with self.assertRaises(CatalogError):
                reader.capture("native_templates", "template")
            with self.assertRaises(CatalogError):
                reader.capture("native_components", "component", ["/bad~2escape"])
            with self.assertRaises(CatalogError):
                reader.capture("native_components", "component", ["/absent/bad~2escape"])

    def test_aggregate_read_and_evidence_budgets_are_enforced(self):
        """! @brief 한 행이 작더라도 전체 선택을 무제한으로 적재하거나 복사하지 않는다."""
        with closing(sqlite3.connect(self.database)) as connection:
            for index in range(7):
                raw = canonical_json({"payload": "x" * 180000, "number": index})
                connection.execute(
                    "INSERT INTO native_components(component_id,template_id,publisher,source_id,source_path,"
                    "source_pointer,source_sha256,component_order,kind,raw_json,raw_sha256,flags_json) "
                    "VALUES (?, 'template', 'Example', 'S1', 'data/native.json', ?, ?, ?, 'Core', ?, ?, '[]')",
                    ("large" + str(index), "/rows/" + str(index), "a" * 64, index + 1, raw,
                     hashlib.sha256(raw.encode("utf-8")).hexdigest()),
                )
            connection.commit()
        with SelectionReader(self.database, self.catalog_id) as reader:
            with self.assertRaises(CatalogError) as caught:
                for index in range(7):
                    reader.native_component("large" + str(index))
        self.assertEqual(caught.exception.code, "E_RESOURCE")
        with closing(sqlite3.connect(self.database)) as connection:
            for index in range(7):
                raw = canonical_json({"payload": "x" * 2800, "number": index})
                connection.execute("UPDATE native_components SET raw_json=?,raw_sha256=? WHERE component_id=?",
                                   (raw, hashlib.sha256(raw.encode("utf-8")).hexdigest(), "large" + str(index)))
            connection.commit()
        with patch("rfad.catalog.selection_reader.MAX_EVIDENCE_BYTES", 12 * 1024), SelectionReader(self.database, self.catalog_id) as reader:
            with self.assertRaises(CatalogError) as caught:
                for index in range(7):
                    reader.capture("native_components", "large" + str(index), ["/payload"])
            self.assertLessEqual(len(canonical_json(reader.evidence).encode("utf-8")), 12 * 1024)
        self.assertEqual(caught.exception.code, "E_RESOURCE")


if __name__ == "__main__":
    unittest.main()
