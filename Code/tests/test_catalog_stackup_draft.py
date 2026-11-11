"""! @brief 원문 구조 변환에서 추정 두께, 재료 물성과 잘못된 합계가 섞이지 않는지 검증한다."""

from copy import deepcopy
import hashlib
import unittest

from rfad.catalog.models import CatalogError, canonical_json, stable_id
from rfad.catalog.stackup_draft import build_observation_draft, build_stackup_draft


class FixtureReader:
    """! @brief 실제 reader와 같은 원문 및 근거 인터페이스로 변환 규칙을 분리 검사한다."""

    def __init__(self, publisher, kind, raw, components):
        """! @brief 작은 원문 object와 원문 순서가 명확한 구성 행을 준비한다."""
        if publisher == "JLCPCB":
            raw["basicDataList"] = components
        self.row = {"template_id": "template", "publisher": publisher, "kind": kind,
                    "source_id": "source", "source_path": "metadata/page.json", "source_pointer": "/body/list/0",
                    "source_sha256": "a" * 64, "raw": raw, "raw_sha256": self.digest(raw)}
        self.components = [{"component_id": "component-" + str(index), "component_order": index,
                            "template_id": "template", "source_id": "source", "source_path": "metadata/page.json",
                            "source_pointer": "/body/list/0/basicDataList/" + str(index), "source_sha256": "a" * 64,
                            "raw": value, "flags_json": "[]"} for index, value in enumerate(components)]
        self.captures = []
        self.record = None

    @staticmethod
    def digest(value):
        """! @brief 관측 fixture의 원문 변경을 초안 ID에 반영한다."""
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

    def catalog(self):
        """! @brief 테스트 개정을 제공한다."""
        return {"catalog_id": "catalog:test"}

    def native_template(self, item_id):
        """! @brief 템플릿 원문을 반환한다."""
        return self.row

    def native_components(self, item_id):
        """! @brief 위에서 아래 원문 행 순서를 반환한다."""
        return self.components

    def observation(self, item_id):
        """! @brief 정규화 관측 원문을 반환한다."""
        return self.record

    def source_evidence(self, item_id):
        """! @brief 출처 사본 식별자를 반환한다."""
        return {"id": "evidence:source"}

    def capture(self, entity, item_id, pointers=None):
        """! @brief 변환기가 요청한 정확한 원문 경로를 기록한다."""
        result = {"id": stable_id("evidence", entity, item_id, pointers)}
        self.captures.append((entity, item_id, deepcopy(pointers), result["id"]))
        return result


