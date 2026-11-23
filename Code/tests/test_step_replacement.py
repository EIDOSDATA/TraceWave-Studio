"""! @brief 독립 STEP 부품으로 조립 말단을 교체하고 동축 참조와 실제 출력을 검증한다."""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rfad.adapters.cad.native import build_package
from rfad.adapters.cad.physical import inspect_step
from rfad.application.physical_setup_service import _replacements
from rfad.domain.errors import ProjectError
from rfad.domain.physical_setup import KEY
from test_cad_native import fixture, identity
from test_step_face_mates import build_mated_examples


def source_file(path):
    """! @brief 미리보기와 같은 형식으로 STEP 원문 바이트와 SHA를 구성한다."""
    raw = path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return {"name": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "chunks": [encoded[start:start + 4096] for start in range(0, len(encoded), 4096)]}


def replace_example(root):
    """! @brief 원통 두 개 중 하나를 더 작고 긴 단일 고체로 바꾸고 원통축을 새 면에 연결한다."""
    import cadquery as cq

    part_id, source, examples = build_mated_examples(root)
    donor_id = identity("cylinder-replacement")
    path = root / "replacement.step"
    cq.exporters.export(cq.Solid.makeCylinder(.7, 3), str(path))
    donor = source_file(path)
    faces = inspect_step(donor)["mate_faces"][0]["faces"]
    new_face = next(face["index"] for face in faces if face["kind"] == "axis")
    offsets = examples["axis"][1]
    original = offsets[1]["mate"]["face"]
    controls = {"parts": [{"kind": "step", "id": donor_id, "step": donor}]}
    replacements = _replacements(f"1.1.2 {donor_id} {original}={new_face}", controls)
    projection = fixture()
    projection["environment_parts"] = [{"id": part_id, "kind": "step", "yaw_deg": 90,
        "translation_mm": [10, 20, 10], "material_id": None, "instance_offsets": offsets, "instance_replacements": replacements}]
    projection["source_semantics"]["extensions"] = {KEY: {"parts": [{"id": part_id, "step": source},
                                                                   {"id": donor_id, "step": donor}]}}
    result = build_package(projection, root / "replaced")
    return projection, result, donor, source


