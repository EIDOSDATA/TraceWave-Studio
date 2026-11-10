"""! @brief 표본 위치에 의존하지 않는 native 급전 접촉과 sheet 연결성 경계를 검증한다."""

from copy import deepcopy
import math
import unittest

from rfad.application.pcb_contacts import validate_native_contacts
from rfad.domain.errors import ProjectError


def rectangle(x_min, y_min, x_max, y_max):
    """! @brief 명시한 경계의 단순 사각형 polygon을 만든다."""
    return [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]]


def shape(identity, net_id, **overrides):
    """! @brief 접촉 판정에 소비되는 유효 도체 의미만 포함한 시험 입력을 만든다."""
    return {"id": identity, "net_id": net_id, "material_id": "copper", "sheet_z_mm": 0,
            "thickness_m": 35e-6, "conductivity_s_per_m": 58e6, **overrides}


def fixture():
    """! @brief 양 끝만 도체와 닿는 10 mm 급전 간극의 작은 순수 계약 사례다."""
    shapes = [shape("reference", "ground"), shape("positive", "signal")]
    port = {"id": "port", "start_mm": [0, 0, 0], "stop_mm": [10, 0, 0],
            "reference_geometry_id": "reference", "positive_geometry_id": "positive"}
    polygons = {"reference": [rectangle(-2, -1, 0, 1)], "positive": [rectangle(10, -1, 12, 1)]}
    return shapes, port, polygons


