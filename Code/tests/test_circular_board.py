"""! @brief 원형 PCB의 저장/편집/투영과 실제 원통 STEP 및 도체 경계를 검증한다."""

from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.adapters.cad.native import build_package, read_step
from rfad.application.cad import build_cad_input
from rfad.application.canvas import build_canvas_dto, canvas_command
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.editor import edit_command, fields_for
from rfad.application.projects import ProjectService
from rfad.domain.design import apply_design_command, preflight_design
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command, new_project, validate_project
from test_cad_projection import cad_fixture, snapshot_for
from test_cad_native import fixture as native_fixture, identity as native_id
from test_design import build_design, identity, quantity, unknown


def circle_document():
    """! @brief 미정 RF 물성은 유지하면서 외곽만 명시적 원으로 바꾼다."""
    document = cad_fixture()
    board = deepcopy(document["board"])
    board["outline"] = {"kind": "circle", "center": [quantity(3.0, "mm"), quantity(-2.0, "mm")], "radius": quantity(30.0, "mm")}
    apply_design_command(document, "board.set", {"board": board})
    return document


class CircularBoardTests(unittest.TestCase):
    """! @brief 원형 외곽을 기하와 독립 저장하며 기존 직사각 문서도 보존한다."""

    def test_circle_creation_roundtrip_and_dto_do_not_infer_ground(self):
        """! @brief 중심/반지름을 SI로 저장하고 원형 접지나 물성을 자동 생성하지 않는다."""
        document = new_project("원형 PCB")
        command = canvas_command(document, "create_circular_board", {"id": str(uuid4()), "center_x_mm": -4.0, "center_y_mm": 9.0, "radius_mm": 20.0})
        result, _, _, _ = apply_command(document, {"command_id": str(uuid4()), **command}, document["revision_id"])
        self.assertEqual(result["board"]["outline"]["center"][0]["value_si"], -0.004)
        self.assertEqual(result["board"]["outline"]["radius"]["value_si"], 0.020)
        dto = build_canvas_dto(result)
        self.assertEqual(dto["board"], {"id": result["board"]["id"], "kind": "circle", "center": [-4.0, 9.0], "radius": 20.0})
        self.assertEqual(result["materials"], [])
        self.assertEqual(result["geometry"], [])
        restored = json.loads(canonical_bytes(result))
        validate_project(restored)
        self.assertEqual(canonical_hash(restored), canonical_hash(result))
        self.assertIsNone(document["board"])

    def test_unknown_center_and_radius_are_saved_and_reported(self):
        """! @brief 중심/반지름 미정은 0 원으로 표시하지 않고 CAD 준비에서 차단한다."""
        document = circle_document()
        document["board"]["outline"]["center"][0] = unknown("length", "mm")
        document["board"]["outline"]["radius"] = unknown("length", "mm")
        validate_project(document)
        dto = build_canvas_dto(document)
        self.assertIsNone(dto["board"]["center"])
        self.assertIsNone(dto["board"]["radius"])
        self.assertEqual(len(dto["omissions"]), 2)
        fields = {item["field_paths"][0] for item in preflight_design(document, "geometry")}
        self.assertIn("board.outline.radius", fields)
        self.assertIn("board.outline.center[0]", fields)
        with self.assertRaises(ProjectError) as caught:
            build_cad_input(document, snapshot_for(document))
        self.assertEqual(caught.exception.code, "E_GEOMETRY")

    def test_circle_schema_and_positive_radius_are_atomic(self):
        """! @brief 누락/추가/0 반지름은 저장하지 않고 기존 기판을 보존한다."""
        document = circle_document()
        original = deepcopy(document)
        malformed = [
            {"kind": "circle", "center": [quantity(0, "mm")], "radius": quantity(1, "mm")},
            {"kind": "circle", "center": [quantity(0, "mm"), quantity(0, "mm")], "radius": quantity(0, "mm")},
            {"kind": "circle", "center": [quantity(0, "mm"), quantity(0, "mm")], "radius": quantity(-1, "mm")},
            {"kind": "circle", "center": [quantity(0, "mm"), quantity(0, "mm")], "radius": quantity(1, "mm"), "width": quantity(2, "mm")},
        ]
        for outline in malformed:
            with self.subTest(outline=outline), self.assertRaises(ProjectError):
                apply_design_command(document, "board.set", {"board": {**document["board"], "outline": outline}})
            self.assertEqual(document, original)

    def test_cad_projection_preserves_circle_and_source_binding(self):
        """! @brief 원의 중심/반지름과 원본 참조를 별도로 유지하며 사각형으로 대체하지 않는다."""
        document = circle_document()
        parameter = identity(50)
        document, _, _, _ = apply_command(document, {"command_id": str(uuid4()), "type": "parameter.set",
            "payload": {"id": parameter, "name": "기판 반지름", "quantity": quantity(30, "mm")}}, document["revision_id"])
        document["board"]["outline"]["radius"] = {"parameter_id": parameter}
        validate_project(document)
        original = deepcopy(document)
        projection = build_cad_input(document, snapshot_for(document))
        self.assertEqual(projection["board"], {"id": document["board"]["id"], "kind": "circle", "center_mm": [3.0, -2.0], "radius_mm": 30.0})
        self.assertEqual(projection["source_semantics"], original)
        self.assertEqual(document, original)
        selected = {"kind": "board", "id": document["board"]["id"]}
        self.assertEqual(next(f for f in fields_for(document, selected) if f["key"] == "outline.radius.mode")["value"], "parameter")
        command = edit_command(document, selected, {"outline.center.1.value": "7"})
        apply_design_command(document, command["type"], command["payload"])
        self.assertEqual(document["board"]["outline"]["radius"], {"parameter_id": parameter})
        self.assertEqual(document["board"]["outline"]["center"][1]["value_si"], 0.007)

    def test_circle_display_and_cad_bounds_fail_explicitly(self):
        """! @brief 원형 외곽의 극단 좌표/반지름 합은 각 표시/커널 범위에서 차단한다."""
        document = circle_document()
        document["board"]["outline"]["center"] = [quantity(1e9, "mm"), quantity(0, "mm")]
        dto = build_canvas_dto(document)
        self.assertIsNone(dto["board"]["radius"])
        self.assertEqual(len(dto["omissions"]), 1)
        with self.assertRaises(ProjectError):
            build_cad_input(document, snapshot_for(document))
        document["board"]["outline"]["center"] = [quantity(1e6, "mm"), quantity(0, "mm")]
        with self.assertRaises(ProjectError) as caught:
            build_cad_input(document, snapshot_for(document))
        self.assertEqual(caught.exception.details["field_path"], "board.outline")

    def test_rectangle_still_uses_existing_schema_and_dto(self):
        """! @brief 직사각 기존 문서는 새 외곽 필드를 강제하지 않는다."""
        document = cad_fixture()
        dto = build_canvas_dto(document)
        self.assertEqual(dto["board"], {"id": document["board"]["id"], "width": 60.0, "height": 40.0})
        self.assertEqual(build_cad_input(document, snapshot_for(document))["board"], {"id": document["board"]["id"], "width_mm": 60.0, "height_mm": 40.0})

    def test_optional_port_box_preserves_units_unknowns_and_legacy_ports(self):
        """! @brief 급전 위치는 명시한 3D 수량만 보존하며 기존 위치 없는 포트를 추정하지 않는다."""
        document = build_design()
        validate_project(document)
        port = deepcopy(document["ports"][0])
        port["excitation_box"] = {"start": [quantity(2, "mm"), quantity(1.25, "mm"), unknown("length", "mm")],
                                  "stop": [quantity(2, "mm"), quantity(2.75, "mm"), unknown("length", "mm")]}
        apply_design_command(document, "port.set", {"port": port})
        fields = fields_for(document, {"kind": "port", "id": port["id"]})
        self.assertEqual(next(f for f in fields if f["key"] == "excitation_box.start.2.mode")["value"], "missing")
        self.assertEqual(document["ports"][0]["excitation_box"], port["excitation_box"])
        original = deepcopy(document)
        for box in ({"start": [quantity(0, "mm")], "stop": [quantity(1, "mm")]},
                    {"start": [quantity(0, "mm")] * 3, "stop": [quantity(0, "mm")] * 3}, None):
            with self.subTest(box=box), self.assertRaises(ProjectError):
                apply_design_command(document, "port.set", {"port": {**port, "excitation_box": box}})
            self.assertEqual(document, original)

    def test_service_history_snapshot_and_restart_keep_circle(self):
        """! @brief 원형 생성의 undo/redo와 봉인 스냅샷이 재시작 뒤에도 같은 원을 유지한다."""
        with TemporaryDirectory(prefix="TraceWave 원형 ") as directory:
            workspace = Path(directory)
            with ProjectService(workspace, auto_run=False) as service:
                def request(data, context):
                    """! @brief 현재 서비스 epoch와 독립 접수 키를 사용한다."""
                    return {"contract_version": "rfad.api/2.0", "context": context, "input": data,
                            "request_key": str(uuid4()), "request_key_epoch": service.policy()["request_key_epoch"]}
                task = service.mutate("project.open", request({"path": "projects/circle", "open_mode": "create", "name": "원형 시험"}, {}))
                service.run_next()
                state = service.journal.read()
                document = state["jobs"][task["job_id"]]["events"][-1]["operation_result"]["document"]
                context = {"project_id": document["project_id"]}
                def edit(method, payload):
                    """! @brief 현재 revision에서 성공한 명령의 다음 revision만 진행한다."""
                    nonlocal document
                    response = service.mutate(method, request({"expected_revision": document["revision_id"], "command_id": str(uuid4()), **payload}, context))
                    document = service._load(service.journal.read()["projects"][context["project_id"]])
                    return response
                edit("canvas.apply", {"operation": "create_circular_board", "values": {"id": str(uuid4()), "center_x_mm": 1, "center_y_mm": -2, "radius_mm": 25}})
                board = deepcopy(document["board"])
                edit("project.undo", {})
                self.assertIsNone(document["board"])
                edit("project.redo", {})
                self.assertEqual(document["board"], board)
                task = service.mutate("snapshot.create", request({"expected_revision": document["revision_id"]}, context))
                service.run_next()
                snapshot = service.journal.read()["jobs"][task["job_id"]]["events"][-1]["operation_result"]
                sealed = service.journal.read_artifact(snapshot["artifact"])
                edited_board = deepcopy(board)
                edited_board["outline"]["radius"] = quantity(26, "mm")
                edit("project.apply_command", {"type": "board.set", "payload": {"board": edited_board}})
                self.assertEqual(service.journal.read_artifact(snapshot["artifact"]), sealed)
            with ProjectService(workspace, auto_run=False) as service:
                restored = service._load(service.journal.read()["projects"][context["project_id"]])
                self.assertEqual(restored["board"]["outline"]["radius"], quantity(26, "mm"))
                self.assertEqual(json.loads(service.journal.read_artifact(snapshot["artifact"]))["board"], board)