@unittest.skipUnless(importlib.util.find_spec("cadquery"), "격리 CAD 환경이 필요합니다.")
class StepReplacementTests(unittest.TestCase):
    """! @brief 교체한 말단만 새 형상과 재대응한 면을 사용하고 공유 형상은 보존하는지 확인한다."""

    def test_native_instance_replacement_remaps_axis_and_preserves_source(self):
        """! @brief 하나의 공유 원통을 교체한 실제 AP242 수신문에서 부피 및 정렬을 검사한다."""
        from rfad.adapters.cad.step_io import _read_step_shapes
        import math

        with TemporaryDirectory() as directory:
            root = Path(directory)
            projection, result, donor, source = replace_example(root)
            row = projection["environment_parts"][0]
            nodes = {}
            _read_step_shapes(root / "replaced/model.step", nodes)
            _, leaves = nodes["environment_" + row["id"]]
            self.assertAlmostEqual(leaves[(1, 1, 1)].Volume(), math.pi * 2)
            changed = leaves[(1, 1, 2)]
            self.assertAlmostEqual(changed.Volume(), math.pi * .7**2 * 3)
            self.assertEqual(result["validation"]["environment_assembly_hierarchy"][0]["shared_leaf_definitions"], 2)
            bounds = changed.BoundingBox()
            for coordinate, expected in zip((bounds.xmin, bounds.ymin, bounds.zmin, bounds.xmax, bounds.ymax, bounds.zmax),
                                            (8.3, 21.3, 17, 9.7, 22.7, 20)):
                self.assertAlmostEqual(coordinate, expected, places=7)
            sidecar = json.loads((root / "replaced/sidecar.json").read_bytes())
            evidence = next(body["source_step"] for body in sidecar["body_map"] if body["id"] == row["id"])
            self.assertEqual(evidence["sha256"], source["sha256"])
            self.assertEqual(evidence["instance_replacements"][0]["source_sha256"], donor["sha256"])
            row["instance_replacements"][0]["faces"].clear()
            with self.assertRaisesRegex(ProjectError, "메이트 면"):
                build_package(projection, root / "missing")


    def test_replacement_in_editor_reopen_and_reference_guard(self):
        """! @brief 후보 미리보기로 두 STEP을 채택한 뒤 교체, 재열기와 원본 참조 차단을 확인한다."""
        import sys
        from rfad.application.cad_runtime import CadRuntime
        from rfad.application.projects import ProjectService
        from rfad.domain.physical_setup import setup
        from test_physical_setup import fixture as project_fixture, load, parameters, METHOD
        from test_cad_worker_process import register_fixture, request, status

        with TemporaryDirectory() as directory:
            root = Path(directory)
            projection, _, donor, source = replace_example(root)
            workspace = root / "workspace"
            runtime = CadRuntime(Path(sys.executable))
            with ProjectService(workspace, cad_runtime=runtime, auto_run=False) as service:
                current, _ = register_fixture(service, project_fixture())
                parent = setup(current)["parts"][0]["id"]
                def adopt(src, changes, part=None):
                    """! @brief 고체를 읽은 개정에서 동일 원본 토큰으로 외부 물체를 적용한다."""
                    preview = service.physical_setup.read("physical.step.preview", {
                        "contract_version": "rfad.api/2.0", "context": {"project_id": current["project_id"]},
                        "input": {"expected_revision": current["revision_id"], "name": src["name"], "chunks": src["chunks"]}})
                    return service.mutate(METHOD, parameters(service, current, "part", changes, identity=part,
                                                             step_token=preview["preview_token"]))
                adopt(source, {"kind": "step", "x": "10", "y": "20", "z": "10", "yaw": "90"}, parent)
                current = load(service, current)
                donor_id = adopt(donor, {"name": "교체용 단일 고체", "kind": "step",
                                        "scenario_id": setup(current)["parts"][0]["scenario_id"]})["record_id"]
                current = load(service, current)
                row = projection["environment_parts"][0]
                original, new = row["instance_replacements"][0]["faces"][0]
                axis = row["instance_offsets"][1]["mate"]
                changes = {"instance_offsets": f"1.1.2 axis {original} = 1.1.1 {axis['target_face']} same",
                           "instance_replacements": f"1.1.2 {donor_id}"}
                with self.assertRaisesRegex(ProjectError, "메이트가 참조"):
                    service.mutate(METHOD, parameters(service, current, "part", changes, identity=parent))
                changes["instance_replacements"] += f" {original}={new}"
                service.mutate(METHOD, parameters(service, current, "part", changes, identity=parent))
                current = load(service, current)
                with self.assertRaisesRegex(ProjectError, "참조 중인"):
                    service.mutate(METHOD, parameters(service, current, "part", {}, identity=donor_id, operation="remove"))
                self.assertEqual(load(service, current), current)
                task = service.mutate("project.save", request(service, current["project_id"],
                                                              {"expected_revision": current["revision_id"]}))
                self.assertTrue(service.run_next())
                self.assertEqual(status(service, task["job_id"])["state"], "completed")
            with ProjectService(workspace, cad_runtime=runtime, auto_run=False) as reopened:
                self.assertEqual(load(reopened, current), current)
                read = reopened.physical_setup.read("physical.setup.get", {
                    "contract_version": "rfad.api/2.0", "context": {"project_id": current["project_id"]},
                    "input": {"expected_revision": current["revision_id"], "record_id": parent, "section": "part"}})
                fields = {field["key"]: field["value"] for field in read["fields"]}
                for key, val in changes.items():
                    self.assertEqual(fields[key], val)
