"""! @brief 실제 원호와 IFA에서 대화식 배선, 간격 차단과 구리면 자동 재채움을 검증한다."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.adapters.planar_backend import runtime
from rfad.application import copper_pour, precision_service
from rfad.application.projects import ProjectService
from rfad.domain.check_geometry import footprint, separation
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture, request, status
from test_pcb_solver import quantity
from test_sketch_constraints import sketch_fixture


def net_and_path(document, start, end):
    """! @brief 기존 급전과 독립된 넷과 배선 시작 도체를 추가한다."""
    net = {"id": str(uuid4()), "name": "검증용 독립 신호"}
    row = deepcopy(next(item for item in document["geometry"] if item["kind"] == "line_path"))
    row.update(id=str(uuid4()), name="검증용 시작선", net_id=net["id"],
               start=[quantity(value, "mm") for value in start], end=[quantity(value, "mm") for value in end],
               width=quantity(.4, "mm"))
    document["nets"] = sorted([*document["nets"], net], key=lambda item: item["id"])
    document["geometry"] = sorted([*document["geometry"], row], key=lambda item: item["id"])
    return row


class InteractiveRouteTests(unittest.TestCase):
    def test_arc_board_route_checks_every_segment_atomically(self):
        """! @brief 다른 넷에 닿은 마지막 구간과 기판 밖 끝점을 거절하고 적법한 두 구간을 함께 저장한다."""
        document, _ = sketch_fixture("arc")
        seed = net_and_path(document, [-2, 3], [0, 3])
        with TemporaryDirectory() as directory, ProjectService(Path(directory), auto_run=False) as service:
            source, _ = register_fixture(service, document)
            project = source["project_id"]
            def current():
                """! @brief 현재 개정의 전체 원본을 읽는다."""
                return service._load(service.journal.read()["projects"][project])

            def route(points):
                """! @brief 클릭 경유점과 실제 도체층 및 간격을 수정 서비스에 전송한다."""
                return service.mutate("canvas.apply", request(service, project, {"command_id": str(uuid4()),
                    "expected_revision": current()["revision_id"], "operation": "create_route", "values": {
                    "id": str(uuid4()), "source_id": seed["id"], "layer_id": seed["layer_id"], "points": points,
                    "width_mm": .2, "clearance_mm": .3}}))

            for points, reason in (([[0, 3], [-1, 4], [-3, 0]], "2구간"), ([[0, 3], [-2, 30]], "외곽"),
                                   ([[2, 3], [2, 4]], "첫 배선점")):
                with self.assertRaisesRegex(ProjectError, reason):
                    route(points)
                self.assertEqual(current(), source)
            result = route([[0, 3], [-1, 4], [-2, 4]])
            self.assertEqual(len(result["changed_ids"]), 2)
            new = [row for row in current()["geometry"] if row["id"] in result["changed_ids"]]
            self.assertTrue(all(row["net_id"] == seed["net_id"] and row["width"]["value_si"] == .0002 for row in new))
            self.assertEqual(current()["ports"], source["ports"])
            service.mutate("project.undo", request(service, project, {"command_id": str(uuid4()),
                                                                       "expected_revision": current()["revision_id"]}))
            self.assertEqual(current()["geometry"], source["geometry"])

    @unittest.skipUnless(runtime()[1]["available"], "고정 Shapely/GEOS 엔진 필요")
    def test_ifa_pour_refills_after_route_and_restores_original(self):
        """! @brief 경계와 원본 구멍, 급전, 현재 채움, 재열기 이후의 재생성을 함께 검사한다."""
        document, _ = sketch_fixture("ifa")
        seed = net_and_path(document, [10, 10], [12, 10])
        plane = next(row for row in document["geometry"] if row["kind"] == "planar_region")
        with TemporaryDirectory() as directory:
            with ProjectService(Path(directory), auto_run=False) as service:
                source, _ = register_fixture(service, document)
                project = source["project_id"]

                def current():
                    """! @brief 모델의 전체 개정을 읽는다."""
                    return service._load(service.journal.read()["projects"][project])

                def apply_pour(operation, values):
                    """! @brief 정밀 편집 미리보기의 해시를 같은 개정에서 적용한다."""
                    data = {"expected_revision": current()["revision_id"], "operation": operation,
                            "values": values, "selection_ids": [plane["id"]]}
                    reviewed, _ = precision_service.preview(current(), data)
                    self.assertTrue(reviewed["can_apply"], reviewed["notices"])
                    return service.mutate("precision.apply", request(service, project, {**data, "command_id": str(uuid4()),
                        "review_hash": reviewed["review_hash"], "reason": "간격 보존 검증"}))

                def geometry(doc, identity):
                    """! @brief 같은 UUID의 도체를 읽는다."""
                    return next(row for row in doc["geometry"] if row["id"] == identity)

                apply_pour(copper_pour.FILL, {"clearance_mm": .25, "tolerance_mm": .01})
                filled = current()
                self.assertGreater(len(geometry(filled, plane["id"])["holes"]), len(plane["holes"]))
                with self.assertRaisesRegex(ProjectError, "구리면 채움 간격"):
                    service.mutate("canvas.apply", request(service, project, {"command_id": str(uuid4()),
                        "expected_revision": filled["revision_id"], "operation": "create_route", "values": {
                        "id": str(uuid4()), "source_id": seed["id"], "layer_id": seed["layer_id"],
                        "points": [[11, 10], [11, 12], [13, 12]], "width_mm": .15, "clearance_mm": .8}}))
                self.assertEqual(current(), filled)
                result = service.mutate("canvas.apply", request(service, project, {"command_id": str(uuid4()),
                    "expected_revision": filled["revision_id"], "operation": "create_route", "values": {
                    "id": str(uuid4()), "source_id": seed["id"], "layer_id": seed["layer_id"],
                    "points": [[11, 10], [11, 12], [13, 12]], "width_mm": .15, "clearance_mm": .2}}))
                routed = current()
                self.assertEqual(len(result["changed_ids"]), 3)
                self.assertIn(plane["id"], result["changed_ids"])
                self.assertNotEqual(geometry(filled, plane["id"])["holes"], geometry(routed, plane["id"])["holes"])
                copper = footprint(routed, geometry(routed, plane["id"]))
                for key in set(result["changed_ids"]) - {plane["id"]}:
                    actual = separation(copper, footprint(routed, geometry(routed, key)), [200000])[0]
                    self.assertGreaterEqual(actual, .25)
                for action, expected in (("undo", filled), ("redo", routed)):
                    service.mutate("project." + action, request(service, project, {"command_id": str(uuid4()),
                        "expected_revision": current()["revision_id"]}))
                    self.assertEqual(current()["geometry"], expected["geometry"])
                saved = service.mutate("project.save", request(service, project, {"expected_revision": current()["revision_id"]}))
                service.run_next()
                self.assertEqual(status(service, saved["job_id"])["state"], "completed")
            with ProjectService(Path(directory), auto_run=False) as service:
                self.assertEqual(current()["geometry"], routed["geometry"])
                self.assertEqual(current()["ports"], source["ports"])
                self.assertEqual(current()["connections"], source["connections"])
                apply_pour(copper_pour.RESTORE, {})
                self.assertEqual(geometry(current(), plane["id"]), plane)
                self.assertFalse(copper_pour.active(current()))
