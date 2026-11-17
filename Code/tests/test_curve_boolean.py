"""! @brief 원호를 근사하지 않는 절삭의 면적/성분/퇴화 경계를 독립 수식으로 검증한다."""

from copy import deepcopy
import importlib.util
import math
import unittest

from rfad.domain.curve_boolean import difference
from rfad.domain.drawing_layout import _inside, arc, polygon, mechanical_loops
from rfad.domain.errors import ProjectError


def rectangle(x0, y0, x1, y1):
    """! @brief 양의 방향 사각형으로 독립 기대 면적을 갖는 fixture를 만든다."""
    return [polygon([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])]


def area(loops):
    """! @brief Green 적분을 직접 사용해 결과 곡선의 signed 면적을 구한다."""
    result = 0.0
    for loop in loops:
        for edge in loop:
            if edge["kind"] == "line":
                a, b = edge["start"], edge["end"]
                result += (a[0] * b[1] - b[0] * a[1]) / 2
            else:
                a = math.radians(edge["start_deg"])
                theta = math.radians(edge["sweep_deg"])
                b, r = a + theta, edge["radius"]
                x, y = edge["center"]
                result += (r * r * theta + r * x * (math.sin(b) - math.sin(a)) + r * y * (math.cos(a) - math.cos(b))) / 2
    return result


class CurveBooleanTests(unittest.TestCase):
    """! @brief 고정 CAD 최소 치수보다 충분히 큰 유한 해석형 경계를 시험한다."""

    def test_contained_hole_area_and_input_immutability(self):
        """! @brief 포함 원을 중공 면으로 만들고 입력의 순서/원호를 유지한다."""
        subject, cut = rectangle(0, 0, 20, 20), [[arc([10, 10], 1)]]
        before = deepcopy((subject, cut))
        result = difference(subject, cut, _inside)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(area(result), 400 - math.pi, places=10)
        self.assertEqual((subject, cut), before)
        self.assertFalse(_inside([10, 10], result))

    def test_crossing_circle_splits_strip_with_exact_arcs(self):
        """! @brief NPTH로 끊어진 도체의 두 성분과 원 절단 적분을 대조한다."""
        result = difference(rectangle(-8, -.5, 8, .5), [[arc([0, 0], 1)]], _inside)
        expected_removed = 2 * (.5 * math.sqrt(.75) + math.asin(.5))
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(area(result), 16 - expected_removed, places=10)
        arcs = [edge for loop in result for edge in loop if edge["kind"] == "arc"]
        self.assertAlmostEqual(sum(abs(edge["sweep_deg"]) for edge in arcs), 120, places=9)
        self.assertTrue(all(edge["radius"] == 1 for edge in arcs))

    def test_line_cut_across_rectangle_has_two_components(self):
        """! @brief 직선 절삭의 연결 성분과 면적을 보존한다."""
        result = difference(rectangle(0, 0, 20, 20), rectangle(9, -1, 11, 21), _inside)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(area(result), 360, places=10)

    def test_circle_lens_uses_two_exact_circle_boundaries(self):
        """! @brief 두 원의 교집합 렌즈 수식과 원 minus 원의 결과를 대조한다."""
        r, d = 2, 3
        result = difference([[arc([0, 0], r)]], [[arc([d, 0], r)]], _inside)
        intersection = 2 * r * r * math.acos(d / (2 * r)) - d / 2 * math.sqrt(4 * r * r - d * d)
        self.assertEqual(len(result), 1)
        self.assertTrue(all(edge["kind"] == "arc" for edge in result[0]))
        self.assertAlmostEqual(area(result), math.pi * r * r - intersection, places=10)

    def test_capsule_formula_rotation_and_counterclockwise_result(self):
        """! @brief 전체 슬롯 길이와 폭에서 산출한 면적은 회전에 따라 바뀌지 않는다."""
        for angle in (0, 25, 90, -173):
            with self.subTest(angle=angle):
                cut = mechanical_loops({"kind": "capsule", "center_mm": [10, 10], "finished_length_mm": 4,
                                        "finished_width_mm": 1, "rotation_deg": angle})
                result = difference(rectangle(0, 0, 20, 20), cut, _inside)
                self.assertAlmostEqual(area(result), 400 - (3 + math.pi / 4), places=9)

    def test_existing_inner_hole_and_disjoint_cut_do_not_create_material(self):
        """! @brief 이미 비어 있는 영역의 제거가 새 구리로 되살아나지 않는다."""
        subject = rectangle(0, 0, 20, 20) + [[arc([10, 10], 3)]]
        for cut in ([[arc([10, 10], 1)]], [[arc([30, 30], 2)]]):
            result = difference(subject, cut, _inside)
            self.assertAlmostEqual(area(result), 400 - 9 * math.pi, places=9)
            self.assertFalse(_inside([10, 10], result))

    def test_tangent_and_coincident_boundaries_are_explicitly_unsupported(self):
        """! @brief 접점/겹친 경계를 임의 치유하거나 성공으로 반환하지 않는다."""
        cases = [(rectangle(0, 0, 20, 20), [[arc([1, 10], 1)]]),
                 ([[arc([0, 0], 2)]], [[arc([0, 0], 2)]]),
                 (rectangle(0, 0, 20, 20), rectangle(0, 2, 5, 4))]
        for subject, cut in cases:
            with self.subTest(cut=cut), self.assertRaises(ProjectError) as caught:
                difference(subject, cut, _inside)
            self.assertEqual(caught.exception.code, "E_UNSUPPORTED")

    def test_long_edges_do_not_merge_a_small_cut_by_parameter_tolerance(self):
        """! @brief 긴 선의 작은 매개변수 차이가 실제 작은 홀을 삭제하지 않는다."""
        result = difference(rectangle(-1e6, -5e-5, 1e6, 5e-5), [[arc([0, 0], 1e-4)]], _inside)
        self.assertEqual(len(result), 2)
        self.assertFalse(_inside([0, 0], result))
        arcs = [edge for loop in result for edge in loop if edge["kind"] == "arc"]
        self.assertAlmostEqual(sum(abs(edge["sweep_deg"]) for edge in arcs), 120, places=3)

    @unittest.skipUnless(importlib.util.find_spec("shapely"), "고정 GEOS 참조 환경에서 실행해야 합니다.")
    def test_ring_cuts_against_independent_geos_topology_and_area(self):
        """! @brief 고정 위치 12개를 GEOS의 고밀도 원 근사와 독립적으로 대조한다."""
        from shapely.geometry import Point
        ring = Point(0, 0).buffer(10, quad_segs=2048).difference(Point(0, 0).buffer(8, quad_segs=2048))
        subject = [[arc([0, 0], 10)], [arc([0, 0], 8)]]
        for radius in (1.3, 2.1):
            for distance in (7.1, 8.3, 9.4):
                for angle in (.23, 1.41):
                    with self.subTest(radius=radius, distance=distance, angle=angle):
                        center = [distance * math.cos(angle), distance * math.sin(angle)]
                        actual = difference(subject, [[arc(center, radius)]], _inside)
                        reference = ring.difference(Point(*center).buffer(radius, quad_segs=2048))
                        self.assertAlmostEqual(area(actual), reference.area, delta=5e-5)
                        components = list(reference.geoms) if reference.geom_type == "MultiPolygon" else [reference]
                        self.assertEqual(len(actual), sum(1 + len(item.interiors) for item in components))


if __name__ == "__main__":
    unittest.main()
