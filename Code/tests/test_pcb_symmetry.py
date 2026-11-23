"""! @brief 대칭 PCB에서 실제 격자, 급전 및 전체 모델의 복소 결과를 대조한다."""

from copy import deepcopy
import os
import sys
import unittest

from rfad.application.pcb_mesh import mesh_lines
from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan
from rfad.application.pcb_symmetry import native_case, reduce_axis
from rfad.domain.errors import ProjectError
from test_pcb_solver import SETTINGS, fixture_document, quantity, runtime_identity, snapshot_for


SPEC = {"axis": "x", "position_mm": 8, "wall": "PEC"}
SETUP = {**SETTINGS, "end_criterion": 1e-5}


class PcbSymmetryTests(unittest.TestCase):
    def test_positive_coordinate_half_matches_original_mesh_and_immutable_inputs(self):
        """! @brief 전체 모델의 원래 포트와 급전 전압 규약을 유지하고 물리 영역 절반을 선택한다."""
        document = fixture_document()
        snap = snapshot_for(document)
        full = build_pcb_plan(document, snap, runtime_identity(), SETUP)
        reduced = build_pcb_plan(document, snap, runtime_identity(), {**SETUP, "symmetry_plane": SPEC})
        original = full["case"]
        case = reduced["case"]
        validate_pcb_plan(reduced)
        self.assertEqual(full["source_semantics"], reduced["source_semantics"])
        self.assertEqual(full["normalization"], reduced["normalization"])
        self.assertEqual(case["boundary_conditions"], ["PEC", *original["boundary_conditions"][1:]])
        whole, half = mesh_lines(original), mesh_lines(case)
        self.assertEqual(half["x"], [v for v in whole["x"] if v >= 8])
        self.assertEqual(half["y"], whole["y"])
        self.assertEqual(half["z"], whole["z"])
        actual = native_case(case)
        self.assertEqual([row["id"] for row in actual["shapes"]], [case["port"]["positive_geometry_id"]])
        self.assertEqual(actual["port"]["resistance_ohm"], 25)
        self.assertEqual(actual["port"]["start_mm"], [8, 6, 1])
        self.assertEqual(case["symmetry"]["mirror_pairs"][case["port"]["reference_geometry_id"]], case["port"]["positive_geometry_id"])
        reversed_doc = deepcopy(document)
        reversed_port = reversed_doc["ports"][0]
        reversed_port["direction"] = [-1, 0, 0]
        a, b = reversed_port["positive_geometry_id"], reversed_port["reference_geometry_id"]
        reversed_port.update(positive_geometry_id=b, reference_geometry_id=a)
        box = reversed_port["excitation_box"]
        box["start"], box["stop"] = box["stop"], box["start"]
        reversed_plan = build_pcb_plan(reversed_doc, snapshot_for(reversed_doc), runtime_identity(), {**SETUP, "symmetry_plane": SPEC})
        probe = native_case(reversed_plan["case"])["port"]
        self.assertEqual((probe["start_mm"][0], probe["stop_mm"][0]), (9, 8))
        self.assertIsNone(probe["positive_geometry_id"])
        self.assertEqual(probe["reference_geometry_id"], a)
        from rfad.application.solver_preview import model_review, mesh_intervals

        view = model_review(document, reduced)
        mirror = next(row for row in view["excluded"] if row["reason"] == "symmetry_image")
        self.assertEqual(mirror["represented_by"], case["port"]["positive_geometry_id"])
        feed = next(row for row in mesh_intervals(actual, half)["intervals"] if row["kind"] == "feed_gap")
        self.assertEqual(feed["bounds_mm"], [8, 9])
        with self.assertRaises(ProjectError):
            reduce_axis(case, "x", [0, 4, 8, 13, 16])

    def test_solver_review_shows_half_domain_and_tracks_original_mirror(self):
        """! @brief GUI가 쓰는 검토에서 실제 반영역 셀과 반사한 객체를 확인하고 현재 설계를 보존한다."""
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import patch
        from rfad.application.projects import ProjectService
        from rfad.application.solver_preview import read
        from test_cad_worker_process import register_fixture
        from test_project_reviews import read_params

        with TemporaryDirectory() as root, ProjectService(Path(root), auto_run=False) as service:
            document, _ = register_fixture(service, fixture_document())
            state = service.journal.read()
            with patch.object(service.solver, "runtime", SimpleNamespace(identity=runtime_identity())):
                view = read(service, read_params(document, settings={**SETUP, "symmetry_plane": SPEC}))
            self.assertEqual(view["mesh"]["model_bounds_mm"][0], [8, 16])
            self.assertEqual(view["mesh"]["axes"]["x"]["air_before_pml_mm"][0], 0)
            source_port = document["ports"][0]
            excluded = next(row for row in view["model"]["excluded"] if row["reason"] == "symmetry_image")
            self.assertEqual(excluded["id"], source_port["reference_geometry_id"])
            self.assertEqual(excluded["represented_by"], source_port["positive_geometry_id"])
            self.assertEqual(service.journal.read(), state)

    def test_geometry_material_drive_and_boundaries_must_be_symmetric(self):
        """! @brief 비대칭 도체 및 물성, 잘못된 여기 위치와 자기벽 단일 포트를 각각 차단한다."""
        document = fixture_document()
        for changed in ({**SPEC, "wall": "PMC"}, {**SPEC, "axis": "z"}, {**SPEC, "position_mm": 7}, {**SPEC, "axis": "y", "position_mm": 6}):
            with self.subTest(spec=changed), self.assertRaises(ProjectError):
                build_pcb_plan(document, snapshot_for(document), runtime_identity(), {**SETUP, "symmetry_plane": changed})
        with self.assertRaisesRegex(ProjectError, "경계 조건"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), {**SETUP, "symmetry_plane": SPEC,
                "boundary_conditions": ["PEC", "MUR", "PML_8", "PML_8", "PML_8", "PML_8"]})
        for attribute in ("shape", "material"):
            altered = deepcopy(document)
            shape = next(row for row in altered["geometry"] if row["role"] == "radiator")
            if attribute == "shape":
                shape["end"][0] = quantity(13, "mm")
            else:
                from uuid import uuid4
                old = next(row for row in altered["materials"] if row["id"] == shape["material_ref"])
                new = {**old, "id": str(uuid4()), "name": "Second explicit copper", "conductivity": quantity(40e6, "S/m")}
                altered["materials"] = sorted([*altered["materials"], new], key=lambda row: row["id"])
                shape["material_ref"] = new["id"]
            with self.subTest(attribute=attribute), self.assertRaisesRegex(ProjectError, "반사 형상"):
                build_pcb_plan(altered, snapshot_for(altered), runtime_identity(), {**SETUP, "symmetry_plane": SPEC})

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("RFAD_OPENEMS_NATIVE") == "1", "고정 openEMS 실행 환경 필요")
    def test_native_full_and_half_complex_s11(self):
        """! @brief 동일한 사용자 PCB의 전체/절반 계획을 봉인한 worker로 준비, 실행하고 31점을 비교한다."""
        self.verify_full_and_half(fixture_document(), SPEC)

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("RFAD_OPENEMS_NATIVE") == "1", "고정 openEMS 실행 환경 필요")
    def test_native_y_axis_reversed_polarity(self):
        """! @brief Y축에서 반대 극성의 단일 PCB 급전도 전체 복소 응답과 비교한다."""
        source = fixture_document()
        board = source["board"]["outline"]
        board["width"], board["height"] = board["height"], board["width"]
        for row in source["geometry"]:
            for key in ("start", "end"):
                row[key] = list(reversed(row[key]))
        port = source["ports"][0]
        a, b = port["positive_geometry_id"], port["reference_geometry_id"]
        port.update(positive_geometry_id=b, reference_geometry_id=a, direction=[0, -1, 0])
        box = port["excitation_box"]
        original = deepcopy(box)
        for a, b in (("start", "stop"), ("stop", "start")):
            x, y, z = original[b]
            box[a] = [y, x, z]
        self.verify_full_and_half(source, {**SPEC, "axis": "y"})

    def verify_full_and_half(self, source, spec):
        """! @brief 같은 양 단자와 물성을 소비한 전체/반영역 worker 결과를 직접 비교한다."""
        from test_pcb_native import PcbNativeTests
        from rfad.application.pcb_results import validate_preparation, validate_result

        sets = []
        for settings in (SETUP, {**SETUP, "symmetry_plane": spec}):
            helper = PcbNativeTests()
            helper.setUp()
            try:
                prep_stage, identity, plan, audit, prepared = helper.prepare_case(settings=settings, document=source)
                validate_preparation(plan, audit)
                stage, identity = helper.stage("simulation")
                request = helper.request("analysis", plan, identity)
                request.update(preparation=audit, prepared_plan=prepared)
                request["input_files"] = helper.copy_inputs(prep_stage, stage, audit["files"])
                result = helper.run_worker(stage, request)["result"]
                validate_result(plan, result, prepared)
                sets.append((audit["mesh_statistics"]["line_counts"], result["termination"], result["samples"]))
            finally:
                helper.tearDown()
        metrics = {}
        for name in ("s11", "impedance_ohm"):
            metrics[name] = max(abs(complex(*a[name]) - complex(*b[name])) for a, b in zip(sets[0][2], sets[1][2]))
        print("PCB 대칭 전체/절반:", [(v[0], v[1]) for v in sets], metrics, flush=True)
        self.assertLessEqual(metrics["s11"], .03)
        self.assertLessEqual(metrics["impedance_ohm"], 1.0)
