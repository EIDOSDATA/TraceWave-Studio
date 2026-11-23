"""! @brief 원본 STEP 평면과 원통축 메이트의 실제 고체, 왕복 좌표와 오류를 검증한다."""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rfad.adapters.cad.native import build_package
from rfad.application.physical_setup_service import _instance_offsets, _placement_text
from rfad.domain.errors import ProjectError
from rfad.domain.physical_setup import KEY
from test_cad_native import fixture, identity


def build_mated_examples(root):
    """! @brief 같은 원통 정의의 두 경로를 회전 배치하고 평면 맞춤과 동축 맞춤 예제를 만든다."""
    import cadquery as cq
    from rfad.adapters.cad.physical import inspect_step

    part = cq.Solid.makeCylinder(1, 2)
    child = cq.Assembly(name="nested").add(part, name="reference").add(
        part, name="follower", loc=cq.Location((6, 3, 7), (0, 1, 0), 90))
    source_path = root / "cylinders.step"
    cq.Assembly(name="fixture").add(child, name="nested").export(str(source_path), "STEP")
    raw = source_path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    source = {"name": source_path.name, "sha256": hashlib.sha256(raw).hexdigest(),
              "chunks": [encoded[start:start + 4096] for start in range(0, len(encoded), 4096)]}
    preview = inspect_step(source)
    fixed, moving = [row["faces"] for row in preview["mate_faces"]]
    reference_plane = next(row["index"] for row in fixed if row["kind"] == "plane" and row["direction"][2] > .99)
    moving_plane = next(row["index"] for row in moving if row["kind"] == "plane" and row["direction"][0] < -.99)
    reference_axis = next(row["index"] for row in fixed if row["kind"] == "axis")
    moving_axis = next(row["index"] for row in moving if row["kind"] == "axis")
    projection = fixture()
    part_id = identity("mated-cylinders")
    row = {"id": part_id, "kind": "step", "yaw_deg": 90, "translation_mm": [10, 20, 10], "material_id": None}
    projection["environment_parts"] = [row]
    projection["source_semantics"]["extensions"] = {KEY: {"parts": [{"id": part_id, "step": source}]}}
    examples = {}
    for kind, first, second, sense in (("plane", moving_plane, reference_plane, "opposed"),
                                        ("axis", moving_axis, reference_axis, "same")):
        text = f"1.1.2 {kind} {first} = 1.1.1 {second} {sense}"
        offsets = _instance_offsets(text + "\n1.1.1 2 1 1")
        row["instance_offsets"] = offsets
        result = build_package(projection, root / kind)
        examples[kind] = (text, offsets, result)
    return part_id, source, examples


@unittest.skipUnless(importlib.util.find_spec("cadquery"), "격리 CAD 환경이 필요합니다.")
class StepFaceMateTests(unittest.TestCase):
    """! @brief 원본 공유 정의와 메이트 상대 방향 및 남는 자유도를 검증한다."""

    def test_exported_planes_axes_and_free_displacement(self):
        """! @brief 직교한 원통의 평면과 축을 각각 맞춘 뒤 AP242의 실제 말단을 다시 측정한다."""
        from rfad.adapters.cad.step_io import _read_step_shapes
        from rfad.adapters.cad.physical import external_metrics

        with TemporaryDirectory() as directory:
            root = Path(directory)
            part_id, source, examples = build_mated_examples(root)
            fixed_bounds = (8, 21, 11, 10, 23, 13)
            bounds = {"plane": (6, 25, 13, 8, 27, 15), "axis": (8, 21, 17, 10, 23, 19)}
            for kind, (text, offsets, result) in examples.items():
                self.assertEqual(_placement_text(offsets[1]), text)
                self.assertEqual(result["validation"]["environment_assembly_hierarchy"][0]["shared_leaf_definitions"], 1)
                assemblies = {}
                _read_step_shapes(root / kind / "model.step", assemblies)
                _, leaves = assemblies["environment_" + part_id]
                for path, expected in (((1, 1, 1), fixed_bounds), ((1, 1, 2), bounds[kind])):
                    for value, limit in zip(external_metrics(leaves[path])["bbox_mm"], expected):
                        self.assertAlmostEqual(value, limit, places=7)
                sidecar = json.loads((root / kind / "sidecar.json").read_bytes())
                record = next(row for row in sidecar["body_map"] if row["id"] == part_id)["source_step"]
                self.assertEqual(record["sha256"], source["sha256"])
                self.assertEqual(record["instance_offsets"], offsets)

    def test_cyclic_or_ambiguous_face_rejected(self):
        """! @brief 자기 참조, 순환, 원본 면 번호 범위 및 방향 오류를 거부한다."""
        for text in ("1.2 axis 1 = 1.2 1 same", "1.2 plane 1 = 1.1 2 same\n1.1 plane 2 = 1.2 1 opposed",
                     "1.2 axis 0 = 1.1 1 same", "1.2 plane 1 = 1.1 2 auto"):
            with self.assertRaises(ProjectError):
                _instance_offsets(text)
