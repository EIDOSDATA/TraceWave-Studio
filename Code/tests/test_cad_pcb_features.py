"""! @brief 기계 절삭/도금 슬롯의 실제 재료와 STEP 재입력 경계를 검증한다."""

from copy import deepcopy
import importlib.util
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.adapters.cad.bodies import _make_bodies
from rfad.adapters.cad.native import build_package
from rfad.domain.errors import ProjectError


def identity():
    """! @brief 독립 합성 fixture에 충돌하지 않는 원본 식별자를 만든다."""
    return str(uuid4())


def projection():
    """! @brief 제조 권고가 아닌 20 mm 정방형/1 mm 적층 시험 입력을 만든다."""
    bottom, dielectric, top, material, net = [identity() for _ in range(5)]
    layers = [{"id": bottom, "name": "하부", "role": "conductor", "order": 0, "z_min_mm": 0.0, "thickness_mm": 0.035, "material_id": material},
              {"id": dielectric, "name": "유전체 미정", "role": "dielectric", "order": 1, "z_min_mm": 0.035, "thickness_mm": 0.93, "material_id": None},
              {"id": top, "name": "상부", "role": "conductor", "order": 2, "z_min_mm": 0.965, "thickness_mm": 0.035, "material_id": material}]
    return {"schema": "rfad.cad-input/0.1", "profile": "rfad.step.mechanical/0.1", "unit": "mm", "angle_unit": "deg",
            "tolerance_mm": 1e-6, "board": {"id": identity(), "width_mm": 20.0, "height_mm": 20.0},
            "layers": layers, "shapes": [], "mechanical": {"holes": [], "cutouts": []},
            "project_id": identity(), "revision_id": identity(), "snapshot": {}, "transform": {},
            "source_semantics": {"manufacturing": None, "measurement": None, "note": "합성 native 계약 시험"},
            "test_net": net}


def hole(kind="circle", *, plated=False, center=(10, 10)):
    """! @brief 완성 치수만 명시하고 실제 공구는 미정으로 둔다."""
    shape = {"kind": kind, "center_mm": list(center)}
    if kind == "circle":
        shape["diameter_mm"] = 2.0
    else:
        shape.update(finished_length_mm=4.0, finished_width_mm=1.0, rotation_deg=25.0)
    return {"id": identity(), "shape": shape,
            "plating": {"state": "plated" if plated else "unplated", "thickness_mm": 0.025 if plated else None,
                        "material_ref": None, "net_id": None, "pad_ids": []},
            "tool_diameter_mm": None, "surface_cut_ids": []}


def add_pads(data, item):
    """! @brief 도금 슬롯 양단에 같은 net의 실제 여유 있는 패드를 추가한다."""
    for layer in (data["layers"][0], data["layers"][-1]):
        pad = {"id": identity(), "kind": "pad", "layer_id": layer["id"], "net_id": data["test_net"],
               "material_ref": None, "pad_shape": "rectangle", "center_mm": list(item["shape"]["center_mm"]),
               "size_mm": [6.0, 3.0], "rotation_deg": item["shape"].get("rotation_deg", 0.0)}
        data["shapes"].append(pad)
        item["plating"]["pad_ids"].append(pad["id"])
    item["plating"]["net_id"] = data["test_net"]


