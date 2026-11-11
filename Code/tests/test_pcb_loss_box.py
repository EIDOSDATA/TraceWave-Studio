"""! @brief 단일 box 가속이 native QuarterCell 좌표/면적 평균과 일치하는지 검증한다."""

import importlib.util
import unittest

from rfad.adapters.solvers.openems.pcb_loss_box import box_partition
from rfad.adapters.solvers.openems.pcb_loss_partition import sampled_material_partition


@unittest.skipUnless(importlib.util.find_spec("CSXCAD") and importlib.util.find_spec("numpy"), "native CSXCAD/numpy가 필요합니다.")
class BoxPartitionTests(unittest.TestCase):
    """! @brief 실제 재료 우선순위를 사용하는 일반 경로를 독립 기준으로 비교한다."""

    def setup_box(self):
        """! @brief 계면/비균일 격자와 source/sheet 제외를 포함한 명시적 시험 재료다."""
        import CSXCAD
        import numpy as np

        csx = CSXCAD.ContinuousStructure()
        prop = csx.AddMaterial("dielectric_d", epsilon=3.66, kappa=0.004)
        prop.AddBox([0, 0, 0], [2, 3, 0.762], priority=1)
        case = {"board": {"kind": "rectangle", "bounds_mm": [[0, 2], [0, 3]]}, "vias": [],
                "layers": [{"id": "d", "role": "dielectric", "z_min_mm": 0, "thickness_mm": 0.762, "kappa_s_per_m": 0.004}]}
        lines = {"x": [-1, -0.2, 0, 0.3, 1, 2, 2.3, 3], "y": [-1, -0.1, 0, 0.5, 2, 3, 3.5, 4],
                 "z": [-1, -0.1, 0, 0.2, 0.6, 0.762, 1, 2]}
        indices = [list(range(1, 7)) for _ in "xyz"]
        sheet = np.full((3, 6, 6, 6), -1)
        sheet[0, 2, 2, 2] = 0
        sheet[1, 3, 3, 3] = -2
        return csx, case, lines, indices, sheet

    def test_nonuniform_box_partition_matches_native_sampling(self):
        """! @brief 세 방향과 모든 계면/공기/제외 edge의 전도도와 분할이 일치한다."""
        import numpy as np

        args = self.setup_box()
        fast = box_partition(*args)
        self.assertIsNotNone(fast)
        reference = sampled_material_partition(*args)
        np.testing.assert_allclose(fast[0], reference[0], rtol=1e-14, atol=0)
        np.testing.assert_array_equal(fast[1][0]["indices"], reference[1][0]["indices"])
        np.testing.assert_allclose(fast[1][0]["fraction"], reference[1][0]["fraction"], rtol=0, atol=0)

    def test_unknown_or_changed_native_geometry_does_not_use_fast_path(self):
        """! @brief 다층/원형/비아와 XML의 다른 box를 단일 box로 추정하지 않는다."""
        for variant in ("board", "via", "layer", "native"):
            args = self.setup_box()
            csx, case, _, _, _ = args
            if variant == "board":
                case["board"]["kind"] = "circle"
            elif variant == "via":
                case["vias"] = [{"id": "v"}]
            elif variant == "layer":
                case["layers"].append(dict(case["layers"][0]))
            else:
                csx.GetAllProperties()[0].GetPrimitive(0).SetStop([2, 3, 0.8])
            with self.subTest(variant=variant):
                self.assertIsNone(box_partition(*args))

    def test_pinned_xml_conductivity_precision_is_explicitly_supported(self):
        """! @brief native XML의 7자리 반올림만 허용하고 입력 가중 전도도는 일반 경로와 같게 유지한다."""
        import numpy as np

        args = self.setup_box()
        csx, case, _, _, _ = args
        value = 0.0015412481697104049
        case["layers"][0]["kappa_s_per_m"] = value
        csx.GetAllProperties()[0].SetMaterialProperty(kappa=float(format(value, ".7g")))
        fast = box_partition(*args)
        self.assertIsNotNone(fast)
        np.testing.assert_allclose(fast[0], sampled_material_partition(*args)[0], rtol=1e-14, atol=0)
        csx.GetAllProperties()[0].SetMaterialProperty(kappa=value * 1.01)
        self.assertIsNone(box_partition(*args))


if __name__ == "__main__":
    unittest.main()
