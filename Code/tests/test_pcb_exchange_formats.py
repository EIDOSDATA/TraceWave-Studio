"""! @brief 실제 제조 조건과 구분한 합성 PCB로 형식 원문/단위/위상을 검증한다."""
from copy import deepcopy
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from rfad.domain.errors import ProjectError
from rfad.adapters.exchange import cam_reader, cam_writer, kicad_reader, kicad_writer, sexpr,pcb,pcb_verification


def identity():
    """! @brief 합성 원본의 유일한 식별자를 만든다."""
    return str(uuid4())


def fixture():
    """! @brief 두께는 합성 시험값이며 제작/측정/공구 원문은 미정으로 유지한다."""
    bottom,dielectric,top,net,board=[identity() for _ in range(5)]
    layers=[{"id":bottom,"name":"하부","role":"conductor","z_min_mm":0.,"thickness_mm":.035},
            {"id":dielectric,"name":"재료 미정","role":"dielectric","z_min_mm":.035,"thickness_mm":.93},
            {"id":top,"name":"상부","role":"conductor","z_min_mm":.965,"thickness_mm":.035}]
    shapes=[{"id":identity(),"kind":"line_path","layer_id":top,"net_id":net,"start_mm":[2.,2.],"end_mm":[8.,2.],"width_mm":.4},
            {"id":identity(),"kind":"arc_path","layer_id":top,"net_id":net,"center_mm":[10.,10.],"radius_mm":3.,"width_mm":.3,"start_angle_deg":20.,"sweep_angle_deg":145.},
            {"id":identity(),"kind":"planar_region","layer_id":bottom,"net_id":net,"outer_mm":[[1.,1.],[19.,1.],[19.,19.],[1.,19.]],"holes_mm":[[[4.,4.],[6.,4.],[6.,6.],[4.,6.]]]}]
    return {"schema":"rfad.pcb-projection/0.1","snapshot":{},"source_semantics":{"project_id":identity(),"nets":[{"id":net,"name":"RF 한글,%"}],"manufacturing":None,"measurement":None},
            "board":{"id":board,"width_mm":20.,"height_mm":20.},"layers":layers,"shapes":shapes,"mechanical":{"cutouts":[],"holes":[]},"footprints":[],"artwork_layers":[],"apertures":[],"keepouts":[],"names":{},"diagnostics":[]}


def add_slot(data,plated=False):
    """! @brief 완성 폭과 총길이를 가진 실제 직선 슬롯 시험값을 추가한다."""
    item={"id":identity(),"shape":{"kind":"capsule","center_mm":[15.,10.],"finished_length_mm":3.,"finished_width_mm":1.,"rotation_deg":30.},"plating":{"state":"plated" if plated else "unplated","thickness_mm":.025 if plated else None,"material_ref":None,"net_id":data["shapes"][0]["net_id"] if plated else None,"pad_ids":[]},"tool_diameter_mm":None,"surface_cut_ids":[]}
    data["mechanical"]["holes"].append(item)
    return item


def add_footprint(data):
    """! @brief world 권위 좌표의 bottom 회전 부품과 한 개 패드를 구성한다."""
    pad={"id":identity(),"kind":"pad","layer_id":data["layers"][0]["id"],"net_id":data["shapes"][0]["net_id"],"center_mm":[8+math.sqrt(3),9.],"size_mm":[2.,1.],"rotation_deg":30.,"pad_shape":"rectangle"}
    data["shapes"].append(pad)
    record={"id":identity(),"name":"한글 부품","library_id":None,"reference":"U1","value":None,"placement":{"origin_mm":[8.,8.],"rotation_deg":30.,"side":"bottom"},"members":[{"collection":"geometry","id":pad["id"]}],"pins":[{"number":"1","pad_ids":[pad["id"]],"hole_id":None}],"placement_envelope":None}
    data["footprints"].append(record)
    return record,pad


