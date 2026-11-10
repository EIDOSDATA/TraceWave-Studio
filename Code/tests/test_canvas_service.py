"""! @brief 2D 표시와 직접 편집이 원본/참조/개정 이력을 지키는지 검증한다."""

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity


class CanvasServiceTests(unittest.TestCase):
    """! @brief 실제 journal과 동일 명령 경계에서 2D 조작의 결과를 확인한다."""

    def setUp(self):
        """! @brief 물성을 가정하지 않는 빈 프로젝트를 준비한다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "2D 원본"
        self.service = ProjectService(self.workspace, auto_run=False)
        task = self.service.mutate("project.open", self.request({"path": "projects/canvas", "open_mode": "create", "name": "2D 설계"}, {}))
        self.service.run_next()
        result = self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})["events"][-1]["operation_result"]
        self.project = result["project_id"]
        self.revision = result["revision_id"]

    def tearDown(self):
        """! @brief 소유한 저장소 잠금과 임시 파일을 해제한다."""
        self.service.close()
        self.temporary.cleanup()

    def request(self, data, context=None):
        """! @brief 정상 발급 epoch와 독립 request key를 사용한다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project} if context is None else context, "input": data,
                "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def params(self, operation, values):
        """! @brief 화면 조작의 기준 개정과 명령 ID를 고정한다."""
        return self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "operation": operation, "values": values})

    def apply(self, operation, values):
        """! @brief 성공한 편집 응답만 현재 개정으로 채택한다."""
        result = self.service.mutate("canvas.apply", self.params(operation, values))
        self.revision = result["new_revision"]
        return result

    def command(self, kind, payload):
        """! @brief 참조와 미정 fixture를 기존 명령으로 명시적으로 구성한다."""
        result = self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()), "type": kind, "payload": payload}))
        self.revision = result["new_revision"]
        return result

    def canvas(self):
        """! @brief 2D 조회가 journal을 바꾸지 않는지 확인한다."""
        before = self.service.journal.read()
        result = self.service.canvas_state({"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": {"expected_revision": self.revision}})
        self.assertEqual(self.service.journal.read(), before)
        return result

    def document(self):
        """! @brief 시험에서만 저장된 원본을 읽어 비교한다."""
        return self.service._load(self.service.journal.read()["projects"][self.project])

    def board_layer(self):
        """! @brief 기판과 미정 물리 적층을 별개 명령으로 만든다."""
        board, layer = str(uuid4()), str(uuid4())
        self.apply("create_board", {"id": board, "width_mm": 40, "height_mm": 60})
        self.apply("create_layer", {"id": layer, "name": "도체 1"})
        return board, layer

    def line(self, layer):
        """! @brief 화면에서 그린 작은 선 패턴을 만든다."""
        identity = str(uuid4())
        self.apply("create_line", {"id": identity, "layer_id": layer, "width_mm": 0.5, "start": [1, 2], "end": [10, 2]})
        return identity

    def arc(self, layer, sweep=-90):
        """! @brief 부호 있는 sweep의 원호를 만든다."""
        identity = str(uuid4())
        self.apply("create_arc", {"id": identity, "layer_id": layer, "width_mm": 0.5, "center": [12, 13], "radius_mm": 5, "start_angle_deg": 30, "sweep_angle_deg": sweep})
        return identity

    def shape(self, identity):
        """! @brief 안정 ID를 사용해 실제 원본 형상을 조회한다."""
        return next(item for item in self.document()["geometry"] if item["id"] == identity)

    def history(self, action):
        """! @brief 동일 저장 이력에서 새 개정 undo/redo를 적용한다."""
        before = self.revision
        result = self.service.mutate("project." + action, self.request({"expected_revision": before, "command_id": str(uuid4())}))
        self.revision = result["new_revision"]
        self.assertNotEqual(before, self.revision)
        self.assertEqual(self.document()["parent_revision_ids"], [before])
        return result

    def assert_rejected(self, operation, values):
        """! @brief 거부된 편집은 원본뿐 아니라 receipt와 이력도 바꾸지 않아야 한다."""
        before = self.service.journal.read()
        with self.assertRaises(ProjectError) as caught:
            self.apply(operation, values)
        self.assertEqual(self.service.journal.read(), before)
        return caught.exception

    def test_empty_read_and_capability_are_explicit_and_do_not_return_original(self):
        dto = self.canvas()
        self.assertEqual(dto["profile"], "rfad.canvas/0.1")
        self.assertIsNone(dto["board"])
        self.assertEqual(dto["shapes"], [])
        self.assertEqual(dto["layers"], [])
        self.assertEqual((dto["unit"], dto["angle_unit"]), ("mm", "deg"))
        self.assertNotIn("document", dto)
        request = {"jsonrpc": "2.0", "id": "capabilities", "method": "capabilities.get", "params": {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}}
        capabilities = handle_frame(json.dumps(request).encode(), self.service)["result"]
        self.assertEqual(capabilities["methods"]["canvas.apply"]["extension_profile"], "rfad.canvas/0.1")
        self.assertIn("translate", capabilities["canvas_profile"]["operations"])
        self.assertIn("create_dielectric_layer", capabilities["canvas_profile"]["operations"])

    def test_canvas_mutating_notification_and_batch_never_modify_project(self):
        params = self.params("create_board", {"id": str(uuid4()), "width_mm": 40, "height_mm": 60})
        notification = {"jsonrpc": "2.0", "method": "canvas.apply", "params": params}
        before = self.service.journal.read()
        self.assertIsNone(handle_frame(json.dumps(notification).encode(), self.service))
        response = handle_frame(json.dumps([{**notification, "id": "일괄 변경"}]).encode(), self.service)
        self.assertEqual(response["error"]["data"]["domain_code"], "E_UNSUPPORTED")
        self.assertEqual(self.service.journal.read(), before)

    def test_display_profile_omits_extreme_objects_but_preserves_normal_shapes_and_original(self):
        board, layer = self.board_layer()
        normal = self.line(layer)
        omitted = set()
        for values in ({"width_mm": 0.5, "start": [1e9 + 1, 0], "end": [1e9 + 2, 0]},
                       {"width_mm": 1e9 + 1, "start": [0, 0], "end": [10, 0]},
                       {"width_mm": 0.5, "start": [0, 0], "end": [1e-10, 0]}):
            identity = str(uuid4())
            self.apply("create_line", {"id": identity, "layer_id": layer, **values})
            omitted.add(identity)
        for radius, sweep in ((1e9 + 1, 90), (5, -1e-11)):
            identity = str(uuid4())
            self.apply("create_arc", {"id": identity, "layer_id": layer, "width_mm": 0.5, "center": [0, 0],
                                      "radius_mm": radius, "start_angle_deg": 0, "sweep_angle_deg": sweep})
            omitted.add(identity)
        changed_board = deepcopy(self.document()["board"])
        changed_board["outline"]["width"] = Quantity.from_value(1e9 + 1, "mm").to_dict()
        self.command("board.set", {"board": changed_board})
        original = self.document()
        dto = self.canvas()
        self.assertEqual(dto["ranges"], {"max_coordinate_mm": 1e9, "min_line_length_mm": 1e-9, "min_abs_sweep_deg": 1e-10})
        self.assertEqual([shape["id"] for shape in dto["shapes"]], [normal])
        self.assertEqual({item["id"] for item in dto["omissions"]}, omitted | {board})
        self.assertTrue(all("표시 profile" in item["message"] for item in dto["omissions"]))
        self.assertEqual(dto["board"], {"id": board, "width": None, "height": 60.0})
        self.assertEqual(self.document(), original)

    def test_display_profile_keeps_boundary_coordinates_and_small_representable_geometry(self):
        _, layer = self.board_layer()
        identities = set()
        for width, start, end in ((1e9, [-1e9, 0], [1e9, 0]), (1e-12, [0, 0], [2e-9, 0])):
            identity = str(uuid4())
            self.apply("create_line", {"id": identity, "layer_id": layer, "width_mm": width, "start": start, "end": end})
            identities.add(identity)
        identity = str(uuid4())
        self.apply("create_arc", {"id": identity, "layer_id": layer, "width_mm": 1e-12, "center": [0, 0],
                                  "radius_mm": 1e-11, "start_angle_deg": 0, "sweep_angle_deg": -2e-10})
        identities.add(identity)
        dto = self.canvas()
        self.assertEqual({shape["id"] for shape in dto["shapes"]}, identities)
        self.assertEqual(dto["omissions"], [])

    def test_board_layer_creation_preserves_missing_physics_and_has_separate_undo(self):
        board, layer = self.board_layer()
        dto = self.canvas()
        self.assertEqual(dto["board"], {"id": board, "width": 40.0, "height": 60.0})
        self.assertEqual(dto["layers"], [{"id": layer, "label": "도체 1", "role": "conductor"}])
        stored = self.document()["stackup"][0]
        self.assertEqual(stored["order"], 0)
        self.assertIsNone(stored["z_min"]["value_si"])
        self.assertIsNone(stored["thickness"]["value_si"])
        self.assertIsNone(stored["material_id"])
        self.assertEqual(self.document()["materials"], [])
        self.history("undo")
        self.assertEqual(self.canvas()["layers"], [])
        self.assertIsNotNone(self.canvas()["board"])
        self.history("undo")
        self.assertIsNone(self.canvas()["board"])

    def test_dielectric_layer_preserves_missing_inputs_order_and_undo(self):
        """! @brief 유전체 추가는 실제 재료나 두께를 추정하지 않고 적층 순서와 역명령을 유지한다."""
        board, conductor = self.board_layer()
        identity = str(uuid4())
        self.apply("create_dielectric_layer", {"id": identity, "name": "사용자 유전체"})
        stored = self.document()["stackup"][-1]
        self.assertEqual((stored["id"], stored["name"], stored["role"], stored["order"]),
                         (identity, "사용자 유전체", "dielectric", 1))
        for field in ("z_min", "thickness"):
            self.assertEqual(stored[field], Quantity.missing("length", "mm").to_dict())
        self.assertIsNone(stored["material_id"])
        self.assertEqual(self.document()["materials"], [])
        self.assertEqual(self.canvas()["layers"][-1], {"id": identity, "label": "사용자 유전체", "role": "dielectric"})
        self.history("undo")
        self.assertEqual([layer["id"] for layer in self.document()["stackup"]], [conductor])
        self.history("redo")
        self.assertEqual(self.document()["stackup"][-1], stored)
        self.assertEqual(self.document()["board"]["id"], board)

    def test_dielectric_layer_rejects_collisions_and_explicit_physics_fields(self):
        """! @brief 생성 전용 입력에 물성을 몰래 넣거나 기존 객체를 덮어쓸 수 없다."""
        _, conductor = self.board_layer()
        self.assertEqual(self.assert_rejected("create_dielectric_layer", {"id": conductor, "name": "충돌"}).code,
                         "E_CONFLICT")
        self.assertEqual(self.assert_rejected("create_dielectric_layer", {"id": str(uuid4()), "name": "추정 재료", "epsilon_r": 4.4}).code,
                         "E_SCHEMA")
        self.assertEqual(self.assert_rejected("create_dielectric_layer", {"id": str(uuid4()), "name": ""}).code,
                         "E_SCHEMA")

    def test_line_si_conversion_translate_replay_restart_and_remove_undo(self):
        _, layer = self.board_layer()
        identity = self.line(layer)
        original = self.shape(identity)
        self.assertEqual(original["start"][0]["value_si"], 0.001)
        self.assertIsNone(original["net_id"])
        self.assertIsNone(original["material_ref"])
        self.assertTrue(original["include_in_em"])
        self.assertTrue(original["include_in_export"])
        params = self.params("translate", {"id": identity, "dx_mm": 2, "dy_mm": -1})
        result = self.service.mutate("canvas.apply", params)
        self.revision = result["new_revision"]
        self.assertEqual(self.service.mutate("canvas.apply", params), result)
        visible = next(item for item in self.canvas()["shapes"] if item["id"] == identity)
        self.assertEqual(visible["start"], [3.0, 1.0])
        self.assertEqual(visible["end"], [12.0, 1.0])
        self.assertTrue(visible["movable"])
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        self.history("undo")
        self.assertEqual(self.shape(identity), original)
        self.history("redo")
        moved = self.shape(identity)
        self.apply("remove", {"id": identity})
        self.assertEqual(self.canvas()["shapes"], [])
        self.history("undo")
        self.assertEqual(self.shape(identity), moved)

    def test_signed_arc_direction_and_translation_preserve_radius_and_angles(self):
        _, layer = self.board_layer()
        for sweep in (-90, 90, -360, 360):
            with self.subTest(sweep=sweep):
                identity = self.arc(layer, sweep)
                original = self.shape(identity)
                self.assertAlmostEqual(original["sweep_angle"]["value_si"], math.radians(sweep))
                visible = next(item for item in self.canvas()["shapes"] if item["id"] == identity)
                self.assertAlmostEqual(visible["start_angle"], 30)
                self.assertAlmostEqual(visible["sweep_angle"], sweep)
                self.apply("translate", {"id": identity, "dx_mm": -2, "dy_mm": 3})
                moved = self.shape(identity)
                for key in ("radius", "width", "start_angle", "sweep_angle"):
                    self.assertEqual(moved[key], original[key])
                self.assertAlmostEqual(moved["center"][0]["value_si"], 0.010)
                self.assertAlmostEqual(moved["center"][1]["value_si"], 0.016)

    def test_coordinate_parameter_reference_resolves_but_direct_move_never_breaks_binding(self):
        _, layer = self.board_layer()
        identity = self.line(layer)
        parameter = str(uuid4())
        self.command("parameter.set", {"id": parameter, "name": "시작 x", "quantity": Quantity.from_value(7, "mm").to_dict()})
        shape = self.shape(identity)
        shape["start"][0] = {"parameter_id": parameter}
        self.command("geometry.set", {"geometry": shape})
        visible = self.canvas()["shapes"][0]
        self.assertEqual(visible["start"], [7.0, 2.0])
        self.assertFalse(visible["movable"])
        error = self.assert_rejected("translate", {"id": identity, "dx_mm": 1, "dy_mm": 1})
        self.assertEqual(error.code, "E_CONFLICT")
        self.assertEqual(self.shape(identity)["start"][0], {"parameter_id": parameter})
        self.command("parameter.set", {"id": parameter, "name": "시작 x", "quantity": Quantity.from_value(8, "mm").to_dict()})
        self.assertEqual(self.canvas()["shapes"][0]["start"], [8.0, 2.0])

    def test_width_and_radius_references_survive_translation_of_literal_center(self):
        _, layer = self.board_layer()
        identity = self.arc(layer)
        width, radius = str(uuid4()), str(uuid4())
        for parameter, name, value in ((width, "선폭", 0.7), (radius, "반지름", 6)):
            self.command("parameter.set", {"id": parameter, "name": name, "quantity": Quantity.from_value(value, "mm").to_dict()})
        shape = self.shape(identity)
        shape["width"], shape["radius"] = {"parameter_id": width}, {"parameter_id": radius}
        self.command("geometry.set", {"geometry": shape})
        self.assertTrue(self.canvas()["shapes"][0]["movable"])
        self.apply("translate", {"id": identity, "dx_mm": 1, "dy_mm": 0})
        moved = self.shape(identity)
        self.assertEqual(moved["width"], {"parameter_id": width})
        self.assertEqual(moved["radius"], {"parameter_id": radius})
        self.assertEqual(moved["center"][1], shape["center"][1])

    def test_missing_board_and_shape_dimensions_are_omitted_without_zero_invention(self):
        board, layer = self.board_layer()
        identity = self.line(layer)
        board_value = deepcopy(self.document()["board"])
        board_value["outline"]["width"] = Quantity.missing("length", "mm").to_dict()
        self.command("board.set", {"board": board_value})
        shape = self.shape(identity)
        shape["width"] = Quantity.missing("length", "mm").to_dict()
        self.command("geometry.set", {"geometry": shape})
        dto = self.canvas()
        self.assertIsNone(dto["board"]["width"])
        self.assertEqual(dto["board"]["height"], 60.0)
        self.assertEqual(dto["shapes"], [])
        self.assertEqual({item["id"] for item in dto["omissions"]}, {board, identity})
        self.assertTrue(all(item["message"] for item in dto["omissions"]))
        self.assertIsNone(self.shape(identity)["width"]["value_si"])

    def test_duplicate_create_ids_and_existing_board_never_overwrite(self):
        board, layer = self.board_layer()
        line = self.line(layer)
        attempts = [
            ("create_board", {"id": str(uuid4()), "width_mm": 100, "height_mm": 100}),
            ("create_layer", {"id": board, "name": "충돌"}),
            ("create_layer", {"id": self.project, "name": "충돌"}),
            ("create_line", {"id": line, "layer_id": layer, "width_mm": 1, "start": [5, 5], "end": [20, 5]}),
        ]
        for operation, values in attempts:
            with self.subTest(operation=operation):
                self.assertEqual(self.assert_rejected(operation, values).code, "E_CONFLICT")

    def test_invalid_inputs_geometry_and_noop_moves_are_atomic(self):
        _, layer = self.board_layer()
        identity = self.line(layer)
        for value in (True, "1", None, float("inf"), float("nan")):
            with self.subTest(value=value):
                self.assert_rejected("translate", {"id": identity, "dx_mm": value, "dy_mm": 0})
        attempts = [
            ("translate", {"id": identity, "dx_mm": 0, "dy_mm": 0}),
            ("create_line", {"id": str(uuid4()), "layer_id": layer, "width_mm": 0.5, "start": [2, 2], "end": [2, 2]}),
            ("create_line", {"id": str(uuid4()), "layer_id": layer, "width_mm": -1, "start": [2, 2], "end": [5, 2]}),
            ("create_line", {"id": str(uuid4()), "layer_id": layer, "width_mm": 1, "start": {"x": 0, "y": 0}, "end": [5, 2]}),
            ("rotate", {"id": identity}),
        ]
        for operation, values in attempts:
            with self.subTest(operation=operation):
                self.assert_rejected(operation, values)
        for sweep in (0, 361, -361):
            self.assert_rejected("create_arc", {"id": str(uuid4()), "layer_id": layer, "width_mm": 0.5, "center": [0, 0], "radius_mm": 5, "start_angle_deg": 0, "sweep_angle_deg": sweep})

    def test_stale_get_apply_and_read_size_limit_preserve_request_id_and_journal(self):
        stale = self.revision
        self.board_layer()
        request = {"jsonrpc": "2.0", "id": "2D 조회", "method": "canvas.get", "params": {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": {"expected_revision": stale}}}
        before = self.service.journal.read()
        response = handle_frame(json.dumps(request).encode(), self.service)
        self.assertEqual(response["id"], "2D 조회")
        self.assertEqual(response["error"]["data"]["domain_code"], "E_CONFLICT")
        request["params"]["input"]["expected_revision"] = self.revision
        with patch("rfad.application.canvas.MAX_DTO_BYTES", 64):
            limited = handle_frame(json.dumps(request).encode(), self.service)
        self.assertEqual(limited["id"], "2D 조회")
        self.assertEqual(limited["error"]["data"]["domain_code"], "E_RESOURCE")
        params = self.params("create_layer", {"id": str(uuid4()), "name": "stale"})
        params["input"]["expected_revision"] = stale
        with self.assertRaises(ProjectError) as caught:
            self.service.mutate("canvas.apply", params)
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        self.assertEqual(self.service.journal.read(), before)

    def test_referenced_geometry_cannot_be_removed_and_publish_failure_keeps_history(self):
        _, layer = self.board_layer()
        positive, reference = self.line(layer), self.arc(layer)
        port = {"id": str(uuid4()), "name": "시험 포트", "kind": "lumped", "positive_geometry_id": positive, "reference_geometry_id": reference,
                "resistance": Quantity.from_value(50, "ohm").to_dict(), "reference_plane": "시험 기준면", "polarity": 1, "direction": [0.0, 1.0, 0.0],
                "validity_hz": {"min": Quantity.from_value(2.4, "GHz").to_dict(), "max": Quantity.from_value(2.5, "GHz").to_dict()}}
        self.command("port.set", {"port": port})
        self.assert_rejected("remove", {"id": positive})
        before = self.service.journal.read()
        def fault(stage):
            if stage == "before_publish":
                raise OSError("2D 게시 실패 시험")
        self.service.journal.fault_hook = fault
        with self.assertRaises(ProjectError):
            self.apply("translate", {"id": positive, "dx_mm": 1, "dy_mm": 0})
        self.service.journal.fault_hook = None
        self.assertEqual(before, self.service.journal.read())

    def test_sub_ulp_translation_and_unrepresentable_display_never_succeed_as_zero(self):
        _, layer = self.board_layer()
        identity = self.line(layer)
        shape = self.shape(identity)
        shape["start"][0] = Quantity.from_value(1e21, "mm").to_dict()
        shape["end"][0] = Quantity.from_value(1e21 + 1e8, "mm").to_dict()
        self.command("geometry.set", {"geometry": shape})
        self.assertEqual(self.assert_rejected("translate", {"id": identity, "dx_mm": 1e-9, "dy_mm": 0}).code, "E_UNIT")
        shape = self.shape(identity)
        shape["width"] = Quantity(1e308, "length", "m", "user_entered").to_dict()
        self.command("geometry.set", {"geometry": shape})
        dto = self.canvas()
        self.assertEqual(dto["shapes"], [])
        self.assertEqual(dto["omissions"][0]["id"], identity)
        self.assertEqual(self.shape(identity)["width"]["value_si"], 1e308)


if __name__ == "__main__":
    unittest.main()
