"""! @brief 경계 비교의 공통 격자 불변성과 고정 PML/자원/성장률을 독립 검사한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest

from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_solver import build_pcb_plan, mesh_lines, validate_pcb_plan
from rfad.domain.errors import ProjectError
from test_pcb_solver import runtime_identity, snapshot_for


ROOT = Path(__file__).resolve().parents[1]
STUDY_SETTINGS = {"frequency_hz": {"start": 2e9, "stop": 3e9, "count": 201}, "grid_mm": 0.4,
                  "air_padding_mm": 102.0, "curve_tolerance_mm": 0.025, "max_timesteps": 100000, "end_criterion": 1e-5,
                  "mesh_policy": {"kind": "graded_air", "air_cell_mm": 6.0, "growth_ratio": 1.5}}


def study_plan(settings=None):
    """! @brief 고정 fixture의 원본을 변경하지 않고 명시적 수치 계획만 생성한다."""
    document = json.loads((ROOT / "fixtures/ifa_feed_smoke.json").read_text(encoding="utf-8"))["document"]
    return build_pcb_plan(document, snapshot_for(document), runtime_identity(), settings or STUDY_SETTINGS)


class GradedPcbMeshTests(unittest.TestCase):
    """! @brief 파장/성장률의 초기 수치 정책을 검증하며 물리 수렴 합격을 주장하지 않는다."""

    def test_legacy_six_field_grid_is_unchanged(self):
        """! @brief optional policy가 없으면 기존 입력과 격자 개수를 유지한다."""
        fixture = json.loads((ROOT / "fixtures/ifa_feed_smoke.json").read_text(encoding="utf-8"))
        before = canonical_bytes(fixture)
        plan = study_plan(fixture["settings"])
        lines = mesh_lines(plan["case"])
        self.assertEqual([len(lines[a]) for a in "xyz"], [113, 153, 37])
        self.assertEqual(plan["resource_estimate"]["estimated_grid_points"], 639693)
        self.assertNotIn("mesh_policy_report", plan["case"])
        self.assertEqual(canonical_bytes(fixture), before)

    def test_all_nine_explicit_cases_fit_existing_budget(self):
        """! @brief 승인한 3개 내부 격자와 3개 경계 거리 조합이 기존 자원 상한 안에 든다."""
        for grid in (0.5, 0.45, 0.4):
            for padding in (90.0, 96.0, 102.0):
                with self.subTest(grid=grid, padding=padding):
                    plan = study_plan({**STUDY_SETTINGS, "grid_mm": grid, "air_padding_mm": padding})
                    self.assertLessEqual(plan["resource_estimate"]["estimated_grid_points"], 1500000)
                    validate_pcb_plan(plan)
                    report = plan["case"]["mesh_policy_report"]
                    self.assertEqual(report["pml_thickness_mm"], 48.0)
                    self.assertGreaterEqual(report["air_cells_per_minimum_wavelength"], 10)
                    for axis in "xyz":
                        audit = report["axes"][axis]
                        self.assertEqual(audit["pml_clearance_mm"], [padding - 48] * 2)
                        self.assertEqual(audit["pml_cell_widths_mm"], [[6.0] * 8] * 2)
                        self.assertLessEqual(audit["air_and_interface_max_adjacent_ratio"], 1.5 + 1e-8)

    def test_padding_extends_existing_grid_without_redistribution(self):
        """! @brief 경계를 늘려도 기존 공기/기판 공통 영역의 모든 좌표가 정확히 같다."""
        for grid in (0.5, 0.45, 0.4):
            previous = None
            for padding in (90.0, 96.0, 102.0):
                current = mesh_lines(study_plan({**STUDY_SETTINGS, "grid_mm": grid, "air_padding_mm": padding})["case"])
                if previous is not None:
                    for axis in "xyz":
                        self.assertEqual(current[axis][1:-1], previous[axis])
                previous = current

    def test_grid_refinement_keeps_outer_boundary_and_pml_fixed(self):
        """! @brief grid만 바꾸면 실제 outer/PML 좌표와 두께는 변하지 않는다."""
        previous = None
        for grid in (0.5, 0.45, 0.4):
            lines = mesh_lines(study_plan({**STUDY_SETTINGS, "grid_mm": grid})["case"])
            boundary = {axis: (lines[axis][:9], lines[axis][-9:]) for axis in "xyz"}
            if previous is not None:
                self.assertEqual(previous, boundary)
            previous = boundary

    def test_graded_policy_preserves_model_interior_and_thin_copper_sheet(self):
        """! @brief graded 공기만 바꾸며 35 um 동박을 별도 작은 volume cell로 만들지 않는다."""
        for grid in (0.5, 0.45, 0.4):
            graded = mesh_lines(study_plan({**STUDY_SETTINGS, "grid_mm": grid})["case"])
            legacy_settings = {key: deepcopy(value) for key, value in STUDY_SETTINGS.items() if key != "mesh_policy"}
            legacy_settings.update(grid_mm=grid, air_padding_mm=5.0)
            legacy = mesh_lines(study_plan(legacy_settings)["case"])
            for axis, bounds in zip("xyz", ((0, 40), (0, 60), (0.035, 0.965))):
                select = lambda values: [v for v in values if bounds[0] <= v <= bounds[1]]
                self.assertEqual(select(graded[axis]), select(legacy[axis]))
            self.assertGreater(min(b-a for a,b in zip(graded["z"], graded["z"][1:])), 0.3)

    def test_invalid_air_policy_is_not_automatically_repaired(self):
        """! @brief 거친 파장/급격한 성장/비정수 경계와 짧은 PML 여백을 거절한다."""
        candidates = [
            {**STUDY_SETTINGS, "air_padding_mm": 95},
            {**STUDY_SETTINGS, "air_padding_mm": 60},
            {**STUDY_SETTINGS, "air_padding_mm": 104, "mesh_policy": {"kind": "graded_air", "air_cell_mm": 8, "growth_ratio": 1.5}},
            {**STUDY_SETTINGS, "mesh_policy": {"kind": "graded_air", "air_cell_mm": 6, "growth_ratio": 1.51}},
            {**STUDY_SETTINGS, "mesh_policy": {"kind": "automatic", "air_cell_mm": 6, "growth_ratio": 1.5}},
        ]
        for candidate in candidates:
            with self.assertRaises(ProjectError):
                study_plan(candidate)

    def test_graded_policy_does_not_raise_production_resource_cap(self):
        """! @brief 1.5M을 넘는 더 큰 경계를 조용히 승인하지 않는다."""
        with self.assertRaises(ProjectError) as caught:
            study_plan({**STUDY_SETTINGS, "air_padding_mm": 114.0})
        self.assertEqual(caught.exception.code, "E_RESOURCE")

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("RFAD_OPENEMS_NATIVE") == "1", "고정 Linux solver venv와 RFAD_OPENEMS_NATIVE=1이 필요합니다.")
    def test_native_prepare_preserves_explicit_pml_and_connectivity(self):
        """! @brief 최대 승인 격자를 실제 CSXCAD로 준비하되 FDTD는 실행하지 않는다."""
        import test_pcb_native as native_tests
        helper = native_tests.PcbNativeTests("test_circle_and_arc_native_xml_preserve_circle_and_source_mapping")
        helper.setUp()
        try:
            document = json.loads((ROOT / "fixtures/ifa_feed_smoke.json").read_text(encoding="utf-8"))["document"]
            stage, _, plan, preparation, _ = helper.prepare_case(document=document, settings=STUDY_SETTINGS)
            self.assertEqual(preparation["mesh_statistics"]["native_grid_points"], 1432800)
            self.assertEqual(preparation["mesh_statistics"]["mesh_policy_report"], plan["case"]["mesh_policy_report"])
            self.assertTrue(preparation["consumption_report"]["native_connectivity"]["yee_connectivity_checked"])
            self.assertFalse((stage / "output/raw").exists())
        finally:
            helper.tearDown()


if __name__ == "__main__":
    unittest.main()
