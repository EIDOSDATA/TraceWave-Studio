"""! @brief 고정 CAD 환경에서 실제 OCCT 고체와 AP242 교환을 검증한다."""

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import NAMESPACE_URL, uuid5

from rfad.adapters.cad.native import build_package, read_step
from rfad.application.display_mesh import validate_display_mesh
from rfad.domain.errors import ProjectError


def identity(name):
    """! @brief 시험 이름에 대응하는 재현 가능한 UUID를 만든다."""
    return str(uuid5(NAMESPACE_URL, "rfad/native-test/" + name))


def fixture():
    """! @brief RF 물성은 미정으로 두고 기하만 명시한 교환 fixture를 만든다."""
    return {
        "schema": "rfad.cad-input/0.1", "profile": "rfad.step.mechanical/0.1",
        "project_id": identity("project"), "revision_id": identity("revision"),
        "run_id": identity("run"), "source_hash": "f" * 64,
        "snapshot": {"snapshot_id": identity("snapshot"), "revision_id": identity("revision"), "content_hash": "f" * 64},
        "unit": "mm", "angle_unit": "deg", "tolerance_mm": 1e-6,
        "transform": {"source_length_unit": "m", "kernel_length_unit": "mm", "scale_to_kernel": 1000.0,
                      "inverse_scale": 0.001, "translation_mm": [0.0, 0.0, 0.0]},
        "board": {"id": identity("board"), "width_mm": 40.0, "height_mm": 60.0},
        "layers": [
            {"id": identity("dielectric"), "name": "미정 재료 기판", "role": "dielectric", "order": 0,
             "z_min_mm": 0.0, "thickness_mm": 1.0, "material_id": None},
            {"id": identity("copper"), "name": "Top Copper", "role": "conductor", "order": 1,
             "z_min_mm": 1.0, "thickness_mm": 0.035, "material_id": None},
        ],
        "shapes": [
            {"id": identity("line"), "kind": "line_path", "role": "conductor", "layer_id": identity("copper"),
             "net_id": identity("net-line"), "material_ref": None, "width_mm": 0.8,
             "start_mm": [5.0, 52.0], "end_mm": [33.0, 52.0]},
            {"id": identity("arc"), "kind": "arc_path", "role": "conductor", "layer_id": identity("copper"),
             "net_id": identity("net-arc"), "material_ref": None, "width_mm": 0.8,
             "center_mm": [20.0, 25.0], "radius_mm": 10.0, "start_angle_deg": 20.0, "sweep_angle_deg": 260.0},
        ],
        "source_semantics": {"materials": [{"epsilon_r": {"value_si": None, "status": "missing"}}], "ports": []},
        "omissions": [],
    }


