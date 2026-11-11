"""! @brief QuarterCell 혼합 전류, 중공 비아와 sheet 계수 대체의 독립 분리를 검증한다."""

import importlib.util
import math
import unittest
from types import SimpleNamespace

from rfad.adapters.solvers.openems.pcb_loss_partition import material_partition, partition_work
from rfad.domain.errors import ProjectError


@unittest.skipUnless(importlib.util.find_spec("numpy"), "격리 native 또는 CAD 환경의 numpy가 필요합니다.")
class LossPartitionTests(unittest.TestCase):
    """! @brief 알려진 혼합 재료/전기장으로 합계 보존과 계면 중복을 검사한다."""

    def fixture(self, *, sheet=False):
        """! @brief 네 quadrant의 반은 유전체, 반은 비아인 명시적 합성 전류를 만든다."""
        import numpy as np

        class Structure:
            """! @brief native MATERIAL 조회와 같은 우선순위 결과만 대역한다."""

            def GetPropertyByCoordPriority(self, point, prop_type):
                """! @brief E_x의 y 부호에 따라 두 재료를 명시적으로 구분한다."""
                if prop_type != 0x002:
                    raise AssertionError("체적은 sheet 속성을 포함하면 안 됩니다.")
                name = "via_v" if point[1] > 0 else "dielectric_d"
                return SimpleNamespace(GetName=lambda: name)

        case = {"layers": [{"id": "d", "role": "dielectric", "kappa_s_per_m": 2}],
                "vias": [{"id": "v", "conductivity_s_per_m": 6}]}
        lines = {axis: [-1, 0, 1, 2] for axis in "xyz"}
        ownership = np.full((3, 2 if sheet else 1, 1, 1), -2)
        ownership[0] = -1
        if sheet:
            ownership[0, 0] = 0
        material = material_partition(Structure(), case, lines, [[1, 2] if sheet else [1], [1], [1]], ownership)
        electric = np.ones(ownership.shape, dtype=complex) * (2 + 3j)
        conduction = electric * material[0]
        if sheet:
            # @brief 실제 dump는 대체 전의 material kappa를 보존하므로 sheet 위치의 J가 0이라고 가정하지 않는다.
            conduction[0, 0] = electric[0, 0] * 4
        frequency, timestep = 2.4e9, 1e-12
        angle = math.pi * frequency * timestep
        total = (conduction + electric * (1.5 + 10j)) * math.cos(angle) * np.exp(1j * angle)
        if sheet:
            total[0, 0] = electric[0, 0] * (1.5 + 10j) * math.cos(angle) * np.exp(1j * angle)
        return electric, conduction, total, [np.ones((1, 1, 1))] * 3, ownership, frequency, timestep, [{"id": "s"}], material

    def test_mixed_edge_allocates_each_conductivity_once(self):
        """! @brief 동일 edge의 비아/유전체 전류를 가중 전도도 비율로 나누고 합계를 보존한다."""
        result, audit = partition_work(*self.fixture())
        self.assertAlmostEqual(result["dielectric_loss_w_s2"], 6.5)
        self.assertAlmostEqual(result["via_loss_w_s2"], 19.5)
        self.assertEqual(result["sheet_loss_w_s2"], 0)
        self.assertAlmostEqual(audit["assigned_volume_work_w_s2"], audit["volume_work_w_s2"])
        self.assertEqual(len(result["via_components"]), 1)

    def test_sheet_overrides_volume_work_at_pad_barrel_interface(self):
        """! @brief EC_G/EC_C 대체 위치는 sheet에만 배정하고 인접 실제 체적만 비아/유전체에 배정한다."""
        result, _ = partition_work(*self.fixture(sheet=True))
        self.assertAlmostEqual(result["sheet_loss_w_s2"], 9.75)
        self.assertAlmostEqual(result["conductor_loss_w_s2"], 19.5 + 9.75)
        self.assertAlmostEqual(result["dielectric_loss_w_s2"] + result["conductor_loss_w_s2"], 35.75)
        fixture = list(self.fixture(sheet=True))
        fixture[1][0, 0] *= 1000
        repeated, _ = partition_work(*fixture)
        self.assertEqual(repeated, result)

    def test_nonuniform_quarter_area_is_not_equal_vote(self):
        """! @brief 비균일 dual 면의 반대쪽 셀 폭에 비례하여 전도도를 평균한다."""
        import numpy as np

        class Structure:
            """! @brief y 양의 quadrant만 비아로 정의한다."""

            def GetPropertyByCoordPriority(self, point, prop_type):
                """! @brief 원래 quarter 좌표로 우선순위를 조회한다."""
                name = "via_v" if point[1] > 0 else "dielectric_d"
                return SimpleNamespace(GetName=lambda: name)

        case = {"layers": [{"id": "d", "role": "dielectric", "kappa_s_per_m": 2}], "vias": [{"id": "v", "conductivity_s_per_m": 6}]}
        ownership = np.full((3, 1, 1, 1), -2)
        ownership[0] = -1
        coefficient, pieces = material_partition(Structure(), case, {"x": [-1, 0, 1], "y": [-1, 0, 3], "z": [-1, 0, 1]}, [[1]] * 3, ownership)
        self.assertAlmostEqual(coefficient[0, 0, 0, 0], 5)
        self.assertAlmostEqual(next(item for item in pieces if item["kind"] == "via")["fraction"][0], 0.9)

    def test_current_mismatch_and_unassigned_current_are_rejected(self):
        """! @brief 잘못된 native 재료 평균이나 빠진 체적 전류를 조용히 유전체로 더하지 않는다."""
        fixture = list(self.fixture())
        fixture[1] *= 1.2
        with self.assertRaisesRegex(ProjectError, "유효 전도도"):
            partition_work(*fixture)

    def test_negative_sheet_work_is_preserved(self):
        """! @brief 독립 sheet 일이 음수이면 0으로 잘라 손실 합격을 만들지 않는다."""
        fixture = list(self.fixture(sheet=True))
        angle = math.pi * fixture[5] * fixture[6]
        fixture[2][0, 0] = -fixture[0][0, 0] * math.cos(angle) * complex(math.cos(angle), math.sin(angle))
        result, _ = partition_work(*fixture)
        self.assertLess(result["sheet_loss_w_s2"], 0)


if __name__ == "__main__":
    unittest.main()
