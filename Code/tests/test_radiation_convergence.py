"""! @brief 물리 합격과 구분한 방사 수렴 및 구면/포트 전력 수지 경계를 검사한다."""

from copy import deepcopy
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import build_pcb_plan, mesh_lines, validate_pcb_plan, validate_settings
from rfad.application.pcb_radiation import SCHEMA, summary
from rfad.application.radiation import spectral_power_metrics
from rfad.application.radiation_study import validate_study
from rfad.application.radiation_study_guards import plan_guards
from rfad.application.radiation_comparison import sphere_power, power_audit, compare_cases, VACUUM_IMPEDANCE_OHM
from rfad.application.radiation_assessment import assess_study
from rfad.domain.errors import ProjectError
from test_pcb_solver import SETTINGS, fixture_document, runtime_identity, snapshot_for


ROOT = Path(__file__).resolve().parents[1]


def definition():
    """! @brief 작은 명시적 시험 PCB에 쓸 연구 조건만 축소하며 판정 한계는 유지한다."""
    study = json.loads((ROOT / "fixtures/pcb_radiation_convergence_study.json").read_bytes())
    study["base_settings"] = {**deepcopy(SETTINGS), "grid_mm": 0.4, "air_padding_mm": 14,
                              "mesh_policy": {"kind": "graded_air", "air_cell_mm": 1, "growth_ratio": 1.5},
                              "radiation": {"frequency_hz": [10e9], "theta_step_deg": 5, "phi_step_deg": 5, "box_clearance_mm": 4}}
    for row, distance in zip((row for row in study["cases"] if row["axis"] == "box"), (2, 3, 4)):
        row["overrides"]["box_clearance_mm"] = distance
    return study


def field(plan, *, scale=1e-12, efficiency=0.9, directivity=1.5):
    """! @brief 독립 적분의 해를 아는 sin(theta) 짧은 다이폴 패턴을 합성한다."""
    recording = deepcopy(plan["case"]["radiation_recording"])
    theta, phi = recording["theta_deg"], recording["phi_deg"]
    radiated = scale * scale * 8 * math.pi / 3 / (2 * VACUUM_IMPEDANCE_OHM)
    accepted = radiated / efficiency
    metrics = spectral_power_metrics(radiated, accepted, accepted / 0.99, directivity)
    et = [[[scale * math.sin(math.radians(angle)), 0.0] for _ in phi] for angle in theta]
    ep = [[[0.0, 0.0] for _ in phi] for _ in theta]
    pattern = [[math.sin(math.radians(angle)) ** 2 for _ in phi] for angle in theta]
    return {"schema": SCHEMA, "analysis_plan_id": plan["plan_id"], "recording": recording,
            "frequencies": [{"frequency_hz": 10e9, "metrics": metrics, "e_theta": et, "e_phi": ep,
                             "normalized_power": pattern, "directivity": [[value * directivity for value in row] for row in pattern]}],
            "electric_field_unit": "V*s/m", "power_unit": "W*s^2", "absolute_power_w": None,
            "physics_validated": False, "status": "computed_unvalidated"}


