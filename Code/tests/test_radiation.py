"""! @brief 지향성/이득/실현 이득과 수치 전력 불일치를 구분한다."""

import unittest
from rfad.application.radiation import power_metrics


class RadiationTests(unittest.TestCase):
    """! @brief 정합과 방사 손실을 서로 다른 전력 비율로 계산한다."""

    def test_gain_and_realized_gain_have_different_power_references(self):
        """! @brief 반사 전력은 실현 이득에만 추가 반영한다."""
        result = power_metrics(0.4, 0.5, 1.0, 1.64)
        self.assertAlmostEqual(result['radiation_efficiency'], 0.8)
        self.assertAlmostEqual(result['gain_linear'], 1.312)
        self.assertAlmostEqual(result['realized_gain_linear'], 0.656)
        self.assertFalse(result['physics_validated'])

    def test_power_imbalance_is_reported_without_clipping(self):
        """! @brief 수치 오차로 1을 넘은 효율을 조용히 보정하지 않는다."""
        result = power_metrics(1.02, 1.0, 1.1, 1.64)
        self.assertEqual(result['power_balance_status'], 'requires_review')
        self.assertEqual(result['radiation_efficiency'], 1.02)
        for value in (float('nan'), float('inf'), -1, 0, True, 10 ** 1000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                power_metrics(value, 1.0, 1.0, 1.64)
        with self.assertRaises(ValueError):
            power_metrics(1e308, 1e-308, 1e308, 1.64)
