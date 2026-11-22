"""! @brief 실제 원호와 IFA의 독립 스케치 자유도, 충돌 및 저장을 검사한다."""

from copy import deepcopy
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application import sketch_service as api
from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.projects import ProjectService
from rfad.application.smart_dimension_service import preview as smart_preview
from rfad.domain import sketch_constraints as sketch
from rfad.domain.errors import ProjectError
from rfad.domain.project import apply_command
from rfad.domain.smart_dimensions import COMMAND as SMART_COMMAND
from test_cad_worker_process import register_fixture, request, status
from test_pcb_ifa import IFA_SETTINGS
from test_pcb_solver import SETTINGS, quantity, runtime_identity, snapshot_for
from test_smart_dimensions import design


def sketch_fixture(kind):
    """! @brief 해석 가능한 접선 원호와 IFA에 명시적 급전 구동 치수를 먼저 만든다."""
    document, _ = design(kind)
    document["metadata"]["name"] = "스케치 원호 검증" if kind == "arc" else "스케치 IFA 검증"
    if kind == "arc":
        document["board"]["outline"]["radius"] = quantity(10, "mm")
        arc = next(row for row in document["geometry"] if row["kind"] == "arc_path")
        arc.update(name="원호 방사 부품", center=[quantity(6, "mm"), quantity(2, "mm")],
                   radius=quantity(2, "mm"), start_angle=quantity(-90, "deg"))
        for row in document["geometry"]:
            if row["kind"] == "line_path":
                row["name"] = "원호 신호선" if row["role"] == "radiator" else "원호 기준선"
        datum_name = "원호 신호선"
    else:
        for row in document["geometry"]:
            names = {"radiator": "IFA 방사선", "short": "IFA 단락선", "ground": "IFA 접지면"}
            row["name"] = ("IFA 급전 패드" if row["kind"] == "pad" else "IFA 급전선") if row["role"] == "feed" else names[row["role"]]
        datum_name = "IFA 방사선"
    port = document["ports"][0]
    review, payload = smart_preview(document, {"operation": "save", "record": {"id": None, "name": "기존 급전 구동",
        "anchors": {"kind": "feed", "ids": [port["id"]]}, "mode": "driving", "target_mm": 2}})
    if not review["can_apply"]:
        raise AssertionError(review["message"])
    document = apply_command(document, {"command_id": str(uuid4()), "type": SMART_COMMAND, "payload": payload},
                             document["revision_id"])[0]
    setup = {"operation": "complete", "name": "원호 구속 검수" if kind == "arc" else "IFA 구속 검수",
             "selection_ids": [row["id"] for row in document["geometry"] if row["kind"] in sketch.SHAPES],
             "datum": sketch.anchor(next(row["id"] for row in document["geometry"] if row["name"] == datum_name), "start"),
             "axis": "x", "requested": None}
    return document, setup