@unittest.skipUnless(importlib.util.find_spec("cadquery") is not None, "격리 CAD Python 환경이 필요합니다.")
class CadNativeTests(unittest.TestCase):
    """! @brief 실제 writer/reader와 독립 산술 기대값을 비교한다."""

    def test_ap242_named_bodies_units_hashes_and_analytic_volumes(self):
        """! @brief 별도 reader의 UUID 이름, mm, 고체와 analytic 체적을 확인한다."""
        source = fixture()
        original = deepcopy(source)
        with TemporaryDirectory(prefix="TraceWave CAD 한글 ") as directory:
            root = Path(directory)
            result = build_package(source, root)
            imported = read_step(root / "model.step")
            sidecar = json.loads((root / "sidecar.json").read_text(encoding="utf-8"))
            mesh = json.loads((root / "mesh.json").read_bytes())
            validate_display_mesh(mesh, snapshot=source["snapshot"], run_id=source["run_id"], body_map=sidecar["body_map"])
            self.assertIn("display_mesh", {item["role"] for item in result["files"]})
            self.assertIn("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING", result["step_schema"])
            self.assertEqual(result["status"], "generated_unverified")
            self.assertFalse(result["validation"]["kernel_independent"])
            self.assertEqual(result["solid_count"], 3)
            self.assertEqual(sidecar["source_semantics"], source["source_semantics"])
            self.assertEqual(sidecar["run_id"], source["run_id"])
            self.assertEqual(sidecar["snapshot"], source["snapshot"])
            for item in result["files"]:
                data = (root / item["path"]).read_bytes()
                self.assertEqual(len(data), item["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
            line = imported["conductor_" + identity("line")]
            arc = imported["conductor_" + identity("arc")]
            substrate = imported["dielectric_" + identity("dielectric")]
            self.assertAlmostEqual(line["volume_mm3"], (28 * 0.8 + math.pi * 0.4 ** 2) * 0.035, places=9)
            self.assertAlmostEqual(arc["volume_mm3"], (10 * 0.8 * math.radians(260) + math.pi * 0.4 ** 2) * 0.035, places=9)
            self.assertAlmostEqual(substrate["volume_mm3"], 40 * 60 * 1.0, places=6)
            for actual, expected in zip(line["bbox_mm"], [4.6, 51.6, 1.0, 33.4, 52.4, 1.035]):
                self.assertAlmostEqual(actual, expected, places=6)
            self.assertEqual(source, original)

    def test_signed_quarter_arc_and_full_ring_keep_exact_geometry(self):
        """! @brief 음수 원호와 양방향 완전 원의 방향, 부피와 중심을 확인한다."""
        for sweep in (90.0, -90.0, 360.0, -360.0):
            with self.subTest(sweep=sweep), TemporaryDirectory(prefix="rfad arc ") as directory:
                source = fixture()
                source["shapes"] = [source["shapes"][1]]
                source["shapes"][0].update(start_angle_deg=0.0, sweep_angle_deg=sweep)
                build_package(source, Path(directory))
                arc = read_step(Path(directory) / "model.step")["conductor_" + identity("arc")]
                mesh = json.loads((Path(directory) / "mesh.json").read_bytes())
                displayed = next(body for body in mesh["bodies"] if body["id"] == identity("arc"))
                self.assertEqual(displayed["source_entity_ids"], [identity("arc")])
                cap_area = 0.0 if abs(sweep) == 360.0 else math.pi * 0.4 ** 2
                expected = (10 * 0.8 * abs(math.radians(sweep)) + cap_area) * 0.035
                self.assertAlmostEqual(arc["volume_mm3"], expected, places=8)
                if abs(sweep) == 360.0:
                    self.assertAlmostEqual(arc["center_mm"][0], 20, places=7)
                    self.assertAlmostEqual(arc["center_mm"][1], 25, places=7)
                    self.assertEqual(arc["through_hole_count"], 1)
                    self.assertEqual(arc["section_loop_count"], 2)
                    self.assertTrue(all(math.hypot(point[0] - 20.0, point[1] - 25.0) >= 9.6 - 1e-6
                                        for point in displayed["vertices"]))
                else:
                    self.assertGreater(arc["center_mm"][0], 20)
                    self.assertGreater((arc["center_mm"][1] - 25) * sweep, 0)
                    self.assertEqual(arc["through_hole_count"], 0)

    def test_same_net_union_preserves_all_source_ids(self):
        """! @brief 연결 선의 같은 net union을 중복 체적 없이 stable map에 기록한다."""
        source = fixture()
        line = source["shapes"][0]
        branch = deepcopy(line)
        branch.update(id=identity("branch"), start_mm=[10.0, 52.0], end_mm=[10.0, 45.0])
        source["shapes"] = [line, branch]
        with TemporaryDirectory(prefix="rfad union ") as directory:
            root = Path(directory)
            result = build_package(source, root)
            sidecar = json.loads((root / "sidecar.json").read_text(encoding="utf-8"))
            body = next(item for item in sidecar["body_map"] if item["role"] == "conductor")
            self.assertEqual(body["source_entity_ids"], sorted([line["id"], branch["id"]]))
            self.assertEqual(body["metrics"]["solid_count"], 1)
            self.assertEqual(result["solid_count"], 2)
            unmerged = ((28 + 7) * 0.8 + 2 * math.pi * 0.4 ** 2) * 0.035
            self.assertLess(body["metrics"]["volume_mm3"], unmerged)
            mesh = json.loads((root / "mesh.json").read_bytes())
            displayed = next(item for item in mesh["bodies"] if item["role"] == "conductor")
            self.assertEqual(displayed["source_entity_ids"], body["source_entity_ids"])

    def test_display_mesh_preserves_orientation_thickness_and_body_bounds(self):
        """! @brief 실제 고체의 표시 삼각형이 외향 법선, 얇은 두께와 경계를 유지한다."""
        for thickness in (0.035, 0.00001):
            with self.subTest(thickness=thickness), TemporaryDirectory(prefix="rfad display mesh ") as directory:
                source = fixture()
                source["layers"][1]["thickness_mm"] = thickness
                root = Path(directory)
                build_package(source, root)
                mesh = json.loads((root / "mesh.json").read_bytes())
                sidecar = json.loads((root / "sidecar.json").read_bytes())
                bodies = {body["id"]: body for body in sidecar["body_map"]}
                self.assertLess((root / "mesh.json").stat().st_size, 16 * 1024 * 1024)
                self.assertEqual(mesh["linear_deflection_mm"], 0.05)
                self.assertEqual(mesh["angular_deflection_rad"], 0.15)
                for displayed in mesh["bodies"]:
                    metrics = bodies[displayed["id"]]["metrics"]
                    vertices = displayed["vertices"]
                    bounds = [min(point[axis] for point in vertices) for axis in range(3)]
                    bounds += [max(point[axis] for point in vertices) for axis in range(3)]
                    self.assertTrue(all(abs(a - b) <= 0.05 + 1e-6 for a, b in zip(bounds, metrics["bbox_mm"])))
                    self.assertAlmostEqual(bounds[5] - bounds[2], metrics["thickness_mm"], places=9)
                    origin = vertices[0]
                    volume = 0.0
                    for indices in displayed["triangles"]:
                        a, b, c = [[vertices[index][axis] - origin[axis] for axis in range(3)] for index in indices]
                        volume += (a[0] * (b[1] * c[2] - b[2] * c[1]) + a[1] * (b[2] * c[0] - b[0] * c[2]) +
                                   a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
                    self.assertGreater(volume, 0.0)
                    self.assertLess(abs(volume / metrics["volume_mm3"] - 1.0), 0.005)

    def test_unassigned_or_different_net_overlap_is_not_silently_fused(self):
        """! @brief net이 다르거나 미정인 접촉 도체는 성공 출력으로 게시하지 않는다."""
        for net in (None, identity("other-net")):
            with self.subTest(net=net), TemporaryDirectory(prefix="rfad short ") as directory:
                source = fixture()
                line = source["shapes"][0]
                branch = deepcopy(line)
                branch.update(id=identity("branch"), net_id=net, start_mm=[10.0, 52.0], end_mm=[10.0, 45.0])
                source["shapes"] = [line, branch]
                with self.assertRaises(ProjectError) as caught:
                    build_package(source, Path(directory))
                self.assertEqual(caught.exception.code, "E_CONNECTIVITY")
                self.assertFalse((Path(directory) / "model.step").exists())

    def test_invalid_physical_ranges_are_blocked_before_export(self):
        """! @brief 부피 중첩, 기판 밖 도체, 미소 두께와 불가능한 원호를 차단한다."""
        for case in ("layer_overlap", "outside", "thin", "inner_radius"):
            with self.subTest(case=case), TemporaryDirectory(prefix="rfad invalid ") as directory:
                source = fixture()
                if case == "layer_overlap":
                    source["layers"][1]["z_min_mm"] = 0.9
                elif case == "outside":
                    source["shapes"][0]["start_mm"] = [0.0, 52.0]
                elif case == "thin":
                    source["layers"][1]["thickness_mm"] = 1e-8
                else:
                    source["shapes"][1]["radius_mm"] = 0.3
                with self.assertRaises(ProjectError):
                    build_package(source, Path(directory))
                self.assertFalse((Path(directory) / "model.step").exists())

    def test_existing_output_is_preserved(self):
        """! @brief 이전 출력 파일을 덮어쓰지 않고 충돌을 반환한다."""
        with TemporaryDirectory(prefix="rfad existing ") as directory:
            path = Path(directory) / "model.step"
            path.write_bytes(b"existing")
            with self.assertRaises(ProjectError) as caught:
                build_package(fixture(), Path(directory))
            self.assertEqual(caught.exception.code, "E_CONFLICT")
            self.assertEqual(path.read_bytes(), b"existing")

    def test_nearly_closed_overlapping_caps_are_explicitly_unsupported(self):
        """! @brief 완전 원과 달리 끝단이 자기 중첩하는 근접 원호를 조용히 치유하지 않는다."""
        for sweep in (359.9, -359.9):
            with self.subTest(sweep=sweep), TemporaryDirectory(prefix="rfad cap gap ") as directory:
                source = fixture()
                source["shapes"] = [source["shapes"][1]]
                source["shapes"][0]["sweep_angle_deg"] = sweep
                with self.assertRaises(ProjectError) as caught:
                    build_package(source, Path(directory))
                self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
                self.assertFalse((Path(directory) / "model.step").exists())

    def test_large_coordinate_small_sweep_uses_explicit_circle_radius(self):
        """! @brief 거의 일직선인 세 점으로 반지름을 추정하지 않고 analytic 체적을 보존한다."""
        for radius, width, sweep in ((100000.0, 0.001, 0.001), (1000.0, 0.8, -0.000001)):
            with self.subTest(radius=radius, sweep=sweep), TemporaryDirectory(prefix="rfad CAD precision ") as directory:
                source = fixture()
                source["board"].update(width_mm=1e6, height_mm=1e6)
                source["shapes"] = [source["shapes"][1]]
                source["shapes"][0].update(center_mm=[500000.0, 500000.0], radius_mm=radius,
                                           width_mm=width, start_angle_deg=0.0, sweep_angle_deg=sweep)
                build_package(source, Path(directory))
                arc = read_step(Path(directory) / "model.step")["conductor_" + identity("arc")]
                expected = (radius * width * abs(math.radians(sweep)) + math.pi * (width / 2.0) ** 2) * 0.035
                self.assertTrue(math.isclose(arc["volume_mm3"], expected, rel_tol=1e-7, abs_tol=1e-18))
                self.assertEqual(arc["solid_count"], 1)
                self.assertEqual(arc["through_hole_count"], 0)


if __name__ == "__main__":
    unittest.main()
