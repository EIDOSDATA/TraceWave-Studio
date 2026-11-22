"""! @brief 해석 조건 비교와 실제 격자 진단의 후속 동작을 검증한다."""

from copy import deepcopy
import math
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
        rows = [a, b, conductor("distant sheet", 2, 2, 1, z=3)]
        exact = pcb_clearance_review.planar_clearances(rows, lines, 1)
        gap, = exact["clearances"]
        self.assertEqual((exact["pair_evaluated"], exact["pair_total"]), (1, 1))
        self.assertAlmostEqual(gap["distance_mm"], 2**0.5)
        self.assertEqual(gap["points_mm"], [(1, 1), (2, 2)])
        self.assertEqual(gap["cells_xy"], [[1, 1], [2, 2], [3, 3], [4, 4]])
        layered = {**lines, "z": [0, .25, .5, .75, 1, 2]}
        direct = conductor("upper layer", 0, 0, 1, z=1)
        vertical, = pcb_clearance_review.planar_clearances([a, direct], layered, 1)["clearances"]
        self.assertEqual(vertical["distance_mm"], 1)
        self.assertEqual(vertical["other_z_mm"], 1)
        self.assertEqual(vertical["points_mm"], [(0, 0), (0, 0)])
        self.assertEqual(vertical["cells_xyz"], [[0, 0, i] for i in range(4)])
        offset = conductor("offset upper layer", 2, 2, 1, z=1)
        diagonal, = pcb_clearance_review.planar_clearances([a, offset], layered, 1)["clearances"]
        self.assertAlmostEqual(diagonal["distance_mm"], 3**0.5)
        self.assertEqual(diagonal["points_mm"], [(1, 1), (2, 2)])
        self.assertEqual(diagonal["cells_xyz"], [[i + 1, i + 1, i] for i in range(4)])
        for overlap in (conductor("enclosed", .25, .25, .5), conductor("touch", 1, 1, 1),
                        conductor("crossing", .75, -.25, .75)):
            self.assertEqual(pcb_clearance_review.planar_clearances([a, overlap], lines, 1)["clearances"], [])
        with patch.object(pcb_clearance_review, "EDGE_PAIR_LIMIT", 0):
            limited = pcb_clearance_review.planar_clearances(rows, lines, 1)
        self.assertEqual((limited["pair_evaluated"], limited["pair_total"]), (0, 1))
        self.assertEqual(limited["clearances"], [])


    def test_via_barrel_and_environment_volume_use_exact_boundaries(self):
        """! @brief 보어 내부, 도금 접촉, Z 높이차와 설치물별 상자의 정확한 간극을 확인한다."""
        def barrel(identity, x, inner, outer, lo=0, hi=2):
            """! @brief 모델 검토의 관통 배럴 표현을 사용한다."""
            circle = {"kind": "circle", "center_mm": [x, 0], "radius_mm": outer, "z_mm": [lo, hi]}
            return {"id": identity, "name": identity, "role": "via",
                    "primitives": [circle, {**circle, "radius_mm": inner, "opening": True}]}

        def box(identity, bounds):
            """! @brief 해석에 투입된 설치물의 닫힌 상자를 만든다."""
            return {"id": identity, "name": identity, "role": "environment",
                    "primitives": [{"kind": "box", "bounds_mm": bounds}]}

        lines = {axis: list(range(-5, 10)) for axis in "xyz"}
        a = barrel("a", 0, 2, 3)
        inner = barrel("inside", 0, .25, 1)
        separate, = pcb_clearance_review.planar_clearances([a, inner], lines, 1)["clearances"]
        self.assertAlmostEqual(separate["distance_mm"], 1)
        self.assertEqual(separate["points_mm"], [(2, 0), (1, 0)])
        self.assertEqual(separate["object_roles"], ["via", "via"])
        crossed = barrel("crossing", 4, 1, 2)
        self.assertEqual(pcb_clearance_review.planar_clearances([a, crossed], lines, 1)["clearances"], [])
        pad = {"id": "pad", "name": "pad", "role": "conductor", "primitives": [
            {"kind": "polygon", "points_mm": [(2, -.5), (4, -.5), (4, .5), (2, .5)], "z_mm": [2, 2]}]}
        self.assertEqual(pcb_clearance_review.planar_clearances([a, pad], lines, 1)["clearances"], [])
        displaced = box("offset", [[4, 5], [-1, 1], [3, 5]])
        gap, = pcb_clearance_review.planar_clearances([a, displaced], lines, 1)["clearances"]
        self.assertAlmostEqual(gap["distance_mm"], 2**.5)
        self.assertEqual(gap["points_mm"], [(3, 0), (4, 0)])
        self.assertEqual([gap["z_mm"], gap["other_z_mm"]], [2, 3])
        self.assertEqual(gap["cells_xyz"], [[8, 5, 7]])
        centered = box("above", [[2.1, 2.5], [-.1, .1], [3, 5]])
        gap, = pcb_clearance_review.planar_clearances([a, centered], lines, 1)["clearances"]
        self.assertEqual(gap["distance_mm"], 1)
        self.assertEqual(gap["points_mm"][0], gap["points_mm"][1])

    def test_dielectric_cylinder_keeps_outer_and_inner_boundary_gaps(self):
        """! @brief 비도금 관통 홀이 내부 간극을 추가하며 외곽 원통 간극도 보존한다."""
        dielectric = {"id": "core", "name": "core", "role": "dielectric", "primitives": [
            {"kind": "circle", "center_mm": [0, 0], "radius_mm": 2, "z_mm": [0, 1]}]}
        surface = {"id": "coat", "name": "coat", "role": "surface", "primitives": [
            {"kind": "box", "bounds_mm": [[2.4, 3], [-.5, .5], [.25, .75]]}]}
        lines = {axis: [count / 4 for count in range(-16, 17)] for axis in "xyz"}
        gap, = pcb_clearance_review.planar_clearances([dielectric, surface], lines, 1)["clearances"]
        self.assertAlmostEqual(gap["distance_mm"], .4)
        self.assertEqual(gap["points_mm"], [(2.0, 0.0), (2.4, 0.0)])
        drilled = {"id": "hole", "name": "hole", "role": "void", "primitives": [
            {"kind": "circle", "center_mm": [0, 0], "radius_mm": .5, "z_mm": [0, 1]}]}
        inside = {"id": "part", "name": "part", "role": "environment", "primitives": [
            {"kind": "box", "bounds_mm": [[.1, .2], [-.2, .2], [.25, .75]]}]}
        report = pcb_clearance_review.planar_clearances([dielectric, surface, drilled, inside], lines, 1)
        self.assertEqual(report["volume_omitted_count"], 0)
        clearances = {frozenset(row["object_ids"]): row for row in report["clearances"]}
        self.assertEqual(clearances[frozenset({"core", "coat"})], gap)
        inner = clearances[frozenset({"core", "part"})]
        self.assertAlmostEqual(inner["distance_mm"], .5 - math.hypot(.2, .2))
        self.assertAlmostEqual(math.hypot(*inner["points_mm"][0]), .5)
        self.assertEqual(abs(inner["points_mm"][1][0]), .2)
        self.assertEqual(abs(inner["points_mm"][1][1]), .2)
        self.assertTrue(inner["cells_xy"])
        partial = {"kind": "circle", "center_mm": [0, 0], "radius_mm": .5, "z_mm": [0, .5]}
        report = pcb_clearance_review.planar_clearances([dielectric, {**drilled, "primitives": [partial]}], lines, 1)
        self.assertEqual(report["volume_omitted_count"], 1)

    def test_rectangular_and_slotted_cutouts_use_only_real_walls(self):
        """! @brief 다각형의 직선 면과 슬롯의 캡 및 직선 벽에 대한 독립 최솟값을 확인한다."""
        core = {"id": "core", "name": "core", "role": "dielectric", "primitives": [
            {"kind": "box", "bounds_mm": [[-4, 4], [-4, 4], [0, 1]]}]}
        slot = [{"kind": "polygon", "points_mm": [[0, .5], [0, -.5], [2, -.5], [2, .5]], "z_mm": [0, 1]},
                {"kind": "circle", "center_mm": [0, 0], "radius_mm": .5, "z_mm": [0, 1]},
                {"kind": "circle", "center_mm": [2, 0], "radius_mm": .5, "z_mm": [0, 1]}]
        polygon = [{"kind": "polygon", "points_mm": [[-2, -1], [-1, -1], [-1, 0], [-2, 0]], "z_mm": [0, 1]}]
        lines = {axis: [count / 10 for count in range(-41, 42)] for axis in "xyz"}
        for primitives, bounds, expected in (
                (slot, [[.9, 1.1], [-.1, .2], [.25, .75]], .3),
                (slot, [[-.35, -.3], [-.1, .1], [.25, .75]], .5 - math.hypot(.35, .1)),
                (polygon, [[-1.8, -1.5], [-.6, -.4], [.25, .75]], .2)):
            with self.subTest(primitives=len(primitives), bounds=bounds):
                void = {"id": "void", "name": "void", "role": "void", "primitives": primitives}
                part = {"id": "part", "name": "part", "role": "environment", "primitives": [
                    {"kind": "box", "bounds_mm": bounds}]}
                report = pcb_clearance_review.planar_clearances([core, void, part], lines, .5)
                self.assertEqual(report["volume_omitted_count"], 0)
                row, = report["clearances"]
                self.assertAlmostEqual(row["distance_mm"], expected, places=11)
                self.assertTrue(row["cells_xy"])

    def test_real_arc_and_ifa_plans_keep_mechanical_cutouts_in_clearance_review(self):
        """! @brief 실제 검토 환경에서 원호와 IFA의 관통 절삭 후 유전체 경계를 사용한다."""
        from rfad.domain.pcb_features import empty_pcb
        from test_pcb_features import hole_record

        for fixture, settings, center in ((fixture_document(arc=True), SETTINGS, (3, 2)),
                                          (ifa_document(), IFA_SETTINGS, (32, 12))):
            with self.subTest(fixture=fixture["metadata"]["name"]), TemporaryDirectory() as directory:
                fixture["pcb"] = empty_pcb()
                hole = hole_record(fixture, x=center[0], y=center[1], diameter=1.5)
                hole["name"] = "비도금 관통 홀"
                fixture["pcb"]["holes"].append(hole)
                with ProjectService(Path(directory), auto_run=False) as service:
                    service.solver.runtime = SimpleNamespace(identity=runtime_identity())
                    document, _ = register_fixture(service, fixture)
                    before = service.journal.read()
                    preview = solver_preview.read(service, {"contract_version": "rfad.api/2.0",
                        "context": {"project_id": document["project_id"]},
                        "input": {"expected_revision": document["revision_id"], "settings": settings}})
                    primitive, = next(row for row in preview["model"]["included"] if row["id"] == hole["id"])["primitives"]
                    self.assertEqual(primitive["center_mm"], list(center))
                    self.assertEqual(primitive["radius_mm"], .75)
                    self.assertEqual(preview["mesh"]["planar_clearances"]["volume_omitted_count"], 0)
                    self.assertEqual(service.journal.read(), before)

    def test_boundary_faces_follow_native_order_and_do_not_mark_absent_pml(self):
        """! @brief 기존 격자와 혼합 외벽을 원호·IFA의 실제 계획 조회에서 비교한다."""
        modes = ["MUR", "PML_8", "PEC", "PMC", "PML_8", "MUR"]
        for fixture, base in ((fixture_document(arc=True), SETTINGS), (ifa_document(), IFA_SETTINGS)):
            with self.subTest(fixture=fixture["metadata"]["name"]), TemporaryDirectory() as directory:
                with ProjectService(Path(directory), auto_run=False) as service:
                    service.solver.runtime = SimpleNamespace(identity=runtime_identity())
                    document, _ = register_fixture(service, fixture)
                    scope = {"project_id": document["project_id"]}
                    settings = {key: value for key, value in base.items() if key not in {"radiation", "power_balance"}}

                    def preview(current):
                        """! @brief 같은 설계 개정에 실제 검토 요청을 보낸다."""
                        return solver_preview.read(service, {"contract_version": "rfad.api/2.0", "context": scope,
                            "input": {"expected_revision": document["revision_id"], "settings": current}})

                    original = preview(settings)
                    result = preview({**settings, "boundary_conditions": modes})
                    self.assertEqual(result["mesh"]["lines_mm"], original["mesh"]["lines_mm"])
                    for i, (axis, values) in enumerate(result["mesh"]["lines_mm"].items()):
                        report = result["mesh"]["axes"][axis]
                        pair = modes[i * 2:i * 2 + 2]
                        pml = tuple(8 if mode == "PML_8" else 0 for mode in pair)
                        self.assertEqual(report["boundary_modes"], pair)
                        self.assertEqual(report["pml_cells"], pml)
                        self.assertEqual(report["pml_inner_mm"], [values[pml[0]], values[-1 - pml[1]]])
                    self.assertIn("boundary_conditions", result["settings"])
                    self.assertNotEqual(result["mesh"]["case_sha256"], original["mesh"]["case_sha256"])
                    with self.assertRaises(ProjectError) as invalid:
                        preview({**settings, "boundary_conditions": [*modes[:5], "periodic"]})
                    self.assertEqual(invalid.exception.code, "E_SCHEMA")
                    with self.assertRaises(ProjectError) as unsupported:
                        preview({**settings, "boundary_conditions": modes, "radiation": {}})
                    self.assertEqual(unsupported.exception.code, "E_UNSUPPORTED")

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
                mask["offset"] = Quantity.from_value(.2, "mm").to_dict()
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
                    substrate = next(row for row in document["stackup"] if row["role"] == "dielectric")
                    gaps = original["planar_clearances"]["clearances"]
                    gap = next(row for row in gaps if set(row["object_ids"]) == {substrate["id"], mask["id"]})
                    self.assertAlmostEqual(gap["distance_mm"], .2)
                    self.assertEqual(set(gap["object_roles"]), {"dielectric", "surface"})
                    self.assertTrue(gap["cells_xyz"])
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