def composite_fixture():
    """! @brief 내부층/홀/슬롯/개구/keepout을 제조 미정과 함께 가진 합성 원본이다."""
    data=fixture();bottom,dielectric,top=data["layers"]
    dielectric["thickness_mm"]=.2
    inner1={"id":identity(),"name":"내부 1","role":"conductor","z_min_mm":.235,"thickness_mm":.017}
    core={"id":identity(),"name":"중심 재료 미정","role":"dielectric","z_min_mm":.252,"thickness_mm":.48}
    inner2={"id":identity(),"name":"내부 2","role":"conductor","z_min_mm":.732,"thickness_mm":.017}
    upper={"id":identity(),"name":"상부 재료 미정","role":"dielectric","z_min_mm":.749,"thickness_mm":.216}
    data["layers"]=[bottom,dielectric,inner1,core,inner2,upper,top]
    data["mechanical"]["cutouts"].append({"id":identity(),"shape":{"kind":"circle","center_mm":[17.,17.],"diameter_mm":1.},"surface_cut_ids":[]})
    add_slot(data,False)
    plated=add_slot(data,True);plated["shape"].update(center_mm=[12.,15.],finished_length_mm=2.,finished_width_mm=.6,rotation_deg=45.)
    for layer in (bottom,top):
        pad={"id":identity(),"kind":"pad","layer_id":layer["id"],"net_id":data["shapes"][0]["net_id"],"center_mm":[12.,15.],"size_mm":[3.,2.],"rotation_deg":45.,"pad_shape":"rectangle"}
        data["shapes"].append(pad);plated["plating"]["pad_ids"].append(pad["id"])
    footprint,pad=add_footprint(data)
    mask={"id":identity(),"name":"상부 개구","role":"solder_mask","side":"top","use_state":"used"}
    paste={"id":identity(),"name":"하부 paste","role":"solder_paste","side":"bottom","use_state":"used"}
    data["artwork_layers"]=[mask,paste]
    data["apertures"]=[{"id":identity(),"artwork_layer_id":mask["id"],"shape":{"kind":"circle","center_mm":[12.,15.],"diameter_mm":2.4}},
                       {"id":identity(),"artwork_layer_id":paste["id"],"shape":{"kind":"rectangle","center_mm":list(pad["center_mm"]),"size_mm":[1.8,.8],"rotation_deg":30.}}]
    footprint["members"].append({"collection":"apertures","id":data["apertures"][-1]["id"]})
    footprint["placement_envelope"]={"kind":"rectangle","center_mm":[9.,9.],"size_mm":[5.,4.],"rotation_deg":30.}
    data["keepouts"]=[{"id":identity(),"layer_ids":[top["id"],inner1["id"]],"shape":{"kind":"polygon","outer_mm":[[1.,16.],[2.,16.],[2.,17.],[1.,17.]],"holes_mm":[]},"prohibit":{"tracks":True,"vias":True,"pads":False,"copper_pours":False,"footprints":False}}]
    return data


