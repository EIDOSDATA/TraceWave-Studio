"""! @brief 제조업체 층의 정확한 원문 대응과 다른 조건의 관측 배제를 검사한다."""

from copy import deepcopy
import unittest

from rfad.catalog.models import CatalogError
from rfad.catalog.stackup_match import resolve_layer_records


class MatchReader:
    """! @brief 정확한 원문 위치를 가진 작은 JLC 2층 자료를 제공한다."""

    def __init__(self):
        """! @brief 원문 코어와 정규화 관측을 별도 사본으로 구성한다."""
        raw = {"material": "Core", "materialName": "Core-X", "dielectricConstant": 4.2}
        self.template = {"template_id": "T", "template_key": "JLC-X", "stackup_id": "S", "publisher": "JLCPCB",
                         "kind": "jlc_named_template", "source_id": "F", "source_path": "data/fixture.json",
                         "source_pointer": "/body/list/0", "source_sha256": "a" * 64, "raw": {"basicDataList": [raw]}}
        self.component = {key: value for key, value in self.template.items()
                          if key in ("template_id", "stackup_id", "publisher", "source_id", "source_path", "source_sha256")}
        self.component.update(component_order=0, component_id="C", source_pointer="/body/list/0/basicDataList/0", raw=deepcopy(raw))
        self.records = [{"record_id": "R1", "publisher": "JLCPCB", "raw": {
            "manufacturer": "JLCPCB", "public_template_id": "JLC-X", "layer_index": 0,
            "material_form": "core", "material_name": "Core-X", "source_file": "data/fixture.json",
            "source_location": "fixture; body.list[0].basicDataList[0]", "dk": 4.2, "df": None}}]

    def catalog(self):
        """! @brief 고정 카탈로그 개정을 반환한다."""
        return {"catalog_id": "CAT"}

    def native_template(self, identity):
        """! @brief 원문 템플릿을 반환한다."""
        return deepcopy(self.template)

    def native_components(self, identity):
        """! @brief 원문 구성 행을 반환한다."""
        return [deepcopy(self.component)]

    def stackup_observations(self, stackup_id, publisher, source_id):
        """! @brief 정확한 적층 조회 조건을 검사한다."""
        if (stackup_id, publisher, source_id) != (self.template["stackup_id"], self.template["publisher"], self.template["source_id"]):
            raise AssertionError("원문 적층 식별자가 다릅니다.")
        return deepcopy(self.records)

    def observation(self, identity):
        """! @brief 선택한 단일 관측을 반환한다."""
        return deepcopy(next(record for record in self.records if record["record_id"] == identity))


