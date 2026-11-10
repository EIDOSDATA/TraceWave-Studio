"""! @brief 실제 region/pad와 중공 PTH의 CAD 기하 및 STEP 재입력 의미를 검증한다."""

from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rfad.adapters.cad.native import build_package, read_step
from rfad.application.cad import build_cad_input
from rfad.domain.errors import ProjectError
from rfad.domain.project import new_project, validate_project
from test_cad_native import fixture, identity
from test_cad_projection import snapshot_for
from test_design import quantity, unknown


def pth_fixture():
    """! @brief 실제 제조 규격이 아닌 명시적 두 층과 PTH 교환 검증 형상을 만든다."""
    source = fixture()
    source["layers"][0]["order"] = 1
    source["layers"][1]["order"] = 2
    source["layers"].insert(0, {"id": identity("bottom"), "name": "Bottom", "role": "conductor", "order": 0,
                                "z_min_mm": -0.035, "thickness_mm": 0.035, "material_id": None})
    common = {"role": "ground", "net_id": identity("ground-net"), "material_ref": None}
    bottom = {**common, "id": identity("pad-bottom"), "kind": "pad", "layer_id": identity("bottom"), "pad_shape": "rectangle",
              "center_mm": [20.0, 25.0], "size_mm": [2.0, 2.0], "rotation_deg": 30.0}
    top = {**common, "id": identity("pad-top"), "kind": "pad", "layer_id": identity("copper"), "pad_shape": "circle",
           "center_mm": [20.0, 25.0], "size_mm": [2.0, 2.0], "rotation_deg": 0.0}
    via = {**common, "id": identity("via"), "kind": "via", "layer_id": identity("bottom"), "end_layer_id": identity("copper"),
           "center_mm": [20.0, 25.0], "finished_hole_diameter_mm": 0.3, "plating_thickness_mm": 0.025,
           "tool_hole_diameter_mm": 0.35, "fill": "none", "pad_ids": [bottom["id"], top["id"]]}
    source["shapes"] = [bottom, top, via]
    return source


def copper_document():
    """! @brief native 시험과 같은 명시적 기하를 실제 Quantity 원본으로 구성한다."""
    projection = pth_fixture()
    document = new_project("CAD 도체 객체 검증; 제조 입력 아님")
    frame = document["frames"]["board"]["id"]
    document["board"] = {"id": projection["board"]["id"], "frame_id": frame, "thickness_convention": "finished",
                         "outline": {"kind": "rectangle", "width": quantity(40, "mm"), "height": quantity(60, "mm")}}
    document["nets"] = [{"id": identity("ground-net"), "name": "Explicit test ground"}]
    document["stackup"] = [{key: value for key, value in layer.items() if not key.endswith("_mm")} | {
        "z_min": quantity(layer["z_min_mm"], "mm"), "thickness": quantity(layer["thickness_mm"], "mm")}
        for layer in projection["layers"]]
    for shape in projection["shapes"]:
        item = {key: shape[key] for key in ("id", "kind", "role", "layer_id", "net_id", "material_ref")}
        item.update(frame_id=frame, source_ref="explicit-cad-test", include_in_export=True, include_in_em=True,
                    center=[quantity(value, "mm") for value in shape["center_mm"]])
        if shape["kind"] == "pad":
            item.update(pad_shape=shape["pad_shape"], size=[quantity(value, "mm") for value in shape["size_mm"]],
                        rotation=quantity(shape["rotation_deg"], "deg"))
        else:
            item.update(end_layer_id=shape["end_layer_id"], fill=shape["fill"], pad_ids=shape["pad_ids"])
            for key in ("finished_hole_diameter", "plating_thickness", "tool_hole_diameter"):
                item[key] = quantity(shape[key + "_mm"], "mm")
        document["geometry"].append(item)
    document["geometry"].sort(key=lambda item: item["id"])
    validate_project(document)
    return document


