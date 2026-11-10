"""! @brief 실제 stdio 프로세스에서 2D 편집의 개정, 이력과 불변 저장을 검증한다."""

import json
import math
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import test_project_process


class CanvasProcessTests(unittest.TestCase):
    """! @brief GUI와 같은 mm/deg DTO 요청으로 저장 및 실패 경계를 검증한다."""

    def setUp(self):
        """! @brief 한글 경로의 독립 작업 영역과 실제 서비스를 준비한다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="rfad 2D 프로세스 ")
        self.workspace = Path(self.temporary.name) / "한글 작업 영역"
        self.client = test_project_process.ProjectProcessTests()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.client.stop)
        self.client.start(self.workspace)
        capability = self.client.rpc("capabilities.get", self.client.params({}, mutation=False))
        self.client.epoch = capability["idempotency_policy"]["request_key_epoch"]
        self.assertEqual(capability["canvas_profile"]["profile"], "rfad.canvas/0.1")
        self.assertFalse(capability["canvas_profile"]["full_document_returned"])
        self.path = "projects/첫 원호 편집"
        created = self.client.finish(self.client.rpc("project.open", self.client.params({
            "open_mode": "create", "path": self.path, "name": "첫 원호 편집",
        })))
        self.project_id = created["project_id"]
        self.revision = created["revision_id"]

    def request(self, operation, values, *, revision=None):
        """! @brief 한 번의 사용자 편집을 하나의 명령과 멱등 키로 만든다."""
        return self.client.params({
            "expected_revision": self.revision if revision is None else revision,
            "command_id": str(uuid4()), "operation": operation, "values": values,
        }, project=self.project_id)

    def apply(self, operation, values):
        """! @brief 서비스가 게시한 새 개정만 다음 요청의 기준으로 사용한다."""
        response = self.client.rpc("canvas.apply", self.request(operation, values))
        self.assertNotEqual(response["new_revision"], self.revision)
        self.revision = response["new_revision"]
        return response

    def view(self):
        """! @brief 원본 전체 대신 현재 개정의 표시 DTO만 가져온다."""
        result = self.client.rpc("canvas.get", self.client.params({
            "expected_revision": self.revision,
        }, project=self.project_id, mutation=False))
        self.assertEqual(result["profile"], "rfad.canvas/0.1")
        self.assertEqual(result["revision_id"], self.revision)
        self.assertEqual((result["unit"], result["angle_unit"]), ("mm", "deg"))
        self.assertNotIn("document", result)
        return result

    def editor_state(self):
        """! @brief 다른 화면에서도 같은 개정과 이력을 보는지 조회한다."""
        return self.client.rpc("editor.get", self.client.params({
            "expected_revision": self.revision,
        }, project=self.project_id, mutation=False))

    def edit(self, kind, identifier, values):
        """! @brief 속성 화면의 참조와 미정값 변경을 2D 화면에 반영한다."""
        response = self.client.rpc("editor.apply", self.client.params({
            "expected_revision": self.revision, "command_id": str(uuid4()),
            "selection": {"kind": kind, "id": identifier}, "values": values,
        }, project=self.project_id))
        self.revision = response["new_revision"]
        return response

    def history(self, method):
        """! @brief 취소 및 재실행도 영속 명령으로 실행하고 재전송용 요청을 남긴다."""
        params = self.client.params({
            "expected_revision": self.revision, "command_id": str(uuid4()),
        }, project=self.project_id)
        response = self.client.rpc(method, params)
        self.assertNotEqual(response["new_revision"], self.revision)
        self.revision = response["new_revision"]
        return params, response

    def restart(self):
        """! @brief 강제 프로세스 종료 후 같은 저장소와 epoch를 복구한다."""
        self.client.stop(kill=True)
        self.client.start(self.workspace)
        capability = self.client.rpc("capabilities.get", self.client.params({}, mutation=False))
        self.assertEqual(capability["idempotency_policy"]["request_key_epoch"], self.client.epoch)

    def reject(self, method, params, code):
        """! @brief 오류 응답도 실제 전송 경계에서 ID와 도메인 코드를 검사한다."""
        request_id = "거절 검사-" + str(uuid4())
        request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self.client.process.stdin.write(json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n")
        self.client.process.stdin.flush()
        line = self.client.responses.get(timeout=8)
        self.assertIsNotNone(line, "service exited before error response")
        response = json.loads(line)
        self.assertEqual(response["id"], request_id)
        self.assertNotIn("result", response)
        self.assertEqual(response["error"]["data"]["domain_code"], code, response)

    def create_scene(self):
        """! @brief 열린 CW 원호와 선분을 미정 적층을 가진 사각 기판 위에 만든다."""
        board, layer, line, arc = (str(uuid4()) for _ in range(4))
        self.apply("create_board", {"id": board, "width_mm": 40, "height_mm": 20})
        self.apply("create_layer", {"id": layer, "name": "상단 도체"})
        self.apply("create_line", {
            "id": line, "layer_id": layer, "width_mm": 0.8,
            "start": [2.5, 4], "end": [10, 4],
        })
        self.apply("create_arc", {
            "id": arc, "layer_id": layer, "width_mm": 1,
            "center": [20, 10], "radius_mm": 8,
            "start_angle_deg": 15, "sweep_angle_deg": -270,
        })
        return board, layer, line, arc

    def shapes(self, scene):
        """! @brief 표시 순서에 의존하지 않고 도메인 UUID로 형상을 비교한다."""
        return {shape["id"]: shape for shape in scene["shapes"]}

    def test_signed_arc_move_history_save_and_snapshot_survive_process_restart(self):
        """! @brief 음수 호각과 독립 치수를 저장, 재실행 및 재시작에서 보존한다."""
        board, layer, line, arc = self.create_scene()
        initial = self.view()
        self.assertEqual(initial["board"], {"id": board, "width": 40, "height": 20})
        self.assertEqual(initial["layers"], [{"id": layer, "label": "상단 도체", "role": "conductor"}])
        self.assertEqual(initial["omissions"], [])
        initial_shapes = self.shapes(initial)
        self.assertEqual(initial_shapes[line]["start"], [2.5, 4])
        self.assertEqual(initial_shapes[arc]["kind"], "arc_path")
        self.assertAlmostEqual(initial_shapes[arc]["start_angle"], 15)
        self.assertAlmostEqual(initial_shapes[arc]["sweep_angle"], -270)
        self.apply("translate", {"id": arc, "dx_mm": -2.5, "dy_mm": 1.25})
        before_line_move = self.shapes(self.view())
        self.assertEqual(before_line_move[arc]["center"], [17.5, 11.25])
        self.apply("translate", {"id": line, "dx_mm": 1.25, "dy_mm": -0.5})
        moved = self.shapes(self.view())
        self.assertEqual(moved[line]["start"], [3.75, 3.5])
        self.assertEqual(moved[line]["end"], [11.25, 3.5])
        self.history("project.undo")
        self.assertEqual(self.shapes(self.view()), before_line_move)
        redo_request, redo_result = self.history("project.redo")
        self.assertEqual(self.shapes(self.view()), moved)
        saved = self.client.finish(self.client.rpc("project.save", self.client.params({
            "expected_revision": self.revision,
        }, project=self.project_id)))
        snapshot = self.client.finish(self.client.rpc("snapshot.create", self.client.params({
            "expected_revision": self.revision, "description": "열린 원호의 불변 기준",
        }, project=self.project_id)))
        frozen_path = self.workspace / snapshot["artifact"]["uri"]
        frozen = frozen_path.read_bytes()
        source = json.loads(frozen)
        source_layer = source["stackup"][0]
        self.assertIsNone(source_layer["material_id"])
        for key in ("z_min", "thickness"):
            self.assertIsNone(source_layer[key]["value_si"])
            self.assertEqual(source_layer[key]["status"], "missing")
        source_arc = next(shape for shape in source["geometry"] if shape["id"] == arc)
        self.assertAlmostEqual(source_arc["radius"]["value_si"], 0.008)
        self.assertAlmostEqual(source_arc["sweep_angle"]["value_si"], -1.5 * math.pi)
        scene = self.view()
        self.restart()
        self.assertEqual(self.view(), scene)
        self.assertEqual(self.client.rpc("project.redo", redo_request), redo_result)
        self.assertEqual(self.view(), scene)
        reopened = self.client.finish(self.client.rpc("project.open", self.client.params({
            "open_mode": "recover", "path": self.path,
        })))
        self.assertEqual(reopened["revision_id"], saved["saved_revision"])
        self.assertEqual(reopened["document"], source)
        self.apply("remove", {"id": arc})
        self.assertNotIn(arc, self.shapes(self.view()))
        self.assertEqual(frozen_path.read_bytes(), frozen)

    def test_invalid_and_stale_requests_leave_scene_history_and_saved_revision_unchanged(self):
        """! @brief 실패한 입력은 형상, 이력, 저장 기준점에 부분 적용되지 않는다."""
        board, layer, line, arc = self.create_scene()
        old_revision = self.revision
        self.apply("translate", {"id": line, "dx_mm": 1, "dy_mm": 0})
        before, history = self.view(), self.editor_state()
        invalid = [
            ("create_board", {"id": str(uuid4()), "width_mm": 80, "height_mm": 40}, "E_CONFLICT"),
            ("create_line", {"id": line, "layer_id": layer, "width_mm": 1, "start": [0, 0], "end": [1, 1]}, "E_CONFLICT"),
            ("create_line", {"id": str(uuid4()), "layer_id": layer, "width_mm": -1, "start": [0, 0], "end": [1, 1]}, "E_SCHEMA"),
            ("create_line", {"id": str(uuid4()), "layer_id": layer, "width_mm": 1, "start": [1, 1], "end": [1, 1]}, "E_GEOMETRY"),
            ("create_arc", {"id": str(uuid4()), "layer_id": layer, "width_mm": 1, "center": [20, 10], "radius_mm": 8, "start_angle_deg": 15, "sweep_angle_deg": 0}, "E_GEOMETRY"),
            ("create_line", {"id": str(uuid4()), "layer_id": layer, "width_mm": 1, "start": [True, 0], "end": [1, 1]}, "E_UNIT"),
            ("create_line", {"id": str(uuid4()), "layer_id": layer, "width_mm": 1, "start": ["0", 0], "end": [1, 1]}, "E_UNIT"),
            ("translate", {"id": arc, "dx_mm": 0, "dy_mm": 0}, "E_CONFLICT"),
            ("translate", {"id": arc, "dx_mm": 1, "dy_mm": 0, "extra": 1}, "E_SCHEMA"),
            ("remove", {"id": str(uuid4())}, "E_CONFLICT"),
            ("rotate", {"id": arc}, "E_UNSUPPORTED"),
        ]
        for operation, values, code in invalid:
            with self.subTest(operation=operation, values=values):
                self.reject("canvas.apply", self.request(operation, values), code)
                self.assertEqual(self.view(), before)
                self.assertEqual(self.editor_state(), history)
        self.reject("canvas.apply", self.request("remove", {"id": line}, revision=old_revision), "E_CONFLICT")
        self.reject("canvas.get", self.client.params({
            "expected_revision": old_revision,
        }, project=self.project_id, mutation=False), "E_CONFLICT")
        self.assertEqual(self.view(), before)
        self.assertEqual(self.editor_state(), history)
        self.restart()
        self.assertEqual(self.view(), before)
        self.assertEqual(self.editor_state(), history)

    def test_delete_undo_restarts_with_redo_and_new_edit_replaces_redo_branch(self):
        """! @brief 삭제 취소를 재시작 후 재실행하고 새 편집이 옛 분기를 닫는지 확인한다."""
        board, layer, line, arc = self.create_scene()
        original_shapes = self.shapes(self.view())
        self.apply("remove", {"id": line})
        self.assertNotIn(line, self.shapes(self.view()))
        self.history("project.undo")
        self.assertEqual(self.shapes(self.view()), original_shapes)
        self.restart()
        self.assertTrue(self.editor_state()["history"]["can_redo"])
        self.history("project.redo")
        self.assertNotIn(line, self.shapes(self.view()))
        self.history("project.undo")
        self.apply("translate", {"id": arc, "dx_mm": 0, "dy_mm": 1})
        before = self.view()
        self.assertIn(line, self.shapes(before))
        self.assertFalse(self.editor_state()["history"]["can_redo"])
        self.reject("project.redo", self.client.params({
            "expected_revision": self.revision, "command_id": str(uuid4()),
        }, project=self.project_id), "E_CONFLICT")
        self.assertEqual(self.view(), before)

    def test_parameter_coordinates_resolve_and_missing_dimensions_are_explicit(self):
        """! @brief 참조 좌표는 재평가하고 미정 형상은 0으로 그리지 않고 생략한다."""
        board, layer, line, arc = self.create_scene()
        center_x = str(uuid4())
        self.edit("new_parameter", center_x, {
            "name": "원호 중심 x", "mode": "value", "value": "0.018", "unit": "m", "dimension": "length",
        })
        self.edit("geometry", arc, {"center.0.mode": "parameter", "center.0.parameter_id": center_x})
        shape = self.shapes(self.view())[arc]
        self.assertAlmostEqual(shape["center"][0], 18)
        self.assertFalse(shape["movable"])
        self.reject("canvas.apply", self.request("translate", {"id": arc, "dx_mm": 1, "dy_mm": 0}), "E_CONFLICT")
        self.edit("parameter", center_x, {"value": "0.019"})
        self.assertAlmostEqual(self.shapes(self.view())[arc]["center"][0], 19)
        self.edit("geometry", arc, {"width.mode": "missing"})
        scene = self.view()
        self.assertNotIn(arc, self.shapes(scene))
        self.assertIn(line, self.shapes(scene))
        self.assertTrue(any(item["id"] == arc and item["message"] for item in scene["omissions"]))
        self.history("project.undo")
        self.assertAlmostEqual(self.shapes(self.view())[arc]["width"], 1)
        self.edit("board", board, {"outline.width.mode": "missing"})
        scene = self.view()
        self.assertIsNone(scene["board"]["width"])
        self.assertEqual(scene["board"]["height"], 20)
        self.assertTrue(any(item["id"] == board and item["message"] for item in scene["omissions"]))
        self.restart()
        self.assertEqual(self.view(), scene)


if __name__ == "__main__":
    unittest.main()