@unittest.skipUnless(importlib.util.find_spec("cadquery"), "고정 CAD Python 환경에서 실행해야 합니다.")
class MechanicalNativeTests(unittest.TestCase):
    """! @brief 동일 커널 검수와 독립 단면 산술을 실제 제조 수용과 구분한다."""

    def setUp(self):
        """! @brief native 의존성은 명시한 시험 환경에서만 읽는다."""
        import cadquery as cq
        self.cq = cq

    def test_npth_really_splits_conductor_and_preserves_unknown_tool(self):
        """! @brief 도체 중심선이 아니라 절삭 뒤 두 연결 성분과 실제 부피를 확인한다."""
        data = projection()
        item = hole(center=(10, 10))
        data["mechanical"]["holes"].append(item)
        data["shapes"].append({"id": identity(), "kind": "planar_region", "layer_id": data["layers"][-1]["id"],
                               "net_id": data["test_net"], "material_ref": None,
                               "outer_mm": [[2, 9.5], [18, 9.5], [18, 10.5], [2, 10.5]], "holes_mm": []})
        before = deepcopy(data)
        bodies = _make_bodies(self.cq, data)
        dielectric = next(body for body in bodies if body["role"] == "dielectric")
        conductor = next(body for body in bodies if body["role"] == "conductor")
        self.assertAlmostEqual(dielectric["metrics"]["volume_mm3"], (400 - math.pi) * 0.93, places=8)
        self.assertEqual(conductor["metrics"]["solid_count"], 2)
        self.assertIn(item["id"], conductor["drill_source_ids"])
        self.assertEqual(data, before)
        self.assertIsNone(item["tool_diameter_mm"])

    def test_project_source_projection_and_actual_step_preserve_unknowns(self):
        """! @brief 실제 0.6 원본에서 봉인 입력과 STEP까지 연결하고 미정값을 대조한다."""
        import json
        from rfad.application.cad import build_cad_input
        from rfad.application.exchange_contract import build_input, PROFILE
        from rfad.domain.pcb_features import empty_pcb
        from rfad.domain.project import validate_project
        from test_cad_projection import cad_fixture, snapshot_for
        from test_pcb_features import hole_record
        document = cad_fixture()
        document["schema_version"] = "rfad.project/0.6"
        item = hole_record(document, x=5, y=1, diameter=1)
        document["pcb"] = {**empty_pcb(), "holes": [item]}
        validate_project(document)
        original = deepcopy(document)
        snapshot = snapshot_for(document)
        projected = build_cad_input(document, snapshot)
        with TemporaryDirectory(prefix="TraceWave 원본 기계 출력 ") as directory:
            package = build_package(projected, Path(directory))
            self.assertEqual(package["validation"]["status"], "passed_same_kernel")
            sidecar = json.loads((Path(directory) / "sidecar.json").read_bytes())
            self.assertEqual(sidecar["source_semantics"], original)
            self.assertEqual(sidecar["snapshot"], snapshot)
        drawing = build_input(document, snapshot, {"profile": PROFILE, "format": "svg", "options": {
            "mode": "drawing", "sheet": "A4", "orientation": "landscape", "scale": 1,
            "views": [{"kind": "outline"}], "dimensions": True, "notes": True}}, identity())
        dimensions = next(row["items"] for row in drawing["dimensions"] if row["entity_id"] == item["id"])
        tool = next(row for row in dimensions if row["key"] == "mechanical.tool_diameter")
        self.assertIsNone(tool["value"])
        self.assertEqual(tool["source_refs"], item["tool_diameter"]["source_refs"])
        self.assertEqual(document, original)

    def test_plated_capsule_volume_connections_and_step_readback(self):
        """! @brief 회전 슬롯의 전체 길이/폭과 shell 부피를 독립 산술 및 실제 STEP로 확인한다."""
        import json
        data = projection()
        item = hole("capsule", plated=True)
        data["mechanical"]["holes"].append(item)
        add_pads(data, item)
        bodies = _make_bodies(self.cq, data)
        barrel = next(body for body in bodies if body.get("feature_kind") == "plated_hole_barrel")
        expected = 3 * 1.05 + math.pi * (1.05 / 2) ** 2 - (3 + math.pi * 0.5 ** 2)
        self.assertAlmostEqual(barrel["metrics"]["volume_mm3"], expected, places=9)
        self.assertEqual(barrel["metrics"]["through_hole_count"], 1)
        self.assertIsNone(barrel["tool_hole_diameter_mm"])
        before = deepcopy(data)
        with TemporaryDirectory(prefix="TraceWave 기계 슬롯 STEP ") as directory:
            result = build_package(data, Path(directory))
            self.assertEqual(result["validation"]["status"], "passed_same_kernel")
            sidecar = json.loads((Path(directory) / "sidecar.json").read_bytes())
            restored = next(body for body in sidecar["body_map"] if body["id"] == item["id"])
            self.assertEqual(restored["finished_shape"], item["shape"])
            self.assertIsNone(restored["tool_hole_diameter_mm"])
            self.assertFalse(sidecar["manufacturing_verified"])
            self.assertEqual(sidecar["source_semantics"], data["source_semantics"])
        self.assertEqual(data, before)

    def test_cutout_and_explicit_surface_cut_have_distinct_coverage(self):
        """! @brief 기본 적층 절삭이 피복을 암묵적으로 뚫지 않고 명시 선택만 소비한다."""
        data = projection()
        cutout = {"id": identity(), "shape": {"kind": "polygon", "outer_mm": [[2, 2], [4, 2], [4, 4], [2, 4]], "holes_mm": []}, "surface_cut_ids": []}
        item = hole(center=(10, 10))
        surface = {"id": identity(), "kind": "coating", "material_id": None, "z_min_mm": 1.0,
                   "thickness_mm": 0.02, "rectangle_mm": None, "openings_mm": []}
        data["mechanical"] = {"cutouts": [cutout], "holes": [item]}
        data["surface_layers"] = [surface]
        bodies = _make_bodies(self.cq, data)
        covered = next(body for body in bodies if body["role"] == "surface")
        self.assertAlmostEqual(covered["metrics"]["volume_mm3"], 8.0, places=9)
        self.assertEqual(covered["metrics"]["through_hole_count"], 0)
        item["surface_cut_ids"] = [surface["id"]]
        bodies = _make_bodies(self.cq, data)
        opened = next(body for body in bodies if body["role"] == "surface")
        self.assertAlmostEqual(opened["metrics"]["volume_mm3"], (400 - math.pi) * 0.02, places=9)
        self.assertEqual(opened["metrics"]["through_hole_count"], 1)
        self.assertEqual(opened["mechanical_cut_source_ids"], [item["id"]])
        dielectric = next(body for body in bodies if body["role"] == "dielectric")
        self.assertAlmostEqual(dielectric["metrics"]["volume_mm3"], (400 - 4 - math.pi) * 0.93, places=8)

    def test_polygon_outline_is_real_and_not_a_bounding_box(self):
        """! @brief 오목한 외곽의 빈 사분면에 도체를 숨겨 넣을 수 없다."""
        data = projection()
        data["board"] = {"id": data["board"]["id"], "kind": "polygon",
                         "outer_mm": [[0, 0], [20, 0], [20, 10], [10, 10], [10, 20], [0, 20]]}
        body = _make_bodies(self.cq, data)[0]
        self.assertAlmostEqual(body["metrics"]["volume_mm3"], 300 * 0.93, places=8)
        item = hole(center=(15, 15))
        data["mechanical"]["holes"].append(item)
        with self.assertRaises(ProjectError):
            _make_bodies(self.cq, data)
        data["mechanical"]["holes"] = []
        data["shapes"] = [{"id": identity(), "kind": "pad", "layer_id": data["layers"][-1]["id"], "net_id": None,
                           "material_ref": None, "pad_shape": "circle", "center_mm": [15, 15], "size_mm": [2, 2], "rotation_deg": 0.0}]
        with self.assertRaises(ProjectError):
            _make_bodies(self.cq, data)

    def test_unknown_plating_overlap_and_boundary_contact_are_blocked(self):
        """! @brief 미정 도금과 겹친 제거를 추정하거나 자동 치유하지 않는다."""
        for variant in ("unknown", "duplicate", "boundary"):
            with self.subTest(variant=variant):
                data = projection()
                item = hole(center=(1, 10) if variant == "boundary" else (10, 10))
                data["mechanical"]["holes"] = [item]
                if variant == "unknown":
                    item["plating"]["state"] = "unknown"
                elif variant == "duplicate":
                    data["mechanical"]["holes"].append({**deepcopy(item), "id": identity()})
                with self.assertRaises(ProjectError):
                    _make_bodies(self.cq, data)

    def test_plated_slot_requires_pad_ring_net_and_consistent_known_tool(self):
        """! @brief 공구 모순, net 단락 및 실제 양단 패드 여유 부족을 차단한다."""
        for variant in ("tool", "net", "ring"):
            with self.subTest(variant=variant):
                data = projection()
                item = hole("capsule", plated=True)
                data["mechanical"]["holes"] = [item]
                add_pads(data, item)
                if variant == "tool":
                    item["tool_diameter_mm"] = 1.2
                elif variant == "net":
                    data["shapes"][0]["net_id"] = identity()
                else:
                    data["shapes"][0]["size_mm"] = [4.0, 1.0]
                with self.assertRaises(ProjectError):
                    _make_bodies(self.cq, data)


if __name__ == "__main__":
    unittest.main()