class CopperFeatureProjectionTests(unittest.TestCase):
    """! @brief 신규 도체가 원본 수량/참조/미정 상태를 보존하며 CAD로 투영되는지 검사한다."""

    def test_pad_and_via_units_and_source_are_preserved(self):
        """! @brief 실제 domain 문서에서 mm/deg를 평가하고 원본을 변경하지 않는다."""
        document = copper_document()
        before = deepcopy(document)
        projection = build_cad_input(document, snapshot_for(document))
        via = next(shape for shape in projection["shapes"] if shape["kind"] == "via")
        self.assertAlmostEqual(via["finished_hole_diameter_mm"], 0.3)
        self.assertAlmostEqual(via["plating_thickness_mm"], 0.025)
        self.assertEqual(via["pad_ids"], [identity("pad-bottom"), identity("pad-top")])
        self.assertEqual(document, before)
        self.assertEqual(projection["source_semantics"], before)

    def test_unknown_finished_geometry_blocks_but_tool_unknown_is_preserved(self):
        """! @brief 실제 기하에 필요한 치수 미정은 차단하고 미정 tool은 추정하지 않는다."""
        for field in ("finished_hole_diameter", "plating_thickness", "tool_hole_diameter"):
            document = copper_document()
            via = next(shape for shape in document["geometry"] if shape["kind"] == "via")
            via[field] = unknown("length", "mm")
            validate_project(document)
            if field == "tool_hole_diameter":
                projection = build_cad_input(document, snapshot_for(document))
                self.assertIsNone(next(shape for shape in projection["shapes"] if shape["kind"] == "via")[field + "_mm"])
            else:
                with self.assertRaises(ProjectError) as caught:
                    build_cad_input(document, snapshot_for(document))
                self.assertEqual(caught.exception.code, "E_GEOMETRY")
                self.assertTrue(caught.exception.details["field_path"].endswith(field))

    def test_region_projection_does_not_fill_hole_or_change_winding(self):
        """! @brief area의 outer/hole 좌표와 winding을 원본 그대로 단위 변환한다."""
        document = copper_document()
        pad = next(shape for shape in document["geometry"] if shape["kind"] == "pad")
        region = {key: value for key, value in pad.items() if key not in {"pad_shape", "center", "size", "rotation"}}
        outer, hole = [[1, 1], [1, 10], [10, 10], [10, 1]], [[3, 3], [4, 3], [4, 4], [3, 4]]
        region.update(id=identity("region"), kind="planar_region", outer=[[quantity(v, "mm") for v in p] for p in outer],
                      holes=[[[quantity(v, "mm") for v in p] for p in hole]])
        document["geometry"].append(region)
        document["geometry"].sort(key=lambda item: item["id"])
        projection = build_cad_input(document, snapshot_for(document))
        projected = next(shape for shape in projection["shapes"] if shape["kind"] == "planar_region")
        self.assertEqual(projected["outer_mm"], outer)
        self.assertEqual(projected["holes_mm"], [hole])

    def test_inconsistent_tool_and_unassigned_via_net_are_blocked(self):
        """! @brief tool/finished 불일치나 의도 net 누락을 임의로 보정하지 않는다."""
        for mode in ("tool", "net", "pads"):
            document = copper_document()
            via = next(shape for shape in document["geometry"] if shape["kind"] == "via")
            if mode == "tool":
                via["tool_hole_diameter"] = quantity(0.4, "mm")
            elif mode == "net":
                via["net_id"] = None
            else:
                via["pad_ids"] = []
            with self.assertRaises(ProjectError):
                build_cad_input(document, snapshot_for(document))