class StackupMatchTests(unittest.TestCase):
    """! @brief 같은 제조업체라는 이유로 다른 층의 수치를 연결하지 않음을 검증한다."""

    def setUp(self):
        """! @brief 카탈로그와 층이 고정된 초안을 구성한다."""
        self.reader = MatchReader()
        self.source = {"catalog_id": "CAT", "entity": "native_templates", "id": "T"}
        self.draft = {"catalog_id": "CAT", "template_id": "T", "layers": [
            {"key": "component:0:dielectric", "role": "dielectric", "thickness_mm": None},
            {"key": "component:0:top", "role": "conductor", "thickness_mm": None}]}

    def result(self):
        """! @brief 첫 유전체 층의 대응 결과만 반환한다."""
        return resolve_layer_records(self.reader, self.source, self.draft)[self.draft["layers"][0]["key"]]

    def test_exact_identity_matches_without_filling_thickness_or_loss(self):
        """! @brief 정확한 원문 대응만 반환하고 미정 두께나 손실은 그대로 둔다."""
        before = deepcopy(self.draft)
        self.assertEqual(self.result()["record_ids"], ["R1"])
        self.assertEqual(self.result()["state"], "matched")
        self.assertEqual(self.draft, before)
        self.assertIsNone(self.reader.records[0]["raw"]["df"])

    def test_identity_mismatch_and_boolean_index_are_not_matches(self):
        """! @brief 비슷한 재질, 다른 원문 위치와 불리언 행 번호를 배제한다."""
        original = deepcopy(self.reader.records[0]["raw"])
        for field, value in (("public_template_id", "other"), ("layer_index", False), ("material_form", "prepreg"),
                             ("material_name", "Core-Y"), ("source_file", "other.json"),
                             ("source_location", "fixture; body.list[1].basicDataList[0]")):
            with self.subTest(field=field):
                self.reader.records[0]["raw"] = {**original, field: value}
                self.assertEqual(self.result()["state"], "missing")

    def test_single_dk_conflict_is_not_suggested_and_duplicates_are_explicit(self):
        """! @brief 원문 불일치는 차단하고 여러 관측은 호출자가 모호성을 판단하도록 모두 반환한다."""
        self.reader.records[0]["raw"]["dk"] = 4.3
        self.assertEqual(self.result()["state"], "unsupported")
        duplicate = deepcopy(self.reader.records[0])
        duplicate.update(record_id="R2")
        duplicate["raw"]["dk"] = 4.2
        self.reader.records.append(duplicate)
        self.assertEqual(self.result()["record_ids"], ["R1", "R2"])

    def test_component_parent_source_mismatch_raises(self):
        """! @brief 구성 행의 출처와 부모 원문 불일치를 누락으로 숨기지 않는다."""
        for field, value in (("source_pointer", "/body/list/1/basicDataList/0"), ("source_id", "other"),
                             ("raw", {"material": "Core", "materialName": "Core-Y", "dielectricConstant": 4.2})):
            with self.subTest(field=field):
                self.reader = MatchReader()
                self.reader.component[field] = value
                with self.assertRaises(CatalogError) as raised:
                    self.result()
                self.assertEqual(raised.exception.code, "E_HASH")

    def test_user_defined_template_and_stale_selection_do_not_match(self):
        """! @brief 사용자 정의 원문을 고정 제조 사양으로 승격하거나 다른 개정을 섞지 않는다."""
        self.reader.template["kind"] = "jlc_user_defined_template"
        self.assertEqual(self.result()["state"], "unsupported")
        self.assertIn("사용자 정의", self.result()["reason"])
        self.source["catalog_id"] = "other"
        with self.assertRaises(CatalogError) as raised:
            self.result()
        self.assertEqual(raised.exception.code, "E_CONFLICT")

    def test_pcbway_uses_one_based_table_row_and_matching_template(self):
        """! @brief PCBWay의 1 기반 표 행과 같은 적층만 연결한다."""
        self.reader.template.update(publisher="PCBWay", kind="pcbway_published_template", template_key="PCB-X",
                                    source_pointer="/0", raw={"rows": [["PP", "2116 RC58% DK:4.45", "0.13", "0.1055"]]})
        self.reader.component.update(publisher="PCBWay", source_pointer="/0/rows/0", raw=self.reader.template["raw"]["rows"][0])
        self.reader.records = [{"record_id": "R1", "publisher": "PCBWay", "raw": {
            "manufacturer": "PCBWay", "stackup_id": "PCB-X", "layer_sequence": 1,
            "material_form": "prepreg", "source_location": "PCB-X; table row 1", "dk": 4.45}}]
        self.draft["layers"] = [{"key": "component:0", "role": "dielectric", "thickness_mm": None}]
        self.assertEqual(self.result()["state"], "matched")
        self.reader.records[0]["raw"]["layer_sequence"] = 0
        self.assertEqual(self.result()["state"], "missing")

    def test_osh_uses_only_the_selected_two_layer_observation(self):
        """! @brief OSH 2층 코어는 선택한 관측 자체만 제안하고 다른 적층에 재사용하지 않는다."""
        self.source.update(entity="observations", id="R1")
        self.draft.update(record_id="R1")
        self.reader.records = [{"record_id": "R1", "publisher": "OSH Park", "raw": {
            "manufacturer": "OSH Park", "stackup_id": "OSH_2L_1.6", "record_kind": "published_stackup_layer",
            "material_form": "core", "layer": "L1-L2", "dataset_role": "fabricator_published_parameter"}}]
        self.assertEqual(self.result()["record_ids"], ["R1"])
        self.reader.records[0]["raw"]["stackup_id"] = "OSH_4L"
        self.assertEqual(self.result()["state"], "unsupported")


if __name__ == "__main__":
    unittest.main()
