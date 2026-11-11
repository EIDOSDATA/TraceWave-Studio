"""! @brief 실제 CSXCAD 중공 shell과 알려진 균일 전계의 해석적 Joule 적분을 대조한다."""

import importlib.util
import math
import unittest

from rfad.adapters.solvers.openems.pcb_loss_partition import material_partition, partition_work
from rfad.adapters.solvers.openems.pcb_absorption import edge_weights


@unittest.skipUnless(importlib.util.find_spec("CSXCAD") and importlib.util.find_spec("numpy"), "격리 native CSXCAD/numpy 환경이 필요합니다.")
class HollowShellIntegralReferenceTests(unittest.TestCase):
    """! @brief 전류를 수용 전력에서 역산하지 않고 별도 해석적 체적과 대조한다."""

    def test_uniform_axial_field_converges_to_analytic_hollow_shell_work(self):
        """! @brief 실제 우선순위/구멍의 QuarterCell 적분이 pi*(ro^2-ri^2)*L로 접근한다."""
        import CSXCAD
        import numpy as np

        observations = []
        for step in (0.1, 0.05, 0.025):
            csx = CSXCAD.ContinuousStructure()
            csx.AddMaterial("dielectric_d", epsilon=4, kappa=2).AddBox([-1, -1, 0], [1, 1, 1], priority=1)
            csx.AddMaterial("via_v", epsilon=1, kappa=10000).AddCylindricalShell(start=[0, 0, 0], stop=[0, 0, 1], radius=0.35, shell_width=0.1, priority=6)
            csx.AddMaterial("drill_v", epsilon=1, kappa=0).AddCylinder(start=[0, 0, 0], stop=[0, 0, 1], radius=0.3, priority=30)
            case = {"layers": [{"id": "d", "role": "dielectric", "kappa_s_per_m": 2}], "vias": [{"id": "v", "conductivity_s_per_m": 10000}]}
            count = round(1.2 / step)
            lines = {axis: [round(-0.6 + i * step, 12) for i in range(count + 1)] for axis in "xy"}
            lines["z"] = [round(-0.1 + i * 0.1, 12) for i in range(14)]
            indices = [list(range(1, len(lines[axis]) - 1)) for axis in "xyz"]
            shape = (3, *(len(item) for item in indices))
            sheet = np.full(shape, -1)
            material = material_partition(csx, case, lines, indices, sheet)
            electric = np.zeros(shape, dtype=complex)
            electric[2] = 1
            conduction = electric * material[0]
            weights = [edge_weights(lines, indices, direction) for direction in range(3)]
            result, audit = partition_work(electric, conduction, conduction, weights, sheet, 1e9, 1e-15, [], material)
            analytic = 0.5 * 10000 * math.pi * (0.4 ** 2 - 0.3 ** 2) * 1.0 * 1e-9
            error = abs(result["via_loss_w_s2"] / analytic - 1)
            observations.append(error)
            self.assertAlmostEqual(audit["volume_work_w_s2"] / audit["assigned_volume_work_w_s2"], 1)
            self.assertEqual(result["sheet_loss_w_s2"], 0)
        self.assertLess(observations[-1], 0.02, observations)
        self.assertLess(observations[-1], observations[0], observations)


if __name__ == "__main__":
    unittest.main()