@unittest.skipUnless(importlib.util.find_spec("cadquery") is not None, "격리 CAD Python 환경이 필요합니다.")
class CopperFeatureNativeTests(unittest.TestCase):
    """! @brief OCCT와 AP242에서 hole/두께/부피/원본 mapping의 실제 보존을 검사한다."""

    def test_region_holes_and_both_windings_preserve_exact_area(self):
        """! @brief 비볼록 region과 명시적 hole을 삼각 mesh로 대체하지 않고 압출한다."""
        outer = [[5, 5], [15, 5], [15, 10], [12, 10], [12, 15], [5, 15]]
        hole = [[7, 7], [9, 7], [9, 9], [7, 9]]
        for reverse in (False, True):
            with self.subTest(reverse=reverse), TemporaryDirectory(prefix="TraceWave 구리 영역 ") as directory:
                source = fixture()
                source["shapes"] = [{"id": identity("region"), "kind": "planar_region", "role": "ground", "layer_id": identity("copper"),
                                     "net_id": identity("ground-net"), "material_ref": None, "outer_mm": outer[::-1] if reverse else outer,
                                     "holes_mm": [hole[::-1] if reverse else hole]}]
                build_package(source, Path(directory))
                region = read_step(Path(directory) / "model.step")["conductor_" + identity("region")]
                self.assertAlmostEqual(region["section_area_mm2"], 81, places=7)
                self.assertAlmostEqual(region["volume_mm3"], 81 * 0.035, places=8)
                self.assertEqual(region["through_hole_count"], 1)

    def test_actual_domain_projection_reaches_native_step(self):
        """! @brief 원본 domain부터 CAD projection과 실제 STEP까지 신규 PTH 경로를 연결한다."""
        document = copper_document()
        projection = build_cad_input(document, snapshot_for(document))
        with TemporaryDirectory(prefix="TraceWave 원본 비아 ") as directory:
            result = build_package(projection, Path(directory))
            self.assertEqual(result["solid_count"], 4)
            self.assertEqual(read_step(Path(directory) / "model.step")["via_barrel_" + identity("via")]["through_hole_count"], 1)

    def test_rotated_pad_keeps_physical_layer_thickness(self):
        """! @brief 회전 사각 pad에 화면용 높이를 추가하지 않는다."""
        source = pth_fixture()
        source["shapes"] = [source["shapes"][0]]
        with TemporaryDirectory(prefix="TraceWave 패드 ") as directory:
            build_package(source, Path(directory))
            pad = read_step(Path(directory) / "model.step")["conductor_" + identity("pad-bottom")]
            self.assertAlmostEqual(pad["volume_mm3"], 4 * 0.035, places=8)
            self.assertAlmostEqual(pad["thickness_mm"], 0.035, places=8)
            half_extent = math.cos(math.pi / 6) + math.sin(math.pi / 6)
            self.assertAlmostEqual(pad["bbox_mm"][0], 20 - half_extent, places=6)
            self.assertAlmostEqual(pad["bbox_mm"][4], 25 + half_extent, places=6)

    def test_pth_is_hollow_and_drills_substrate_and_both_pads(self):
        """! @brief 실제 drill 공간, annular barrel과 양끝 접속을 STEP에서 재확인한다."""
        source = pth_fixture()
        before = deepcopy(source)
        with TemporaryDirectory(prefix="TraceWave 관통 비아 ") as directory:
            output = Path(directory)
            result = build_package(source, output)
            restored = read_step(output / "model.step")
            barrel = restored["via_barrel_" + identity("via")]
            substrate = restored["dielectric_" + identity("dielectric")]
            top = restored["conductor_" + identity("pad-top")]
            bottom = restored["conductor_" + identity("pad-bottom")]
            self.assertAlmostEqual(barrel["volume_mm3"], math.pi * (0.175 ** 2 - 0.15 ** 2) * 1.07, places=9)
            self.assertAlmostEqual(substrate["volume_mm3"], 40 * 60 - math.pi * 0.175 ** 2, places=6)
            self.assertAlmostEqual(top["volume_mm3"], math.pi * (1 - 0.175 ** 2) * 0.035, places=8)
            self.assertAlmostEqual(bottom["volume_mm3"], (4 - math.pi * 0.175 ** 2) * 0.035, places=8)
            self.assertTrue(all(item["through_hole_count"] == 1 for item in (barrel, substrate, top, bottom)))
            self.assertTrue(result["validation"]["explicit_via_pad_contacts_checked_before_and_after"])
            sidecar = json.loads((output / "sidecar.json").read_bytes())
            mapping = next(body for body in sidecar["body_map"] if body["id"] == identity("via"))
            self.assertEqual(mapping["fill"], "none")
            self.assertEqual(mapping["layer_ids"], [identity("bottom"), identity("copper")])
            self.assertEqual(mapping["vertical_span_mm"], [-0.035, 1.035])
            self.assertIsNone(mapping["material_id"])
            self.assertEqual(source, before)

    def test_unknown_tool_is_preserved_and_not_assigned_to_source(self):
        """! @brief 미정 tool bore는 원본에 채우지 않고 modeled drill의 산술 근거만 기록한다."""
        source = pth_fixture()
        source["shapes"][2]["tool_hole_diameter_mm"] = None
        with TemporaryDirectory(prefix="TraceWave 미정 tool ") as directory:
            build_package(source, Path(directory))
            sidecar = json.loads((Path(directory) / "sidecar.json").read_bytes())
            barrel = next(body for body in sidecar["body_map"] if body.get("feature_kind") == "via_barrel")
            self.assertIsNone(barrel["tool_hole_diameter_mm"])
            self.assertAlmostEqual(barrel["modeled_drill_diameter_mm"], 0.35)
            self.assertIsNone(source["shapes"][2]["tool_hole_diameter_mm"])

    def test_ground_region_and_pad_union_keep_via_contact_and_sources(self):
        """! @brief 접지 region에 포함된 pad의 병합 뒤에도 via 연결과 원본 대응이 남는다."""
        source = pth_fixture()
        source["shapes"].append({"id": identity("ground-region"), "kind": "planar_region", "role": "ground", "layer_id": identity("copper"),
                                 "net_id": identity("ground-net"), "material_ref": None,
                                 "outer_mm": [[15, 20], [25, 20], [25, 30], [15, 30]], "holes_mm": []})
        with TemporaryDirectory(prefix="TraceWave 접지 패드 비아 ") as directory:
            build_package(source, Path(directory))
            sidecar = json.loads((Path(directory) / "sidecar.json").read_bytes())
            ground = next(body for body in sidecar["body_map"] if identity("ground-region") in body["source_entity_ids"])
            self.assertIn(identity("pad-top"), ground["source_entity_ids"])
            self.assertIn(identity("via"), ground["drill_source_ids"])
            self.assertAlmostEqual(ground["metrics"]["volume_mm3"], (100 - math.pi * 0.175 ** 2) * 0.035, places=8)

    def test_invalid_region_topology_and_subtolerance_neck_are_blocked(self):
        """! @brief 자기교차/접촉 hole/커널보다 좁은 연결을 자동 치유하지 않는다."""
        for outer, holes in (([[5, 5], [10, 10], [5, 10], [10, 5]], []),
                             ([[5, 5], [10, 5], [10, 10], [5, 10]], [[[5, 6], [6, 6], [6, 7], [5, 7]]]),
                             ([[5, 5], [10, 5], [10, 10], [5, 10]], [[[5.000001, 6], [6, 6], [6, 7], [5.000001, 7]]])):
            source = fixture()
            source["shapes"] = [{"id": identity("invalid-region"), "kind": "planar_region", "role": "ground", "layer_id": identity("copper"),
                                 "net_id": identity("ground-net"), "material_ref": None, "outer_mm": outer, "holes_mm": holes}]
            with TemporaryDirectory(prefix="TraceWave 영역 차단 ") as directory:
                with self.assertRaises(ProjectError):
                    build_package(source, Path(directory))
                self.assertFalse((Path(directory) / "model.step").exists())

    def test_invalid_via_constraints_fail_before_step_publication(self):
        """! @brief 미충족 bore/접속/패드/net/범위를 채우거나 자동 보정하지 않는다."""
        for mode in ("tool", "pad-missing", "pad-net", "annulus", "fill", "same-layer", "outside"):
            with self.subTest(mode=mode), TemporaryDirectory(prefix="TraceWave 비아 차단 ") as directory:
                source = pth_fixture()
                via = source["shapes"][2]
                if mode == "tool":
                    via["tool_hole_diameter_mm"] = 0.4
                elif mode == "pad-missing":
                    via["pad_ids"] = [identity("pad-top")]
                elif mode == "pad-net":
                    source["shapes"][0]["net_id"] = identity("other")
                elif mode == "annulus":
                    source["shapes"][1]["size_mm"] = [0.35, 0.35]
                elif mode == "fill":
                    via["fill"] = "copper"
                elif mode == "same-layer":
                    via["end_layer_id"] = via["layer_id"]
                else:
                    via["center_mm"] = [0.1, 25]
                with self.assertRaises(ProjectError):
                    build_package(source, Path(directory))
                self.assertFalse((Path(directory) / "model.step").exists())

    def test_foreign_net_drilled_copper_cannot_touch_barrel(self):
        """! @brief drill로 잘린 다른 net 도체의 barrel 접촉을 정상 PTH로 오인하지 않는다."""
        source = pth_fixture()
        source["layers"][0]["z_min_mm"] = -0.1
        source["layers"][0]["thickness_mm"] = 0.035
        source["layers"].insert(1, {"id": identity("inner"), "name": "Other copper", "role": "conductor", "order": 1,
                                   "z_min_mm": -0.05, "thickness_mm": 0.01, "material_id": None})
        source["shapes"].append({"id": identity("foreign"), "kind": "line_path", "role": "feed", "net_id": identity("foreign-net"),
                                 "material_ref": None, "layer_id": identity("inner"), "start_mm": [19, 25], "end_mm": [21, 25], "width_mm": 0.1})
        with TemporaryDirectory(prefix="TraceWave 비아 단락 ") as directory:
            with self.assertRaises(ProjectError) as caught:
                build_package(source, Path(directory))
            self.assertEqual(caught.exception.code, "E_CONNECTIVITY")
            self.assertFalse((Path(directory) / "model.step").exists())


if __name__ == "__main__":
    unittest.main()