class NativeContactsTests(unittest.TestCase):
    """! @brief 실제 polygon의 접촉, 간극과 서로 다른 전기 의미 충돌을 검사한다."""

    def assert_code(self, code, shapes, port, polygons, tolerance=0.01):
        """! @brief 오류 종류와 관련 원본 위치가 함께 전달되는지 검사한다."""
        with self.assertRaises(ProjectError) as raised:
            validate_native_contacts(shapes, port, tolerance, polygons)
        self.assertEqual(raised.exception.code, code)
        self.assertIn("field_path", raised.exception.details)

    def test_boundary_contact_does_not_mutate_source(self):
        """! @brief 정상 급전은 원본 polygon/port/도체를 변경하지 않는다."""
        shapes, port, polygons = fixture()
        before = deepcopy((shapes, port, polygons))
        validate_native_contacts(shapes, port, 0.01, polygons)
        self.assertEqual((shapes, port, polygons), before)

    def test_analytic_curve_without_native_contact_is_rejected(self):
        """! @brief 원래 곡선의 접점이 내접 polygon에서 떨어지면 단절을 숨기지 않는다."""
        shapes, port, polygons = fixture()
        port["start_mm"] = [math.sqrt(0.5), math.sqrt(0.5), 0]
        port["stop_mm"][1] = math.sqrt(0.5)
        polygons["reference"] = [[[0, -1], [1, 0], [0, 1], [-1, 0]]]
        self.assert_code("E_PORT", shapes, port, polygons)

    def test_thin_crossing_between_old_sample_locations_is_rejected(self):
        """! @brief 31개 고정 표본 사이의 얇은 횡단 도체도 간극 충돌로 잡는다."""
        shapes, port, polygons = fixture()
        shapes.append(shape("blocker", "ground"))
        polygons["blocker"] = [rectangle(0.14, -0.01, 0.15, 0.01)]
        self.assertFalse(any(0.14 <= 10 * i / 32 <= 0.15 for i in range(1, 32)))
        self.assert_code("E_PORT", shapes, port, polygons)

    def test_tangent_collinear_and_contained_gap_are_rejected(self):
        """! @brief 점 하나 접촉, 경계 중첩과 간극 전체 포함도 급전 단락으로 차단한다."""
        for blocker in ([[5, 0], [6, 1], [4, 1]], rectangle(4, 0, 6, 1), rectangle(-3, -2, 13, 2)):
            with self.subTest(blocker=blocker):
                shapes, port, polygons = fixture()
                shapes.append(shape("blocker", "ground"))
                polygons["blocker"] = [blocker]
                self.assert_code("E_PORT", shapes, port, polygons)

    def test_same_projection_on_different_sheet_is_allowed(self):
        """! @brief 서로 다른 높이의 도체를 평면 단락으로 오인하지 않는다."""
        shapes, port, polygons = fixture()
        shapes.append(shape("bridge", "third-net", sheet_z_mm=1))
        polygons["bridge"] = [rectangle(-3, -2, 13, 2)]
        validate_native_contacts(shapes, port, 0.01, polygons)

    def test_same_net_and_effective_material_may_overlap(self):
        """! @brief 같은 net과 sheet 물성은 의도한 도체 합집합으로 접속할 수 있다."""
        shapes, port, polygons = fixture()
        shapes.append(shape("extension", "ground"))
        polygons["extension"] = [rectangle(-3, -0.5, -1, 0.5)]
        validate_native_contacts(shapes, port, 0.01, polygons)

    def test_incompatible_sheet_semantics_cannot_touch(self):
        """! @brief net 또는 유효 재료/두께/전도율이 다른 sheet 접촉을 각각 차단한다."""
        for overrides in ({"net_id": "other"}, {"material_id": "other"}, {"thickness_m": 18e-6}, {"conductivity_s_per_m": 1e7}):
            with self.subTest(overrides=overrides):
                shapes, port, polygons = fixture()
                incompatible = shape("other", "ground")
                incompatible.update(overrides)
                shapes.append(incompatible)
                polygons["other"] = [rectangle(-3, -0.5, -2, 0.5)]
                self.assert_code("E_CONNECTIVITY", shapes, port, polygons)

    def test_containment_and_crossing_without_containment_are_rejected(self):
        """! @brief 완전 포함과 양쪽 첫 점이 바깥인 변 교차도 연결성 충돌로 검출한다."""
        for polygon in (rectangle(-1.5, -0.5, -0.5, 0.5), rectangle(-2.5, 0.5, -1.5, 1.5)):
            shapes, port, polygons = fixture()
            shapes.append(shape("other", "other"))
            polygons["other"] = [polygon]
            self.assert_code("E_CONNECTIVITY", shapes, port, polygons)

    def test_two_curve_tolerances_define_conservative_clearance(self):
        """! @brief 각 polygon의 근사 오차 합 이내 간격은 전기적 분리를 보장하지 않는다."""
        for gap in (0.01, 0.019, 0.02, 0.03):
            with self.subTest(gap=gap):
                shapes, port, polygons = fixture()
                shapes.append(shape("other", "other"))
                polygons["other"] = [rectangle(-3, -0.5, -2 - gap, 0.5)]
                if gap <= 0.02:
                    self.assert_code("E_CONNECTIVITY", shapes, port, polygons)
                else:
                    validate_native_contacts(shapes, port, 0.01, polygons)

    def test_port_plane_identity_and_nonfinite_coordinates_are_rejected(self):
        """! @brief 실제 도체 높이/식별과 다른 급전 및 비유한 좌표를 허용하지 않는다."""
        for mode in ("height", "different-height", "identity", "nan"):
            shapes, port, polygons = fixture()
            if mode == "height":
                port["start_mm"][2] = port["stop_mm"][2] = 1
            elif mode == "different-height":
                port["stop_mm"][2] = 1
            elif mode == "identity":
                port["reference_geometry_id"] = "absent"
            else:
                port["start_mm"][0] = float("nan")
            self.assert_code("E_PORT", shapes, port, polygons)

    def test_native_polygon_validation_and_resource_limits(self):
        """! @brief native 경계 누락/퇴화/점 상한을 구조화된 오류로 처리한다."""
        for invalid in ([], [[[0, 0], [1, 1]]], [[[0, 0], [1, 1], [2, 2]]], [[[0, 0], [1, 0], [0, float("nan")]]]):
            shapes, port, polygons = fixture()
            polygons["reference"] = invalid
            self.assert_code("E_GEOMETRY", shapes, port, polygons)
        shapes, port, polygons = fixture()
        polygons["reference"] = [[[math.cos(i * 2 * math.pi / 8193), math.sin(i * 2 * math.pi / 8193)] for i in range(8193)]]
        self.assert_code("E_RESOURCE", shapes, port, polygons)
        shapes, port, polygons = fixture()
        del polygons["reference"]
        self.assert_code("E_SCHEMA", shapes, port, polygons)


if __name__ == "__main__":
    unittest.main()