class SketchConstraintTests(unittest.TestCase):
    def test_analysis_apply_and_reopen_both_designs(self):
        """! @brief 모순된 후보, 실제 자유도와 기존 치수/해석형 원본을 대조한다."""
        for kind, degrees, variables in (("arc", 6, 13), ("ifa", 10, 15)):
            with self.subTest(kind=kind), TemporaryDirectory() as folder:
                root = Path(folder)
                with ProjectService(root, auto_run=False) as service:
                    source, setup = sketch_fixture(kind)
                    document, snapshot = register_fixture(service, source)
                    project = document["project_id"]
                    context = {"project_id": project}

                    def current():
                        """! @brief 커밋에 연결된 실제 개정을 읽는다."""
                        return service._load(service.journal.read()["projects"][project])

                    def review(data):
                        """! @brief 검토 전후의 상태를 검사하고 현재 개정으로 요청한다."""
                        before = service.journal.read()
                        result = api.read(service, api.PREVIEW, {"contract_version": "rfad.api/2.0", "context": context,
                            "input": {"expected_revision": current()["revision_id"], **data}})
                        self.assertEqual(service.journal.read(), before)
                        return result

                    calculation = review(setup)
                    self.assertTrue(calculation["can_apply"], calculation)
                    self.assertEqual((calculation["variables"], calculation["before"], calculation["after"]),
                                     (variables, degrees, 0))
                    self.assertIn("급전 접촉", "\n".join(calculation["existing"]))
                    self.assertIn("접선" if kind == "arc" else "선 위의 점", "\n".join(calculation["existing"]))
                    selected = [row["id"] for row in calculation["proposals"] if row["selected"]]
                    for state in ("conflict", "redundant"):
                        invalid = next(row for row in calculation["proposals"] if row["state"] == state)
                        blocked = review({**setup, "requested": [*selected, invalid["id"]]})
                        self.assertFalse(blocked["can_apply"])
                        self.assertEqual(len(blocked["conflicts"]), 1)
                    result = service.mutate(api.MUTATION, request(service, project, {**setup,
                        "command_id": str(uuid4()), "expected_revision": document["revision_id"],
                        "review_hash": calculation["review_hash"]}))
                    self.assertEqual(sketch.groups(current())[0]["id"], result["sketch_id"])
                    for key in ("geometry", "ports", "connections"):
                        self.assertEqual(current()[key], document[key])
                    self.assertEqual(current()["extensions"]["rfad.smart-dimensions"], document["extensions"]["rfad.smart-dimensions"])
                    self.assertEqual(review(setup)["before"], 0)
                    removal = review({"operation": "remove", "id": result["sketch_id"]})
                    self.assertTrue(removal["can_apply"])
                    self.assertEqual((removal["before"], removal["after"]), (0, degrees))
                    for operation, count in (("project.undo", 0), ("project.redo", 1)):
                        service.mutate(operation, request(service, project, {"command_id": str(uuid4()),
                                                                             "expected_revision": current()["revision_id"]}))
                        self.assertEqual(len(sketch.groups(current())), count)
                    save = service.mutate("project.save", request(service, project, {"expected_revision": current()["revision_id"]}))
                    service.run_next()
                    self.assertEqual(status(service, save["job_id"])["state"], "completed")
                    self.assertEqual(service.journal.read_artifact(snapshot["artifact"]),
                                     canonical_bytes(document))
                with ProjectService(root, auto_run=False) as service:
                    reopened = service._load(service.journal.read()["projects"][project])
                    self.assertEqual(reopened["geometry"], document["geometry"])
                    self.assertEqual(reopened["ports"], document["ports"])
                    self.assertEqual(len(api.get(reopened)["groups"]), 1)
                    settings = SETTINGS if kind == "arc" else IFA_SETTINGS
                    expected = build_pcb_plan(document, snapshot_for(document), runtime_identity(), settings)
                    actual = build_pcb_plan(reopened, snapshot_for(reopened), runtime_identity(), settings)
                    self.assertEqual(actual["case"], expected["case"])

    def test_short_line_stays_non_degenerate_during_rank_evaluation(self):
        """! @brief 차분 간격을 작은 선보다 작게 설정해 기존 분기의 자유도를 유지한다."""
        document, setup = sketch_fixture("arc")
        document["ports"] = []
        document["extensions"] = {}
        left, right = [row for row in document["geometry"] if row["kind"] == "line_path"]
        right["net_id"] = left["net_id"]
        left["start"], left["end"] = [quantity(0, "mm")] * 2, [quantity(0.00001, "mm"), quantity(0, "mm")]
        right["start"] = [quantity(0.000005, "mm"), quantity(0, "mm")]
        right["end"] = [quantity(0.000005, "mm"), quantity(1, "mm")]
        document["geometry"] = [left, right]
        setup.update(selection_ids=[left["id"], right["id"]], datum=sketch.anchor(left["id"], "start"))
        review, _ = api.preview(document, setup)
        self.assertTrue(review["can_apply"], review)
        self.assertEqual((review["before"], review["after"]), (7, 0))

    def test_partial_selection_persists_tangent_without_freezing_all_shapes(self):
        """! @brief 기준 값 한 개만 저장해도 기존 접선과 급전 경계가 이후 편집에 남는다."""
        document, setup = sketch_fixture("arc")
        result, _ = api.preview(document, setup)
        chosen = next(row["id"] for row in result["proposals"] if row["selected"])
        partial, payload = api.preview(document, {**setup, "requested": [chosen]})
        self.assertTrue(partial["can_apply"])
        self.assertEqual((partial["before"], partial["after"]), (6, 5))
        applied = apply_command(document, {"command_id": str(uuid4()), "type": sketch.COMMAND, "payload": payload},
                                document["revision_id"])[0]
        changed = deepcopy(next(row for row in applied["geometry"] if row["kind"] == "arc_path"))
        angle = math.radians(-75)
        changed.update(start_angle=quantity(-75, "deg"),
                       center=[quantity(6 - 2 * math.cos(angle), "mm"), quantity(-2 * math.sin(angle), "mm")])
        with self.assertRaises(ProjectError) as problem:
            apply_command(applied, {"command_id": str(uuid4()), "type": "geometry.set", "payload": {"geometry": changed}},
                          applied["revision_id"])
        self.assertEqual(problem.exception.code, "E_CONFLICT")
        self.assertIn("(tangent)", problem.exception.message)
