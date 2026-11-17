"""! @brief 실제 KiCad 편집 복사본의 net/구리/드릴을 별도 수신 경로로 검사한다."""
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_pcb_exchange_formats import composite_fixture,identity
from rfad.adapters.exchange import kicad_writer,kicad_reader,cam_reader,pcb_verification
from rfad.adapters.exchange.pcb_geometry import polygonize,native_fill,compare_regions
from rfad.domain import drawing_layout as geometry

KICAD=os.environ.get("RFAD_TEST_KICAD")


def expected_copper(projection,layer_id):
    """! @brief 독립 원문 산술로 구리 합집합 뒤 완성 홀을 뺀다.

    @details 개별 절삭 polygon과 annulus를 다시 붙여 생기는 chord 수치 틈을
    실제 hole로 세지 않도록 원래 솔리드 합집합을 먼저 계산한다.
    """
    from shapely import GeometryCollection
    result=GeometryCollection();drills=GeometryCollection()
    for item in projection["shapes"]:
        if item["kind"]=="via":
            outer={"kind":"circle","center_mm":item["center_mm"],"diameter_mm":item["finished_hole_diameter_mm"]+2*item["plating_thickness_mm"]}
            result=result.union(polygonize(geometry.mechanical_loops(outer)))
            drills=drills.union(polygonize(geometry.mechanical_loops({**outer,"diameter_mm":item["finished_hole_diameter_mm"]})))
        elif item["layer_id"]==layer_id:
            result=result.union(polygonize(geometry.shape_loops(item)))
    for item in projection["mechanical"]["holes"]:
        if item["plating"]["state"]=="plated":
            result=result.union(polygonize(geometry.mechanical_loops(item["shape"],item["plating"]["thickness_mm"])))
        drills=drills.union(polygonize(geometry.mechanical_loops(item["shape"])))
    for item in projection["mechanical"]["cutouts"]:
        drills=drills.union(polygonize(geometry.mechanical_loops(item["shape"])))
    return result.difference(drills)


def actual_copper(decoded,layer,net):
    """! @brief 수신 파일의 실제 구리 합집합에서 수신 drill/Edge.Cuts를 적용한다.

    @details 원본의 홀/절삭/위치를 읽지 않는다. PTH는 완성 드릴 차집합 후
    남은 실제 pad 외경이 annulus가 된다. 단순 원문 기대 절삭으로 오류를 숨기지 않는다.
    """
    from shapely import GeometryCollection
    material=GeometryCollection();drills=GeometryCollection()
    for item in decoded["shapes"]:
        kind=item["kind"]
        if kind=="pad" and item["drill"] is not None:
            drill=item["drill"];width,height=drill["size_mm"]
            assert drill["offset_mm"]==[0,0]
            shape={"kind":"circle","center_mm":item["center_mm"],"diameter_mm":width} if drill["shape"]=="circle" else {"kind":"capsule","center_mm":item["center_mm"],"finished_length_mm":max(width,height),"finished_width_mm":min(width,height),"rotation_deg":item["rotation_deg"]+(0 if width>=height else 90)}
            drills=drills.union(polygonize(geometry.mechanical_loops(shape)))
        elif kind=="via":
            drills=drills.union(polygonize(geometry.mechanical_loops({"kind":"circle","center_mm":item["center_mm"],"diameter_mm":item["finished_hole_diameter_mm"]})))
        include=item.get("layer")==layer or layer in item.get("layers",[]) or "*.Cu" in item.get("layers",[]) or kind=="via"
        if not include or item["net_name"]!=net or kind=="pad" and item["pad_type"]=="np_thru_hole":
            continue
        if kind=="planar_region":
            value=native_fill(item["filled_polygons_mm"])
        elif kind in ("line_path","arc_path"):
            value=polygonize(geometry.shape_loops(item))
        elif kind=="pad":
            width,height=item["size_mm"]
            if item["pad_shape"]=="oval":
                value=polygonize(geometry.mechanical_loops({"kind":"capsule","center_mm":item["center_mm"],"finished_length_mm":max(width,height),"finished_width_mm":min(width,height),"rotation_deg":item["rotation_deg"]+(0 if width>=height else 90)}))
            else:
                value=polygonize(geometry.shape_loops({**item,"pad_shape":"circle" if item["pad_shape"]=="circle" else "rectangle"}))
        elif kind=="via":
            value=polygonize(geometry.mechanical_loops({"kind":"circle","center_mm":item["center_mm"],"diameter_mm":item["size_mm"]}))
        else:
            raise AssertionError(kind)
        material=material.union(value)
    # 합성 수신 fixture의 독립 Edge.Cuts는 rectangle 외곽과 원형 cutout이다.
    for edge in decoded["edges"]:
        if edge["kind"]=="circle":
            drills=drills.union(polygonize(geometry.mechanical_loops({"kind":"circle","center_mm":edge["center_mm"],"diameter_mm":2*edge["radius_mm"]})))
    return material.difference(drills)


