"""! @brief 복소 반사/공진 bracket/실제 격자 근거가 없는 수치 합격을 방지한다."""

from copy import deepcopy
import math
import unittest

from rfad.application.canonical import canonical_hash
from rfad.application.convergence import assess_study, compare_samples


PROFILE = {"id": "test-only-proposed-np02", "minimum_levels": 3,
           "max_resonance_relative_shift": 0.01, "max_s11_complex_delta": 0.02}
FREQUENCIES = [2.49e9, 2.495e9, 2.5e9, 2.505e9, 2.51e9]


def fixture_result(*, grid=0.25, padding=1, end=1e-5, magnitudes=None, phase=0.0, frequencies=None):
    """! @brief 물리 해석 증거가 아닌 순수 비교기 시험용 자료를 명시적으로 만든다."""
    frequencies = frequencies or FREQUENCIES
    magnitudes = magnitudes or [0.8, 0.5, 0.2, 0.5, 0.8]
    settings = {"frequency_hz": {"start": frequencies[0], "stop": frequencies[-1], "count": len(frequencies)},
                "grid_mm": grid, "air_padding_mm": padding, "curve_tolerance_mm": 0.01,
                "max_timesteps": 1000, "end_criterion": end,
                "mesh_policy": {"kind": "graded_air", "air_cell_mm": 1, "growth_ratio": 1.3}}
    source = {"purpose": "pure comparator fixture", "material": {"epsilon_r": 2.2}, "geometry": [0, 1]}
    normalization = {"kind": "power-wave", "reference_impedance_ohm": 50, "reference_plane": "test-gap"}
    case = {"board": {"bounds_mm": [[0, 1], [0, 1]]}, "layers": [{"z_min_mm": 0, "thickness_mm": 1}],
            "settings": settings, "frequency_hz": deepcopy(settings["frequency_hz"]),
            "stop_criteria": {"max_timesteps": 1000, "energy_decay": end, "exact_end_criteria": True}}
    plan = {"plan_id": "plan-" + canonical_hash(settings), "snapshot": {"snapshot_id": "same-snapshot", "content_hash": canonical_hash(source)},
            "source_semantics": source, "runtime_identity": {"manifest_sha256": "same-native-and-source"},
            "analysis_profile": "rfad.openems.pcb-single-port/0.1", "runtime_profile": "openems-wsl-reference/0.1",
            "normalization": normalization, "case": case, "model_report": {"physical_validation_state": "not_validated"}}
    inner = list(range(-padding, 0)) + [index * grid for index in range(round(1 / grid) + 1)] + list(range(2, padding + 2))
    lines = [inner[0] - index for index in range(8, 0, -1)] + inner + [inner[-1] + index for index in range(1, 9)]
    mesh = {"lines_mm": {axis: deepcopy(lines) for axis in "xyz"}, "grid_mm": grid, "pml_cells_per_end": 8}
    result = {"schema": "rfad.openems-pcb-result/0.1", "analysis_plan_id": plan["plan_id"], "normalization": deepcopy(normalization),
              "assessment": {"status": "computed_unvalidated", "physics_validated": False, "converged": True, "finite_samples": True},
              "provenance": {"analysis_plan": plan, "runtime": {"packages": {"openEMS": "test-only"}}},
              "mesh_statistics": mesh, "native_statistics": {"iterations": 100},
              "termination": {"status": "end_criterion_reached", "iterations": 100,
                              "target_energy_ratio": end, "exact_endcriterion_schedule": True},
              "samples": [{"frequency_hz": frequency, "s11": [magnitude * math.cos(phase), magnitude * math.sin(phase)],
                           "impedance_ohm": [50, 1], "s11_db": -12345, "vswr": None}
                          for frequency, magnitude in zip(frequencies, magnitudes)]}
    recount(result)
    return result


def recount(result):
    """! @brief 합성 격자를 변경하는 회귀 시험에서 실제 배열의 개수를 함께 갱신한다."""
    mesh = result["mesh_statistics"]
    counts = [len(mesh["lines_mm"][axis]) for axis in "xyz"]
    mesh.update(line_counts=counts, interval_counts=[value - 1 for value in counts],
                native_grid_points=math.prod(counts), yee_interval_cells=math.prod(value - 1 for value in counts))
    result["native_statistics"]["native_cells"] = math.prod(counts)


