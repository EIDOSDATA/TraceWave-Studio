"""! @brief 실제 journal에서 구리 영역/패드/비아의 저장, 표시와 편집 원자성을 검증한다."""

from copy import deepcopy
import json
import math
import unittest
from uuid import uuid4

import test_canvas_service as canvas_fixture
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity


class CopperDesignTests(unittest.TestCase):
    """! @brief native CAD/solver 없이 실제 프로젝트 서비스 경계를 통과시킨다."""

    def setUp(self):
        """! @brief 실제 journal과 미정 물리 적층을 갖는 별도 프로젝트를 만든다."""
        self.fixture = canvas_fixture.CanvasServiceTests()
        self.fixture.setUp()
        self.board, self.bottom = self.fixture.board_layer()
        self.core, self.top = str(uuid4()), str(uuid4())
        self.fixture.apply("create_dielectric_layer", {"id": self.core, "name": "미정 유전체"})
        self.fixture.apply("create_layer", {"id": self.top, "name": "상부 도체"})

    def tearDown(self):
        """! @brief 시험이 소유한 저장소와 임시 workspace만 닫는다."""
        self.fixture.tearDown()

    def polygon_values(self, **overrides):
        """! @brief 구멍 두 개를 가진 명시적 영역 생성 입력을 반환한다."""
        return {"id": str(uuid4()), "layer_id": self.top, "outer": [[5, 5], [25, 5], [25, 25], [5, 25]],
                "holes": [[[8, 8], [11, 8], [11, 11], [8, 11]], [[16, 16], [19, 16], [19, 19], [16, 19]]], **overrides}

    def create_polygon(self):
        """! @brief 화면 생성 경로에서 실제 planar_region 객체를 저장한다."""
        values = self.polygon_values()
        self.fixture.apply("create_polygon", values)
        return values["id"]

    def pad_values(self, layer, **overrides):
        """! @brief 단위와 회전이 명시된 단일 층 pad 입력을 만든다."""
        return {"id": str(uuid4()), "layer_id": layer, "pad_shape": "circle", "center": [20, 30],
                "width_mm": 2.0, "height_mm": 2.0, "rotation_deg": 0, **overrides}

    def create_pad(self, layer, **overrides):
        """! @brief pad를 만들고 추적할 안정 식별자를 반환한다."""
        values = self.pad_values(layer, **overrides)
        self.fixture.apply("create_pad", values)
        return values["id"]

    def via_values(self, pads, **overrides):
        """! @brief 미정 plating/tool과 명시적 양끝 pad를 가진 via 입력을 만든다."""
        return {"id": str(uuid4()), "layer_id": self.bottom, "end_layer_id": self.top, "center": [20, 30],
                "finished_hole_diameter_mm": 0.3, "plating_thickness_mm": None, "tool_hole_diameter_mm": None,
                "pad_ids": list(pads), **overrides}

    def create_via(self):
        """! @brief 양끝 pad와 미정 공정 조건을 가진 via를 순서대로 생성한다."""
        pads = [self.create_pad(self.bottom), self.create_pad(self.top)]
        values = self.via_values(pads)
        self.fixture.apply("create_via", values)
        return values["id"], pads

    def displayed(self, identity):
        """! @brief 개정에 결합된 읽기 전용 DTO에서 안정 ID로 도체를 찾는다."""
        return next(item for item in self.fixture.canvas()["shapes"] if item["id"] == identity)

    def assert_command_rejected(self, kind, payload):
        """! @brief 실패한 저수준 도메인 명령도 원본/receipt/이력을 바꾸지 않는다."""
        before = self.fixture.service.journal.read()
        with self.assertRaises(ProjectError) as caught:
            self.fixture.command(kind, payload)
        self.assertEqual(self.fixture.service.journal.read(), before)
        return caught.exception

    def test_canvas_creates_all_features_without_inferred_physics(self):
        """! @brief 새 도체는 원본 종류/단위를 지키고 물성/net/물리 적층을 자동 확정하지 않는다."""
        region = self.create_polygon()
        via, pads = self.create_via()
        document = self.fixture.document()
        self.assertEqual({shape["kind"] for shape in document["geometry"]}, {"planar_region", "pad", "via"})
        self.assertEqual(document["materials"], [])
        self.assertEqual(document["nets"], [])
        self.assertTrue(all(shape["net_id"] is None and shape["material_ref"] is None for shape in document["geometry"]))
        self.assertTrue(all(layer["z_min"]["value_si"] is None and layer["thickness"]["value_si"] is None for layer in document["stackup"]))
        self.assertEqual(self.fixture.shape(region)["role"], "ground")
        self.assertEqual(self.fixture.shape(via)["pad_ids"], pads)
        self.assertEqual(self.fixture.shape(via)["fill"], "none")
        self.assertEqual(self.displayed(via)["span_layer_ids"], [self.bottom, self.top])
        restored = json.loads(canonical_bytes(document))
        validate_project(restored)
        self.assertEqual(restored, document)

    def test_missing_via_dimensions_are_nullable_without_losing_location(self):
        """! @brief 미정 finished/plating/tool은 0으로 보이지 않고 좌표와 span은 유지된다."""
        via, _ = self.create_via()
        visible = self.displayed(via)
        self.assertEqual(visible["center"], [20, 30])
        self.assertAlmostEqual(visible["finished_hole_diameter"], 0.3)
        self.assertIsNone(visible["plating_thickness"])
        self.assertIsNone(visible["tool_hole_diameter"])
        source = self.fixture.shape(via)
        self.assertEqual(source["plating_thickness"]["status"], "missing")
        self.assertEqual(source["tool_hole_diameter"]["status"], "missing")
        self.assertEqual(len([item for item in self.fixture.canvas()["omissions"] if item["id"] == via]), 2)
        source["finished_hole_diameter"] = Quantity.missing("length", "mm").to_dict()
        self.fixture.command("geometry.set", {"geometry": source})
        self.assertIsNone(self.displayed(via)["finished_hole_diameter"])
        self.assertTrue(self.displayed(via)["movable"])

    def test_pad_references_guard_delete_and_preserve_multiple_choices(self):
        """! @brief 선택한 pad 배열은 저장되며 참조 중 삭제만 차단한다."""
        via, pads = self.create_via()
        extra = self.create_pad(self.top, center=[22, 30])
        source = self.fixture.shape(via)
        source["pad_ids"] = [extra, *reversed(pads)]
        self.fixture.command("geometry.set", {"geometry": source})
        self.assertEqual(self.fixture.shape(via)["pad_ids"], [extra, *reversed(pads)])
        for identity in [*pads, extra]:
            self.fixture.assert_rejected("remove", {"id": identity})
        source["pad_ids"] = pads
        self.fixture.command("geometry.set", {"geometry": source})
        self.fixture.apply("remove", {"id": extra})
        self.assertNotIn(extra, {item["id"] for item in self.fixture.document()["geometry"]})
        source = self.fixture.shape(via)
        source["pad_ids"] = [pads[0], pads[0]]
        self.assert_command_rejected("geometry.set", {"geometry": source})

    def test_polygon_translation_moves_every_hole_and_preserves_source(self):
        """! @brief outer와 모든 hole을 같은 SI 이동량으로 옮기며 입력 객체를 변경하지 않는다."""
        identity = self.create_polygon()
        original = self.fixture.shape(identity)
        before = deepcopy(original)
        self.fixture.apply("translate", {"id": identity, "dx_mm": 2.5, "dy_mm": -1.25})
        moved = self.fixture.shape(identity)
        self.assertEqual(original, before)
        for old_loop, new_loop in zip([before["outer"], *before["holes"]], [moved["outer"], *moved["holes"]]):
            for old_point, new_point in zip(old_loop, new_loop):
                self.assertAlmostEqual(new_point[0]["value_si"] - old_point[0]["value_si"], 0.0025)
                self.assertAlmostEqual(new_point[1]["value_si"] - old_point[1]["value_si"], -0.00125)
        self.assertEqual(self.displayed(identity)["outer"][0], [7.5, 3.75])
        self.assertEqual(len(self.displayed(identity)["holes"]), 2)

    def test_polygon_history_snapshot_and_restart_preserve_holes(self):
        """! @brief 이동 이력과 봉인 snapshot은 재시작 뒤에도 각 hole을 보존한다."""
        identity = self.create_polygon()
        original = self.fixture.shape(identity)
        task = self.fixture.service.mutate("snapshot.create", self.fixture.request({"expected_revision": self.fixture.revision}))
        self.fixture.service.run_next()
        snapshot = self.fixture.service.journal.read()["jobs"][task["job_id"]]["events"][-1]["operation_result"]
        sealed = self.fixture.service.journal.read_artifact(snapshot["artifact"])
        self.fixture.apply("translate", {"id": identity, "dx_mm": 1, "dy_mm": 2})
        moved = self.fixture.shape(identity)
        self.fixture.history("undo")
        self.assertEqual(self.fixture.shape(identity), original)
        self.fixture.history("redo")
        self.assertEqual(self.fixture.shape(identity), moved)
        self.fixture.service.close()
        self.fixture.service = ProjectService(self.fixture.workspace, auto_run=False)
        self.assertEqual(self.fixture.shape(identity), moved)
        self.assertEqual(self.fixture.service.journal.read_artifact(snapshot["artifact"]), sealed)
        self.assertEqual(next(item for item in json.loads(sealed)["geometry"] if item["id"] == identity), original)
        self.assertEqual(len(self.displayed(identity)["holes"]), 2)

    def test_parameter_coordinate_changes_display_without_detaching_binding(self):
        """! @brief 매개변수 변경은 표시만 재평가하며 직접 이동과 참조 삭제는 차단한다."""
        identity = self.create_polygon()
        parameter = str(uuid4())
        self.fixture.command("parameter.set", {"id": parameter, "name": "영역 시작 x", "quantity": Quantity.from_value(5, "mm").to_dict()})
        source = self.fixture.shape(identity)
        source["outer"][0][0] = {"parameter_id": parameter}
        self.fixture.command("geometry.set", {"geometry": source})
        self.assertFalse(self.displayed(identity)["movable"])
        self.fixture.assert_rejected("translate", {"id": identity, "dx_mm": 1, "dy_mm": 1})
        self.fixture.command("parameter.set", {"id": parameter, "name": "영역 시작 x", "quantity": Quantity.from_value(6, "mm").to_dict()})
        self.assertEqual(self.displayed(identity)["outer"][0], [6, 5])
        self.assertEqual(self.fixture.shape(identity)["outer"][0][0], {"parameter_id": parameter})
        self.fixture.assert_rejected("translate", {"id": identity, "dx_mm": 1, "dy_mm": 1})
        self.assert_command_rejected("parameter.set", {"id": parameter, "name": "영역 시작 x", "quantity": Quantity.from_value(30, "mm").to_dict()})
        self.assertEqual(self.displayed(identity)["outer"][0], [6, 5])
        self.assert_command_rejected("parameter.remove", {"id": parameter})

    def test_parameter_bound_hole_also_blocks_direct_translation(self):
        """! @brief outer가 직접 수치여도 hole 좌표 결합을 이동으로 해제하지 않는다."""
        identity = self.create_polygon()
        parameter = str(uuid4())
        self.fixture.command("parameter.set", {"id": parameter, "name": "첫 hole x", "quantity": Quantity.from_value(8, "mm").to_dict()})
        source = self.fixture.shape(identity)
        source["holes"][0][0][0] = {"parameter_id": parameter}
        self.fixture.command("geometry.set", {"geometry": source})
        self.assertFalse(self.displayed(identity)["movable"])
        self.fixture.assert_rejected("translate", {"id": identity, "dx_mm": 1, "dy_mm": 0})
        self.assertEqual(self.fixture.shape(identity)["holes"][0][0][0], {"parameter_id": parameter})

    def test_invalid_region_is_atomic_and_never_clipped_or_healed(self):
        """! @brief 자기교차/반복점/접촉 hole/외부 hole은 원본과 journal을 바꾸지 않는다."""
        for outer, holes in (([[5, 5], [25, 25], [5, 25], [25, 5]], []),
                             ([[5, 5], [25, 5], [25, 25], [5, 25], [5, 5]], []),
                             ([[5, 5], [25, 5], [25, 25], [5, 25]], [[[5, 8], [8, 8], [8, 11], [5, 11]]]),
                             ([[5, 5], [25, 5], [25, 25], [5, 25]], [[[30, 30], [32, 30], [32, 32], [30, 32]]])):
            with self.subTest(outer=outer, holes=holes):
                self.fixture.assert_rejected("create_polygon", self.polygon_values(outer=outer, holes=holes))

    def test_circle_pad_dimensions_and_rectangle_rotation_are_explicit(self):
        """! @brief 원형 두 지름 불일치는 차단하고 사각 회전을 라디안 원본/도 표시로 보존한다."""
        self.fixture.assert_rejected("create_pad", self.pad_values(self.top, width_mm=2, height_mm=3))
        self.fixture.assert_rejected("create_pad", self.pad_values(self.top, width_mm=0, height_mm=0))
        identity = self.create_pad(self.top, pad_shape="rectangle", width_mm=2, height_mm=3, rotation_deg=-30)
        self.assertAlmostEqual(self.fixture.shape(identity)["rotation"]["value_si"], -math.pi / 6)
        visible = self.displayed(identity)
        self.assertEqual(visible["size"], [2, 3])
        self.assertAlmostEqual(visible["rotation"], -30)

    def test_via_layer_order_and_pad_identity_are_checked_atomically(self):
        """! @brief 역방향/동일/유전체 끝층과 pad가 아닌 참조를 저장하지 않는다."""
        pads = [self.create_pad(self.bottom), self.create_pad(self.top)]
        for overrides in ({"layer_id": self.top, "end_layer_id": self.bottom}, {"end_layer_id": self.bottom}, {"end_layer_id": self.core},
                          {"pad_ids": [pads[0], pads[0]]}, {"pad_ids": [pads[0], str(uuid4())]}):
            self.fixture.assert_rejected("create_via", self.via_values(pads, **overrides))
        region = self.create_polygon()
        self.fixture.assert_rejected("create_via", self.via_values([pads[0], region]))

    def test_via_first_invalid_referenced_pad_layer_returns_domain_error(self):
        """! @brief UUID 순서상 via가 먼저여도 잘못된 pad 층은 KeyError 없이 원자적으로 거절한다."""
        pads = [self.create_pad(self.bottom), self.create_pad(self.top)]
        values = self.via_values(pads, id="00000000-0000-0000-0000-000000000001")
        self.fixture.apply("create_via", values)
        self.assertEqual(self.fixture.document()["geometry"][0]["kind"], "via")
        original = self.fixture.shape(pads[0])
        for missing in (False, True):
            with self.subTest(missing=missing):
                changed = deepcopy(original)
                if missing:
                    changed.pop("layer_id")
                else:
                    changed["layer_id"] = str(uuid4())
                self.assert_command_rejected("geometry.set", {"geometry": changed})
                self.assertEqual(self.fixture.shape(pads[0]), original)


if __name__ == "__main__":
    unittest.main()
