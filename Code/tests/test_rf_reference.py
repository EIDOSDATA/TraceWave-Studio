"""! @brief 독립 다이폴 적분과 slab의 저주파/표피 극한으로 참조 산술을 검사한다."""

from copy import deepcopy
import math
import unittest

from rfad.domain.errors import ProjectError
from rfad.domain.rf_reference import (DIPOLE_DIRECTIVITY, assess_dipole, halfwave_power_pattern,
                                      sheet_reference, symmetric_sheet_impedance)


class RfReferenceTests(unittest.TestCase):
    """! @brief 구현식 복제 대신 독립 적분과 물리 극한 및 상태 경계를 확인한다."""

    def test_dipole_axes_symmetry_and_integrated_directivity(self):
        """! @brief 반파장 패턴의 구면 적분 지향성이 보존한 1.6409와 일치한다."""
        self.assertEqual(halfwave_power_pattern([0, 90, 180]), [0, 1, 0])
        samples = halfwave_power_pattern(list(range(181)))
        for a, b in zip(samples, reversed(samples)):
            self.assertAlmostEqual(a, b, places=14)
        # @brief 함수의 361개 상한 안에서 Simpson 구면 적분을 독립적으로 구성한다.
        angles = [index / 2 for index in range(361)]
        values = [power * math.sin(math.radians(angle))
                  for angle, power in zip(angles, halfwave_power_pattern(angles))]
        integral = math.radians(0.5) / 3 * (values[0] + values[-1]
                    + 4 * sum(values[1:-1:2]) + 2 * sum(values[2:-1:2]))
        self.assertAlmostEqual(2 / integral, 1.64092237698, places=8)
        self.assertLess(abs((2 / integral) / DIPOLE_DIRECTIVITY - 1), 2e-5)

    def test_comparison_keeps_historical_plane_and_unestablished_states(self):
        """! @brief phi 첫 면의 기존 판정과 전체 phi 관찰을 혼동하지 않는다."""
        theta = [0, 90, 180]
        power = [[0, 0.3], [1, 1], [0, 0]]
        metrics = {"directivity_linear": DIPOLE_DIRECTIVITY, "radiation_efficiency": 1}
        before = deepcopy((theta, power, metrics))
        result = assess_dipole(theta, power, metrics)
        self.assertTrue(result["passed"])
        self.assertEqual(result["maximum_pattern_error"], 0)
        self.assertEqual(result["maximum_pattern_error_all_phi"], 0.3)
        self.assertFalse(result["physics_validated"])
        self.assertFalse(result["measurement_validated"])
        self.assertEqual(result["formal_convergence"], "not_established")
        self.assertEqual((theta, power, metrics), before)

    def test_error_is_retained_without_normalizing_to_a_pass(self):
        """! @brief 효율 1 초과나 모델 차이를 잘라 합격으로 만들지 않는다."""
        result = assess_dipole([0, 90, 180], [[0.2], [1], [0]],
                               {"directivity_linear": 2, "radiation_efficiency": 1.3})
        self.assertEqual(result["status"], "requires_review")
        self.assertFalse(result["passed"])
        self.assertGreater(result["efficiency_error"], 0.15)
        self.assertEqual(result["acceptance"], {"maximum_pattern_error": 0.15,
                                               "relative_directivity_error": 0.1, "efficiency_error": 0.15})

    def test_sheet_dc_and_internal_inductance_limit(self):
        """! @brief 얇은 slab의 DC 저항과 내부 인덕턴스 omega*mu*t/12를 확인한다."""
        frequency, sigma, thickness, permeability = 1.0, 5.8e7, 1e-6, 4e-7 * math.pi
        value = symmetric_sheet_impedance(frequency, sigma, thickness, permeability)
        self.assertAlmostEqual(value.real / (1 / (sigma * thickness)), 1, places=12)
        self.assertAlmostEqual(value.imag / (2 * math.pi * frequency * permeability * thickness / 12), 1, places=7)

    def test_thick_sheet_is_two_halfspaces_in_parallel(self):
        """! @brief 충분히 두꺼운 대칭 slab이 두 표면의 병렬 저항/리액턴스가 된다."""
        frequency, sigma, thickness, permeability = 2.4e9, 5.8e7, 1e-3, 4e-7 * math.pi
        value = symmetric_sheet_impedance(frequency, sigma, thickness, permeability)
        expected_component = math.sqrt(math.pi * frequency * permeability / sigma) / 2
        self.assertAlmostEqual(value.real / expected_component, 1, places=13)
        self.assertAlmostEqual(value.imag / expected_component, 1, places=13)
        report = sheet_reference(frequency, sigma, thickness, permeability)
        self.assertAlmostEqual(report["skin_depth_m"] * 1e6, 1.348964479, places=8)
        self.assertFalse(report["native_executed"])
        self.assertFalse(report["physics_validated"])
        self.assertIn("requires_explicit", report["applicability"])

    def test_bad_or_unbounded_inputs_do_not_create_reference_values(self):
        """! @brief 미정/비유한/잘못된 단위 범위를 수치로 채우지 않는다."""
        for value in (None, True, 0, -1, float("nan"), float("inf"), 10 ** 400):
            with self.subTest(value=str(value)[:30]), self.assertRaises(ProjectError):
                symmetric_sheet_impedance(value, 5.8e7, 35e-6, 4e-7 * math.pi)
        for theta in ([], [None], [True], [-1], [181], [float("nan")], [0] * 362):
            with self.subTest(theta=str(theta)[:30]), self.assertRaises(ProjectError):
                halfwave_power_pattern(theta)
        for power in ([[0], [float("nan")], [0]], [[0], [1, 0], [0]], [[0], [1.1], [0]]):
            with self.assertRaises(ProjectError):
                assess_dipole([0, 90, 180], power, {"directivity_linear": 1.64, "radiation_efficiency": 1})