class CatalogStackupDraftTests(unittest.TestCase):
    """! @brief 제조업체별 확실한 구조와 미정 조건의 경계를 확인한다."""

    def jlc(self, *, included=False, thickness=1.36, name="1.36mm without copper"):
        """! @brief 코어 한 행에 양면 구리가 포함된 2층 fixture를 만든다."""
        return FixtureReader("JLCPCB", "jlc_named_template", {"plateLayerNumber": 2, "plateThickness": 1.6},
                             [{"material": "Core", "layerName": "L1/L2", "materialName": name,
                               "plateContainCopper": included, "dielectricThick": thickness,
                               "topConductorThick": 0.061, "botConductorThick": 0.061,
                               "dielectricConstant": 4.42,
                               "impedanceDefaultTemplateBasicDataBizKey": 613675914401259521}])

    def pcbway(self):
        """! @brief 실제 공개 4층 표의 압착 전후와 코어 3행 합계를 재현한다."""
        rows = [["L1-CU", "Outer Base Copper 0.5OZ", "0.0175", "0.0175 (Plating to 1OZ)"],
                ["PP", "7628 RC46% DK:4.74", "0.1960", "0.1855"],
                ["L2-CU", "Inner Copper 1OZ", "0.0350", "1.1 (Core with Cu)"],
                ["CORE", "Core DK:4.6", "1.0300"], ["L3-CU", "Inner Copper 1OZ", "0.0350"],
                ["PP", "7628 RC46% DK:4.74", "0.1960", "0.1855"],
                ["L4-CU", "Outer Base Copper 0.5OZ", "0.0175", "0.0175 (Plating to 1OZ)"]]
        groups = {str(index): {"value": 1.1, "rows": 3, "start": 2, "label": "1.1 (Core with Cu)"}
                  for index in (2, 3, 4)}
        for index in (1, 5):
            groups[str(index)] = {"value": 0.1855, "rows": 1, "start": index, "label": "0.1855"}
        return FixtureReader("PCBWay", "pcbway_published_template",
                             {"attributes": {"layers": "4", "boardthickness": "1.6"},
                              "column_headers": ["Layer", "Material", "Thickness (mm)", "Thickness after lamination(mm)"],
                              "post_lamination_groups": groups}, rows)

    def test_jlc_unambiguous_core_splits_and_reverses_source_order(self):
        """! @brief 원문 L1/L2 코어를 도체 2개와 유전체로 분리하고 아래부터 반환한다."""
        reader = self.jlc()
        original = deepcopy(reader.components)
        draft = build_stackup_draft(reader, "template")
        self.assertEqual([item["name"] for item in draft["layers"]], ["L2", "Core 1", "L1"])
        self.assertEqual([item["thickness_mm"] for item in draft["layers"]], [None, 1.36, None])
        core = draft["layers"][1]
        self.assertEqual(core["thickness_source_pointer"], "/basicDataList/0/dielectricThick")
        self.assertIn(core["thickness_evidence_id"], core["evidence_ids"])
        self.assertEqual(draft["layer_order"], "bottom_to_top")
        self.assertEqual(draft["source_order"], "top_to_bottom")
        self.assertFalse(any(item["severity"] == "blocker" for item in draft["issues"]))
        self.assertEqual(reader.components, original)
        self.assertNotIn("epsilon_r", canonical_json(draft))
        self.assertNotIn("dielectricConstant", canonical_json(draft))
        self.assertEqual(len(reader.captures), 1)
        self.assertEqual(reader.captures[0][0], "native_templates")
        self.assertIn("/basicDataList/0/topConductorThick", reader.captures[0][2])
        self.assertNotIn("/basicDataList/0/impedanceDefaultTemplateBasicDataBizKey", reader.captures[0][2])

    def test_copper_including_core_is_not_subtracted_or_oz_converted(self):
        """! @brief 공칭 두께와 동박 수치를 빼거나 oz로 완성 동박 두께를 만들지 않는다."""
        draft = build_stackup_draft(self.jlc(included=True, name="1.5mm 2/2OZ with copper"), "template")
        self.assertEqual(draft["nominal_thickness_mm"], 1.6)
        self.assertTrue(all(item["thickness_mm"] is None for item in draft["layers"]))
        self.assertIn("copper_inclusion_unresolved", [item["code"] for item in draft["issues"]])
        self.assertTrue(all(item["thickness_source_pointer"] is None for item in draft["layers"]))

    def test_conflicting_text_and_flag_does_not_adopt_core_thickness(self):
        """! @brief 동박 제외 플래그와 포함 문구가 충돌하면 수치를 미정으로 남긴다."""
        draft = build_stackup_draft(self.jlc(name="1.5mm with copper"), "template")
        self.assertIsNone(draft["layers"][1]["thickness_mm"])

    def test_nonpositive_bool_and_string_thickness_remain_unknown(self):
        """! @brief 불리언과 단위 없는 문자열은 수치로 강제 변환하지 않는다."""
        for value in (0, -1, True, "1.36", None):
            with self.subTest(value=value):
                reader = self.jlc()
                reader.components[0]["raw"]["dielectricThick"] = value
                draft = build_stackup_draft(reader, "template")
                self.assertIsNone(draft["layers"][1]["thickness_mm"])
        reader.components[0]["raw"]["dielectricThick"] = float("inf")
        with self.assertRaises(CatalogError):
            build_stackup_draft(reader, "template")

    def test_missing_faces_and_mismatched_copper_count_block_topology(self):
        """! @brief 코어 양면 식별과 전체 도체 층수가 불명확하면 수동 정의를 요구한다."""
        reader = self.jlc()
        reader.components[0]["raw"]["layerName"] = None
        draft = build_stackup_draft(reader, "template")
        self.assertFalse(draft["layers"])
        self.assertIn("core_faces_unidentified", [item["code"] for item in draft["issues"]])
        self.assertIn("copper_layer_count_mismatch", [item["code"] for item in draft["issues"]])

    def test_reversed_or_duplicate_source_faces_do_not_pass(self):
        """! @brief 층수만 같고 도체 이름이 뒤집히거나 중복된 구조를 승인하지 않는다."""
        for name in ("L2/L1", "L1/L1"):
            reader = self.jlc()
            reader.components[0]["raw"]["layerName"] = name
            draft = build_stackup_draft(reader, "template")
            self.assertIn("conductor_order_unverified", [item["code"] for item in draft["issues"]])

    def test_pcbway_uses_individual_post_lamination_only(self):
        """! @brief 압착 전 PP와 코어 합계를 대신 쓰지 않고 명시된 개별 압착값만 채택한다."""
        draft = build_stackup_draft(self.pcbway(), "template")
        self.assertEqual([item["thickness_mm"] for item in draft["layers"]], [None, 0.1855, None, None, None, 0.1855, None])
        self.assertEqual(draft["layers"][1]["thickness_source_pointer"], "/post_lamination_groups/5/value")
        self.assertIn(draft["layers"][1]["thickness_evidence_id"], draft["layers"][1]["evidence_ids"])
        self.assertIn("shared_lamination_total_unallocated", [item["code"] for item in draft["issues"]])
        self.assertFalse(any(item["severity"] == "blocker" for item in draft["issues"]))

    def test_pcbway_units_and_disagreeing_group_prevent_thickness(self):
        """! @brief 원문 열 단위가 다르거나 문자열과 수치가 다르면 자동 채택하지 않는다."""
        reader = self.pcbway()
        reader.row["raw"]["post_lamination_groups"]["1"]["value"] = 0.9
        draft = build_stackup_draft(reader, "template")
        self.assertIsNone(next(item for item in draft["layers"] if item["key"] == "component:1")["thickness_mm"])
        self.assertIn("lamination_value_conflict", [item["code"] for item in draft["issues"]])
        reader.row["raw"]["column_headers"][3] = "Thickness (mil)"
        draft = build_stackup_draft(reader, "template")
        self.assertTrue(all(item["thickness_mm"] is None for item in draft["layers"]))

    def test_we_partial_and_contaminated_fields_are_evidence_only(self):
        """! @brief 누락된 WE 도체를 복원하거나 다른 층 접두 필드를 재사용하지 않는다."""
        reader = FixtureReader("Wurth Elektronik", "we_altium_native_file", {"file": "example.stackup"},
                               [{"layer_index": 1, "raw_fields": {"NAME": "Top Solder", "0NAME": "Core", "0DIELHEIGHT": "5mil"}}])
        reader.components[0]["flags_json"] = '["prefix_cross_layer_fields_present"]'
        draft = build_stackup_draft(reader, "template")
        self.assertFalse(draft["layers"])
        self.assertIn("incomplete_native_layer_set", [item["code"] for item in draft["issues"]])
        self.assertIn("prefix_cross_layer_fields_present", [item["code"] for item in draft["issues"]])
        self.assertTrue(any("/raw_fields/0NAME" in pointers for _, _, pointers, _ in reader.captures))

    def test_osh_known_two_layer_observation_preserves_source_core(self):
        """! @brief 2층 관측의 유전체 값만 사용하고 GHz 물성이나 동박을 만들지 않는다."""
        reader = self.jlc()
        value = {"stackup_id": "OSH_2L_1.6", "record_kind": "published_stackup_layer", "material_form": "core",
                 "layer": "L1-L2", "dataset_role": "fabricator_published_parameter", "thickness_mm": 1.524, "dk": 4.5,
                 "frequency_ghz": 0.01}
        reader.record = {"publisher": "OSH Park", "record_id": "record", "source_id": "source", "raw": value,
                         "raw_sha256": reader.digest(value)}
        draft = build_observation_draft(reader, "record")
        self.assertEqual([item["thickness_mm"] for item in draft["layers"]], [None, 1.524, None])
        self.assertIsNone(draft["nominal_thickness_mm"])
        self.assertEqual(draft["layers"][1]["thickness_source_pointer"], "/thickness_mm")
        reader.record["raw"]["stackup_id"] = "OSH_4L_1.6"
        unsupported = build_observation_draft(reader, "record")
        self.assertFalse(unsupported["layers"])

    def test_unsupported_native_and_wrong_json_type_fail_safely(self):
        """! @brief 알 수 없는 템플릿은 수동 정의로 보내고 잘못된 JSON object는 거부한다."""
        reader = FixtureReader("Other", "unrecognized", {}, [])
        draft = build_stackup_draft(reader, "template")
        self.assertIn("unsupported_native_template", [item["code"] for item in draft["issues"]])
        reader = self.jlc()
        reader.components[0]["raw"] = []
        with self.assertRaises(CatalogError):
            build_stackup_draft(reader, "template")

    def test_draft_identifier_is_deterministic_and_source_revision_bound(self):
        """! @brief 동일 원문 재선택은 같은 초안 ID이고 원문 변경은 다른 ID이다."""
        reader = self.jlc()
        first = build_stackup_draft(reader, "template")
        self.assertEqual(first, build_stackup_draft(reader, "template"))
        reader.row["raw_sha256"] = "f" * 64
        self.assertNotEqual(first["id"], build_stackup_draft(reader, "template")["id"])

    def test_component_and_template_value_types_must_match_exactly(self):
        """! @brief Python에서 같은 값으로 비교되는 불리언/정수도 원문 타입이 다르면 거부한다."""
        reader = self.jlc()
        reader.components[0]["raw"] = deepcopy(reader.components[0]["raw"])
        reader.components[0]["raw"]["plateContainCopper"] = 0
        with self.assertRaises(CatalogError) as error:
            build_stackup_draft(reader, "template")
        self.assertEqual(error.exception.code, "E_HASH")
        self.assertFalse(reader.captures)

    def test_component_source_location_and_count_must_match_template(self):
        """! @brief 구성 행의 출처 또는 개수가 달라지면 템플릿 근거로 대체하지 않는다."""
        for field, value in (("source_path", "other.json"), ("source_pointer", "/body/list/1/basicDataList/0"),
                             ("source_sha256", "b" * 64), ("template_id", "different"), ("component_order", 1)):
            with self.subTest(field=field):
                reader = self.jlc()
                reader.components[0][field] = value
                with self.assertRaises(CatalogError):
                    build_stackup_draft(reader, "template")
        reader = self.jlc()
        reader.components.clear()
        with self.assertRaises(CatalogError):
            build_stackup_draft(reader, "template")

    def test_projection_batches_keep_each_component_together(self):
        """! @brief 큰 템플릿의 필드 묶음을 분할하되 한 층의 판단 근거는 함께 둔다."""
        components = [{"material": "Copper", "layerName": "L1", "topConductorThick": 0.035}]
        components.extend({"material": "Prepreg", "materialName": "1080 without copper", "plateContainCopper": False,
                           "dielectricThick": 0.1} for _ in range(20))
        components.append({"material": "Copper", "layerName": "L2", "topConductorThick": 0.035})
        reader = FixtureReader("JLCPCB", "jlc_named_template", {"plateLayerNumber": 2}, components)
        draft = build_stackup_draft(reader, "template")
        self.assertGreater(len(reader.captures), 1)
        self.assertTrue(all(len(item[2]) <= 64 for item in reader.captures))
        for item in draft["layers"]:
            if item["role"] == "dielectric":
                evidence = next(entry for entry in reader.captures if entry[3] == item["thickness_evidence_id"])
                self.assertIn(item["thickness_source_pointer"], evidence[2])
                self.assertIn(item["thickness_source_pointer"].replace("dielectricThick", "plateContainCopper"), evidence[2])

    def test_oversized_single_component_evidence_is_not_truncated(self):
        """! @brief 한 판단 묶음 자체가 상한보다 크면 문자열을 자르지 않고 실패한다."""
        reader = self.jlc(name="x" * 5000)
        with self.assertRaises(CatalogError) as error:
            build_stackup_draft(reader, "template")
        self.assertEqual(error.exception.code, "E_RESOURCE")


if __name__ == "__main__":
    unittest.main()
