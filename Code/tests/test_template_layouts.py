"""! @brief 사용자가 지정한 한 설치 영역에서 생성된 두 PCB 후보를 검증한다."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from test_cad_worker_process import register_fixture, request, status
from rfad.application.template_layouts import screen
from rfad.domain.pcb_features import empty_pcb
from test_pcb_features import keepout_record
from rfad.domain.project import apply_command, validate_project
from rfad.templates.cards import ARC, IFA
from test_targets import target_input
from test_template_candidates import apply_payload, base_document, preview, specification


class LayoutTests(unittest.TestCase):
    """! @brief 요구에 맞는 실제 형상 생성, 저장과 기존 장애물에 의한 제외를 검사한다."""

    def test_populated_cards_bounds_and_obstacles(self):
        """! @brief 원호와 IFA 양쪽을 재열고 설치 영역 및 같은 층 도체와의 충돌을 보인다."""
        document = base_document(IFA)
        target = target_input(start=2.4, end=2.6)
        document = apply_command(document, {"command_id": str(uuid4()), "type": "target.set",
            "payload": {"target": target}}, document["revision_id"])[0]
        design = specification(document, IFA)
        options = {"expected_revision": document["revision_id"], "target_id": document["targets"][0]["id"],
                   "binding": design["binding"], "instance_id": design["instance_id"],
                   "region_mm": [2, 2, 38, 55], "width_mm": 1, "ground_height_mm": 25,
                   "feed_gap_mm": 2, "branch_pitch_mm": 4, "clearance_mm": .2}
        before = deepcopy(document)
        proposed = screen(document, options)
        self.assertEqual(document, before)
        self.assertFalse(proposed["rf_evaluated"])
        with TemporaryDirectory() as folder, ProjectService(Path(folder), auto_run=False) as service:
            register_fixture(service, document)
            params = {"contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]}, "input": options}
            frame = {"jsonrpc": "2.0", "id": 1, "method": "template.layout_candidates", "params": params}
            response = handle_frame(json.dumps(frame).encode("utf8"), service)
            self.assertIn("result", response, response)
            self.assertEqual(response["result"], proposed)
        a, b = proposed["candidates"]
        self.assertTrue(all(c["available"] for c in (a,b)), proposed)
        for kind, row in ((ARC, a), (IFA, b)):
            inputs = specification(document, kind)
            inputs.update(instance_id=options["instance_id"], explicit_inputs=row["requested_inputs"],
                          target_refs=[{k: document["targets"][0][k] for k in ("id", "revision_id")}])
            review, payload = preview(document, inputs)
            self.assertTrue(review["can_apply"], review)
            saved = apply_payload(document, payload)[0]
            validate_project(json.loads(canonical_bytes(saved)))
            self.assertTrue(all(v["status"] == "estimated" for v in payload["replacement"]["inputs"].values()))
            project_id = document["project_id"]
            with TemporaryDirectory() as folder:
                with ProjectService(Path(folder), auto_run=False) as service:
                    register_fixture(service, document)
                    command = {**inputs, "command_id": str(uuid4()), "preview_hash": review["preview_hash"]}
                    applied = service.mutate("template.apply", request(service, project_id, command))
                    revision = applied["new_revision"]
                    job = service.mutate("project.save", request(service, project_id, {"expected_revision": revision}))
                    self.assertTrue(service.run_next())
                    self.assertEqual(status(service, job["job_id"])["state"], "completed")
                    original = service._load(service.journal.read()["projects"][project_id])
                with ProjectService(Path(folder), auto_run=False) as reopened:
                    record = reopened.journal.read()["projects"][project_id]
                    self.assertEqual(record["current"], record["saved"])
                    restored = reopened._load(record)
                    self.assertEqual(restored, original)
                    self.assertEqual(restored["geometry"], saved["geometry"])
            current = screen(saved, {**options, "instance_id": str(uuid4())})
            same = next(c for c in current["candidates"] if c["template_id"] == kind)
            self.assertFalse(same["available"])
            self.assertIn("간격", same["reason"])
        narrow = screen(document, {**options, "region_mm": [2, 2, 6, 7]})
        self.assertFalse(any(c["available"] for c in narrow["candidates"]))

        outside = screen(document, {**options, "region_mm": [50, 50, 87, 115]})
        self.assertTrue(all(not row["available"] and row["code"] == "E_GEOMETRY" for row in outside["candidates"]), outside)
        keepout = keepout_record(document, x=5, y=15, all_layers=True)
        keepout["prohibit"]["copper_pours"] = True
        restricted = {**document, "pcb": {**empty_pcb(), "keepouts": [keepout]}}
        screened = screen(restricted, options)
        arc, ifa = screened["candidates"]
        self.assertTrue(arc["available"], arc)
        self.assertFalse(ifa["available"], ifa)
        self.assertIn(keepout["id"], ifa["reason"])
