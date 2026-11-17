"""! @brief PCB 출력의 실제 원본/표시 층/검토 hash와 기계 미정을 함께 검증한다."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from rfad.application import exchange_contract as contract
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from test_exchange_service import ExchangeFixture, AdmissionRuntime
from test_pcb_features import candidate, hole_record, footprint_record
from test_design import quantity


def prepare(fixture):
    """! @brief 없는 층을 writer가 보충하지 않도록 합성 두 번째 도체를 직접 입력한다."""
    f = fixture
    bottom = deepcopy(f.document["stackup"][-1])
    bottom.update(id=str(uuid4()), name="하부 도체 / 시험 입력", order=0, z_min=quantity(-1.035, "mm"))
    for row in sorted(f.document["stackup"], key=lambda item: item["order"], reverse=True):
        changed = deepcopy(row)
        changed["order"] += 1
        f.command("layer.set", {"layer": changed})
    f.command("layer.set", {"layer": bottom})
    document = f.service._load(f.service.journal.read()["projects"][f.project])
    hole = hole_record(document, x=5, y=5)
    review, _, data = candidate(document, "hole.set", {"record": hole})
    applied = f.service.mutate("pcb.features.apply", f.request({**data, "command_id": str(uuid4()), "review_hash": review["review_hash"]}))
    f.revision = applied["new_revision"]
    f.document = f.service._load(f.service.journal.read()["projects"][f.project])
    f.snapshot = f.complete("snapshot.create", {"expected_revision": f.revision, "description": "PCB 교환 원본 / 공구 미정"})
    return hole


def request(fixture, format_name="kicad_pcb"):
    """! @brief 고정 스냅샷과 해당 형식의 닫힌 옵션만 만든다."""
    profile = next(key for key, value in contract.PCB_PROFILES.items() if value == format_name)
    options = {}
    if format_name == "gerber_job":
        options = {"layer_ids": fixture.read("export.context", {})["pcb"]["default_cam_layer_ids"]}
    return {"snapshot": {key: fixture.snapshot[key] for key in ("snapshot_id", "content_hash")},
            "profile": profile, "format": format_name, "options": options}


class PcbExchangeServiceTests(unittest.TestCase):
    """! @brief 형식 라이브러리 없이 실패와 검토 원본의 경계를 확인한다."""
    def setUp(self):
        self.f = ExchangeFixture(AdmissionRuntime())

    def tearDown(self):
        self.f.close()

    def test_one_copper_board_is_blocked_without_adding_fake_layer(self):
        f = self.f
        before = deepcopy(f.document)
        review = f.complete("export.preview", request(f))
        self.assertFalse(review["can_build"])
        self.assertIn("짝수", review["issues"][0]["message_ko"])
        self.assertEqual(f.service._load(f.service.journal.read()["projects"][f.project]), before)

    def test_layer_display_does_not_change_export_hash_or_source(self):
        f = self.f
        hole = prepare(f)
        data = request(f)
        first = f.complete("export.preview", data)
        self.assertTrue(first["can_build"], first)
        bottom = next(row["id"] for row in f.document["stackup"] if row["order"] == 0)
        second = f.complete("export.preview", {**data, "view_layer_id": bottom})
        self.assertEqual(first["review_hash"], second["review_hash"])
        self.assertNotEqual(first["pages"], second["pages"])
        self.assertIsNone(first["pcb_preview"]["holes"][0]["tool_diameter_mm"])
        value = contract.build_input(f.document, f.snapshot, data, str(uuid4()))
        self.assertEqual(value["projection"]["source_semantics"], f.document)
        self.assertEqual(f.document["pcb"]["holes"][0]["tool_diameter"], hole["tool_diameter"])
        with self.assertRaises(ProjectError):
            f.service.mutate("export.build", f.request({**data, "view_layer_id": bottom, "review_hash": first["review_hash"]}))

    def test_cam_requires_all_declared_used_layers(self):
        f = self.f
        prepare(f)
        data = request(f, "gerber_job")
        self.assertTrue(f.complete("export.preview", data)["can_build"])
        data["options"]["layer_ids"].pop()
        failed = f.complete("export.preview", data)
        self.assertFalse(failed["can_build"])
        self.assertIsNone(failed["review_hash"])


class PcbPreviewScopeTests(unittest.TestCase):
    """! @brief 파일에 포함되지 않는 부품/층을 실제 출력 미리보기로 표시하지 않는다."""
    def test_selected_footprint_only_and_local_coordinates(self):
        from test_pcb_exchange_formats import fixture, add_footprint
        projection = fixture()
        owner, pad = add_footprint(projection)
        projection["omissions"] = []
        projection["names"].update({owner["id"]: "선택한 부품", pad["id"]: "선택한 패드"})
        value = {"format": "kicad_mod", "options": {"footprint_id": owner["id"]}, "projection": projection}
        before = deepcopy(value)
        review = contract.pcb_preview(value, pad["layer_id"])
        self.assertEqual(review["pcb_preview"]["footprints"], [owner])
        self.assertEqual({row["source_id"] for row in review["pages"][0]["primitives"]}, {pad["id"]})
        self.assertEqual(review["pcb_preview"]["coordinate_policy"], "footprint_local_mm_y_up_no_mirror")
        points = [point for row in review["pages"][0]["primitives"] for loop in row["loops"] for edge in loop for point in (edge["start"], edge["end"])]
        self.assertAlmostEqual((min(row[0] for row in points) + max(row[0] for row in points)) / 2, 2.0)
        self.assertAlmostEqual((min(row[1] for row in points) + max(row[1] for row in points)) / 2, 0.0)
        self.assertEqual(value, before)

    def test_via_does_not_appear_beyond_its_explicit_layer_span(self):
        from test_pcb_exchange_formats import fixture
        projection = fixture()
        lower = {"id": str(uuid4()), "name": "내층 1", "role": "conductor", "z_min_mm": .3, "thickness_mm": .035}
        upper = {**lower, "id": str(uuid4()), "name": "내층 2", "z_min_mm": .6}
        projection["layers"][1:1] = [lower, upper]
        via = {"id": str(uuid4()), "kind": "via", "layer_id": projection["layers"][0]["id"], "end_layer_id": lower["id"],
               "net_id": None, "center_mm": [10, 10], "finished_hole_diameter_mm": 1, "plating_thickness_mm": .025}
        projection["shapes"] = [via]
        projection["omissions"] = []
        value = {"format": "kicad_pcb", "options": {}, "projection": projection}
        top = contract.pcb_preview(value, projection["layers"][-1]["id"])
        self.assertNotIn(via["id"], {row["source_id"] for row in top["pages"][0]["primitives"]})
        low = contract.pcb_preview(value, lower["id"])
        self.assertIn(via["id"], {row["source_id"] for row in low["pages"][0]["primitives"]})

    def test_excluded_board_uses_frozen_name_without_storing_temporary_name(self):
        from rfad.application.exchange_service import display_omissions
        from test_cad_projection import cad_fixture
        document = cad_fixture()
        before = deepcopy(document)
        row = display_omissions(document, [{"id": document["board"]["id"], "reason": "outside_selected_footprint"}])[0]
        self.assertNotEqual(row["name_state"], "unresolved")
        self.assertIn("기판", row["label"])
        self.assertEqual(document, before)


@unittest.skipUnless(os.environ.get("RFAD_EXCHANGE_PYTHON"), "별도 실제 PCB 출력 환경을 지정합니다.")
class PcbExchangeNativeTests(unittest.TestCase):
    """! @brief worker가 만든 보드/CAM의 실제 봉인과 환경 없는 재열기를 확인한다."""
    def test_actual_board_and_cam_preserve_source_and_fresh_verification(self):
        f = ExchangeFixture(ExchangeRuntime(Path(os.environ["RFAD_EXCHANGE_PYTHON"])))
        try:
            prepare(f)
            original = deepcopy(f.document)
            records = []
            for format_name in ("kicad_pcb", "gerber_job"):
                data = request(f, format_name)
                preview = f.complete("export.preview", data)
                self.assertTrue(preview["can_build"], preview)
                task = f.service.mutate("export.build", f.request({**data, "review_hash": preview["review_hash"]}))
                f.service.exchange.run_next()
                record = f.read("export.get", {"job_id": task["job_id"]})
                self.assertEqual(record["state"], "completed", record)
                source = next(row for row in record["result"]["artifacts"] if row["role"] == "source")
                self.assertEqual(json.loads(f.service.journal.read_artifact(source))["source_semantics"], original)
                self.assertFalse(record["report"]["manufacturing_verified"])
                checked = f.service.mutate("export.verify", f.request({"job_id": task["job_id"], "manifest_sha256": record["manifest_sha256"]}))
                f.service.exchange.run_next()
                repeated = f.read("export.get", {"job_id": checked["job_id"]})
                self.assertEqual(repeated["state"], "completed", repeated)
                records.extend(((task, record), (checked, repeated)))
            f.complete("project.save", {"expected_revision": f.revision})
            f.service.close()
            f.service = ProjectService(f.workspace, auto_run=False)
            self.assertEqual(f.service._load(f.service.journal.read()["projects"][f.project]), original)
            for task, record in records:
                self.assertEqual(f.read("export.get", {"job_id": task["job_id"]}), record)
        finally:
            f.close()