def cases_for(study=None, *, circle=False):
    """! @brief 실제 계획/격자와 합성 필드를 결합하되 native 실행 근거로 집계하지 않는다."""
    study = study or definition()
    document = fixture_document(circle=circle)
    snapshot, runtime = snapshot_for(document), runtime_identity()
    result = []
    for row in validate_study(study):
        plan = build_pcb_plan(document, snapshot, runtime, row["settings"])
        radiation = field(plan)
        lines = mesh_lines(plan["case"])
        counts = [len(lines[axis]) for axis in "xyz"]
        normalized = {"schema": "rfad.openems-pcb-result/0.1", "analysis_plan_id": plan["plan_id"], "normalization": plan["normalization"],
                      "assessment": {"status": "computed_unvalidated", "physics_validated": False, "converged": True, "finite_samples": True},
                      "provenance": {"analysis_plan": plan, "runtime": {"packages": {"openEMS": "test-only"}}},
                      "samples": [{"frequency_hz": 8e9 + 4e9 * i / 30, "s11": [0.1, 0.0], "impedance_ohm": [50.0, 0.0]} for i in range(31)],
                      "native_statistics": {"native_cells": math.prod(counts), "iterations": 100},
                      "termination": {"status": "end_criterion_reached", "iterations": 100, "target_energy_ratio": row["settings"]["end_criterion"], "exact_endcriterion_schedule": True},
                      "mesh_statistics": {"lines_mm": lines, "grid_mm": row["settings"]["grid_mm"], "pml_cells_per_end": 8,
                                          "line_counts": counts, "native_grid_points": math.prod(counts), "interval_counts": [x - 1 for x in counts],
                                          "yee_interval_cells": math.prod(x - 1 for x in counts)}, "radiation_summary": summary(radiation)}
        result.append({**row, "normalized_result": normalized, "radiation_result": radiation,
                       "artifact": {"artifact_id": row["settings_hash"], "normalized": {}, "radiation": {}}})
    return result