class CamSyntaxTests(unittest.TestCase):
    """! @brief writer를 통과하지 않은 독립 원문과 실패 경계도 함께 검사한다."""
    def test_xnc_inch_slot_and_finished_diameter_are_independent(self):
        """! @brief inch 원문의 완성 0.1 inch 폭을 실제 공구값으로 덮지 않는다."""
        value=cam_reader.read_xnc(b'M48\n; #@! TF.FileFunction,NonPlated,1,2,NPTH\nINCH\nT01C0.1\n%\nT01\nG00X1.0Y2.0\nM15\nG01X1.5Y2.0\nM16\nM30\n')
        self.assertEqual(value["plating"],"unplated")
        self.assertEqual(value["holes"][0]["start_mm"],[25.4,50.8])
        self.assertAlmostEqual(value["holes"][0]["finished_width_mm"],2.54)
        self.assertIsNone(value["holes"][0]["tool_diameter_mm"])

    def test_xnc_decimal_g85_keeps_modal_end_axis_and_missing_classification(self):
        """! @brief 절대 decimal G85와 명시되지 않은 도금/공구를 함께 보존한다."""
        raw = b"M48\nMETRIC\nT01C1.2\n%\nG90\nT01\nX22.499Y9.999G85X27.499\nM30\n"
        result = cam_reader.read_xnc(raw)
        self.assertEqual(result["holes"][0]["end_mm"], [27.499, 9.999])
        self.assertIsNone(result["holes"][0]["tool_diameter_mm"])
        self.assertEqual(result["plating"], "unknown")
        self.assertEqual({loss["code"] for loss in result["losses"]},
                         {"cam_source_id_unspecified", "xnc_plating_unspecified"})
        with self.assertRaises(ProjectError):
            cam_reader.read_xnc(raw.replace(b"X27.499", b"X27499"))
        with self.assertRaises(ProjectError):
            cam_reader.read_xnc(raw.replace(b"X27.499", b"X22.499"))

    def test_missing_gerber_net_attribute_is_distinct_from_explicit_empty_net(self):
        """! @brief 명시 미연결과 사라진 동박 넷 속성의 안내를 구분한다."""
        header = b"%FSLAX46Y46*%%MOMM*%%TF.FileFunction,Copper,L1,Top*%%ADD10C,0.1*%D10*"
        body = b"X1000000Y2000000D03*M02*"
        missing = cam_reader.read_gerber(header + body)
        self.assertEqual({row["code"] for row in missing["losses"]},
                         {"cam_source_id_unspecified", "cam_copper_net_unspecified"})
        explicit = cam_reader.read_gerber(header + b"%TO.N,*%%TOTraceWaveId,track-1*%" + body)
        self.assertFalse(explicit["losses"])

    def test_gerber_decimal_units_and_clear_polarity_are_not_file_polarity(self):
        """! @brief LP clear는 이미지 연산이고 FilePolarity Negative는 mask 개구 의미이다."""
        raw=b'%FSLAX24Y24*%%MOIN*%%TF.FileFunction,Soldermask,Top*%%TF.FilePolarity,Negative*%%ADD10C,0.1*%D10*X10000Y20000D03*%LPC*%X10000Y20000D03*M02*'
        result=cam_reader.read_gerber(raw)
        self.assertEqual(result["file_attributes"][".FilePolarity"],["Negative"])
        self.assertEqual(result["objects"][0]["center_mm"],[25.4,50.8])
        self.assertEqual([item["polarity"] for item in result["objects"]],["dark","clear"])

    def test_unknown_cam_syntax_and_external_job_are_explicitly_rejected(self):
        """! @brief 압축/외부참조/미지원 macro/종료후 데이터는 조용히 생략하지 않는다."""
        cases=[b'%FSLAX46Y46*%%MOMM*%%AMNAME*1,1,1,0,0*%M02*',b'%FSLAX46Y46*%%MOMM*%M02*G04 trailing*']
        for raw in cases:
            with self.assertRaises(ProjectError):
                cam_reader.read_gerber(raw)
        with self.assertRaises(ProjectError):
            cam_reader.read_job(json.dumps({"FilesAttributes":[{"Path":"../outside.gbr"}]}).encode())
        with self.assertRaises(ProjectError):
            sexpr.parse(b'(a '+b'('*65+b'b'+b')'*65+b')')

    def test_job_duplicate_nonfinite_and_whole_package_limits(self):
        """! @brief Job 중복 키/비유한 수치/경로와 총 원문 예산은 조용히 수용하지 않는다."""
        for raw in (b'{"FilesAttributes":[],"FilesAttributes":[]}',b'{"FilesAttributes":[{"Path":"a"}],"bad":1e999}',b'{"FilesAttributes":[{"Path":"a"}],"bad":NaN}'):
            with self.assertRaises(ProjectError):
                cam_reader.read_job(raw)
        job={"FilesAttributes":[{"Path":"layer-"+str(i)+".gbr"} for i in range(40)]}
        self.assertEqual(len(cam_reader.read_job(json.dumps(job).encode())["job"]["FilesAttributes"]),40)
        for files in ({"../input.kicad_pcb":b"x"},{"a.kicad_pcb":b"x"*(8*1024*1024),"b":b"x"*(8*1024*1024+1)}):
            with self.assertRaises(ProjectError):
                pcb.parse_package(files,"kicad_pcb",{})

    def test_zero_circular_aperture_is_region_metadata_only(self):
        """! @brief 공식 C0 aperture를 사용한 실제 KiCad paste region을 읽는다."""
        raw=b'%FSLAX46Y46*%%MOMM*%%ADD10C,0*%D10*G01*G36*X0Y0D02*X1000000Y0D01*X0Y1000000D01*X0Y0D01*G37*M02*'
        self.assertEqual(cam_reader.read_gerber(raw)["objects"][0]["kind"],"region")
        with self.assertRaises(ProjectError):
            cam_reader.read_gerber(raw.replace(b'ADD10C,0',b'ADD10R,0X1'))

    def test_initial_current_point_and_interpolation_stay_undefined(self):
        """! @brief 최초 D01의 원점/보간을 임의로 채우지 않으며 flash는 보간을 요구하지 않는다."""
        header=b'%FSLAX46Y46*%%MOMM*%%ADD10C,0.4*%D10*'
        for body in (b'G01*X1000000Y1000000D01*',b'G01*X1000000D02*',b'X0Y0D02*X1000000Y1000000D01*'):
            with self.assertRaises(ProjectError):
                cam_reader.read_gerber(header+body+b'M02*')
        valid=cam_reader.read_gerber(header+b'X0Y0D02*G01*X1000000Y1000000D01*M02*')
        self.assertEqual(valid["objects"][0]["edge"]["start"],[0,0])
        self.assertEqual(cam_reader.read_gerber(header+b'X1000000Y2000000D03*M02*')["objects"][0]["center_mm"],[1,2])

    def test_analytic_region_holes_and_bottom_coordinates_roundtrip(self):
        """! @brief 기하 원문과 한글 net을 보존하고 bottom에 시각 mirror를 넣지 않는다."""
        data=fixture();before=deepcopy(data)
        raw,_,_=cam_writer.gerber(data,data["layers"][0]);actual=cam_reader.read_gerber(raw)
        region=actual["objects"][0]
        self.assertEqual(len(region["loops"]),2)
        self.assertEqual(region["loops"][0][0]["start"],[1.,1.])
        self.assertEqual(region["attributes"][".N"],["RF 한글,%"])
        top=cam_reader.read_gerber(cam_writer.gerber(data,data["layers"][-1])[0])
        arc=top["objects"][1]
        self.assertEqual(arc["kind"],"stroke")
        self.assertEqual(arc["edge"]["kind"],"arc")
        self.assertEqual(data,before)

    def test_drill_slot_tool_null_and_mask_usage_guard(self):
        """! @brief 원문 공구 미정과 별도 도금 분류를 보존한다."""
        data=fixture();slot=add_slot(data)
        raw,_=cam_writer.drill(data,False);result=cam_reader.read_xnc(raw)
        self.assertEqual(result["holes"][0]["finished_width_mm"],1)
        self.assertAlmostEqual(math.dist(result["holes"][0]["start_mm"],result["holes"][0]["end_mm"]),2,delta=1.5e-6)
        self.assertIsNone(slot["tool_diameter_mm"])
        self.assertIsNone(result["holes"][0]["tool_diameter_mm"])
        slot["plating"]["state"]="unknown"
        with self.assertRaises(ProjectError):
            cam_writer.drill(data,False)


