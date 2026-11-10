"""! @brief native 패키지 없이 표시 mesh의 입력 결합과 렌더링 경계를 검증한다."""

from copy import deepcopy
import unittest
from uuid import NAMESPACE_URL, uuid5

from rfad.application.display_mesh import MAX_TRIANGLES, MAX_VERTICES, validate_display_mesh
from rfad.domain.errors import ProjectError


def fixture():
    """! @brief 안정 식별자와 닫힌 사면체를 가진 작은 표시 자료를 만든다."""
    identity = str(uuid5(NAMESPACE_URL, "rfad/display-mesh/body"))
    body = {"id": identity, "layer_id": identity, "role": "dielectric", "source_entity_ids": [identity],
            "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0.035]],
            "triangles": [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]]}
    return {"schema": "rfad.display-mesh/0.1", "snapshot": {"snapshot_id": "fixed-snapshot"}, "run_id": "fixed-run",
            "unit": "mm", "purpose": "display_only", "linear_deflection_mm": 0.05, "angular_deflection_rad": 0.15,
            "bodies": [body]}


class DisplayMeshTests(unittest.TestCase):
    """! @brief 파일 내용의 변조가 원본 또는 잘못된 GPU 자료로 승격되지 않도록 확인한다."""

    def setUp(self):
        """! @brief 원본 snapshot과 body mapping을 표시 자료와 별도로 보존한다."""
        self.mesh = fixture()
        self.snapshot = deepcopy(self.mesh["snapshot"])
        self.body_map = deepcopy(self.mesh["bodies"])

    def validate(self):
        """! @brief 원본 실행의 별도 기대값을 기준으로 표시 자료를 검사한다."""
        validate_display_mesh(self.mesh, snapshot=self.snapshot, run_id="fixed-run", body_map=self.body_map)

    def test_thin_geometry_mapping_and_source_are_preserved(self):
        """! @brief 유효 자료의 얇은 두께와 원본 데이터를 변경하지 않는다."""
        original = deepcopy(self.mesh)
        self.validate()
        self.assertEqual(self.mesh, original)

    def test_input_binding_purpose_and_tolerances_are_required(self):
        """! @brief 다른 snapshot/run/단위와 숨긴 표시 근사 설정을 거부한다."""
        for key, value in (("snapshot", {}), ("run_id", "other"), ("unit", "m"), ("purpose", "solver"),
                           ("linear_deflection_mm", 0.1), ("angular_deflection_rad", 0.3), ("schema", "wrong")):
            with self.subTest(key=key):
                self.mesh = fixture()
                self.mesh[key] = value
                with self.assertRaises(ProjectError):
                    self.validate()

    def test_body_identity_mapping_is_not_order_based(self):
        """! @brief UUID/층/원본 대응이 달라지면 같은 삼각형도 정상 결과로 받지 않는다."""
        for key, value in (("id", "wrong"), ("layer_id", "wrong"), ("source_entity_ids", []), ("role", "conductor")):
            with self.subTest(key=key):
                self.mesh = fixture()
                self.mesh["bodies"][0][key] = value
                with self.assertRaises(ProjectError):
                    self.validate()

    def test_nonfinite_outside_or_malformed_vertices_are_rejected(self):
        """! @brief NaN/무한대/범위 밖 숫자와 좌표 형식 오류를 거부한다."""
        for value in (float("nan"), float("inf"), -float("inf"), 1000002, 10 ** 1000, True, "1"):
            with self.subTest(value=str(value)[:20]):
                self.mesh = fixture()
                self.mesh["bodies"][0]["vertices"][0][0] = value
                with self.assertRaises(ProjectError):
                    self.validate()

    def test_bad_or_degenerate_triangle_indices_are_rejected(self):
        """! @brief 음수/소수/불리언/범위 밖 색인과 면적 없는 면을 차단한다."""
        for triangle in ([-1, 1, 2], [0, 1, 4], [0.0, 1, 2], [False, 1, 2], [0, 0, 1], [0, 1], [0, 1, 2, 3]):
            with self.subTest(triangle=triangle):
                self.mesh = fixture()
                self.mesh["bodies"][0]["triangles"][0] = triangle
                with self.assertRaises(ProjectError):
                    self.validate()
        self.mesh = fixture()
        self.mesh["bodies"][0]["vertices"][2] = [2, 0, 0]
        with self.assertRaises(ProjectError):
            self.validate()

    def test_counts_are_bounded_before_per_item_processing(self):
        """! @brief 정점과 삼각형 과다 자료는 렌더링 전에 명시적 자원 오류가 된다."""
        for key, count in (("vertices", MAX_VERTICES), ("triangles", MAX_TRIANGLES)):
            with self.subTest(key=key):
                self.mesh = fixture()
                self.mesh["bodies"][0][key] = [self.mesh["bodies"][0][key][0]] * (count + 1)
                with self.assertRaises(ProjectError) as caught:
                    self.validate()
                self.assertEqual(caught.exception.code, "E_RESOURCE")

    def test_empty_or_duplicate_body_map_is_rejected(self):
        """! @brief 빈 장면과 중복 body가 성공 화면으로 표시되지 않도록 한다."""
        self.mesh["bodies"] = []
        with self.assertRaises(ProjectError):
            self.validate()
        self.mesh = fixture()
        self.mesh["bodies"].append(deepcopy(self.mesh["bodies"][0]))
        self.body_map.append(deepcopy(self.body_map[0]))
        with self.assertRaises(ProjectError):
            self.validate()


if __name__ == "__main__":
    unittest.main()
