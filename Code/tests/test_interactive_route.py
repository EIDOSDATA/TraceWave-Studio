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


    @unittest.skipUnless(runtime()[1]["available"], "고정 Shapely/GEOS 엔진 필요")
    def test_split_merge_owns_each_island_and_undo_restores_exactly(self):
        """! @brief 장애물 이동에 따른 분할과 병합, 이름 보존, 소유권 위조 거절과 자식 선택 복원을 검사한다."""
        from rfad.domain import copper_islands
        from rfad.domain.project import validate_project

        doc, _ = sketch_fixture("ifa")
        seed = net_and_path(doc, [20, 0], [20, 51])
        plane = next(item for item in doc["geometry"] if item["kind"] == "planar_region")
        key = plane["id"]
        with TemporaryDirectory() as directory:
            with ProjectService(Path(directory), auto_run=False) as service:
                source, _ = register_fixture(service, doc)
                project = source["project_id"]

                def current():
                    """! @brief 시험 서비스가 가리키는 개정을 읽는다."""
                    return service._load(service.journal.read()["projects"][project])

                def apply_pour(selection, operation, values):
                    """! @brief 섬 또는 원본 선택으로 실제 변경 명령을 적용한다."""
                    data = {"expected_revision": current()["revision_id"], "selection_ids": [selection],
                            "operation": operation, "values": values}
                    preview, _ = precision_service.preview(current(), data)
                    self.assertTrue(preview["can_apply"], preview["notices"])
                    return service.mutate("precision.apply", request(service, project, {**data, "command_id": str(uuid4()),
                        "review_hash": preview["review_hash"], "reason": "다중 섬 검증"}))

                def move(dx, dy):
                    """! @brief 전기적으로 다른 넷에 속한 장애물을 이동한다."""
                    return service.mutate("canvas.apply", request(service, project, {"operation": "translate",
                        "command_id": str(uuid4()), "expected_revision": current()["revision_id"],
                        "values": {"id": seed["id"], "dx_mm": dx, "dy_mm": dy}}))

                collision = deepcopy(source)
                foreign = {**deepcopy(seed), "id": copper_islands.slots(key)[1], "name": "다른 소유의 선"}
                collision["geometry"] = sorted([*collision["geometry"], foreign], key=lambda item: item["id"])
                blocked, payload = precision_service.preview(collision, {"expected_revision": source["revision_id"],
                    "selection_ids": [key], "operation": copper_pour.FILL,
                    "values": {"clearance_mm": .25, "tolerance_mm": .01}})
                self.assertIsNone(payload)
                self.assertIn("다른 도체", blocked["notices"][0]["message"])
                apply_pour(key, copper_pour.FILL, {"clearance_mm": .25, "tolerance_mm": .01})
                from rfad.application.pcb_solver import check_pcb_input
                from test_pcb_solver import SETTINGS

                check_pcb_input(current(), SETTINGS)
                split = current()
                ids = copper_islands.members(split, key)
                self.assertEqual(len(ids), 2)
                self.assertEqual(ids[0], key)
                corrupt = deepcopy(split)
                corrupt["extensions"][copper_islands.KEY]["owners"][key][1] = seed["id"]
                with self.assertRaisesRegex(ProjectError, "소유권"):
                    validate_project(corrupt)
                move(1, 0)
                shifted = current()
                self.assertEqual(copper_islands.members(shifted, key), ids)
                before_merge = {r["id"]: r for r in shifted["geometry"]}
                self.assertEqual(before_merge[ids[1]]["name"], next(r["name"] for r in split["geometry"] if r["id"] == ids[1]))
                move(0, 5)
                merged = current()
                self.assertEqual(copper_islands.members(merged, key), [key])
                self.assertNotIn(ids[1], {r["id"] for r in merged["geometry"]})
                for action, expected in (("undo", shifted), ("redo", merged), ("undo", shifted)):
                    service.mutate("project." + action, request(service, project, {"command_id": str(uuid4()),
                        "expected_revision": current()["revision_id"]}))
                    self.assertEqual(current()["geometry"], expected["geometry"])
                    self.assertEqual(current()["extensions"], expected["extensions"])
                saved = service.mutate("project.save", request(service, project, {"expected_revision": current()["revision_id"]}))
                service.run_next()
                self.assertEqual(status(service, saved["job_id"])["state"], "completed")
            with ProjectService(Path(directory), auto_run=False) as service:
                self.assertEqual(copper_islands.members(current(), key), ids)
                apply_pour(ids[1], copper_pour.RESTORE, {})
                self.assertEqual(next(r for r in current()["geometry"] if r["id"] == key), plane)
                self.assertNotIn(ids[1], {r["id"] for r in current()["geometry"]})
                self.assertEqual(current()["ports"], source["ports"])


    def test_route_switches_layers_with_checked_pads_and_via(self):
        """! @brief IFA 상하층 배선과 두 랜드, 도금홀의 거절/검토, 저장과 이력을 검증한다."""
        from rfad.application.interactive_route import review
        doc, _ = sketch_fixture("ifa")
        seed = next(row for row in doc["geometry"] if row["role"] == "radiator")
        bottom = next(row for row in doc["stackup"] if row["role"] == "conductor" and row["id"] != seed["layer_id"])
        with TemporaryDirectory() as directory:
            with ProjectService(Path(directory), auto_run=False) as service:
                source, _ = register_fixture(service, doc)
                project = source["project_id"]
                values = {"id": str(uuid4()), "source_id": seed["id"], "layer_id": seed["layer_id"],
                          "points": [[31, 57], [32, 57], [33, 58]], "width_mm": .25, "clearance_mm": .2,
                          "transitions": [{"index": 1, "layer_id": bottom["id"], "pad_diameter_mm": .8,
                            "finished_hole_diameter_mm": .3, "plating_thickness_mm": .025, "tool_hole_diameter_mm": .35}]}
                params = {"contract_version": "rfad.api/2.0", "context": {"project_id": project},
                          "input": {"expected_revision": source["revision_id"], "values": values}}
                state = service.journal.read()
                self.assertTrue(review(service, params)["valid"])
                bad = deepcopy(params)
                bad["input"]["values"]["transitions"][0]["pad_diameter_mm"] = .31
                self.assertFalse(review(service, bad)["valid"])
                self.assertEqual(service.journal.read(), state)
                changed = service.mutate("canvas.apply", request(service, project, {"expected_revision": source["revision_id"],
                    "command_id": str(uuid4()), "operation": "create_route", "values": values}))
                def current():
                    """! @brief 저장 전후 현재 개정을 비교한다."""
                    return service._load(service.journal.read()["projects"][project])
                after = current()
                created = [row for row in after["geometry"] if row["id"] in changed["changed_ids"]]
                self.assertEqual(len(created), 5)
                via, = [row for row in created if row["kind"] == "via"]
                pads = [row for row in created if row["kind"] == "pad"]
                lines = [row for row in created if row["kind"] == "line_path"]
                self.assertEqual({r["id"] for r in pads}, set(via["pad_ids"]))
                self.assertEqual({r["layer_id"] for r in lines}, {seed["layer_id"], bottom["id"]})
                self.assertEqual((via["layer_id"], via["end_layer_id"]), (bottom["id"], seed["layer_id"]))
                self.assertEqual({r["net_id"] for r in created}, {seed["net_id"]})
                self.assertEqual(after["ports"], source["ports"])
                for method, expected in (("project.undo", source), ("project.redo", after)):
                    service.mutate(method, request(service, project, {"command_id": str(uuid4()), "expected_revision": current()["revision_id"]}))
                    self.assertEqual(current()["geometry"], expected["geometry"])
                save = service.mutate("project.save", request(service, project, {"expected_revision": current()["revision_id"]}))
                service.run_next()
                self.assertEqual(status(service, save["job_id"])["state"], "completed")
            with ProjectService(Path(directory), auto_run=False) as service:
                self.assertEqual(current()["geometry"], after["geometry"])