def fixture_case(axis, label, **kwargs):
    """! @brief 정규화 결과와 그대로 일치하는 명시적 사례/불변 참조를 만든다."""
    result = fixture_result(**kwargs)
    return {"label": label, "axis": axis, "settings": deepcopy(result["provenance"]["analysis_plan"]["case"]["settings"]),
            "normalized_result": result, "artifact": {"artifact_id": label, "sha256": canonical_hash(result)}}


def fixture_study():
    """! @brief 각 공간 축 세 수준과 별도 시간 종료 두 수준을 구성한다."""
    return ([fixture_case("mesh", "mesh-" + str(grid), grid=grid, padding=3) for grid in (1.0, 0.5, 0.25)]
            + [fixture_case("boundary", "boundary-" + str(padding), padding=padding) for padding in (1, 2, 3)]
            + [fixture_case("termination", "termination-" + str(end), padding=3, end=end) for end in (1e-5, 1e-6)])


class ConvergenceComparisonTests(unittest.TestCase):
    """! @brief 위상/주파수/근거를 잃는 비교와 공진 미포착의 거짓 합격을 막는다."""

    def test_same_db_different_phase_fails_complex_threshold(self):
        left, right = fixture_result(), fixture_result(phase=0.1)
        report = compare_samples(left, right, PROFILE)
        self.assertEqual(report["status"], "failed")
        self.assertGreater(report["metrics"]["max_s11_complex_delta"], 0.02)
        self.assertAlmostEqual(report["metrics"]["max_s11_db_delta"], 0)

    def test_zero_reflection_keeps_undefined_db_auxiliary(self):
        result = fixture_result(magnitudes=[0.8, 0.5, 0, 0.5, 0.8])
        report = compare_samples(result, result, PROFILE)
        self.assertEqual(report["status"], "established")
        self.assertEqual(report["metrics"]["s11_db_undefined_pair_count"], 1)

    def test_endpoint_multiple_and_flat_minima_are_not_established(self):
        for magnitudes in ([0.8, 0.6, 0.4, 0.2, 0.1], [0.8, 0.2, 0.8, 0.2, 0.8], [0.8, 0.2, 0.2, 0.2, 0.8]):
            with self.subTest(magnitudes=magnitudes):
                result = fixture_result(magnitudes=magnitudes)
                report = compare_samples(result, result, PROFILE)
                self.assertEqual(report["status"], "not_established")
                self.assertEqual(report["resonance"]["left"]["status"], "not_established")

    def test_identical_coarse_resonance_does_not_claim_one_percent_precision(self):
        result = fixture_result(frequencies=[2.3e9, 2.4e9, 2.5e9, 2.6e9, 2.7e9])
        report = compare_samples(result, result, PROFILE)
        self.assertEqual(report["status"], "not_established")
        self.assertEqual(report["resonance"]["sampled_relative_shift"], 0)
        self.assertGreater(report["resonance"]["bracket_max_relative_shift"], 0.01)

    def test_complex_failure_is_reported_even_when_resonance_is_not_bracketed(self):
        left = fixture_result(magnitudes=[0.8, 0.6, 0.4, 0.2, 0.1])
        right = fixture_result(magnitudes=[0.8, 0.6, 0.4, 0.2, 0.1], phase=0.1)
        report = compare_samples(left, right, PROFILE)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["resonance"]["status"], "not_established")

    def test_sampled_resonance_shift_over_threshold_fails(self):
        frequencies = [2.3e9, 2.4e9, 2.5e9, 2.6e9, 2.7e9]
        left = fixture_result(frequencies=frequencies)
        right = fixture_result(frequencies=frequencies, magnitudes=[0.8, 0.6, 0.4, 0.2, 0.8])
        report = compare_samples(left, right, PROFILE)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["resonance"]["status"], "failed")

    def test_nonfinite_complex_and_nonincreasing_frequency_are_rejected(self):
        mutations = [("s11", [float("nan"), 0]), ("s11", [float("inf"), 0]), ("s11", [True, 0]),
                     ("impedance_ohm", [0, float("inf")]), ("frequency_hz", FREQUENCIES[0])]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                left, right = fixture_result(), fixture_result()
                right["samples"][1][key] = value
                with self.assertRaises(ValueError):
                    compare_samples(left, right, PROFILE)

    def test_changed_identity_cannot_be_compared(self):
        for target in ("source", "snapshot", "normalization", "runtime_identity", "observed_runtime", "consumed_material"):
            with self.subTest(target=target):
                left, right = fixture_result(), fixture_result()
                plan = right["provenance"]["analysis_plan"]
                if target == "source":
                    plan["source_semantics"]["material"]["epsilon_r"] = 3.0
                    plan["snapshot"]["content_hash"] = canonical_hash(plan["source_semantics"])
                elif target == "snapshot":
                    plan["snapshot"]["snapshot_id"] = "other-snapshot"
                elif target == "normalization":
                    right["normalization"]["reference_impedance_ohm"] = 75
                    plan["normalization"] = deepcopy(right["normalization"])
                elif target == "runtime_identity":
                    plan["runtime_identity"]["manifest_sha256"] = "other-source-runtime"
                elif target == "observed_runtime":
                    right["provenance"]["runtime"]["packages"]["openEMS"] = "other-native"
                else:
                    plan["case"]["layers"][0]["epsilon_r"] = 3.0
                with self.assertRaises(ValueError):
                    compare_samples(left, right, PROFILE)

    def test_different_frequency_array_is_rejected_without_resampling(self):
        left, right = fixture_result(), fixture_result()
        right["samples"][1]["frequency_hz"] += 100
        with self.assertRaises(ValueError):
            compare_samples(left, right, PROFILE)

    def test_fabricated_mesh_or_max_step_termination_is_rejected(self):
        for target in ("counts", "native", "iterations", "termination", "status", "physics"):
            with self.subTest(target=target):
                left, right = fixture_result(), fixture_result()
                if target == "counts":
                    right["mesh_statistics"]["native_grid_points"] += 1
                elif target == "native":
                    right["native_statistics"]["native_cells"] += 1
                elif target == "iterations":
                    right["native_statistics"]["iterations"] = 1000
                    right["termination"]["iterations"] = 1000
                elif target == "termination":
                    right["termination"]["status"] = "maximum_timesteps_reached"
                elif target == "status":
                    right["assessment"]["converged"] = False
                else:
                    right["assessment"]["physics_validated"] = True
                with self.assertRaises(ValueError):
                    compare_samples(left, right, PROFILE)

    def test_acceptance_profile_requires_explicit_finite_thresholds(self):
        result = fixture_result()
        for profile in ({}, {**PROFILE, "minimum_levels": 2}, {**PROFILE, "max_s11_complex_delta": True},
                        {**PROFILE, "max_resonance_relative_shift": float("nan")}, {**PROFILE, "extra": 1}):
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError):
                    compare_samples(result, result, profile)