class RadiationConvergenceTests(unittest.TestCase):
    """! @brief 기록 상자 독립성과 각도 적분 및 수치 미확립의 보존을 검증한다."""

    def test_three_axes_share_one_anchor_and_preserve_definition(self):
        """! @brief 세 기준 행을 하나로 공유하고 입력 원문을 바꾸지 않는다."""
        study = definition()
        before = deepcopy(study)
        rows = validate_study(study)
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({row["settings_hash"] for row in rows}), 7)
        self.assertEqual(study, before)
        for circle in (False, True):
            cases = cases_for(study, circle=circle)
            result = assess_study(cases, study["acceptance_profile"])
            self.assertEqual(result["numerical_stability"]["status"], "established")
            self.assertEqual(result["power_balance"]["full_energy_closure"], "not_evaluated")
            self.assertFalse(result["physics_validated"])

    def test_sphere_integral_converges_to_analytic_dipole_power(self):
        """! @brief 극의 sin 가중과 phi 마지막-처음 구간을 포함해 알려진 해에 접근한다."""
        cases = cases_for()
        errors = []
        for case in cases[-3:]:
            value = case["radiation_result"]
            exact = value["frequencies"][0]["metrics"]["radiated_power_w_s2"]
            errors.append(abs(sphere_power(value["recording"], value["frequencies"][0]) - exact) / exact)
        self.assertGreater(errors[0], errors[1])
        self.assertGreater(errors[1], errors[2])
        self.assertLess(errors[2], 1e-5)

    def test_invalid_profile_levels_and_coupled_axes_are_blocked(self):
        """! @brief bool/NaN 기준, 다른 anchor, 역순과 숨은 복수 변수 변경을 거부한다."""
        original = definition()
        for mode in ("nan", "bool", "levels", "coupled", "order", "anchor", "angle"):
            value = deepcopy(original)
            if mode == "nan":
                value["acceptance_profile"]["max_pattern_delta"] = float("nan")
            elif mode == "bool":
                value["acceptance_profile"]["max_efficiency_delta"] = True
            elif mode == "levels":
                value["cases"].pop()
            elif mode == "coupled":
                value["cases"][0]["overrides"]["air_padding_mm"] = 20
            elif mode == "order":
                value["cases"][1]["overrides"]["grid_mm"] = 0.6
            elif mode == "anchor":
                value["cases"][5]["overrides"]["box_clearance_mm"] = 5
            else:
                value["cases"][7]["overrides"] = {"theta_step_deg": 15, "phi_step_deg": 30}
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_study(value)

    def test_fixed_mesh_box_expansion_and_fixed_phase_center(self):
        """! @brief 기록 상자를 늘려도 물리 격자와 PML, 위상 중심은 유지한다."""
        cases = cases_for()
        a, b = (row["normalized_result"]["provenance"]["analysis_plan"] for row in cases[3:5])
        self.assertTrue(plan_guards(a, b, "box")["actual_mesh_fixed"])
        self.assertEqual(a["case"]["radiation_recording"]["center_m"], b["case"]["radiation_recording"]["center_m"])
        self.assertEqual(a["case"]["radiation_recording"]["actual_clearance_mm"], [[2.0, 2.0], [2.0, 2.0], [2.0, 2.0]])
        changed = deepcopy(b)
        changed["case"]["radiation_recording"]["start_mm"] = a["case"]["radiation_recording"]["start_mm"]
        with self.assertRaisesRegex(ValueError, "독립 비교"):
            plan_guards(a, changed, "box")

    def test_box_intersection_pml_and_invalid_distance_are_blocked(self):
        """! @brief 실제 셀 여유를 보존하며 PML 안의 요청을 자동 축소하지 않는다."""
        document = fixture_document()
        settings = definition()["base_settings"]
        for value in (None, True, float("inf"), 0, -1):
            changed = deepcopy(settings)
            changed["radiation"]["box_clearance_mm"] = value
            with self.subTest(value=value), self.assertRaises(ProjectError):
                validate_settings(changed)
        changed = deepcopy(settings)
        changed["radiation"]["box_clearance_mm"] = 5
        with self.assertRaisesRegex(ProjectError, "NF2FF"):
            build_pcb_plan(document, snapshot_for(document), runtime_identity(), changed)

    def test_power_excess_remains_negative_loss_and_not_full_energy_closure(self):
        """! @brief 100% 초과 효율을 자르지 않고 독립 흡수 전력의 미평가도 남긴다."""
        case = cases_for()[2]
        plan = case["normalized_result"]["provenance"]["analysis_plan"]
        radiation = field(plan, efficiency=1.05)
        audit = power_audit(case["normalized_result"], radiation, definition()["acceptance_profile"])
        self.assertEqual(audit["status"], "failed")
        self.assertLess(audit["frequencies"][0]["inferred_loss_w_s2"], 0)
        self.assertIsNone(audit["frequencies"][0]["independent_absorption_power_w_s2"])
        self.assertEqual(audit["frequencies"][0]["strict_passivity_status"], "requires_review")

    def test_last_pair_failure_is_not_hidden_by_stable_coarse_cases(self):
        """! @brief 마지막 격자의 이득 차이가 크면 전체 수렴을 미확립으로 유지한다."""
        cases = cases_for()
        case = cases[2]
        plan = case["normalized_result"]["provenance"]["analysis_plan"]
        case["radiation_result"] = field(plan, directivity=1.8)
        case["normalized_result"]["radiation_summary"] = summary(case["radiation_result"])
        result = assess_study(cases, definition()["acceptance_profile"])
        self.assertEqual(result["numerical_stability"]["status"], "not_established")
        self.assertEqual(result["numerical_stability"]["axes"]["mesh"]["comparisons"][-1]["status"], "failed")

    def test_changed_source_phase_center_grid_and_missing_frequency_cannot_pass(self):
        """! @brief 출처/위상 중심/실제 격자 대입 및 직접 포트 표본 누락을 차단한다."""
        cases = cases_for()
        for mode in ("source", "center", "grid", "frequency"):
            left, right = deepcopy(cases[0]), deepcopy(cases[1])
            plan = right["normalized_result"]["provenance"]["analysis_plan"]
            if mode == "source":
                plan["source_semantics"]["metadata"]["description"] += "changed"
            elif mode == "center":
                plan["case"]["radiation_recording"]["center_m"][0] += 0.01
                right["radiation_result"]["recording"] = deepcopy(plan["case"]["radiation_recording"])
            elif mode == "grid":
                right["normalized_result"]["mesh_statistics"]["lines_mm"]["x"][0] -= 1
            else:
                right["normalized_result"]["samples"][15]["frequency_hz"] += 1
            with self.subTest(mode=mode), self.assertRaises((ValueError, ProjectError)):
                if mode == "frequency":
                    power_audit(right["normalized_result"], right["radiation_result"], definition()["acceptance_profile"])
                else:
                    compare_cases(left, right, definition()["acceptance_profile"])


if __name__ == "__main__":
    unittest.main()