@unittest.skipUnless(KICAD,"명시한 KiCad 10.0.8 수신 환경 필요")
class KicadReceiverTests(unittest.TestCase):
    """! @brief 제조 DRC 합격과 구분한 실제 파일 수신/편집/재채움 시험이다."""
    def test_composite_native_net_topology_artwork_drills_and_edit(self):
        """! @brief 전 객체 net과 내부층을 실제 수신하고 열린 급전 간격을 유지한다."""
        from shapely import GeometryCollection
        projection=composite_fixture();net=projection["shapes"][0]["net_id"]
        top=projection["layers"][-1]["id"];bottom=projection["layers"][0]["id"]
        via={"id":identity(),"kind":"via","center_mm":[3.,10.],"finished_hole_diameter_mm":.4,"plating_thickness_mm":.025,"layer_id":bottom,"end_layer_id":top,"net_id":net}
        projection["shapes"].append(via)
        # 원래 선 끝 x=8, 반폭 .2와 새 선 시작 8.5, 반폭 .2 사이 0.1 mm.
        projection["shapes"].append({"id":identity(),"kind":"line_path","layer_id":top,"net_id":net,"start_mm":[8.5,2.],"end_mm":[10.,2.],"width_mm":.4})
        with tempfile.TemporaryDirectory(prefix="tracewave-native-pcb-") as temp:
            root=Path(temp);original=root/"source.kicad_pcb";original.write_bytes(kicad_writer.write_board(projection));before=original.read_bytes()
            target=root/"copy.kicad_pcb";target.write_bytes(before);target.with_suffix(".kicad_pro").write_bytes(kicad_writer.project_settings())
            command=[str(Path(KICAD)/"kicad-cli.exe"),"pcb","drc","--refill-zones","--save-board","--format","json","--output",str(root/"drc.json"),str(target)]
            subprocess.run(command,capture_output=True,text=True,encoding="utf-8",timeout=60,check=True)
            script='import pcbnew,json,sys; b=pcbnew.LoadBoard(sys.argv[1]); print(json.dumps({"version":pcbnew.GetBuildVersion(),"copper":b.GetCopperLayerCount(),"tracks":[[t.GetNetname(),t.GetLayerName()] for t in b.GetTracks()],"zones":[[z.GetNetname(),[b.GetLayerName(i) for i in z.GetLayerSet().Seq()],z.GetIsRuleArea()] for z in b.Zones()],"pads":[[p.GetNetname(),list(p.GetDrillSize()),p.GetAttribute()] for f in b.GetFootprints() for p in f.Pads()]}))'
            probe=subprocess.run([str(Path(KICAD)/"python.exe"),"-c",script,str(target)],capture_output=True,text=True,encoding="utf-8",timeout=60,check=True)
            data=json.loads(probe.stdout);self.assertEqual(data["version"],"10.0.8");self.assertEqual(data["copper"],4)
            self.assertTrue(all(row[0]=="RF 한글,%" for row in data["tracks"]))
            self.assertEqual([row[0] for row in data["zones"] if not row[2]],["RF 한글,%"])
            self.assertEqual({name for row in data["zones"] if row[2] for name in row[1]},{"F.Cu","In2.Cu"})
            decoded=kicad_reader.read(target.read_bytes());layer_map=kicad_writer.layer_map(projection)
            for layer_id,layer in layer_map.items():
                expected=expected_copper(projection,layer_id)
                comparison=compare_regions(actual_copper(decoded,layer,"RF 한글,%"),expected,.001)
                self.assertLessEqual(comparison["boundary_error_mm"],.001)
            lines=[row for row in decoded["shapes"] if row["kind"]=="line_path"]
            actual_gap=polygonize(geometry.shape_loops(lines[0])).distance(polygonize(geometry.shape_loops(lines[1])))
            self.assertAlmostEqual(actual_gap,.1,delta=3e-5)
            # 수신 source UUID를 보존한 실제 편집 저장; 원본 파일은 그대로 둔다.
            footprint=projection["footprints"][0];pad=next(row["id"] for row in footprint["members"] if row["collection"]=="geometry")
            edit='import pcbnew,sys; b=pcbnew.LoadBoard(sys.argv[1]); f=next(f for f in b.GetFootprints() if f.GetReference()=="U1"); f.SetValue("사용자 수정"); f.Move(pcbnew.VECTOR2I(1000000,0)); pcbnew.SaveBoard(sys.argv[2],b)'
            subprocess.run([str(Path(KICAD)/"python.exe"),"-c",edit,str(target),str(root/"edited.kicad_pcb")],capture_output=True,text=True,encoding="utf-8",timeout=60,check=True)
            edited=kicad_reader.read((root/"edited.kicad_pcb").read_bytes());actual=next(row for row in edited["footprints"] if row["id"]==footprint["id"])
            self.assertEqual(actual["properties"]["Value"],"사용자 수정");self.assertEqual(actual["placement"]["origin_mm"],[9,8])
            old=next(row for row in decoded["shapes"] if row["id"]==pad);new=next(row for row in edited["shapes"] if row["id"]==pad)
            self.assertAlmostEqual(new["center_mm"][0]-old["center_mm"][0],1,places=6);self.assertEqual(new["net_name"],old["net_name"])
            self.assertEqual(original.read_bytes(),before)

    def test_native_footprint_load_and_cam_exports(self):
        """! @brief 실제 library 로드와 수신기가 다시 쓴 Gerber/XNC를 별도 읽는다."""
        projection=composite_fixture();footprint=projection["footprints"][0]
        with tempfile.TemporaryDirectory(prefix="tracewave-native-cam-") as temp:
            root=Path(temp);library=root/"parts.pretty";library.mkdir();mod=library/"Part.kicad_mod";mod.write_bytes(kicad_writer.write_footprint(projection,footprint["id"]));before=mod.read_bytes()
            script='import pcbnew,json,sys; f=pcbnew.FootprintLoad(sys.argv[1],"Part"); print(json.dumps({"pads":[[p.GetNumber(),list(p.GetPosition()),p.GetOrientationDegrees(),list(p.GetLayerSet().Seq())] for p in f.Pads()],"reference":f.GetReference()}))'
            result=subprocess.run([str(Path(KICAD)/"python.exe"),"-c",script,str(library)],capture_output=True,text=True,encoding="utf-8",timeout=60,check=True)
            self.assertEqual(json.loads(result.stdout)["pads"],[["1",[2000000,0],0.0,[2]]]);self.assertEqual(mod.read_bytes(),before)
            path=root/"board.kicad_pcb";path.write_bytes(kicad_writer.write_board(projection));path.with_suffix(".kicad_pro").write_bytes(kicad_writer.project_settings())
            for args in (["gerbers","--layers","F.Cu,B.Cu,F.Mask,B.Paste,Edge.Cuts","--disable-aperture-macros"],["drill","--excellon-separate-th","--excellon-oval-format","route"]):
                subprocess.run([str(Path(KICAD)/"kicad-cli.exe"),"pcb","export",*args,"--output",str(root/"cam"),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=60,check=True)
            gerbers=[file for file in (root/"cam").glob("*.g*") if file.suffix!=".gbrjob"];self.assertEqual(len(gerbers),5)
            for file in gerbers:
                decoded=cam_reader.read_gerber(file.read_bytes());self.assertTrue(decoded["objects"])
            drills={file.name:cam_reader.read_xnc(file.read_bytes()) for file in (root/"cam").glob("*.drl")}
            self.assertEqual(len(drills),2)
            for name,value in drills.items():
                self.assertEqual(len(value["holes"]),1);hole=value["holes"][0];self.assertEqual(hole["kind"],"slot");self.assertIsNone(hole["tool_diameter_mm"])
                source=next(row for row in projection["mechanical"]["holes"] if row["plating"]["state"]==value["plating"])["shape"]
                self.assertAlmostEqual(hole["finished_width_mm"],source["finished_width_mm"],places=3)
                self.assertAlmostEqual(math.dist(hole["start_mm"],hole["end_mm"])+hole["finished_width_mm"],source["finished_length_mm"],delta=.002)
