"""! @brief 복소 위상 변화, 실제 Yee 중심 좌표, 기존 셀 범위와 비유한 원문을 검사한다."""

from copy import deepcopy
import math
import unittest

from rfad.application.result_field_refine import cells
from rfad.domain.errors import ProjectError


class FieldRefinementTests(unittest.TestCase):
    """! @brief 진폭이 동일한 표본의 위상 반전도 반영하며 상수장은 보존한다."""

    def setUp(self):
        self.lines = {axis: [0, 1, 2, 3] for axis in "xyz"}
        self.bounds = [[0, 3]] * 3
        self.positions = [[0.5, 1.5], [0, 1]]

    def candidates(self, values):
        return cells(values, ["x", "y"], self.positions, "z", 1, self.lines, self.bounds, 0.2)

    def test_complex_phase_discontinuity_spans_two_primary_cells(self):
        values = [[1j, -1j], [1j, -1j]]
        original = deepcopy(values)
        result = self.candidates(values)
        self.assertEqual([(entry["axis"], entry["source_interval"]) for entry in result], [("x", 0), ("x", 1)])
        self.assertTrue(all(entry["target_cell_mm"] == 0.5 and entry["relative_change"] == 2 for entry in result))
        self.assertEqual(values, original)

    def test_uniform_zero_and_outside_model(self):
        for value in (0j, 2 + 3j):
            self.assertEqual(self.candidates([[value] * 2] * 2), [])
        self.bounds = [[0, 3], [0, 3], [2, 3]]
        self.assertEqual(self.candidates([[0j, 1j], [0j, 1j]]), [])

    def test_board_face_from_both_sides_uses_real_interior_and_preserves_input(self):
        """! @brief 모델 윗면과 표본 위치가 각각 한 ULP씩 달라도 공기 쪽 껍질을 만들지 않는다."""
        node = .965
        self.lines["z"] = [.035, .5, node, 1.45]
        around = (math.nextafter(node, -math.inf), node, math.nextafter(node, math.inf))
        for upper in around:
            for position in around:
                bounds = [[0, 3], [0, 3], [.035, upper]]
                original = deepcopy((self.lines, bounds))
                selected = cells([[1j, -1j]], ["x", "y"], [[.5, 1.5], [0]], "z", position,
                                 self.lines, bounds, .05)
                self.assertEqual([row["bounds_mm"][2] for row in selected], [[.5, min(upper, node)]] * 2)
                self.assertEqual((self.lines, bounds), original)
        for position in around:
            linked = cells([[1j, -1j]], ["x", "y"], [[.5, 1.5], [0]], "z", position,
                           self.lines, [[0, 3], [0, 3], [node, 1.45]], .05)
            self.assertEqual([row["bounds_mm"][2] for row in linked], [[node, 1.45]] * 2)

    def test_comparison_axis_snaps_both_endpoints_but_rejects_external_samples(self):
        """! @brief 변화축 양 끝의 ULP 차이로 이웃 셀을 추가하지 않고 양 끝의 실제 외부점은 거절한다."""
        node, stop = .965, 1.45
        self.lines["x"] = [.1, .5, node, stop, 2.]
        self.lines["z"] = [.035, .5, node, 1.45]
        for left in (math.nextafter(node, -math.inf), node, math.nextafter(node, math.inf)):
            for right in (math.nextafter(stop, -math.inf), stop, math.nextafter(stop, math.inf)):
                candidates = cells([[1j, -1j]], ["x", "y"], [[left, right], [0]], "z", node,
                                   self.lines, [[.1, stop], [0, 3], [.035, node]], .05)
                self.assertEqual([c["source_interval"] for c in candidates], [2])
        bounds = [[node, stop], [0, 3], [.035, node]]
        for left, right, z in ((node - 1e-10, stop, node), (node, stop + 1e-10, node),
                               (node, stop, node + 1e-10), (node, stop, .035 - 1e-10)):
            self.assertEqual(cells([[1j, -1j]], ["x", "y"], [[left, right], [0]], "z", z,
                                   self.lines, bounds, .05), [])

    def test_distinct_thin_layer_and_subminimum_clip_are_not_snapped(self):
        """! @brief 유효한 얇은 물리층과 최소 셀 미만의 실제 절단을 반올림 오차와 구분한다."""
        bottom, top = .965, .965123
        self.lines["z"] = [.5, bottom, top, 1.4]
        for upper, expected in ((top, [[bottom, top]] * 2), (bottom + 1e-10, [])):
            selected = cells([[1j, -1j]], ["x", "y"], [[.5, 1.5], [0]], "z", bottom,
                             self.lines, [[0, 3], [0, 3], [.5, upper]], .05)
            self.assertEqual([row["bounds_mm"][2] for row in selected], expected)

    def test_minimum_thickness_survives_translation_using_endpoint_precision(self):
        """! @brief 실제 최소 두께 층은 평행 이동해도 유지하고 하한보다 확실히 얇은 층은 제외한다."""
        for lo, hi, expected in ((0., .0001, 2), (.965, .9651, 2), (.965, .9651 - 1e-10, 0)):
            self.lines["z"] = [lo - .5, lo, hi, hi + .5]
            selected = cells([[1j, -1j]], ["x", "y"], [[.5, 1.5], [0]], "z", lo,
                             self.lines, [[0, 3], [0, 3], [lo, hi]], .05)
            self.assertEqual([c["bounds_mm"][2] for c in selected], [[lo, hi]] * expected)

    def test_nonfinite_samples_fail(self):
        with self.assertRaises(ProjectError):
            self.candidates([[1j, float("nan")]])
