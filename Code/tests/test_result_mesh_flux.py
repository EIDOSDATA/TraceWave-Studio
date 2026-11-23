"""! @brief 비평면 유향 곡면의 면적, 부호, 기하 검증과 실제 필드 대조를 확인한다."""

from copy import deepcopy
import math
import os
from pathlib import Path
import unittest

from rfad.application.result_field_flux import integrate_surface
from rfad.domain.errors import ProjectError


def surface(vertices, triangles):
    """! @brief 입력 좌표는 기판의 mm 좌표계를 그대로 사용한다."""
    return {"kind": "mesh", "vertices_mm": vertices, "triangles": triangles}


class MeshFluxTests(unittest.TestCase):
    def test_tilted_open_face_against_projected_area(self):
        """! @brief 일정한 방향의 전력과 기울인 삼각면의 투영 면적을 대조한다."""
        import numpy as np

        axes = dict.fromkeys("xyz", [-2., -.6, 0., .8, 2.])
        zero, unit = (np.ones((5, 5, 5), dtype=complex) * v for v in (0, 1))
        e = [(axes, unit), (axes, zero), (axes, zero)]
        h = [(axes, zero), (axes, unit), (axes, zero)]
        patch = surface([[-1., -1., -1.], [1., -1., 1.], [-1., 1., .7]], [[0, 1, 2]])
        for sign in (1, -1):
            result = integrate_surface(e, h, patch)
            self.assertAlmostEqual(result["total_flux_w_s2"], sign * 1e-6, delta=1e-19)
            self.assertFalse(result["surface"]["indexed_edges_closed"])
            self.assertGreater(result["surface"]["quadrature_points"], 16)
            patch["triangles"][0].reverse()
        for invalid in ({"vertices_mm": [[-3., 0, 0], [0, 1, 0], [0, 0, 0]]},
                        {"triangles": [[0, 1, 2], [2, 1, 0]]}, {"triangles": [[0, 0, 2]]}):
            with self.subTest(invalid=invalid), self.assertRaises(ProjectError):
                integrate_surface(e, h, {**patch, **invalid})

    def test_curved_octahedron_against_divergence_and_orientation(self):
        """! @brief 닫힌 비평면 표면에서 발산 정리와 반대 법선의 통과량을 검사한다."""
        import numpy as np

        fields = []
        for j in range(6):
            axis = [-2., -.8+j*.05, .21+j*.02, 1.2, 2.]
            coords = dict.fromkeys("xyz", axis)
            x, y, _ = np.meshgrid(*coords.values(), indexing="ij")
            grid = (0*x, 0*x, 1+0*x, y, -x, 0*x)[j]
            fields.append((coords, grid.astype(complex)))
        vertices = [[1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0], [0, 0, 1.3], [0, 0, -.7]]
        triangles = [[i, (i+1)%4, 4] for i in range(4)] + [[(i+1)%4, i, 5] for i in range(4)]
        closed = surface(vertices, triangles)
        old = deepcopy(closed)
        result = integrate_surface(fields[:3], fields[3:], closed)
        self.assertEqual(old, closed)
        self.assertTrue(result["surface"]["indexed_edges_closed"])
        self.assertAlmostEqual(result["total_flux_w_s2"], 4 / 3 * 1e-6, delta=1e-19)
        expected_area = 2 * (math.sqrt(1+2*1.3**2)+math.sqrt(1+2*.7**2))
        self.assertAlmostEqual(result["surface"]["area_m2"], expected_area * 1e-6, delta=1e-19)
        flipped = [list(reversed(row)) for row in triangles]
        self.assertAlmostEqual(integrate_surface(fields[:3], fields[3:], surface(vertices, flipped))["total_flux_w_s2"],
                               -result["total_flux_w_s2"], delta=1e-19)

    @unittest.skipUnless(os.environ.get("RFAD_FLUX_WORKSPACE") and os.environ.get("RFAD_FLUX_ARTIFACT"),
                         "실제 E/H 봉인 결과 작업공간이 필요합니다.")
    def test_sealed_plane_as_mesh_and_read_only(self):
        """! @brief 실제 복소 E/H 결과의 사각면과 두 삼각형 및 보존 해시를 대조한다."""
        from rfad.application.projects import ProjectService
        from rfad.application.result_service import read
        from rfad.application.canonical import canonical_hash

        picked = os.environ["RFAD_FLUX_ARTIFACT"]
        with ProjectService(Path(os.environ["RFAD_FLUX_WORKSPACE"]), auto_run=False) as service:
            original = service.journal.read()
            context = {"project_id": original["solver_results"][picked]["project_id"]}
            source = {"kind": "solver", "artifact_id": picked}

            def call(method, **params):
                """! @brief 원래 공개 요청을 검증한 현재 개정에서 실행한다."""
                return read(service, method, {"contract_version": "rfad.api/2.0", "context": context,
                                               "input": {"source": source, **params}})
            pin = call("result.describe")["pin"]
            bounds = [[6.5, 8.5], [4.9, 6.9], [2, 2]]
            original_flux = call("result.field.flux", pin=pin, frequency_index=0,
                                 surface={"kind": "rectangle", "axis": "z", "direction": 1, "bounds_mm": bounds})
            mesh = surface([[6.5, 4.9, 2], [8.5, 4.9, 2], [8.5, 6.9, 2], [6.5, 6.9, 2]], [[0, 1, 2], [0, 2, 3]])
            curved = call("result.field.flux", pin=pin, frequency_index=0, surface=mesh)
            value = original_flux["total_flux_w_s2"]
            self.assertAlmostEqual(curved["total_flux_w_s2"], value, delta=abs(value)*1e-12)
            self.assertEqual(curved["surface"]["sha256"], canonical_hash(mesh))
            self.assertEqual(curved["electric_ref"], original_flux["electric_ref"])
            self.assertEqual(curved["magnetic_ref"], original_flux["magnetic_ref"])
            self.assertEqual(service.journal.read(), original)
            print("native_z_face", value, "mesh", curved["total_flux_w_s2"], "mesh_sha256", curved["surface"]["sha256"])
