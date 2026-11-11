"""! @brief 개별 손실 기준, 정규화와 최소 수준을 에너지 수지와 독립 검사한다."""

from copy import deepcopy
import math
import unittest

from rfad.application.pcb_loss_convergence import assess_losses, compare_losses, initial_profile, validate_profile
from rfad.domain.errors import ProjectError


def result(conductor=0.01, *, scale=1.0):
    """! @brief 물리/제조 근거가 아닌 비교 경계용 명시적 전력 분할을 만든다."""
    return {"frequencies": [{"frequency_hz": 2.4e9, "accepted_power_w_s2": scale,
                              "dielectric_loss_w_s2": 0.02 * scale, "conductor_loss_w_s2": conductor * scale,
                              "sheet_components": [{"entity_id": "s", "loss_w_s2": conductor * scale}]}]}


class LossConvergenceTests(unittest.TestCase):
    """! @brief 작은 수지 잔차를 개별 손실 합격으로 대체하지 않는다."""

    def test_each_component_and_normalization_are_compared(self):
        """! @brief 여기 크기는 제거하지만 도체 변화 3.5%는 새 2% 기준에서 실패한다."""
        profile = initial_profile()
        self.assertEqual(compare_losses(result(), result(scale=1e-24), profile)["status"], "passed")
        self.assertEqual(compare_losses(result(), result(0.01035), profile)["status"], "not_established")

    def test_minimum_levels_and_all_previous_comparisons_remain(self):
        """! @brief 2수준 합격을 수렴으로 승격하지 않고 거친 쌍의 실패도 보존한다."""
        profile = initial_profile()
        self.assertEqual(assess_losses([result(), result()], profile)["status"], "not_established")
        assessed = assess_losses([result(0.02), result(0.01), result(0.01001)], profile)
        self.assertEqual(assessed["status"], "passed")
        self.assertEqual(assessed["comparisons"][0]["status"], "not_established")
        self.assertFalse(assessed["physics_validated"])

    def test_absolute_floor_and_negative_loss(self):
        """! @brief 영점 근처에는 명시적 바닥을 쓰지만 음수 손실은 합격하지 않는다."""
        profile = initial_profile()
        self.assertEqual(compare_losses(result(0), result(1e-6), profile)["status"], "passed")
        self.assertEqual(compare_losses(result(-1e-9), result(0), profile)["status"], "not_established")

    def test_unknown_frequency_or_partition_is_rejected(self):
        """! @brief 서로 다른 직접 주파수 또는 분할의 결과를 비교하지 않는다."""
        for name in ("frequency", "entity", "accepted"):
            wrong = deepcopy(result())
            row = wrong["frequencies"][0]
            if name == "frequency":
                row["frequency_hz"] += 1
            elif name == "entity":
                row["sheet_components"][0]["entity_id"] = "other"
            else:
                row["accepted_power_w_s2"] = 0
            with self.subTest(name=name), self.assertRaises(ProjectError):
                compare_losses(result(), wrong, initial_profile())

    def test_invalid_profile_is_rejected(self):
        """! @brief bool/NaN/무제한 한계를 후속 사후 합격 기준으로 받지 않는다."""
        for key, value in (("minimum_levels", 2), ("minimum_levels", True), ("max_relative_delta", math.nan),
                           ("max_relative_delta", 1), ("absolute_fraction_floor", 0.01)):
            with self.subTest(key=key, value=value), self.assertRaises(ProjectError):
                validate_profile({**initial_profile(), key: value})


if __name__ == "__main__":
    unittest.main()