@unittest.skipUnless(importlib.util.find_spec("shapely"),"구멍 cache의 고정 교환 환경 필요")
class KicadSyntaxTests(unittest.TestCase):
    """! @brief source/net/layer와 원호/구멍의 S 식 의미를 검사한다."""
    def test_board_native_objects_and_no_material_guess(self):
        """! @brief copper를 graphic으로 바꾸지 않고 원문 재료 null을 유지한다."""
        data=fixture();before=deepcopy(data);raw=kicad_writer.write_board(data);result=kicad_reader.read(raw)
        self.assertEqual([item["kind"] for item in result["shapes"]],["line_path","arc_path","planar_region"])
        self.assertEqual(result["shapes"][0]["start_mm"],[2,2])
        self.assertEqual(result["shapes"][0]["net_name"],"RF 한글,%")
        self.assertEqual(len(result["shapes"][2]["holes_mm"]),1)
        self.assertTrue(all(item["material"] is None for item in result["stackup"]))
        self.assertEqual(data,before)
        self.assertFalse(result["losses"])

    def test_unconsumed_per_object_rules_are_explicit_losses(self):
        """! @brief 원문 pad의 임의 clearance를 이름/기하만 읽고 조용히 버리지 않는다."""
        data=fixture();add_footprint(data)
        raw=kicad_writer.write_board(data).replace(b'(pad "1" smd rect',b'(pad "1" smd rect (clearance 0.3)')
        value=kicad_reader.read(raw)
        self.assertTrue(any(row.get("token")=="clearance" and row["raw_preserved"] for row in value["losses"]))
        parsed=pcb.parse_package({"board.kicad_pcb":raw},"kicad_pcb",{})
        self.assertTrue(any(row["code"]=="zone_rules_not_in_edit_model" and row["raw_preserved"] for row in parsed["losses"]))

    def test_plated_slot_and_npth_are_actual_drills(self):
        """! @brief 슬롯을 원형 via로 축소하지 않고 complete width/length를 보존한다."""
        data=fixture();add_slot(data,True)
        result=kicad_reader.read(kicad_writer.write_board(data))
        pad=next(item for item in result["shapes"] if item["kind"]=="pad")
        self.assertEqual(pad["drill"]["size_mm"],[3.,1.])
        self.assertEqual(pad["size_mm"],[3.05,1.05])
        self.assertEqual(pad["drill"]["plating"],"plated")
        self.assertIsNone(pad["drill"]["tool_diameter_mm"])

    def test_single_copper_does_not_invent_receiver_layer(self):
        """! @brief 수신기가 요구하는 두 번째 구리층을 원본 물성으로 발명하지 않는다."""
        data=fixture();data["layers"]=data["layers"][1:]
        with self.assertRaises(ProjectError):
            kicad_writer.write_board(data)

    def test_packages_verify_and_original_sidecar_mismatch_is_rejected(self):
        """! @brief 파일 hash를 다시 계산해도 source 사본 위조는 검수에서 차단한다."""
        from rfad.application.canonical import canonical_bytes
        import hashlib
        for format_name in ("kicad_pcb","kicad_mod","gerber_job"):
            projection=fixture();add_slot(projection);footprint,_=add_footprint(projection)
            options={} if format_name=="kicad_pcb" else {"footprint_id":footprint["id"]} if format_name=="kicad_mod" else {"layer_ids":[projection["layers"][-1]["id"],projection["layers"][0]["id"]]}
            data={"schema":"rfad.exchange-input/0.1","profile":pcb.PROFILES[format_name],"run_id":identity(),"snapshot":{},"format":format_name,"options":options,"projection":projection,"names":{},"dimensions":[]}
            before=deepcopy(data)
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);manifest=pcb.generate(data,root)
                report=pcb.verify(data,root,manifest)
                self.assertEqual(report["status"],"passed_profile")
                self.assertFalse(report["manufacturing_verified"])
                self.assertEqual(data,before)
                sidecar=json.loads((root/"sidecar.json").read_text("utf-8"));sidecar["source_semantics"]["measurement"]={"invented":True}
                raw=canonical_bytes(sidecar);(root/"sidecar.json").write_bytes(raw)
                record=next(item for item in manifest["files"] if item["path"]=="sidecar.json");record.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
                with self.assertRaises(ProjectError):
                    pcb.verify(data,root,manifest)

    def test_footprint_world_and_local_coordinates_are_not_applied_twice(self):
        """! @brief bottom 배치를 유지하면서 library 사본만 상대좌표로 변환한다."""
        data=fixture();footprint,pad=add_footprint(data)
        board=kicad_reader.read(kicad_writer.write_board(data))
        actual=next(item for item in board["shapes"] if item["id"]==pad["id"])
        self.assertAlmostEqual(actual["center_mm"][0],pad["center_mm"][0],places=6)
        self.assertEqual(actual["rotation_deg"],30)
        library=kicad_reader.read(kicad_writer.write_footprint(data,footprint["id"]))
        self.assertEqual(library["shapes"][0]["center_mm"],[2.,0.])
        self.assertEqual(library["shapes"][0]["rotation_deg"],0.)
        self.assertIsNone(library["shapes"][0]["net_name"])

    def test_composite_layers_artwork_and_slot_verify_before_receiver(self):
        """! @brief 내부층과 실제 개구/keepout의 원문 의미를 모두 게시 전 검사한다."""
        data=composite_fixture()
        raw=kicad_writer.write_board(data)
        result=pcb_verification.kicad(raw,data,"kicad_pcb",{})
        self.assertEqual(result["footprints"],5)
        layers=[item["id"] for item in data["layers"] if item["role"]=="conductor"]+[item["id"] for item in data["artwork_layers"]]
        package=cam_writer.package(data,layers)
        result=pcb_verification.cam(package,data,{"layer_ids":layers})
        self.assertEqual(result["holes"],2)
        decoded=cam_reader.read_job(package["fabrication.gbrjob"])["job"]
        self.assertEqual(decoded["GeneralSpecs"]["LayerNumber"],4)
        self.assertTrue(all("Material" not in item for item in decoded["MaterialStackup"]))

    def test_actual_object_semantics_are_checked_beyond_file_hash(self):
        """! @brief 위치/층/슬롯/연결 정책의 변조는 형식이 유효해도 검수 실패이다."""
        from unittest.mock import patch
        data=composite_fixture();raw=kicad_writer.write_board(data);decoded=kicad_reader.read(raw)
        variants=[]
        changed=deepcopy(decoded);changed["keepouts"][0]["outer_mm"][0][0]+=.2;variants.append(changed)
        changed=deepcopy(decoded);next(row for row in changed["artwork"] if row["layer"].endswith(".CrtYd"))["start_mm"][0]+=.2;variants.append(changed)
        changed=deepcopy(decoded);next(row for row in changed["shapes"] if row.get("drill") is not None)["rotation_deg"]+=45;variants.append(changed)
        changed=deepcopy(decoded);next(row for row in changed["shapes"] if row["kind"]=="planar_region")["fill_settings"]["connect_pads"]="no";variants.append(changed)
        changed=deepcopy(decoded);next(row for row in changed["shapes"] if row["kind"]=="arc_path")["start_mm"][0]+=.1;variants.append(changed)
        changed=deepcopy(decoded);changed["stackup"][1]["epsilon_r"]=4.2;variants.append(changed)
        for changed in variants:
            with patch.object(kicad_reader,"read",return_value=changed),self.assertRaises(ProjectError):
                pcb_verification.kicad(raw,data,"kicad_pcb",{})

    def test_cam_slot_orientation_outline_and_job_mutations_fail(self):
        """! @brief 재해시한 package라도 실제 외곽/층/미정/슬롯 변조를 잡는다."""
        from unittest.mock import patch
        data=composite_fixture();layers=[row["id"] for row in data["layers"] if row["role"]=="conductor"]+[row["id"] for row in data["artwork_layers"]]
        files=cam_writer.package(data,layers);options={"layer_ids":layers}
        changed=dict(files);job=json.loads(changed["fabrication.gbrjob"]);job["GeneralSpecs"]["LayerNumber"]=2;changed["fabrication.gbrjob"]=json.dumps(job).encode()
        with self.assertRaises(ProjectError):
            pcb_verification.cam(changed,data,options)
        changed=dict(files);changed["outline.gbr"]=changed["outline.gbr"].replace(b'X20000000Y0D01',b'X19000000Y0D01')
        with self.assertRaises(ProjectError):
            pcb_verification.cam(changed,data,options)
        reader=cam_reader.read_xnc
        def rotated(raw):
            """! @brief 전체 길이/중심/폭은 같지만 방향을 바꾼 수신 drill이다."""
            value=reader(raw)
            for hole in value["holes"]:
                center=[(a+b)/2 for a,b in zip(hole["start_mm"],hole["end_mm"])]
                for key in ("start_mm","end_mm"):
                    x,y=hole[key][0]-center[0],hole[key][1]-center[1];hole[key]=[center[0]-y,center[1]+x]
            return value
        with patch.object(cam_reader,"read_xnc",side_effect=rotated),self.assertRaises(ProjectError):
            pcb_verification.cam(files,data,options)