class ConvergenceStudyTests(unittest.TestCase):
    """! @brief 한 축의 교란/부족/비실행 격자 또는 빠진 시간 검증을 전체 합격으로 만들지 않는다."""

    def test_all_axes_required_and_source_assessments_remain_immutable(self):
        cases = fixture_study()
        before = deepcopy(cases)
        report = assess_study(cases, PROFILE)
        self.assertEqual(report["numerical_stability"]["status"], "established")
        self.assertEqual(cases, before)
        self.assertIs(report["physics_validated"], False)
        self.assertTrue(all(item["assessment"]["status"] == "computed_unvalidated" for item in report["source_assessments"]))
        report["source_assessments"][0]["assessment"]["status"] = "mutated-report"
        report["numerical_stability"]["axes"]["mesh"]["artifacts"][0]["artifact"]["sha256"] = "mutated-report"
        self.assertEqual(cases, before)

    def test_missing_termination_or_third_spatial_level_is_not_established(self):
        for removed in ("termination", "mesh-1.0", "boundary-1"):
            with self.subTest(removed=removed):
                cases = [case for case in fixture_study() if case["axis"] != removed and case["label"] != removed]
                self.assertEqual(assess_study(cases, PROFILE)["numerical_stability"]["status"], "not_established")

    def test_reversed_mesh_levels_are_not_sorted_into_pass(self):
        cases = fixture_study()
        cases[:3] = reversed(cases[:3])
        report = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["mesh"]
        self.assertEqual(report["status"], "not_established")
        self.assertIn("axis_levels_not_strictly_ordered", report["issues"])

    def test_relabelled_mesh_without_actual_refinement_is_not_established(self):
        cases = fixture_study()
        result = cases[2]["normalized_result"]
        result["mesh_statistics"]["lines_mm"] = deepcopy(cases[1]["normalized_result"]["mesh_statistics"]["lines_mm"])
        recount(result)
        report = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["mesh"]
        self.assertEqual(report["status"], "not_established")
        self.assertIn("actual_native_mesh_did_not_increase", report["issues"])

    def test_changed_common_air_grid_blocks_boundary_even_with_same_board_grid(self):
        cases = fixture_study()
        result = cases[5]["normalized_result"]
        lines = result["mesh_statistics"]["lines_mm"]["x"]
        lines[lines.index(-1)] = -0.9
        report = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["boundary"]
        self.assertEqual(report["status"], "not_established")
        self.assertIn("boundary_changed_common_interior_grid", report["issues"])
        self.assertTrue(all(report["final_pair"]["grid_comparison"]["board_axes_match"].values()))

    def test_padding_setting_without_actual_domain_expansion_cannot_pass(self):
        cases = fixture_study()
        result = cases[5]["normalized_result"]
        result["mesh_statistics"]["lines_mm"] = deepcopy(cases[4]["normalized_result"]["mesh_statistics"]["lines_mm"])
        recount(result)
        report = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["boundary"]
        self.assertEqual(report["status"], "not_established")
        self.assertIn("actual_boundary_did_not_expand", report["issues"])

    def test_multiple_changed_settings_cannot_be_attributed_to_one_axis(self):
        cases = fixture_study()
        cases[2] = fixture_case("mesh", "mixed-settings", grid=0.25, padding=2)
        report = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["mesh"]
        self.assertEqual(report["status"], "not_established")
        self.assertIn("expected_exactly_one_axis_setting", report["issues"])

    def test_case_settings_must_match_the_executed_result(self):
        cases = fixture_study()
        cases[-1]["settings"]["end_criterion"] = 1e-7
        with self.assertRaises(ValueError):
            assess_study(cases, PROFILE)

    def test_termination_cannot_change_spatial_mesh(self):
        cases = fixture_study()
        lines = cases[-1]["normalized_result"]["mesh_statistics"]["lines_mm"]["x"]
        lines[lines.index(-1)] = -0.9
        report = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["termination"]
        self.assertEqual(report["status"], "not_established")
        self.assertIn("termination_changed_mesh", report["issues"])

    def test_final_pair_decides_but_earlier_failed_pair_is_preserved(self):
        cases = fixture_study()
        cases[0] = fixture_case("mesh", "coarse-phase", grid=1.0, padding=3, phase=0.1)
        report = assess_study(cases, PROFILE)["numerical_stability"]["axes"]["mesh"]
        self.assertEqual(report["status"], "established")
        self.assertEqual(report["pairs"][0]["status"], "failed")
        self.assertEqual(report["final_pair"]["status"], "established")

    def test_final_pair_failure_fails_whole_study(self):
        cases = fixture_study()
        cases[-1] = fixture_case("termination", "strict-phase", padding=3, end=1e-6, phase=0.1)
        report = assess_study(cases, PROFILE)["numerical_stability"]
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["axes"]["termination"]["status"], "failed")

    def test_individually_stable_axes_need_a_shared_finest_anchor(self):
        cases = fixture_study()
        cases[:3] = [fixture_case("mesh", "mesh-" + str(grid), grid=grid, padding=1) for grid in (1.0, 0.5, 0.25)]
        report = assess_study(cases, PROFILE)["numerical_stability"]
        self.assertTrue(all(axis["status"] == "established" for axis in report["axes"].values()))
        self.assertEqual(report["status"], "not_established")
        self.assertIn("axis_anchors_do_not_match", report["issues"])

    def test_derived_mesh_report_differences_do_not_change_physics_identity(self):
        cases = fixture_study()
        for case in cases:
            result = case["normalized_result"]
            result["provenance"]["analysis_plan"]["case"]["mesh_policy_report"] = {
                "test_observation_native_grid_points": result["mesh_statistics"]["native_grid_points"]}
        self.assertEqual(assess_study(cases, PROFILE)["numerical_stability"]["status"], "established")


if __name__ == "__main__":
    unittest.main()
