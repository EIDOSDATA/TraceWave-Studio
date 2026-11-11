"""! @brief 총 Df 손실 모델의 명시 선택과 출처/이력/저장 보존을 검증한다."""

from copy import deepcopy
import json
import unittest
from uuid import uuid4

from rfad.application.projects import ProjectService
from rfad.catalog.material_selection import build_material
from rfad.catalog.models import CatalogError
from rfad.domain.errors import ProjectError
from rfad.domain.material_models import LEGACY_MODEL, TOTAL_TAN_DELTA_MODEL
import test_pcb_selection_service as fixtures


class MaterialModelSelectionTests(unittest.TestCase):
    """! @brief 숫자 물성 보완 없이 물리 모델의 변경만 명시적으로 적용한다."""

    def setUp(self):
        """! @brief 공개 선택 API를 사용하는 작은 카탈로그 프로젝트를 만든다."""
        self.fixture = fixtures.PcbSelectionServiceTests()
        self.fixture.setUp()
        self.spec = fixtures.manual_specification()
        material = self.spec["materials"][0]
        material.update(model=TOTAL_TAN_DELTA_MODEL, model_reason="총 측정 손실 Df를 사용하므로 추가 전도도를 소비하지 않음")
        material["properties"]["conductivity"] = {"mode": "missing", "reason": "독립 전도도는 미정으로 보존"}

    def tearDown(self):
        """! @brief 시험 소유 저장소와 잠금을 정리한다."""
        self.fixture.tearDown()

    def test_model_selection_undo_snapshot_and_catalog_free_restart(self):
        """! @brief 선택 모델과 사유를 같은 원자 명령으로 저장하고 재열어 보존한다."""
        fixture = self.fixture
        before = fixture.document()
        fixture.apply(fixture.selection(self.spec))
        selected = fixture.document()
        material = selected["materials"][0]
        self.assertEqual(material["model"], TOTAL_TAN_DELTA_MODEL)
        self.assertIsNone(material["conductivity"]["value_si"])
        extension = selected["extensions"]["rfad.pcb-selection"]
        decisions = [item for item in extension["decisions"] if item["target"]["field"] == "model"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(json.loads(decisions[0]["value_json"]), TOTAL_TAN_DELTA_MODEL)
        self.assertEqual(decisions[0]["basis"], "user_assumption")
        self.assertTrue(decisions[0]["reason"])
        fixture.service.mutate("project.undo", fixture.request({"expected_revision": selected["revision_id"], "command_id": str(uuid4())}))
        self.assertEqual(fixture.document()["materials"], before["materials"])
        fixture.service.mutate("project.redo", fixture.request({"expected_revision": fixture.document()["revision_id"], "command_id": str(uuid4())}))
        self.assertEqual(fixture.document()["materials"], selected["materials"])
        fixture.complete("project.save", fixture.request({"expected_revision": fixture.document()["revision_id"]}))
        snapshot = fixture.complete("snapshot.create", fixture.request({"expected_revision": fixture.document()["revision_id"]}))
        fixture.service.close()
        fixture.database.unlink()
        fixture.service = ProjectService(fixture.workspace, auto_run=False)
        restored = json.loads(fixture.service.journal.read_artifact(snapshot["artifact"]))
        self.assertEqual(restored, fixture.document())
        self.assertEqual(restored["materials"], selected["materials"])

    def test_model_change_is_tracked_and_omission_cannot_reset_it(self):
        """! @brief 기존 총 Df 모델을 구형 선택 입력이 암묵적으로 가산 모델로 바꾸지 않는다."""
        fixture = self.fixture
        fixture.apply(fixture.selection(self.spec))
        original = fixture.document()
        updated = deepcopy(self.spec)
        updated["material_ids"] = {"core": original["materials"][0]["id"]}
        del updated["materials"][0]["model"]
        del updated["materials"][0]["model_reason"]
        with self.assertRaises(ProjectError):
            fixture.preview(fixture.selection(updated))
        self.assertEqual(fixture.document(), original)
        material = deepcopy(original["materials"][0])
        material["model"] = LEGACY_MODEL
        fixture.command("material.set", {"material": material})
        selected = fixture.service.pcb_selection.get(fixture.request({}, read=True))
        self.assertTrue(selected["modified_since_selection"])
        self.assertTrue(any(item["target"]["field"] == "model" for item in selected["changed_selected_fields"]))

    def test_explicit_model_requires_known_enum_and_reason(self):
        """! @brief 알 수 없는 모델, 짝 없는 필드와 빈 사유를 거절한다."""
        source = {**self.spec["materials"][0], "id": str(uuid4())}
        for change in ({"model": "guess"}, {"model": None}, {"model_reason": ""}):
            with self.subTest(change=change):
                with self.assertRaises(CatalogError):
                    build_material({**source, **change}, None)
        for field in ("model", "model_reason"):
            item = deepcopy(source)
            del item[field]
            with self.assertRaises(CatalogError):
                build_material(item, None)

    def test_legacy_selection_keeps_previous_shape(self):
        """! @brief 구형 입력에는 새 모델 결정이나 가정을 삽입하지 않는다."""
        source = {**fixtures.manual_material(), "id": str(uuid4())}
        result = build_material(source, None)
        self.assertEqual(result["material"]["model"], LEGACY_MODEL)
        self.assertEqual(len(result["decisions"]), 5)
        self.assertFalse(any(item.startswith("model:") for item in result["material"]["assumptions"]))


if __name__ == "__main__":
    unittest.main()
