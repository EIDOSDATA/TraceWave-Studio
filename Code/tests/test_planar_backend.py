"""! @brief 선택 평면 엔진의 표현 한계, 빈 결과와 자동 수정 금지를 검증한다."""

import math
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rfad.adapters.planar_backend import operate, runtime
from rfad.domain.errors import ProjectError
from rfad.domain.planar import signed_area


class PlanarRuntimeCompatibilityTests(unittest.TestCase):
    """! @brief 선택 엔진의 구버전과 불완전 설치가 기본 설계 조회를 막지 않는지 확인한다."""

    def test_missing_or_mismatched_engine_metadata_disables_only_planar_support(self):
        """! @brief 구형 메타데이터를 고정 버전으로 오인하거나 AttributeError로 전파하지 않는다."""
        from rfad.application.precision_service import get
        from rfad.domain.project import new_project, validate_project

        for module in (SimpleNamespace(__version__="1.8.5"),
                       SimpleNamespace(__version__="2.2.0", geos_version_string="3.13.0"),
                       SimpleNamespace(__version__=None, geos_version_string=None)):
            with self.subTest(module=vars(module)):
                runtime.cache_clear()
                try:
                    with patch.dict(sys.modules, {"shapely": module}):
                        engine, metadata = runtime()
                        self.assertIsNone(engine)
                        self.assertFalse(metadata["available"])
                        self.assertTrue(metadata["reason"])
                        document = new_project("선택 엔진 불일치")
                        validate_project(document)
                        self.assertFalse(get(document, [])["planar_engine"]["available"])
                finally:
                    runtime.cache_clear()


class PlanarBackendTests(unittest.TestCase):
    """! @brief 작은 독립 면적/위상 기준 사례로 실제 GEOS 경계를 검증한다."""

    def setUp(self):
        """! @brief 엔진이 없는 환경은 계산 사례만 조건부 제외한다."""
        if not runtime()[1]["available"]:
            self.skipTest("고정 Shapely/GEOS 선택 엔진 필요")

    @staticmethod
    def box(x, y, width, height):
        """! @brief 기준 면적이 알려진 직사각형을 만든다."""
        return {"outer": [[x, y], [x + width, y], [x + width, y + height], [x, y + height]], "holes": []}

    def test_union_intersection_difference_have_independent_known_areas(self):
        a, b = self.box(0, 0, 10, 10), self.box(5, 0, 10, 10)
        for operation, expected in (("union", 150), ("intersection", 50), ("difference", 50)):
            with self.subTest(operation=operation):
                result, engine = operate([a, b], operation, {})
                self.assertEqual(len(result), 1)
                self.assertAlmostEqual(abs(signed_area(result[0]["outer"])), expected)
                self.assertEqual(engine["geos_version"], "3.14.1")

    def test_touching_intersection_and_empty_difference_do_not_become_deletions(self):
        a, b = self.box(0, 0, 10, 10), self.box(10, 0, 10, 10)
        for inputs, operation in (([a, b], "intersection"), ([a, a], "difference")):
            with self.subTest(operation=operation):
                with self.assertRaises(ProjectError):
                    operate(inputs, operation, {})

    def test_close_disjoint_edges_are_not_snapped_or_merged(self):
        result, _ = operate([self.box(0, 0, 1, 1), self.box(1 + 1e-8, 0, 1, 1)], "union", {})
        self.assertEqual(len(result), 2)
        edges = [max(point[0] for point in result[0]["outer"]), min(point[0] for point in result[1]["outer"])]
        self.assertGreater(edges[1] - edges[0], 0)

    def test_sixty_four_point_results_are_not_silently_simplified(self):
        def polygon(offset):
            """! @brief 서로 어긋난 64각형을 사용해 128개 교점을 만든다."""
            return {"outer": [[10 * math.cos((index + offset) * math.tau / 64),
                               10 * math.sin((index + offset) * math.tau / 64)] for index in range(64)], "holes": []}

        with self.assertRaises(ProjectError) as caught:
            operate([polygon(0), polygon(.5)], "intersection", {})
        self.assertEqual(caught.exception.code, "E_RESOURCE")

    def test_ninth_hole_is_reported_instead_of_filled_or_removed(self):
        outer = self.box(0, 0, 30, 30)
        outer["holes"] = [self.box(2 + (index % 3) * 8, 2 + (index // 3) * 8, 2, 2)["outer"] for index in range(8)]
        with self.assertRaises(ProjectError) as caught:
            operate([outer, self.box(18, 18, 2, 2)], "difference", {})
        self.assertEqual(caught.exception.code, "E_RESOURCE")

    def test_invalid_source_is_never_repaired(self):
        bow_tie = {"outer": [[0, 0], [2, 2], [0, 2], [2, 0]], "holes": []}
        with self.assertRaises(ProjectError):
            operate([bow_tie, self.box(0, 0, 3, 3)], "union", {})

    def test_negative_offset_preserves_hole_and_explicit_empty_block(self):
        outer = self.box(0, 0, 10, 10)
        outer["holes"] = [self.box(4, 4, 2, 2)["outer"]]
        result, _ = operate([outer], "offset", {"distance_mm": -1, "join": "mitre", "mitre_limit": 5})
        self.assertEqual(len(result[0]["holes"]), 1)
        area = abs(signed_area(result[0]["outer"])) - abs(signed_area(result[0]["holes"][0]))
        self.assertAlmostEqual(area, 48)
        with self.assertRaises(ProjectError):
            operate([outer], "offset", {"distance_mm": -100, "join": "mitre", "mitre_limit": 5})

    def test_round_offset_is_not_an_implicit_curve_approximation(self):
        with self.assertRaises(ProjectError) as caught:
            operate([self.box(0, 0, 2, 2)], "offset", {"distance_mm": 1, "join": "round", "mitre_limit": 5})
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
