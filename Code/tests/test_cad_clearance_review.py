"""! @brief 원호 및 IFA에서 실제 곡면 STEP 간극과 봉인한 개정의 격자만 연결하는지 검증한다."""

import base64
import hashlib
import math
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.cad_clearance_review import map_witness, review as cad_review
from rfad.application.cad_runtime import CadRuntime
from rfad.application.projects import ProjectService
from rfad.application.solver_preview import read
from rfad.domain.errors import ProjectError
from rfad.domain.physical_setup import KEY
from test_cad_worker_process import cad_request, register_fixture, request, status
from test_pcb_ifa import IFA_SETTINGS
from test_pcb_solver import SETTINGS, quantity, runtime_identity
from test_physical_setup import fixture as physical_fixture
from test_project_reviews import read_params
from test_sketch_constraints import sketch_fixture


class CadClearanceTests(unittest.TestCase):
    def test_witness_clipping_and_unknowns(self):
        """! @brief 격자 밖 또는 일부가 겹친 임의의 증거 선분과 접촉점을 구분한다."""
        lines = {axis: [0, 1, 2, 3] for axis in "xyz"}
        def inspect(a, b, distance=None):
            """! @brief 입력 선분을 OCCT 증거점 형식으로 검사한다."""
            row = {"id": "a", "nearest_id": "b", "witness_points_mm": [a, b],
                   "clearance_mm": math.dist(a, b) if distance is None else distance, "relation": "separated"}
            return map_witness(row, lines, {})
        self.assertEqual(inspect([-.5, -.5, 1], [3.5, 3.5, 1])["cells_xyz"], [[0, 0, 1], [1, 1, 1], [2, 2, 1]])
        partial = inspect([-1, 2, 2], [2, 2, 2])
        self.assertEqual((partial["grid_state"], partial["clipped_points_mm"]), ("partial", [[0, 2, 2], [2, 2, 2]]))
        outside = inspect([0, 0, 4], [0, 1, 5])
        self.assertEqual(outside["grid_state"], "outside")
        self.assertNotIn("cells_xyz", outside)
        self.assertEqual(inspect([-1, 1, 1], [1, -1, 1])["grid_state"], "boundary_point")
        self.assertEqual(inspect([.3, .4, .5], [.3, .4, .5])["cells_xyz"], [[0, 0, 0]])
        with self.assertRaises(ProjectError):
            inspect([0, 0, 0], [0, 1, 0], 4)

    @unittest.skipUnless(os.environ.get("RFAD_CAD_PYTHON"), "고정 OCCT CAD Python 필요")
    def test_arc_and_ifa_with_external_spherical_step(self):
        """! @brief 실제 구 STEP 생성, CAD 봉인, 해석 검토, 과거 개정 거절 및 파일 변경 검출을 확인한다."""
        python = os.environ["RFAD_CAD_PYTHON"]
        with TemporaryDirectory() as root:
            sphere = Path(root) / "ball.step"
            subprocess.run([python, "-I", "-c", "import cadquery as cq, sys; "
                "cq.exporters.export(cq.Workplane('XY').sphere(1), sys.argv[1])", str(sphere)], check=True, timeout=120)
            raw = sphere.read_bytes()
            encoded = base64.b64encode(raw).decode("ascii")
            source = {"name": "ball.step", "sha256": hashlib.sha256(raw).hexdigest(),
                      "chunks": [encoded[i:i + 4096] for i in range(0, len(encoded), 4096)]}
            for kind, xy, settings in (("arc", [6, 0], SETTINGS), ("ifa", [25, 57], IFA_SETTINGS)):
                with self.subTest(kind=kind), ProjectService(Path(root) / kind, cad_runtime=CadRuntime(Path(python)), auto_run=False) as service:
                    doc, _ = sketch_fixture(kind)
                    cfg = physical_fixture()["extensions"][KEY]
                    part = cfg["parts"][0]
                    part.update(name="지름 2 mm STEP 구", kind="step", step=source, x=quantity(xy[0], "mm"),
                                y=quantity(xy[1], "mm"), z=quantity(4, "mm"), visible=True, include_in_export=True)
                    doc["extensions"][KEY] = cfg
                    doc, snap = register_fixture(service, doc)
                    with patch.object(service.solver, "runtime", SimpleNamespace(identity=runtime_identity())):
                        self.assertEqual(read(service, read_params(doc, settings=settings))["mesh"]["cad_clearances"]["status"], "missing")
                        job = service.mutate("export.build", cad_request(service, doc, snap))
                        self.assertTrue(service.cad.run_next())
                        result = status(service, job["job_id"])
                        self.assertEqual(result["state"], "completed", result)
                        frozen = service.journal.read()
                        view = read(service, read_params(doc, settings=settings))
                        cad = view["mesh"]["cad_clearances"]
                        self.assertEqual(cad["status"], "available", cad)
                        row, = cad["rows"]
                        self.assertEqual((row["object_ids"][0], row["job_id"], row["revision_id"]), (part["id"], job["job_id"], doc["revision_id"]))
                        self.assertFalse(row["em_included"])
                        self.assertEqual(row["grid_state"], "inside")
                        self.assertTrue(row["cells_xyz"])
                        self.assertAlmostEqual(math.dist(row["witness_points_mm"][0], [*xy, 4]), 1, places=6)
                        self.assertEqual(service.journal.read(), frozen)
                        other = {**frozen, "jobs": {job["job_id"]: {**frozen["jobs"][job["job_id"]],
                                                    "context": {"project_id": str(uuid4())}}}}
                        invisible = cad_review(service, other, doc, view["mesh"]["lines_mm"])
                        self.assertEqual((invisible["status"], invisible["rows"]), ("missing", []))
                        print(kind, row["distance_mm"], row["witness_points_mm"], len(row["cells_xyz"]), flush=True)
                        artifact = next(a for a in frozen["jobs"][job["job_id"]]["artifacts"] if a["role"] == "validation")
                        path = service.journal._safe_path(artifact["uri"])
                        saved = path.read_bytes()
                        path.write_bytes(b"x" + saved[1:])
                        rejected = read(service, read_params(doc, settings=settings))["mesh"]["cad_clearances"]
                        self.assertEqual((rejected["status"], rejected["rows"]), ("invalid", []))
                        path.write_bytes(saved)
                        service.mutate("project.apply_command", request(service, doc["project_id"], {
                            "expected_revision": doc["revision_id"], "command_id": str(uuid4()), "type": "metadata.set",
                            "payload": {"name": "새 개정", "description": "과거 간극 분리"}}))
                        service.run_next()
                        revised = service._load(service.journal.read()["projects"][doc["project_id"]])
                        self.assertNotEqual(revised["revision_id"], doc["revision_id"])
                        excluded = read(service, read_params(revised, settings=settings))["mesh"]["cad_clearances"]
                        self.assertEqual((excluded["status"], excluded["rows"]), ("stale", []))
