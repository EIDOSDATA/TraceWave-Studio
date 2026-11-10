"""! @brief 실제 계획 격자와 합성 응답으로 공간 연구의 PML 교란 합격을 차단한다."""

from copy import deepcopy
import unittest

from rfad.application.canonical import canonical_hash
from rfad.application.convergence import assess_study
from rfad.application.pcb_solver import build_pcb_plan, mesh_lines
from test_convergence import PROFILE, fixture_result, recount
from test_pcb_solver import SETTINGS, fixture_document, runtime_identity, snapshot_for


def planned_case(document, snapshot, axis, label, settings):
    """! @brief 실제로 생성한 격자에 비교기 전용 합성 응답을 붙이며 native 실행을 주장하지 않는다."""
    plan = build_pcb_plan(document, snapshot, runtime_identity(), settings)
    frequency = settings["frequency_hz"]
    frequencies = [frequency["start"] + (frequency["stop"] - frequency["start"]) * index / (frequency["count"] - 1)
                   for index in range(frequency["count"])]
    result = fixture_result(frequencies=frequencies)
    result["analysis_plan_id"] = plan["plan_id"]
    result["normalization"] = deepcopy(plan["normalization"])
    result["provenance"]["analysis_plan"] = plan
    result["termination"]["target_energy_ratio"] = settings["end_criterion"]
    result["mesh_statistics"] = {"lines_mm": mesh_lines(plan["case"]), "grid_mm": settings["grid_mm"], "pml_cells_per_end": 8}
    if "mesh_policy_report" in plan["case"]:
        result["mesh_statistics"]["mesh_policy_report"] = deepcopy(plan["case"]["mesh_policy_report"])
    recount(result)
    return {"axis": axis, "label": label, "settings": deepcopy(settings), "normalized_result": result,
            "artifact": {"artifact_id": label, "sha256": canonical_hash(result), "purpose": "synthetic-response-comparator-regression"}}


def planned_study():
    """! @brief 작은 유효 PCB에 독립 graded mesh/거리/시간 설정을 적용한다."""
    document = fixture_document()
    snapshot = snapshot_for(document)
    base = {**SETTINGS, "frequency_hz": {"start": 9.99e9, "stop": 10.01e9, "count": 5},
            "grid_mm": 0.25, "air_padding_mm": 14,
            "mesh_policy": {"kind": "graded_air", "air_cell_mm": 1, "growth_ratio": 1.5}}
    return ([planned_case(document, snapshot, "mesh", "mesh-" + str(grid), {**base, "grid_mm": grid}) for grid in (0.5, 0.4, 0.25)]
            + [planned_case(document, snapshot, "boundary", "boundary-" + str(padding), {**base, "air_padding_mm": padding}) for padding in (12, 13, 14)]
            + [planned_case(document, snapshot, "termination", "termination-" + str(end), {**base, "end_criterion": end}) for end in (1e-4, 1e-5)])


class ConvergenceBoundaryGuardTests(unittest.TestCase):
    """! @brief 반사 응답이 같아도 PML 위치나 cell 폭이 교란되면 독립 축 합격을 거부한다."""

    def test_legacy_mesh_refinement_with_moving_pml_interface_is_not_established(self):
        document = fixture_document()
        snapshot = snapshot_for(document)
        base = {**SETTINGS, "frequency_hz": {"start": 9.99e9, "stop": 10.01e9, "count": 5}}
        cases = [planned_case(document, snapshot, "mesh", "legacy-" + str(grid), {**base, "grid_mm": grid})
                 for grid in (0.5, 0.4, 0.25)]
        self.assertEqual([case["normalized_result"]["mesh_statistics"]["lines_mm"]["x"][8] for case in cases], [-2.0, -2.8, -4.0])
        axis = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["mesh"]
        self.assertEqual(axis["status"], "not_established")
        self.assertIn("mesh_changed_boundary_or_pml", axis["issues"])

    def test_valid_graded_mesh_keeps_independent_axes_established(self):
        report = assess_study(planned_study(), PROFILE)["numerical_stability"]
        self.assertEqual(report["status"], "established")
        self.assertTrue(all(axis["status"] == "established" for axis in report["axes"].values()))

    def test_mesh_cannot_change_pml_widths_with_fixed_outer_and_inner_faces(self):
        cases = planned_study()
        result = cases[1]["normalized_result"]
        result["mesh_statistics"]["lines_mm"]["x"][1] += 0.01
        axis = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["mesh"]
        self.assertEqual(axis["status"], "not_established")
        self.assertIn("mesh_changed_boundary_or_pml", axis["issues"])

    def test_boundary_expansion_cannot_change_pml_widths(self):
        cases = planned_study()
        result = cases[4]["normalized_result"]
        result["mesh_statistics"]["lines_mm"]["x"][1] += 0.01
        axis = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["boundary"]
        self.assertEqual(axis["status"], "not_established")
        self.assertIn("boundary_changed_pml_cells", axis["issues"])

    def test_boundary_pml_width_comparison_allows_native_rounding_noise(self):
        cases = planned_study()
        result = cases[4]["normalized_result"]
        result["mesh_statistics"]["lines_mm"]["x"][1] += 1e-12
        self.assertEqual(assess_study(cases, PROFILE)["numerical_stability"]["status"], "established")


if __name__ == "__main__":
    unittest.main()
