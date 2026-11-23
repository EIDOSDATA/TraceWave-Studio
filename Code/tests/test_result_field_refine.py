"""! @brief 복소 위상 변화, 실제 Yee 중심 좌표, 기존 셀 범위와 비유한 원문을 검사한다."""

from copy import deepcopy
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

    def test_nonfinite_samples_fail(self):
        with self.assertRaises(ProjectError):
            self.candidates([[1j, float("nan")]])
