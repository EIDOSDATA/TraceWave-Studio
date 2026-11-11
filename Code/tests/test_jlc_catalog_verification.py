"""! @brief JLC 검증 입력에서 시험 물성과 출처 없는 치수가 실제 재료로 승격되지 않는지 검사한다."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from create_jlc_catalog_verification import prepare_geometry_fixture, selection_specification
from rfad.application.pcb_selection_layers import assemble_layers


class JlcCatalogVerificationTests(unittest.TestCase):
    """! @brief 실제 기하 fixture와 기존 적층 조립기를 사용하고 카탈로그나 외부 worker는 실행하지 않는다."""

    def setUp(self):
        """! @brief 디스크의 원본 fixture를 읽기 전용으로 열어 각 시험의 독립된 입력을 만든다."""
        path = Path(__file__).resolve().parents[1] / "fixtures/pcb_worker_smoke.json"
        self.fixture = json.loads(path.read_text(encoding="utf-8"))
        self.source = {"catalog_id": "catalog:test-only", "entity": "native_templates", "id": "template:test-only"}

    def test_preparation_clears_material_assumptions_without_mutating_fixture(self):
        """! @brief 모든 RF 물성과 대역을 미정으로 바꾸되 입력 기하와 급전의 명시 시험 조건은 보존한다."""
        before = deepcopy(self.fixture)
        prepared = prepare_geometry_fixture(self.fixture)
        self.assertEqual(self.fixture, before)
        original, actual = before["document"], prepared["document"]
        for collection in ("board", "geometry", "nets", "stackup"):
            self.assertEqual(actual[collection], original[collection])
        names = [material["name"] for material in actual["materials"]]
        self.assertEqual(len(names), len(set(names)))
        for material in actual["materials"]:
            self.assertEqual(material["source_refs"], [])
            quantities = [material[field] for field in ("epsilon_r", "tan_delta", "conductivity")]
            quantities.extend(material["validity_hz"].values())
            for quantity in quantities:
                self.assertIsNone(quantity["value_si"])
                self.assertEqual(quantity["status"], "missing")
                self.assertEqual(quantity["source_refs"], [])
        for old, new in zip(original["ports"], actual["ports"], strict=True):
            self.assertEqual({key: value for key, value in new.items() if key != "validity_hz"},
                             {key: value for key, value in old.items() if key != "validity_hz"})
            for boundary in new["validity_hz"].values():
                self.assertIsNone(boundary["value_si"])
                self.assertEqual(boundary["status"], "missing")

    def test_selection_preserves_ids_and_port_xy_but_moves_to_explicit_stackup(self):
        """! @brief 기존 도체와 코어 UUID를 유지하며 급전 Z만 선택한 코어와 하부 동박 높이로 갱신한다."""
        prepared = prepare_geometry_fixture(self.fixture)
        before, source_before = deepcopy(prepared), deepcopy(self.source)
        spec = selection_specification(prepared, self.source)
        self.assertEqual(prepared, before)
        self.assertEqual(self.source, source_before)
        layers = {layer["role"]: layer for layer in prepared["document"]["stackup"]}
        self.assertEqual(spec["material_ids"], {"core": layers["dielectric"]["material_id"], "copper": layers["conductor"]["material_id"]})
        self.assertEqual(spec["layer_ids"], {"component:0:dielectric": layers["dielectric"]["id"], "component:0:top": layers["conductor"]["id"]})
        for port, update in zip(prepared["document"]["ports"], spec["port_updates"], strict=True):
            self.assertEqual(update["id"], port["id"])
            for endpoint in ("start", "stop"):
                original_xy = [point["value_si"] * 1000 for point in port["excitation_box"][endpoint][:2]]
                self.assertEqual(update[endpoint + "_mm"][:2], original_xy)
                self.assertAlmostEqual(update[endpoint + "_mm"][2], 0.535)
            self.assertTrue(update["reason"])
        for material in spec["materials"]:
            self.assertIsNone(material["validity_hz"]["min"])
            self.assertIsNone(material["validity_hz"]["max"])
            for field, choice in material["properties"].items():
                expected = "catalog" if material["key"] == "core" and field == "epsilon_r" else "missing"
                self.assertEqual(choice["mode"], expected)
                self.assertNotIn("value", choice)

    def test_explicit_copper_choice_preserves_raw_draft_and_nominal_difference(self):
        """! @brief 공개 외층 선택은 raw 0.03 mm를 덮어쓰거나 공칭 0.6 mm의 차이를 자동 배분하지 않는다."""
        prepared = prepare_geometry_fixture(self.fixture)
        spec = selection_specification(prepared, self.source)
        rows = []
        for key, role, thickness in (("bottom", "conductor", None), ("dielectric", "dielectric", 0.5), ("top", "conductor", None)):
            rows.append({"key": "component:0:" + key, "name": key, "role": role, "thickness_mm": thickness,
                         "status": "source_value" if thickness is not None else "unresolved",
                         "thickness_basis": "source_dielectric_excluding_copper" if thickness is not None else "core_copper_finished_thickness_unspecified"})
        draft = {"nominal_thickness_mm": 0.6, "layers": rows,
                 "raw_component": {"topConductorThick": 0.03, "botConductorThick": 0.03}}
        before = deepcopy(draft)
        self.assertEqual(set(spec["thickness_overrides"]), {"component:0:bottom", "component:0:top"})
        result, decisions = assemble_layers(prepared["document"], str(uuid4()), spec, draft,
                                           spec["material_ids"], prepared["document"]["materials"])
        self.assertEqual(draft, before)
        for layer, expected in zip(result, [0.000035, 0.0005, 0.000035], strict=True):
            self.assertAlmostEqual(layer["thickness"]["value_si"], expected, places=12)
        self.assertAlmostEqual(sum(layer["thickness"]["value_si"] for layer in result) * 1000, 0.570)
        self.assertNotAlmostEqual(sum(layer["thickness"]["value_si"] for layer in result) * 1000, draft["nominal_thickness_mm"])
        self.assertAlmostEqual(result[-1]["z_min"]["value_si"] * 1000, 0.535)
        thickness_decisions = [decision for decision in decisions if decision["target"]["field"] == "thickness"]
        self.assertEqual([decision["basis"] for decision in thickness_decisions], ["user_override", "published", "user_override"])
        for decision in (thickness_decisions[0], thickness_decisions[2]):
            self.assertIn("https://jlcpcb.com/", decision["reason"])


if __name__ == "__main__":
    unittest.main()
