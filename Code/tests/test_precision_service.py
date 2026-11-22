"""! @brief 정밀 편집 후보와 원자 이력 및 출처의 저장 복원 계약을 검증한다."""

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.adapters.planar_backend import runtime
from rfad.application import precision_service
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from rfad.domain.precision_command import EXTENSION_KEY, apply_precision_command, record_hash, validate_precision_origins
from rfad.domain.units import Quantity


class PrecisionServiceTests(unittest.TestCase):
    """! @brief 실제 journal과 프로젝트 명령을 사용해 후보/확정 경계를 검사한다."""

    def setUp(self):
        """! @brief 제작 물성을 정하지 않은 작은 설계를 만든다."""
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "정밀 편집"
        self.service = ProjectService(self.workspace, auto_run=False)
        task = self.service.mutate("project.open", self.request({"path": "projects/precision", "open_mode": "create", "name": "정밀 편집"}, {}))
        self.service.run_next()
        event = self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})["events"][-1]
        self.project = event["operation_result"]["project_id"]
        self.revision = event["operation_result"]["revision_id"]
        self.layer = str(uuid4())
        self.canvas("create_board", {"id": str(uuid4()), "width_mm": 80, "height_mm": 80})
        self.canvas("create_layer", {"id": self.layer, "name": "도체 1"})

    def tearDown(self):
        """! @brief 소유한 서비스와 임시 자료만 정리한다."""
        self.service.close()
        self.temp.cleanup()

    def request(self, data, context=None):
        """! @brief 발급 epoch와 개별 요청 식별자를 사용하는 변경 요청을 만든다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project} if context is None else context,
                "input": data, "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def read_request(self, data):
        """! @brief 읽기에 영수증 필드를 넣지 않는다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": data}

    def document(self):
        """! @brief 검사 목적으로 현재 불변 원본을 읽는다."""
        return self.service._load(self.service.journal.read()["projects"][self.project])

    def shape(self, identity):
        """! @brief UUID로 현재 객체를 찾는다."""
        return next(row for row in self.document()["geometry"] if row["id"] == identity)

    def canvas(self, operation, values):
        """! @brief 기존 직접 입력 경로로 시험 형상을 작성한다."""
        result = self.service.mutate("canvas.apply", self.request({"expected_revision": self.revision, "command_id": str(uuid4()),
                                                                 "operation": operation, "values": values}))
        self.revision = result["new_revision"]
        return result

    def command(self, kind, payload):
        """! @brief 기존 의미 명령으로 출처나 참조 fixture를 구성한다."""
        result = self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()),
                                                                          "type": kind, "payload": payload}))
        self.revision = result["new_revision"]
        return result

    def line(self):
        """! @brief 길이 5 mm의 방향이 있는 선을 만든다."""
        identity = str(uuid4())
        self.canvas("create_line", {"id": identity, "layer_id": self.layer, "width_mm": 0.4, "start": [1, 2], "end": [4, 6]})
        return identity

    def arc(self, sweep=-130):
        """! @brief 열린 signed sweep 원호를 만든다."""
        identity = str(uuid4())
        self.canvas("create_arc", {"id": identity, "layer_id": self.layer, "width_mm": 1.2, "center": [10, 12],
                                   "radius_mm": 20, "start_angle_deg": 25, "sweep_angle_deg": sweep})
        return identity

    def region(self, outer, holes=None):
        """! @brief 직선 외곽과 명시 구멍을 가진 도체 영역을 만든다."""
        identity = str(uuid4())
        self.canvas("create_polygon", {"id": identity, "layer_id": self.layer, "outer": outer, "holes": holes or []})
        return identity

    def get(self, identities):
        """! @brief 표시 조회가 journal을 변경하지 않는지 함께 확인한다."""
        before = self.service.journal.read()
        result = precision_service.read(self.service, "precision.get", self.read_request({"expected_revision": self.revision, "selection_ids": identities}))
        self.assertEqual(before, self.service.journal.read())
        return result

    def preview(self, identities, operation, values):
        """! @brief 후보 생성은 이력과 영수증을 만들지 않아야 한다."""
        data = {"expected_revision": self.revision, "selection_ids": identities, "operation": operation, "values": values}
        before = self.service.journal.read()
        result = precision_service.read(self.service, "precision.preview", self.read_request(data))
        self.assertEqual(before, self.service.journal.read())
        return result, data

    def apply(self, identities, operation, values):
        """! @brief 실제 검토 해시와 같은 입력만 확정한다."""
        preview, data = self.preview(identities, operation, values)
        self.assertTrue(preview["can_apply"], preview["notices"])
        request = self.request({**data, "command_id": str(uuid4()), "review_hash": preview["review_hash"], "reason": "사용자 정밀 편집 시험"})
        result = self.service.mutate("precision.apply", request)
        self.revision = result["new_revision"]
        return result, request

    def history(self, action):
        """! @brief 영속 명령/역명령을 통해 새로운 개정으로 복원한다."""
        result = self.service.mutate("project." + action, self.request({"expected_revision": self.revision, "command_id": str(uuid4())}))
        self.revision = result["new_revision"]
        return result

    def require_planar(self):
        """! @brief 선택 엔진이 없는 환경에서는 계산 사례만 조건부 제외한다."""
        if not runtime()[1]["available"]:
            self.skipTest("고정 Shapely/GEOS 선택 엔진 필요")

    def test_dimensions_are_associative_and_queries_and_capability_are_read_only(self):
        line = self.line()
        rows = {row["key"]: row for row in self.get([line])["dimensions"]}
        self.assertEqual(rows["line.length"]["value"], 5)
        self.assertEqual(rows["line.length"]["anchors_mm"], [[1, 2], [4, 6]])
        self.apply([line], "dimension_set", {"dimension_key": "line.length", "value": 10000, "unit": "um"})
        rows = {row["key"]: row for row in self.get([line])["dimensions"]}
        self.assertAlmostEqual(rows["line.length"]["value"], 10)
        self.assertEqual(rows["line.length"]["anchors_mm"][0], [1, 2])
        request = {"jsonrpc": "2.0", "id": 1, "method": "capabilities.get", "params": {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}}
        capability = handle_frame(json.dumps(request).encode(), self.service)["result"]
        self.assertTrue(capability["precision_profile"]["preview_required"])
        self.assertFalse(capability["precision_profile"]["geometry_solver_supported"])
        self.assertNotIn("geometry.precision.apply", capability["project_profile"]["commands"])

    def test_capability_inspects_installation_without_loading_native_planar_engine(self):
        """! @brief 기초 기능 조회는 설치 메타데이터와 실제 native 사용 가능 상태를 구분한다."""
        request = {"jsonrpc": "2.0", "id": 1, "method": "capabilities.get", "params": {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}}
        with patch("rfad.application.precision_service.runtime", side_effect=AssertionError("일반 조회에서 native 엔진을 읽음")), \
             patch("rfad.adapters.planar_backend.metadata.version", return_value="2.2.0"):
            engine = handle_frame(json.dumps(request).encode(), self.service)["result"]["precision_profile"]["planar_engine"]
        self.assertTrue(engine["installation_detected"])
        self.assertTrue(engine["version_matches"])
        self.assertFalse(engine["runtime_checked"])
        self.assertIsNone(engine["available"])
        self.assertIsNone(engine["geos_version"])
        self.assertEqual(engine["required_geos_version"], "3.14.1")

    def test_pattern_copies_and_arc_offset_preserve_source_and_reopen(self):
        """! @brief 직선과 원형 피치 및 반경을 독립 수치, 원본과 영속 이력으로 대조한다."""
        arc, line = self.arc(), self.line()
        originals = {identity: self.shape(identity) for identity in (arc, line)}
        values = {"count": 3, "dx_mm": 4, "dy_mm": -1}
        review, _ = self.preview([arc, line], "linear_pattern", values)
        self.assertEqual([row["action"] for row in review["changes"]], ["create"] * 4)
        result, _ = self.apply([arc, line], "linear_pattern", values)
        self.assertEqual(result["selection_ids"], review["result_ids"])
        for copy_id, position in zip(result["selection_ids"][2::2], ((14, 11), (18, 10))):
            item = self.shape(copy_id)
            centers = [Quantity(**value).as_unit("mm") for value in item["center"]]
            for value, target in zip(centers, position):
                self.assertAlmostEqual(value, target)
            self.assertEqual(item["radius"], originals[arc]["radius"])
        self.assertEqual({identity: self.shape(identity) for identity in (arc, line)}, originals)
        generated = self.document()["geometry"]
        self.history("undo")
        self.assertEqual(len(self.document()["geometry"]), 2)
        self.history("redo")
        self.assertEqual(self.document()["geometry"], generated)
        circle, _ = self.apply([line], "circular_pattern", {"count": 4, "pivot_x_mm": 5,
                                                           "pivot_y_mm": 5, "step_deg": 90})
        one = self.shape(circle["selection_ids"][1])
        self.assertEqual([Quantity(**value).as_unit("mm") for value in one["start"]], [8, 1])
        disabled, _ = self.preview([line], "circular_pattern", {"count": 5, "pivot_x_mm": 5,
                                                               "pivot_y_mm": 5, "step_deg": 90})
        self.assertFalse(disabled["can_apply"])
        self.apply([arc], "arc_offset", {"distance_mm": 2})
        self.assertAlmostEqual(Quantity(**self.shape(arc)["radius"]).as_unit("mm"), 22)
        for key in ("center", "start_angle", "sweep_angle", "width", "layer_id"):
            self.assertEqual(self.shape(arc)[key], originals[arc][key])
        final = self.document()
        save = self.service.mutate("project.save", self.request({"expected_revision": self.revision}))
        self.service.run_next()
        self.assertEqual(self.service.status({"contract_version": "rfad.api/2.0", "context": {},
                    "input": {"job_id": save["job_id"]}})["state"], "completed")
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        self.assertEqual(self.document(), final)

    def test_ifa_branch_and_complete_pth_pattern_preserve_connections(self):
        """! @brief IFA 급전과 PTH의 패드 ID가 복사 뒤에도 올바른 원본을 참조하는지 검사한다."""
        from test_cad_worker_process import register_fixture
        from test_pcb_ifa import ifa_document, via_document

        for fixture in (ifa_document, via_document):
            with self.subTest(fixture=fixture.__name__):
                source, _ = register_fixture(self.service, fixture())
                self.project, self.revision = source["project_id"], source["revision_id"]
                if fixture is ifa_document:
                    ids = [next(row["id"] for row in source["geometry"] if row["role"] == "radiator")]
                else:
                    via = next(row for row in source["geometry"] if row["kind"] == "via")
                    values = {"count": 2, "dx_mm": 4, "dy_mm": 2}
                    preview, _ = self.preview([via["id"]], "linear_pattern", values)
                    self.assertFalse(preview["can_apply"])
                    ids = [via["id"], *via["pad_ids"]]
                result, _ = self.apply(ids, "linear_pattern", {"count": 2, "dx_mm": 4, "dy_mm": 2})
                saved = self.document()
                original = {row["id"]: row for row in saved["geometry"] if row["id"] in ids}
                self.assertEqual(original, {row["id"]: row for row in source["geometry"] if row["id"] in ids})
                self.assertEqual(saved["ports"], source["ports"])
                self.assertEqual(saved["connections"], source["connections"])
                if fixture is via_document:
                    copied_ids = result["selection_ids"][len(ids):]
                    copied_via = self.shape(copied_ids[0])
                    self.assertEqual(copied_via["pad_ids"], copied_ids[1:])
                    for value, expected in zip(copied_via["center"], (7, 8)):
                        self.assertAlmostEqual(Quantity(**value).as_unit("mm"), expected)
                    self.assertEqual(copied_via["plating_thickness"], via["plating_thickness"])

    def test_rotate_two_objects_is_one_undo_and_preserves_unknowns_and_sources(self):
        line, arc = self.line(), self.arc()
        source = self.shape(line)
        source["end"][0] = Quantity.from_value(4000, "um", status="estimated", source_refs=["원문 자료 p.2"]).to_dict()
        self.command("geometry.set", {"geometry": source})
        before = self.document()
        before_count = self.get([line])["revision_id"]
        result, request = self.apply([line, arc], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 90})
        self.assertIn("network", result["invalidation_set"])
        self.assertEqual(self.service.mutate("precision.apply", request), result)
        updated = self.shape(line)
        self.assertEqual(Quantity(**updated["end"][0]).as_unit("mm"), -6)
        self.assertEqual(updated["end"][0]["display_unit"], "um")
        self.assertEqual(updated["end"][0]["source_refs"], ["원문 자료 p.2"])
        self.assertEqual(self.shape(arc)["kind"], "arc_path")
        self.assertEqual(self.shape(arc)["sweep_angle"], next(row for row in before["geometry"] if row["id"] == arc)["sweep_angle"])
        self.assertEqual(self.document()["stackup"], before["stackup"])
        self.history("undo")
        self.assertEqual(self.document()["geometry"], before["geometry"])
        self.assertNotIn(EXTENSION_KEY, self.document()["extensions"])
        self.history("redo")
        self.assertEqual(self.shape(line), updated)
        self.assertNotEqual(before_count, self.revision)

    def test_mirror_preserves_circle_and_reverses_signed_sweep_and_holes(self):
        arc = self.arc(130)
        region = self.region([[0, 0], [8, 0], [8, 8], [0, 8]], [[[2, 2], [4, 2], [4, 4], [2, 4]]])
        before = self.document()["geometry"]
        self.apply([arc, region], "mirror", {"axis": "x", "offset_mm": 1})
        after = self.shape(arc)
        self.assertEqual(Quantity(**after["start_angle"]).as_unit("deg"), -25)
        self.assertEqual(Quantity(**after["sweep_angle"]).as_unit("deg"), -130)
        self.assertEqual(Quantity(**after["center"][1]).as_unit("mm"), -10)
        self.assertEqual(len(self.shape(region)["holes"]), 1)
        self.history("undo")
        self.assertEqual(self.document()["geometry"], before)

    def test_parameter_binding_and_expression_update_recomputes_dimensions_without_detaching(self):
        arc = self.arc()
        parameter = str(uuid4())
        self.command("parameter.set", {"id": parameter, "name": "반지름 변수", "quantity": Quantity.from_value(23, "mm", source_refs=["사용자 치수"]).to_dict()})
        old = self.shape(arc)["radius"]
        self.apply([arc], "bind_dimension", {"dimension_key": "arc.radius", "parameter_id": parameter})
        self.assertEqual(self.shape(arc)["radius"], {"parameter_id": parameter})
        row = next(row for row in self.get([arc])["dimensions"] if row["key"] == "arc.radius")
        self.assertFalse(row["editable"])
        self.assertEqual(row["value"], 23)
        blocked, _ = self.preview([arc], "dimension_set", {"dimension_key": "arc.radius", "value": 5, "unit": "mm"})
        self.assertFalse(blocked["can_apply"])
        self.command("parameter.set_expression", {"id": parameter, "name": "반지름 변수", "expression": "24 mm", "bindings": {}, "dimension": "length", "display_unit": "mm"})
        self.assertEqual(next(row for row in self.get([arc])["dimensions"] if row["key"] == "arc.radius")["value"], 24)
        origin = self.document()["extensions"][EXTENSION_KEY]["records"][0]
        self.assertEqual(origin["before"][0]["radius"], old)
        self.assertEqual(origin["parameters"][parameter]["quantity"]["value_si"], 0.023)

    def test_changed_review_stale_revision_and_locked_coordinates_are_atomic(self):
        identity = self.line()
        preview, data = self.preview([identity], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 90})
        before = self.service.journal.read()
        request = self.request({**data, "values": {**data["values"], "angle_deg": 180}, "command_id": str(uuid4()), "review_hash": preview["review_hash"], "reason": "변경된 입력"})
        with self.assertRaises(ProjectError):
            self.service.mutate("precision.apply", request)
        self.assertEqual(before, self.service.journal.read())
        self.canvas("translate", {"id": identity, "dx_mm": 1, "dy_mm": 0})
        with self.assertRaises(ProjectError):
            precision_service.read(self.service, "precision.preview", self.read_request(data))
        parameter = str(uuid4())
        self.command("parameter.set", {"id": parameter, "name": "고정 좌표", "quantity": Quantity.from_value(2, "mm").to_dict()})
        shape = self.shape(identity)
        shape["start"][0] = {"parameter_id": parameter}
        self.command("geometry.set", {"geometry": shape})
        blocked, _ = self.preview([identity], "mirror", {"axis": "y", "offset_mm": 0})
        self.assertFalse(blocked["can_apply"])
        self.assertEqual(self.shape(identity)["start"][0], {"parameter_id": parameter})

    def test_planar_difference_preserves_hole_and_sources_and_undo_without_engine(self):
        self.require_planar()
        outer = self.region([[0, 0], [10, 0], [10, 10], [0, 10]])
        cutter = self.region([[2, 2], [4, 2], [4, 4], [2, 4]])
        before = self.document()["geometry"]
        result, _ = self.apply([outer, cutter], "difference", {})
        new_id = result["selection_ids"][0]
        self.assertNotIn(new_id, [outer, cutter])
        self.assertEqual(len(self.shape(new_id)["holes"]), 1)
        self.assertEqual(next(row for row in self.get([new_id])["dimensions"] if row["key"] == "region.area")["value"], 96)
        with patch("rfad.application.precision_candidates.runtime", return_value=(None, {"available": False, "reason": "엔진 없음"})):
            self.history("undo")
            self.assertEqual(self.document()["geometry"], before)
            self.history("redo")
            self.assertEqual(len(self.shape(new_id)["holes"]), 1)

    def test_planar_union_disjoint_parts_and_offset_are_explicit(self):
        self.require_planar()
        a = self.region([[0, 0], [2, 0], [2, 2], [0, 2]])
        b = self.region([[5, 0], [7, 0], [7, 2], [5, 2]])
        result, _ = self.apply([a, b], "union", {})
        self.assertEqual(len(result["selection_ids"]), 2)
        first = result["selection_ids"][0]
        result, _ = self.apply([first], "offset", {"distance_mm": 1, "join": "mitre", "mitre_limit": 5})
        rows = self.get(result["selection_ids"])["dimensions"]
        self.assertAlmostEqual(next(row for row in rows if row["key"] == "region.area")["value"], 16)

    def test_planar_empty_mixed_role_reference_and_curve_are_blocked(self):
        self.require_planar()
        a = self.region([[0, 0], [2, 0], [2, 2], [0, 2]])
        b = self.region([[5, 0], [7, 0], [7, 2], [5, 2]])
        empty, _ = self.preview([a, b], "intersection", {})
        self.assertFalse(empty["can_apply"])
        shape = self.shape(b)
        shape["role"] = "feed"
        self.command("geometry.set", {"geometry": shape})
        self.assertFalse(self.preview([a, b], "union", {})[0]["can_apply"])
        shape["role"] = self.shape(a)["role"]
        self.command("geometry.set", {"geometry": shape})
        self.command("connection.set", {"record": {"id": str(uuid4()), "name": "연결 의도", "kind": "isolated", "object_ids": [a, b], "source_refs": []}})
        self.assertFalse(self.preview([a, b], "union", {})[0]["can_apply"])
        line = self.line()
        self.assertFalse(self.preview([line, b], "union", {})[0]["can_apply"])

    def test_saved_origins_unknown_material_and_engine_absence_survive_reopen(self):
        identity = self.arc()
        self.apply([identity], "mirror", {"axis": "y", "offset_mm": 3})
        before = self.document()
        task = self.service.mutate("project.save", self.request({"expected_revision": self.revision}))
        self.service.run_next()
        self.assertEqual(self.service.journal.read()["jobs"][task["job_id"]]["state"], "completed")
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        task = self.service.mutate("project.open", self.request({"path": "projects/precision", "open_mode": "open"}, {}))
        self.service.run_next()
        self.assertEqual(self.service.journal.read()["jobs"][task["job_id"]]["state"], "completed")
        self.assertEqual(before, self.document())
        self.assertIsNone(self.shape(identity)["material_ref"])
        validate_precision_origins(self.document())
        self.history("undo")
        self.assertNotIn(EXTENSION_KEY, self.document()["extensions"])
        self.history("redo")
        self.assertEqual(self.document()["extensions"], before["extensions"])

    def test_mutating_batch_and_notification_do_not_apply_precision(self):
        identity = self.line()
        preview, data = self.preview([identity], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 90})
        params = self.request({**data, "command_id": str(uuid4()), "review_hash": preview["review_hash"], "reason": "수신 검토"})
        before = self.service.journal.read()
        message = {"jsonrpc": "2.0", "method": "precision.apply", "params": params}
        self.assertIsNone(handle_frame(json.dumps(message).encode(), self.service))
        message["id"] = 1
        response = handle_frame(json.dumps([message]).encode(), self.service)
        self.assertEqual(response["error"]["data"]["domain_code"], "E_UNSUPPORTED")
        self.assertEqual(before, self.service.journal.read())

    def test_limits_and_origin_tampering_fail_without_silent_truncation(self):
        identity = self.line()
        with self.assertRaises(ProjectError):
            self.get([identity] * 17)
        no_change, _ = self.preview([identity], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 0})
        self.assertFalse(no_change["can_apply"])
        with patch("rfad.application.precision_service.MAX_DTO_BYTES", 100):
            with self.assertRaises(ProjectError):
                self.get([identity])
        self.apply([identity], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 90})
        broken = deepcopy(self.document())
        broken["extensions"][EXTENSION_KEY]["records"][0]["before"][0]["width"]["value_si"] *= 2
        with self.assertRaises(ProjectError):
            validate_precision_origins(broken)

    def test_large_saved_quantities_reject_preview_without_losing_their_originals(self):
        """! @brief 유효한 과거 SI 값의 표시 단위 오버플로를 후보 차단으로 정리한다."""
        identity = self.arc()
        original = self.shape(identity)
        original["start_angle"] = Quantity.from_value(1e308, "rad", source_refs=["기존 직접 입력"]).to_dict()
        self.command("geometry.set", {"geometry": original})
        row = next(row for row in self.get([identity])["dimensions"] if row["key"] == "arc.start_angle")
        self.assertEqual(row["status"], "unsupported")
        self.assertIsNone(row["value"])
        result, _ = self.preview([identity], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 90})
        self.assertFalse(result["can_apply"])
        self.assertEqual(result["notices"][0]["code"], "E_RESOURCE")
        self.assertEqual(self.shape(identity), original)
        parameter = str(uuid4())
        self.command("parameter.set", {"id": parameter, "name": "큰 과거 치수", "quantity": Quantity.from_value(1e308, "m").to_dict()})
        result, _ = self.preview([identity], "bind_dimension", {"dimension_key": "arc.radius", "parameter_id": parameter})
        self.assertFalse(result["can_apply"])
        self.assertEqual(result["notices"][0]["code"], "E_RESOURCE")
        self.assertEqual(self.shape(identity), original)

    def test_port_references_and_missing_values_are_preserved(self):
        self.require_planar()
        a = self.region([[0, 0], [2, 0], [2, 2], [0, 2]])
        b = self.region([[3, 0], [5, 0], [5, 2], [3, 2]])
        port = {"id": str(uuid4()), "name": "기준 포트", "kind": "lumped", "positive_geometry_id": a, "reference_geometry_id": b,
                "resistance": Quantity.from_value(50, "ohm").to_dict(), "reference_plane": "제작 기준면 미정", "polarity": 1,
                "direction": [0.0, 1.0, 0.0], "validity_hz": {"min": Quantity.from_value(2, "GHz").to_dict(), "max": Quantity.from_value(3, "GHz").to_dict()}}
        self.command("port.set", {"port": port})
        self.assertFalse(self.preview([a, b], "union", {})[0]["can_apply"])
        self.assertEqual(self.document()["ports"], [port])
        arc = self.arc()
        shape = self.shape(arc)
        shape["radius"] = Quantity.missing("length", "mm").to_dict()
        shape["start_angle"] = Quantity.missing("angle", "deg").to_dict()
        self.command("geometry.set", {"geometry": shape})
        row = next(row for row in self.get([arc])["dimensions"] if row["key"] == "arc.radius")
        self.assertIsNone(row["value"])
        self.assertEqual(row["status"], "missing")

    def test_empty_note_and_failed_publication_keep_single_authoritative_state(self):
        identity = self.line()
        preview, data = self.preview([identity], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 90})
        request = self.request({**data, "command_id": str(uuid4()), "review_hash": preview["review_hash"], "reason": ""})
        before = self.service.journal.read()

        def fault(stage):
            """! @brief 게시 직전 저장 실패를 주입한다."""
            if stage == "before_publish":
                raise OSError("정밀 편집 게시 실패")

        self.service.journal.fault_hook = fault
        try:
            with self.assertRaises(ProjectError):
                self.service.mutate("precision.apply", request)
        finally:
            self.service.journal.fault_hook = None
        self.assertEqual(before, self.service.journal.read())
        result = self.service.mutate("precision.apply", request)
        self.revision = result["new_revision"]
        self.assertEqual(self.document()["extensions"][EXTENSION_KEY]["records"][0]["reason"], "")
        self.assertEqual(self.service.mutate("precision.apply", request), result)

    def test_template_origin_is_unchanged_by_explicit_dimension_rebinding(self):
        from test_template_candidates import specification

        data = specification(self.document())
        for key, value in (("center_x", 20), ("center_y", 20), ("feed_start_x", 22), ("feed_start_y", 20)):
            data["explicit_inputs"][key] = Quantity.from_value(value, "mm", source_refs=["보드 내부 시험 배치"]).to_dict()
        candidate = self.service.templates.query("template.synthesize", self.read_request(data))
        self.assertTrue(candidate["can_apply"], candidate["issues"])
        result = self.service.mutate("template.apply", self.request({**data, "command_id": str(uuid4()), "preview_hash": candidate["preview_hash"]}))
        self.revision = result["new_revision"]
        arc = next(row["id"] for row in self.document()["geometry"] if row["kind"] == "arc_path")
        origin = deepcopy(self.document()["extensions"]["rfad.template-origin"])
        parameter = str(uuid4())
        self.command("parameter.set", {"id": parameter, "name": "새 반지름", "quantity": Quantity.from_value(8, "mm").to_dict()})
        self.apply([arc], "bind_dimension", {"dimension_key": "arc.radius", "parameter_id": parameter})
        self.assertEqual(self.document()["extensions"]["rfad.template-origin"], origin)
        self.history("undo")
        self.assertEqual(self.document()["extensions"]["rfad.template-origin"], origin)

    def test_internal_command_is_not_public_and_provenance_matches_actual_changes(self):
        identity = self.line()
        _, data = self.preview([identity], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 90})
        _, payload = precision_service.preview(self.document(), data)
        before = self.service.journal.read()
        with self.assertRaises(ProjectError) as caught:
            self.command("geometry.precision.apply", payload)
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
        self.assertEqual(before, self.service.journal.read())
        forged = deepcopy(payload)
        forged["replacement_origin"]["after"][0]["width"]["value_si"] *= 2
        forged["replacement_origin"]["record_hash"] = record_hash(forged["replacement_origin"])
        document = self.document()
        saved = deepcopy(document)
        with self.assertRaises(ProjectError) as caught:
            apply_precision_command(document, forged)
        self.assertEqual(caught.exception.code, "E_HASH")
        self.assertEqual(document, saved)
        _, _, inverse = apply_precision_command(document, payload)
        forged_inverse = deepcopy(inverse["payload"])
        forged_inverse["replacement_objects"][0]["width"]["value_si"] *= 2
        saved = deepcopy(document)
        with self.assertRaises(ProjectError):
            apply_precision_command(document, forged_inverse)
        self.assertEqual(document, saved)

    def test_pad_dimensions_and_via_transform_keep_undeclared_manufacturing_values(self):
        pad = str(uuid4())
        self.canvas("create_pad", {"id": pad, "layer_id": self.layer, "pad_shape": "circle", "center": [3, 4],
                                   "width_mm": 2, "height_mm": 2, "rotation_deg": 0})
        self.apply([pad], "dimension_set", {"dimension_key": "pad.diameter", "value": 3, "unit": "mm"})
        self.assertEqual([value["value_si"] for value in self.shape(pad)["size"]], [0.003, 0.003])
        upper = str(uuid4())
        self.canvas("create_layer", {"id": upper, "name": "도체 2"})
        via = str(uuid4())
        self.canvas("create_via", {"id": via, "layer_id": self.layer, "end_layer_id": upper, "center": [3, 4],
                                   "finished_hole_diameter_mm": None, "plating_thickness_mm": None, "tool_hole_diameter_mm": None, "pad_ids": []})
        original = self.shape(via)
        self.apply([pad, via], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 90})
        updated = self.shape(via)
        self.assertEqual({**updated, "center": original["center"]}, original)
        self.apply([via], "dimension_set", {"dimension_key": "via.plating_thickness", "value": 25, "unit": "um"})
        self.assertAlmostEqual(self.shape(via)["plating_thickness"]["value_si"], 25e-6)
        self.assertEqual(self.shape(via)["finished_hole_diameter"]["status"], "missing")
        self.assertEqual(self.shape(via)["tool_hole_diameter"]["status"], "missing")

    def test_absent_engine_disables_only_planar_operations_and_invalid_units_are_atomic(self):
        identity = self.line()
        unavailable = (None, {"available": False, "reason": "엔진 미설치"})
        with patch("rfad.application.precision_candidates.runtime", return_value=unavailable), patch("rfad.application.precision_service.runtime", return_value=unavailable):
            context = self.get([identity])
            operations = {row["id"]: row for row in context["operations"]}
            self.assertTrue(operations["rotate"]["enabled"])
            self.assertFalse(operations["union"]["enabled"])
            self.apply([identity], "rotate", {"pivot_x_mm": 0, "pivot_y_mm": 0, "angle_deg": 90})
        for value, unit in ((True, "mm"), (10, "ohm"), (0, "mm"), (1e9, "mm")):
            with self.subTest(value=value, unit=unit):
                result, _ = self.preview([identity], "dimension_set", {"dimension_key": "line.length", "value": value, "unit": unit})
                self.assertFalse(result["can_apply"])


if __name__ == "__main__":
    unittest.main()
