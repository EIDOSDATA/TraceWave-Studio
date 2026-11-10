"""! @brief 구멍과 비볼록 경계의 실제 면적을 보존하는 순수 기하를 검증한다."""

from copy import deepcopy
import math
import unittest

from rfad.domain.errors import ProjectError
from rfad.domain.planar import decompose_region, point_in_loop, signed_area, validate_region


class PlanarTests(unittest.TestCase):
    """! @brief 단위/방향/이동과 무관하게 빈 영역을 채우지 않는지 확인한다."""

    def test_concave_region_two_holes_and_reversed_winding(self):
        """! @brief 비볼록 면과 두 hole의 면적 및 각 조각 내부를 독립 계산으로 확인한다."""
        outer = [[0, 0], [10, 0], [10, 8], [6, 8], [6, 10], [0, 10]]
        holes = [[[1, 1], [3, 1], [3, 4], [1, 4]], [[5, 2], [8, 3], [5, 4]]]
        before = deepcopy((outer, holes))
        for reverse in (False, True):
            for scale in (1e-3, 1, 1000):
                transformed = [[[scale * x + 100 * scale, scale * y - 50 * scale] for x, y in (loop[::-1] if reverse else loop)] for loop in [outer, *holes]]
                pieces = decompose_region(transformed[0], transformed[1:])
                self.assertAlmostEqual(math.fsum(signed_area(piece) for piece in pieces) / scale ** 2, 83, places=8)
                for piece in pieces:
                    self.assertIn(len(piece), (3, 4))
                    center = [sum(p[i] for p in piece) / len(piece) for i in (0, 1)]
                    self.assertTrue(point_in_loop(center, transformed[0]))
                    self.assertFalse(any(point_in_loop(center, hole, include_boundary=False) for hole in transformed[1:]))
        self.assertEqual((outer, holes), before)

    def test_self_touch_cross_overlap_and_external_holes_rejected(self):
        """! @brief 경계 교차/접촉/중첩을 면으로 자동 보정하지 않는다."""
        box = [[0, 0], [10, 0], [10, 10], [0, 10]]
        hole = [[2, 2], [8, 2], [8, 8], [2, 8]]
        invalid = [
            ([[0, 0], [10, 10], [0, 10], [10, 0]], []),
            (box + [box[0]], []),
            ([[0, 0], [5, 0], [2, 0], [2, 5], [0, 5]], []),
            (box, [[[0, 2], [1, 2], [1, 3], [0, 3]]]),
            (box, [[[12, 2], [13, 2], [13, 3], [12, 3]]]),
            (box, [hole, [[3, 3], [4, 3], [4, 4], [3, 4]]]),
            (box, [hole, [[7, 7], [9, 7], [9, 9], [7, 9]]]),
        ]
        for outer, holes in invalid:
            with self.subTest(outer=outer, holes=holes), self.assertRaises(ProjectError):
                validate_region(outer, holes)

    def test_collinear_vertices_and_triangular_tip_are_retained(self):
        """! @brief 합법적인 일직선 점과 사선 꼭짓점도 분할에서 면적을 잃지 않는다."""
        outer = [[0, 0], [2, 0], [4, 0], [7, 5], [2, 8], [0, 5]]
        pieces = decompose_region(outer, [])
        self.assertAlmostEqual(sum(signed_area(piece) for piece in pieces), 38, places=10)

    def test_nonfinite_and_resource_limits_are_explicit(self):
        """! @brief 비유한 수치와 과도한 점 목록을 계산 전에 거절한다."""
        for points in ([[0, 0], [1, 0], [1, float("nan")]], [[math.cos(i), math.sin(i)] for i in range(65)]):
            with self.assertRaises(ProjectError):
                validate_region(points, [])


if __name__ == "__main__":
    unittest.main()