KICAD=os.environ.get("RFAD_TEST_KICAD")


@unittest.skipUnless(KICAD,"명시한 KiCad 10.0.8 수신 시험 환경 필요")
class ActualKicadReceiverTests(unittest.TestCase):
    """! @brief 독립 수신 도구에서 실제 재열기/저장/영역 fill을 검사한다."""
    def test_actual_load_refill_save_and_drill_preserve_geometry(self):
        """! @brief 복사본만 수정하고 원래 내보낸 바이트는 유지한다."""
        data=fixture();add_slot(data,False)
        with tempfile.TemporaryDirectory(prefix="tracewave-kicad-") as temp:
            root=Path(temp);path=root/"board.kicad_pcb";path.write_bytes(kicad_writer.write_board(data));original=path.read_bytes()
            (root/"board.kicad_pro").write_bytes(kicad_writer.project_settings())
            filled=root/"filled.kicad_pcb";filled.write_bytes(original)
            (root/"filled.kicad_pro").write_bytes(kicad_writer.project_settings())
            subprocess.run([str(Path(KICAD)/"kicad-cli.exe"),"pcb","drc","--refill-zones","--save-board","--format","json","--output",str(root/"drc.json"),str(filled)],capture_output=True,text=True,encoding="utf-8",timeout=60,check=True)
            script='import pcbnew,json,sys; b=pcbnew.LoadBoard(sys.argv[1]); print(json.dumps({"version":pcbnew.GetBuildVersion(),"tracks":len(b.GetTracks()),"zones":len(b.Zones()),"area":sum(z.CalculateFilledArea() for z in b.Zones())/1e12,"holes":[list(p.GetDrillSize()) for f in b.GetFootprints() for p in f.Pads()]}))'
            result=subprocess.run([str(Path(KICAD)/"python.exe"),"-c",script,str(filled)],capture_output=True,text=True,timeout=60,check=True)
            report=json.loads(result.stdout)
            self.assertEqual(report["version"],"10.0.8")
            self.assertEqual(report["tracks"],2)
            self.assertEqual(report["zones"],1)
            self.assertEqual(report["holes"],[[3000000,1000000]])
            self.assertAlmostEqual(report["area"],320-(2+math.pi*.5**2),delta=(4+math.pi)*.001)
            self.assertEqual(path.read_bytes(),original)
            actual=kicad_reader.read((root/"filled.kicad_pcb").read_bytes())
            self.assertEqual(len(next(item for item in actual["shapes"] if item["kind"]=="planar_region")["holes_mm"]),1)
