"""! @brief 구동 거리의 원자 편집과 두 기준점 참조를 실제 원호와 IFA에서 검증한다."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application import smart_dimension_service as api
from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_features import empty_pcb
from rfad.domain.smart_dimensions import dimensions
from test_cad_worker_process import register_fixture, request, status
from test_pcb_features import hole_record
from test_pcb_ifa import IFA_SETTINGS, ifa_document
from test_pcb_solver import SETTINGS, fixture_document, quantity, runtime_identity, snapshot_for


def design(kind):
    """! @brief 실제 원호/IFA 해석형 입력에 독립 비도금 홀 두 개를 배치한다."""
    arc = kind == "arc"
    document = fixture_document(circle=True, arc=True) if arc else ifa_document()
    document["metadata"]["name"] = "스마트 치수 원호 검증" if arc else "스마트 치수 IFA 검증"
    centers = [(-3, -3), (3, -3)] if arc else [(23, 54), (29, 54)]
    holes = []
    for label, (x, y) in zip(("기준 홀 왼쪽", "이동 홀 오른쪽"), centers):
        hole = hole_record(document, x=x, y=y, diameter=1.2)
        hole.update(id=str(uuid4()), name=label)
        holes.append(hole)
    document["pcb"] = {**empty_pcb(), "holes": sorted(holes, key=lambda row: row["id"])}
    return document, [row["id"] for row in holes]


class SmartDimensionTests(unittest.TestCase):
    def test_archive_roundtrip_and_undo_for_holes_and_port(self):
        """! @brief 저장, 다시 열기, 실행 취소와 실제 계획 입력까지 대조한다."""
        for kind, target in (("arc", 2.4), ("ifa", 1.7)):
            with self.subTest(kind=kind), TemporaryDirectory() as folder:
                root = Path(folder)
                with ProjectService(root, auto_run=False) as service:
                    initial, pair = design(kind)
                    original, _ = register_fixture(service, initial)
                    identity = original["project_id"]
                    context = {"project_id": identity}

                    def load():
                        """! @brief 보존한 current 참조를 사용한다."""
                        return service._load(service.journal.read()["projects"][identity])

                    def save_dimension(name, anchors, mode, target_mm=None, dimension_id=None, *, reject=False):
                        """! @brief 미리 보기와 적용이 같은 후보를 보존하는지 확인한다."""
                        data = {"expected_revision": load()["revision_id"], "operation": "save",
                                "record": {"id": dimension_id, "name": name, "anchors": anchors,
                                           "mode": mode, "target_mm": target_mm}}
                        state = service.journal.read()
                        reviewed = api.read(service, api.PREVIEW, {"contract_version": "rfad.api/2.0",
                                                                 "context": context, "input": data})
                        self.assertEqual(service.journal.read(), state)
                        self.assertEqual(reviewed["can_apply"], not reject, reviewed.get("message"))
                        if reject:
                            return reviewed
                        item = service.mutate(api.MUTATION, request(service, identity, {
                            **data, "command_id": str(uuid4()), "review_hash": reviewed["review_hash"],
                        }))
                        return item["dimension_id"]

                    holes = {"kind": "holes", "ids": pair}
                    feed = {"kind": "feed", "ids": [original["ports"][0]["id"]]}
                    h_id = save_dimension("홀 사이", holes, "reference")
                    self.assertEqual(load()["pcb"], original["pcb"])
                    self.assertAlmostEqual(api.get(load())["items"][0]["measurement"]["distance_mm"], 6)
                    save_dimension("홀 사이", holes, "driving", 7, h_id)
                    save_dimension("홀 사이", holes, "driving", 100, h_id, reject=True)
                    port_id = save_dimension("급전 간극", feed, "driving", target)
                    if kind == "ifa":
                        self.assertEqual(save_dimension("급전 간극", feed, "driving", 2.3, port_id,
                                                       reject=True)["diagnostic"], "E_PORT")
                    edited = load()
                    port = edited["ports"][0]
                    self.assertEqual(port["excitation_box"]["start"], original["ports"][0]["excitation_box"]["start"])
                    self.assertEqual(port["positive_geometry_id"], original["ports"][0]["positive_geometry_id"])
                    self.assertEqual(port["reference_geometry_id"], original["ports"][0]["reference_geometry_id"])
                    for before, after in zip(original["geometry"], edited["geometry"]):
                        self.assertEqual(before["source_ref"], after["source_ref"])
                        if before["id"] != port["positive_geometry_id"]:
                            self.assertEqual(before, after)
                    moving = next(row for row in edited["pcb"]["holes"] if row["id"] == pair[1])
                    before = next(row for row in original["pcb"]["holes"] if row["id"] == pair[1])
                    self.assertEqual(moving["shape"]["center"][0]["source_refs"], before["shape"]["center"][0]["source_refs"])
                    wrong = deepcopy(port)
                    wrong["excitation_box"]["stop"][0 if kind == "arc" else 1] = quantity(100, "mm")
                    with self.assertRaises(ProjectError) as conflict:
                        service.mutate("project.apply_command", request(service, identity, {
                            "expected_revision": edited["revision_id"], "command_id": str(uuid4()),
                            "type": "port.set", "payload": {"port": wrong},
                        }))
                    self.assertEqual(conflict.exception.code, "E_CONFLICT")
                    for method in ("project.undo", "project.redo"):
                        service.mutate(method, request(service, identity, {"expected_revision": load()["revision_id"],
                                                                               "command_id": str(uuid4())}))
                        self.assertEqual(len(dimensions(load())), 1 if method.endswith("undo") else 2)
                    save_job = service.mutate("project.save", request(service, identity, {"expected_revision": load()["revision_id"]}))
                    service.run_next()
                    self.assertEqual(status(service, save_job["job_id"])["state"], "completed")
                with ProjectService(root, auto_run=False) as service:
                    reopened = service._load(service.journal.read()["projects"][identity])
                    items = {row["id"]: row for row in api.get(reopened)["items"]}
                    self.assertAlmostEqual(items[h_id]["measurement"]["distance_mm"], 7)
                    self.assertAlmostEqual(items[port_id]["measurement"]["distance_mm"], target)
                    self.assertEqual(items[port_id]["measurement"]["azimuth_deg"], 0 if kind == "arc" else 90)
                    self.assertEqual(items[port_id]["mode"], "driving")
                    settings = SETTINGS if kind == "arc" else IFA_SETTINGS
                    plan = build_pcb_plan(reopened, snapshot_for(reopened), runtime_identity(), settings)
                    self.assertAlmostEqual(items[port_id]["target_mm"], target)
                    self.assertAlmostEqual(plan["case"]["port"]["stop_mm"][0 if kind == "arc" else 1],
                                           plan["case"]["port"]["start_mm"][0 if kind == "arc" else 1] + target)
                    self.assertEqual(len(plan["case"]["mechanical_voids"]), 2)

    def test_reference_follows_the_hole_without_managing_it(self):
        """! @brief 참조 치수는 다른 편집 이후에도 형상을 바꾸지 않고 새 거리를 표시한다."""
        from rfad.domain.project import apply_command
        from rfad.domain.pcb_features import COMMAND as PCB_COMMAND, make_patch
        from rfad.domain.smart_dimensions import COMMAND

        document, ids = design("arc")
        data = {"operation": "save", "record": {"id": None, "name": "참조",
            "anchors": {"kind": "holes", "ids": ids}, "mode": "reference", "target_mm": None}}
        review, payload = api.preview(document, data)
        self.assertTrue(review["can_apply"])
        document = apply_command(document, {"command_id": str(uuid4()), "type": COMMAND, "payload": payload},
                                 document["revision_id"])[0]
        candidate = deepcopy(document)
        hole = next(row for row in candidate["pcb"]["holes"] if row["id"] == ids[1])
        hole["shape"]["center"][0] = quantity(4, "mm")
        patch = make_patch(document, candidate, "hole.set", "참조 치수 갱신 검증")
        moved = apply_command(document, {"command_id": str(uuid4()), "type": PCB_COMMAND, "payload": patch},
                              document["revision_id"])[0]
        self.assertEqual(moved["pcb"], candidate["pcb"])
        self.assertEqual(api.get(moved)["items"][0]["mode"], "reference")
        self.assertAlmostEqual(api.get(moved)["items"][0]["measurement"]["distance_mm"], 7)
