"""! @brief 해석 조건 비교와 실제 격자 진단의 후속 동작을 검증한다."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from uuid import uuid4

from rfad.application import pcb_clearance_review, solver_preview
from rfad.application.pcb_execution import energy_observations, latest_energy_observation, valid_energy_observation
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.physical_setup import KEY as PHYSICAL_KEY, setup
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture, request
from test_pcb_ifa import ifa_document, IFA_SETTINGS
from test_pcb_solver import fixture_document, runtime_identity, SETTINGS
from test_pcb_surfaces import add_mask, rectangle
from test_solver_conditions import query


class SolverReviewFollowup(unittest.TestCase):
    def test_planar_clearance_uses_solver_polygons_and_grid_cells(self):
        """! @brief 대각선 간극과 격자 교차, 도체 겹침 및 다른 층을 구분한다."""
        from unittest.mock import patch

        def conductor(identity, x, y, size, z=0):
            """! @brief 실제 해석 입력 DTO와 같은 폐곡선 도체를 구성한다."""
            return {"id": identity, "name": identity, "role": "conductor", "primitives": [
                {"kind": "polygon", "points_mm": [(x, y), (x + size, y),
                    (x + size, y + size), (x, y + size)], "z_mm": [z, z]}]}

        a = conductor("a", 0, 0, 1)
        b = conductor("b", 2, 2, 1)
        lines = {axis: [0, 1, 1.25, 1.5, 1.75, 2, 3] for axis in "xy"}
        rows = [a, b, conductor("another sheet", 2, 2, 1, z=1)]
        exact = pcb_clearance_review.planar_clearances(rows, lines, 1)
        gap, = exact["clearances"]
        self.assertEqual((exact["pair_evaluated"], exact["pair_total"]), (1, 1))
        self.assertAlmostEqual(gap["distance_mm"], 2**0.5)
        self.assertEqual(gap["points_mm"], [(1, 1), (2, 2)])
        self.assertEqual(gap["cells_xy"], [[1, 1], [2, 2], [3, 3], [4, 4]])
        for overlap in (conductor("enclosed", .25, .25, .5), conductor("touch", 1, 1, 1),
                        conductor("crossing", .75, -.25, .75)):
            self.assertEqual(pcb_clearance_review.planar_clearances([a, overlap], lines, 1)["clearances"], [])
        with patch.object(pcb_clearance_review, "EDGE_PAIR_LIMIT", 0):
            limited = pcb_clearance_review.planar_clearances(rows, lines, 1)
        self.assertEqual((limited["pair_evaluated"], limited["pair_total"]), (0, 1))
        self.assertEqual(limited["clearances"], [])


    def test_conditions_comparison_and_multiple_blockers(self):
        """! @brief 원호와 IFA의 보존값은 편집과 독립이며 같은 요청에서 재료와 급전을 확인한다."""
        for document, settings in ((fixture_document(arc=True), SETTINGS), (ifa_document(), IFA_SETTINGS)):
            with self.subTest(document=document["metadata"]["name"]), TemporaryDirectory() as folder:
                with ProjectService(Path(folder), auto_run=False) as service:
                    service.solver.runtime = SimpleNamespace(identity=runtime_identity())
                    source, _ = register_fixture(service, document)
                    identity = source["project_id"]
                    service.mutate("solver.conditions.save", request(service, identity, {
                        "expected_revision": source["revision_id"], "command_id": str(uuid4()),
                        "name": "원래 조건", "settings": settings}))
                    def current():
                        return service._load(service.journal.read()["projects"][identity])

                    original = current()
                    record = query(service, original)["saved"][0]
                    port = deepcopy(original["ports"][0])
                    old = port["resistance"]
                    port["resistance"] = Quantity.missing("impedance", "ohm").to_dict()
                    dielectric = next(row["material_id"] for row in original["stackup"] if row["role"] == "dielectric")
                    material = deepcopy(next(row for row in original["materials"] if row["id"] == dielectric))
                    material["epsilon_r"] = Quantity.missing("dimensionless", "1").to_dict()
                    for command, payload in (("port.set", {"port": port}), ("material.set", {"material": material})):
                        service.mutate("project.apply_command", request(service, identity, {
                            "expected_revision": current()["revision_id"], "command_id": str(uuid4()),
                            "type": command, "payload": payload}))
                    editing = current()
                    state = service.journal.read()
                    result = query(service, editing, condition_id=record["id"])
                    rows = result["configuration"]["items"]
                    resistance = next(row for row in rows if row["key"] == "resistance")
                    self.assertEqual(resistance["source"], f'{old["value_si"]:.17g} ohm')
                    self.assertIsNone(resistance["current"])
                    self.assertTrue(resistance["current_exists"])
                    params = {"contract_version": "rfad.api/2.0", "context": {"project_id": identity},
                              "input": {"expected_revision": editing["revision_id"], "settings": settings}}
                    with self.assertRaises(ProjectError):
                        solver_preview.read(service, params)
                    params["input"]["include_all_diagnostics"] = True
                    warnings = solver_preview.read(service, params)["blocking_diagnostics"]
                    paths = [row["details"]["field_path"] for row in warnings]
                    self.assertTrue(any(path.startswith("materials.") for path in paths), warnings)
                    self.assertIn(f'ports.{port["id"]}.resistance', paths)
                    self.assertEqual(service.journal.read(), state)

    def test_surface_and_gap_report_follow_actual_axes(self):
        """! @brief 두 형상에서 개구와 선택 영역을 실제 격자선 및 CFL 참고값과 대조한다."""
        for document, settings in ((fixture_document(arc=True), SETTINGS), (ifa_document(), IFA_SETTINGS)):
            with self.subTest(document=document["metadata"]["name"]), TemporaryDirectory() as folder:
                document["extensions"].setdefault(PHYSICAL_KEY, setup(document))
                dielectric = next(row["material_id"] for row in document["stackup"] if row["role"] == "dielectric")
                mask = add_mask(document)
                mask["material_id"] = dielectric
                mask["openings"] = [rectangle(2, 2, 1, 1)]
                with ProjectService(Path(folder), auto_run=False) as service:
                    service.solver.runtime = SimpleNamespace(identity=runtime_identity())
                    source, _ = register_fixture(service, document)
                    def preview(**extra):
                        return solver_preview.read(service, {
                            "contract_version": "rfad.api/2.0", "context": {"project_id": source["project_id"]},
                            "input": {"expected_revision": source["revision_id"], "settings": {**settings, **extra}}})

                    choices = query(service, source)["local_mesh_targets"]
                    opening = next(row for row in choices if row["kind"] == "surface_opening")
                    original = preview()["mesh"]
                    bounds = original["model_bounds_mm"]
                    region = [[lo + (hi - lo) / 4, lo + (hi - lo) / 3] for lo, hi in bounds]
                    target = {"kind": "surface_opening", "object_id": mask["id"],
                              "opening_sha256": opening["opening_sha256"], "priority": 75,
                              "max_cell_mm": {"x": .2, "y": .2, "z": .05}}
                    reported = preview(local_mesh=[target, {"kind": "gap", "name": "선택 영역", "bounds_mm": region,
                                                            "priority": 20, "max_cell_mm": {"x": .2}}])["mesh"]
                    self.assertNotEqual(reported["lines_sha256"], original["lines_sha256"])
                    report = reported["interval_report"]
                    self.assertGreater(report["vacuum_cartesian_cfl_seconds"], 0)
                    self.assertEqual(sum(row["kind"] == "minimum_cell" for row in report["intervals"]), 3)
                    self.assertTrue(any(row["kind"] == "surface_opening" and row["full_cells"] >= 5
                                        for row in report["intervals"]))
                    self.assertTrue(any(row["kind"] == "local_gap" and row["cells"] > 0 for row in report["intervals"]))
                    with self.assertRaisesRegex(ProjectError, "개구의 위치"):
                        preview(local_mesh=[{**target, "opening_sha256": "0" * 64}])

    def test_decay_preserves_log_sign_and_final_sample(self):
        """! @brief 부호가 있는 관측값과 정확히 종료한 마지막 표본을 유지한다."""
        log = ("[@ 12s] Timestep: 248 || Speed: 41.1 MC/s || Energy: ~2.31e-02 (- 14.37dB)\\n"
               "[@ 25s] Timestep: 496 || Speed: 40.9 MC/s || Energy: ~1.17e+00 (+ 0.72dB)")
        history = energy_observations(log, {"iterations": 500, "reported_zero_energy": False, "reported_decay_db": 30.8})
        self.assertEqual([row["decay_db"] for row in history["samples"]], [14.37, -0.72, 30.8])
        self.assertEqual([row["final"] for row in history["samples"]], [False, False, True])
        latest = latest_energy_observation(log, 500)
        self.assertEqual(latest, history["samples"][1])
        self.assertTrue(valid_energy_observation(latest))
        self.assertFalse(valid_energy_observation({**latest, "reported_energy": -1}))
        self.assertFalse(valid_energy_observation({**latest, "final": True}))
        self.assertIsNone(latest_energy_observation(log, 200))