@unittest.skipUnless(importlib.util.find_spec("cadquery") is not None, "격리 CAD Python 환경이 필요합니다.")
class CircularBoardNativeTests(unittest.TestCase):
    """! @brief 사각 bbox 검사로 대신할 수 없는 정확 원통과 원 외부 도체를 검사한다."""

    def source(self):
        """! @brief 중심을 이동한 원형 기판과 내부 원호를 실제 native 입력으로 만든다."""
        source = native_fixture()
        source["board"] = {"id": native_id("board"), "kind": "circle", "center_mm": [2.0, -3.0], "radius_mm": 20.0}
        arc = source["shapes"][1]
        arc.update(center_mm=[2.0, -3.0], radius_mm=12.0, start_angle_deg=30.0, sweep_angle_deg=250.0)
        source["shapes"] = [arc]
        return source

    def test_circle_step_reimport_keeps_analytic_cylinder_and_display_mesh(self):
        """! @brief STEP 재입력의 부피/중심/단면과 표시 mesh가 원형 외곽을 따른다."""
        source = self.source()
        original = deepcopy(source)
        with TemporaryDirectory(prefix="TraceWave 원형 STEP ") as directory:
            output = Path(directory)
            result = build_package(source, output)
            imported = read_step(output / "model.step")
            board = imported["dielectric_" + native_id("dielectric")]
            self.assertEqual(result["solid_count"], 2)
            self.assertAlmostEqual(board["volume_mm3"], math.pi * 400.0, places=6)
            self.assertAlmostEqual(board["section_area_mm2"], math.pi * 400.0, places=6)
            for actual, expected in zip(board["center_mm"], [2.0, -3.0, 0.5]):
                self.assertAlmostEqual(actual, expected, places=7)
            for actual, expected in zip(board["bbox_mm"], [-18.0, -23.0, 0.0, 22.0, 17.0, 1.0]):
                self.assertAlmostEqual(actual, expected, places=6)
            mesh = json.loads((output / "mesh.json").read_bytes())
            substrate = next(body for body in mesh["bodies"] if body["role"] == "dielectric")
            self.assertTrue(all(math.hypot(point[0] - 2, point[1] + 3) <= 20 + 1e-6 for point in substrate["vertices"]))
            self.assertEqual(source, original)

    def test_round_cap_and_arc_outside_circle_are_not_clipped(self):
        """! @brief 사각 bbox 안에 있지만 원 밖인 cap/원호를 자르지 않고 출력 차단한다."""
        for kind in ("line_path", "arc_path"):
            with self.subTest(kind=kind), TemporaryDirectory(prefix="TraceWave 원형 경계 ") as directory:
                source = self.source()
                source["board"]["center_mm"] = [0.0, 0.0]
                shape = source["shapes"][0]
                if kind == "line_path":
                    shape.update(kind=kind, start_mm=[13.0, 13.0], end_mm=[13.0, 14.0], width_mm=2.0)
                else:
                    shape.update(center_mm=[5.0, 5.0], radius_mm=13.0, start_angle_deg=0.0, sweep_angle_deg=90.0, width_mm=0.5)
                with self.assertRaises(ProjectError) as caught:
                    build_package(source, Path(directory))
                self.assertEqual(caught.exception.code, "E_GEOMETRY")
                self.assertIn("외곽", caught.exception.message)
                self.assertFalse((Path(directory) / "model.step").exists())
