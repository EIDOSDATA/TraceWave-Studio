"""! @brief 원호 및 IFA 프로젝트에서 선택한 도체 사이의 연립 관계를 대조한다."""

from copy import deepcopy
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application import precision_service as precision
from rfad.application import sketch_service as api
from rfad.application.projects import ProjectService
from rfad.domain import sketch_constraints as sketch
from rfad.domain.project import apply_command
from test_cad_worker_process import register_fixture, request, status
from test_pcb_solver import quantity
from test_sketch_constraints import sketch_fixture


def xy(x, y):
    """! @brief 기존 좌표계의 정규 길이를 만든다."""
    return [quantity(x, "mm"), quantity(y, "mm")]


def candidate(rows, prefix):
    """! @brief 사용자가 보는 문구에서 관계를 찾아 안정 식별자를 반환한다."""
    return next(row["id"] for row in rows if row["label"].startswith(prefix))


def submit(service, document, data):
    """! @brief 현재 설계 검토를 통과한 명령만 실제 저장소에 적용한다."""
    project = document["project_id"]
    source = {"expected_revision": document["revision_id"], **data}
    preview = api.read(service, api.PREVIEW, {"contract_version": "rfad.api/2.0",
                                             "context": {"project_id": project}, "input": source})
    if not preview["can_apply"]:
        raise AssertionError((preview["message"], preview["conflicts"]))
    service.mutate(api.MUTATION, request(service, project, {**source, "command_id": str(uuid4()),
                                                            "review_hash": preview["review_hash"]}))
    return service._load(service.journal.read()["projects"][project])


