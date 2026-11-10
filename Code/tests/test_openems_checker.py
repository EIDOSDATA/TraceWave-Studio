"""! @brief native 해석과 구분하여 참조 결과 판정기의 실패 검출을 시험한다."""

from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import unittest


_PATH = Path(__file__).resolve().parents[1] / "tools" / "check_openems_environment.py"
_SPEC = importlib.util.spec_from_file_location("check_openems_environment", _PATH)
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


def ideal_samples() -> list[dict]:
    """! @brief 해석식으로 만든 이상적인 포트 값은 판정기 시험에만 사용한다."""
    samples = []
    for index in range(31):
        frequency = 9.5e9 + index * (1e9 / 30)
        impedance, _ = checker.analytic_te10(frequency)
        beta = math.sqrt((2 * math.pi * frequency / checker.C0) ** 2 - (math.pi / checker.WIDTH_M) ** 2)
        angle = -beta * checker.PROBE_SEPARATION_M
        samples.append({"frequency_hz": frequency, "s11": [0.0, 0.0], "s21": [math.cos(angle), math.sin(angle)], "impedance_ohm": [impedance, 0.0]})
    return samples


class OpenemsCheckerTests(unittest.TestCase):
    """! @brief 수치 이상을 합격으로 기록하지 않는지 독립 검사한다."""

    def test_analytic_impedance_and_delay_at_known_cutoff_ratio(self):
        """! @brief 차단 주파수의 sqrt(2)배에서 알려진 폐형식 값을 비교한다."""
        cutoff = checker.C0 / (2 * checker.WIDTH_M)
        impedance, delay = checker.analytic_te10(cutoff * math.sqrt(2))
        self.assertAlmostEqual(impedance, checker.Z0 * math.sqrt(2), places=10)
        self.assertAlmostEqual(delay, checker.PROBE_SEPARATION_M / checker.C0 * math.sqrt(2), places=20)
        for frequency in (0, cutoff, float("nan"), float("inf")):
            with self.assertRaises(RuntimeError):
                checker.analytic_te10(frequency)

    def test_ideal_result_passes_without_mutating_samples(self):
        """! @brief 판정기 계산이 원래 복소 데이터를 바꾸지 않는다."""
        samples = ideal_samples()
        before = deepcopy(samples)
        report = checker.assess_samples(samples)
        self.assertTrue(report["passed"])
        self.assertLess(report["metrics"]["max_group_delay_relative_error"], 1e-4)
        self.assertEqual(samples, before)

    def test_reflection_transmission_impedance_and_delay_fail_separately(self):
        """! @brief 각 기준 위반을 독립적으로 검출한다."""
        for field in ("s11", "s21", "impedance_ohm", "delay"):
            with self.subTest(field=field):
                samples = ideal_samples()
                for sample in samples:
                    if field == "delay":
                        sample["s21"] = [1.0, 0.0]
                    elif field == "s11":
                        sample[field] = [0.3, 0.0]
                    else:
                        sample[field] = [value * 0.5 for value in sample[field]]
                self.assertFalse(checker.assess_samples(samples)["passed"])

    def test_nonfinite_missing_signal_and_bad_frequency_order_are_rejected(self):
        """! @brief 결과가 없거나 순서가 깨진 입력을 검사 성공으로 만들지 않는다."""
        for mode in ("nan", "zero", "order", "multimode"):
            samples = ideal_samples()
            if mode == "nan":
                samples[3]["impedance_ohm"][0] = float("nan")
            elif mode == "zero":
                samples[3]["s21"] = [0.0, 0.0]
            elif mode == "order":
                samples[3]["frequency_hz"] = samples[2]["frequency_hz"]
            else:
                samples[-1]["frequency_hz"] = 20e9
            with self.subTest(mode=mode):
                with self.assertRaises(RuntimeError):
                    checker.assess_samples(samples)

    def test_grid_comparison_requires_same_frequencies_and_bounded_change(self):
        """! @brief 서로 다른 표본을 비교하거나 큰 격자 차이를 숨기지 않는다."""
        coarse, fine = ideal_samples(), ideal_samples()
        self.assertTrue(checker.compare_grids(coarse, fine)["passed"])
        fine[0]["frequency_hz"] += 1.0
        with self.assertRaises(RuntimeError):
            checker.compare_grids(coarse, fine)
        fine = ideal_samples()
        fine[0]["impedance_ohm"][0] *= 1.10
        self.assertFalse(checker.compare_grids(coarse, fine)["passed"])

    def test_native_end_criterion_requires_log_and_statistics_agreement(self):
        """! @brief 실제 종료 에너지 메시지와 통계 반복 수를 대조한다."""
        log = "Exact-endcriteria: evaluating the end criteria every 8 timestep(s)\nRunFDTD: end-criteria of -70dB reached after 3280 timesteps (-70.18dB)\n"
        result = checker.check_termination(log, 3280)
        self.assertEqual(result["status"], "end_criterion_reached")
        self.assertEqual(result["reported_decay_db"], 70.18)
        for bad_log, iterations in ((log, 3279), (log.replace("-70.18dB", "-69.99dB"), 3280), (log.replace("of -70dB", "of -60dB"), 3280), (log.splitlines()[-1], 3280), ("Exact-endcriteria: evaluating the end criteria every 8 timestep(s)\n", 3280), (log + log, 3280)):
            with self.assertRaises(RuntimeError):
                checker.check_termination(bad_log, iterations)

    def test_native_abort_is_rejected_even_with_early_stats_or_success_text(self):
        """! @brief SIGINT/ABORT의 조기 통계를 정상 완료로 오판하지 않는다."""
        valid = "Exact-endcriteria: evaluating the end criteria every 8 timestep(s)\nRunFDTD: end-criteria of -70dB reached after 3280 timesteps (-70.18dB)\n"
        for marker in ("openEMS::CheckAbortCond(): Received SIGINT, aborting simulation gracefully...", 'openEMS::CheckAbortCond(): Found file "ABORT", aborting simulation gracefully...', "RunFDTD: Warning: Max. number of timesteps was reached before the end-criteria"):
            with self.subTest(marker=marker):
                with self.assertRaises(RuntimeError):
                    checker.check_termination(marker + "\n" + valid, 3280)


if __name__ == "__main__":
    unittest.main()
