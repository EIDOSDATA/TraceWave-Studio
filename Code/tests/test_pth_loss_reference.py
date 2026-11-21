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


    def test_axial_shell_weighting_for_prescribed_ghz_boundary_skin_profile(self):
        """! @brief 10 GHz 두께 방향 지수 감쇠의 해석 적분과 native PTH 분할을 비교한다."""
        import CSXCAD
        import numpy as np

        frequency = 10e9
        conductivity = 58e6
        permeability = 4 * math.pi * 1e-7
        depth = math.sqrt(2 / (2 * math.pi * frequency * permeability * conductivity))
        inner, outer, length = 8 * depth, 13 * depth, 10 * depth
        step_mm = depth * 1000 / 6
        outer_mm, inner_mm, length_mm = (value * 1000 for value in (outer, inner, length))
        csx = CSXCAD.ContinuousStructure()
        csx.AddMaterial("via_v", epsilon=1, kappa=conductivity).AddCylindricalShell(
            start=[0, 0, 0], stop=[0, 0, length_mm], radius=(outer_mm + inner_mm) / 2,
            shell_width=outer_mm - inner_mm, priority=6)
        case = {"layers": [], "vias": [{"id": "v", "conductivity_s_per_m": conductivity}]}
        limit = math.ceil(outer_mm / step_mm) + 2
        lateral = [i * step_mm for i in range(-limit, limit + 1)]
        lines = {"x": lateral, "y": lateral, "z": [-length_mm / 4, 0.0, length_mm / 2, length_mm, 5 * length_mm / 4]}
        indices = [list(range(1, len(lateral) - 1)) for _ in "xy"] + [[1, 2]]
        shape = (3, *(len(axis) for axis in indices))
        sheet = np.full(shape, -1)
        partition = material_partition(csx, case, lines, indices, sheet)
        electric = np.zeros(shape, dtype=complex)
        transverse_m = np.asarray(lateral[1:-1]) * 0.001
        radius_m = np.hypot(transverse_m[:, None], transverse_m)
        electric[2] = np.exp(-(1 + 1j) * (outer - radius_m) / depth)[:, :, None]
        conduction = electric * partition[0]
        weights = [edge_weights(lines, indices, direction) for direction in range(3)]
        recorded, audit = partition_work(electric, conduction, conduction, weights, sheet, frequency, 1e-15, [], partition)

        #! r dr의 곡률을 포함한 원통 껍질의 독립 해석 적분이다.
        decay = 2 / depth
        thickness = outer - inner
        endpoint = math.exp(-decay * thickness)
        integral = outer * (1 - endpoint) / decay - (1 - (1 + decay * thickness) * endpoint) / decay**2
        reference = math.pi * conductivity * length * integral
        relative_error = abs(recorded["via_loss_w_s2"] / reference - 1)
        self.assertLess(relative_error, 0.02, {"reference": reference, "actual": recorded["via_loss_w_s2"],
                                             "relative_error": relative_error})
        self.assertAlmostEqual(audit["volume_work_w_s2"] / audit["assigned_volume_work_w_s2"], 1)
        self.assertEqual(recorded["sheet_loss_w_s2"], 0)


if __name__ == "__main__":
    unittest.main()