class PairedSketchConstraintTests(unittest.TestCase):
    def test_shared_radius_respects_existing_precision_dimension_parameter_and_group(self):
        """! @brief 정밀 반경을 상대 원호로 덮어쓰지 않고 기존 변수·구동 그룹과 중복한 관계도 막는다."""
        source, setup = sketch_fixture("arc")
        original = next(row for row in source["geometry"] if row["kind"] == "arc_path")
        ids = []
        for index, radius in enumerate((1, .8, 1)):
            arc = deepcopy(original)
            arc.update(id=str(uuid4()), name=f"정밀 반경 {index}", center=xy(-5 + index * 3, 4),
                       radius=quantity(radius, "mm"), start_angle=quantity(index * 45, "deg"),
                       sweep_angle=quantity(60, "deg"))
            ids.append(arc["id"])
            source["geometry"].append(arc)
        source["geometry"].sort(key=lambda row: row["id"])

        def apply(document, operation, payload):
            """! @brief 읽기 검토의 후보 명령을 현재 개정에 실제 적용한다."""
            return apply_command(document, {"command_id": str(uuid4()), "type": operation,
                                 "payload": payload}, document["revision_id"])[0]

        def precision_edit(document, identity, operation, values):
            """! @brief 반경 변경 또는 변수 결합의 정밀 편집 원문과 개정을 함께 만든다."""
            review, patch = precision.preview(document, {"expected_revision": document["revision_id"],
                "operation": operation, "selection_ids": [identity], "values": {"dimension_key": "arc.radius", **values}})
            self.assertTrue(review["can_apply"], review["notices"])
            return apply(document, precision.COMMANDS[0], patch)

        source = precision_edit(source, ids[1], "dimension_set", {"value": 1, "unit": "mm"})
        pair = {**setup, "datum": sketch.anchor(ids[0], "center"), "selection_ids": ids[:2]}
        prior_shape = deepcopy(source["geometry"])
        first = api.preview(source, pair)[0]
        equal = candidate(first["proposals"], "두 원호의 동일 반경")
        relation, patch = api.preview(source, {**pair, "requested": [equal]})
        self.assertTrue(relation["can_apply"])
        radii = [row for row in relation["proposals"] if row["label"].startswith("원호 반경")]
        self.assertEqual([row["state"] for row in radii], ["redundant", "redundant"])
        for radius in radii:
            denied, _ = api.preview(source, {**pair, "requested": [equal, radius["id"]]})
            self.assertFalse(denied["can_apply"])
        joined = apply(source, sketch.COMMAND, patch)
        self.assertEqual(joined["geometry"], prior_shape)
        self.assertFalse(api.get(joined)["groups"][0]["dimensions"])

        parameter = str(uuid4())
        bound = apply(source, "parameter.set", {"id": parameter, "name": "반경 조건", "quantity": quantity(1, "mm")})
        bound = precision_edit(bound, ids[0], "bind_dimension", {"parameter_id": parameter})

        other = {**pair, "selection_ids": [ids[0], ids[2]]}
        rows = api.preview(source, other)[0]["proposals"]
        other_equal = candidate(rows, "두 원호의 동일 반경")
        rows = api.preview(source, {**other, "requested": [other_equal]})[0]["proposals"]
        other_review, patch = api.preview(source, {**other, "requested": [other_equal, candidate(rows, "원호 반경")]})
        self.assertTrue(other_review["can_apply"])
        grouped = apply(source, sketch.COMMAND, patch)
        for document in (bound, grouped):
            rows = api.preview(document, pair)[0]["proposals"]
            self.assertEqual(next(row["state"] for row in rows if row["id"] == equal), "redundant")
            self.assertFalse(api.preview(document, {**pair, "requested": [equal]})[0]["can_apply"])

    def test_shared_driving_dimension_and_reopen(self):
        """! @brief 동일 길이 및 반경 한 곳을 고쳐 두 원본이 바뀌는지 저장 후 비교한다."""
        for board in ("arc", "ifa"):
            with self.subTest(board=board), TemporaryDirectory() as folder:
                source, setup = sketch_fixture(board)
                curved = board == "arc"
                kind = "arc_path" if curved else "line_path"
                original = next(item for item in source["geometry"] if item["kind"] == kind)
                copies = []
                for index in range(2):
                    item = deepcopy(original)
                    item.update(id=str(uuid4()), name="검수 기준 " + str(index + 1))
                    if curved:
                        item.update(center=xy(-4, 4), radius=quantity(1, "mm"),
                                    start_angle=quantity(180 * index, "deg"), sweep_angle=quantity(60, "deg"))
                    else:
                        item.update(start=xy(1, 6 + index), end=xy(3, 6 + index))
                    copies.append(item)
                source["geometry"].extend(copies)
                source["geometry"].sort(key=lambda row: row["id"])
                ids = [item["id"] for item in copies]
                setup.update(selection_ids=ids, datum=sketch.anchor(ids[0], "center" if curved else "start"))
                prefix = "두 원호의 동일 반경" if curved else "두 선의 동일 길이"
                related = "두 원호의 동심" if curved else "두 선의 평행"
                first, _ = api.preview(source, setup)
                dimension_id = candidate(first["proposals"], prefix)
                only_dimension, _ = api.preview(source, {**setup, "requested": [dimension_id]})
                self.assertEqual(only_dimension["before"], first["before"])
                self.assertEqual(only_dimension["after"], first["before"] + (1 if curved else -1))
                selected = [dimension_id, candidate(first["proposals"], related)]
                second, _ = api.preview(source, {**setup, "requested": selected})
                selected.append(candidate(second["proposals"], "원호 반경" if curved else "선 길이"))
                with ProjectService(Path(folder), auto_run=False) as service:
                    document, _ = register_fixture(service, source)
                    applied = submit(service, document, {**setup, "requested": selected})
                    group, = api.get(applied)["groups"]
                    index = group["dimensions"][0]["index"]
                    solved = submit(service, applied, {"operation": "solve", "id": group["id"],
                                                       "edits": [{"index": index, "value": 1.5 if curved else 3}]})
                    job = service.mutate("project.save", request(service, solved["project_id"],
                                         {"expected_revision": solved["revision_id"]}))
                    service.run_next()
                    self.assertEqual(status(service, job["job_id"])["state"], "completed")
                with ProjectService(Path(folder), auto_run=False) as reopened:
                    model_document = reopened._load(reopened.journal.read()["projects"][solved["project_id"]])
                    self.assertEqual(model_document["geometry"], solved["geometry"])
                    self.assertEqual(model_document["ports"], source["ports"])
                    self.assertEqual(model_document["connections"], source["connections"])
                    saved, = sketch.groups(model_document)
                    self.assertEqual(saved["constraints"], sketch.groups(solved)[0]["constraints"])
                    model = sketch.Model(model_document)
                    for identity in ids:
                        model.shape(identity)
                        ref = sketch.anchor(identity, "center" if curved else "start")
                        if curved:
                            actual = model.values[identity]["radius"]
                        else:
                            actual = math.dist(model.location(ref), model.location(sketch.anchor(identity, "end")))
                        self.assertAlmostEqual(actual, 1.5 if curved else 3)
                    for row in saved["constraints"]:
                        self.assertLessEqual(max(map(abs, model.residual(row))), sketch.TOLERANCE)

    def test_axis_mirror_follows_datum_and_rejects_incompatible_direction(self):
        """! @brief 세 객체의 축 대칭을 저장하고 대칭을 깨는 편집 및 직교 충돌을 검출한다."""
        source, setup = sketch_fixture("ifa")
        line = next(item for item in source["geometry"] if item["kind"] == "line_path")
        selected = []
        for x, y in ((6, 4), (6, 2), (1, 3)):
            item = deepcopy(line)
            item.update(id=str(uuid4()), name=f"대칭 기준 {len(selected) + 1}", start=xy(x, y), end=xy(x + 1, y))
            source["geometry"].append(item)
            selected.append(item["id"])
        source["geometry"].sort(key=lambda row: row["id"])
        setup.update(selection_ids=selected, datum=sketch.anchor(selected[-1], "start"))
        rows = api.preview(source, setup)[0]["proposals"]
        mirror = candidate(rows, "기준축 대칭점")
        perpendicular = candidate(rows, "두 선의 직교")
        blocked, _ = api.preview(source, {**setup, "requested": [perpendicular]})
        self.assertFalse(blocked["can_apply"])
        checked, payload = api.preview(source, {**setup, "requested": [mirror]})
        self.assertTrue(checked["can_apply"], checked["message"])
        self.assertEqual(checked["before"] - checked["after"], 2)
        document = apply_command(source, {"command_id": str(uuid4()), "type": sketch.COMMAND, "payload": payload},
                                 source["revision_id"])[0]
        model = sketch.Model(document)
        relation = sketch.groups(document)[0]["constraints"][0]
        self.assertEqual(max(map(abs, model.residual(relation))), 0)
        model.values[selected[-1]]["sy"] += 0.25
        self.assertAlmostEqual(max(map(abs, model.residual(relation))), 0.25)
