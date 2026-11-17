"""! @brief 봉인 parser 자료를 명시 대응하고 한 역명령으로 되돌리는 수입 경계를 검사한다."""
from copy import deepcopy
import unittest
from uuid import uuid4

from rfad.application import pcb_exchange_service as api
from rfad.application.pcb_import_mapping import import_candidate
from rfad.application.canonical import canonical_hash
from rfad.domain.pcb_features import COMMAND
from rfad.domain.project import apply_command
from test_pcb_features import pcb_document
from test_design import quantity


def raw_record(document):
    """! @brief 수입 서비스가 전달할 원문 artifact 참조만 만든다."""
    base = "projects/import-test/pcb-import/"
    return {"id": str(uuid4()), "format": "kicad_board", "format_version": "20260206", "parser_profile": "rfad.pcb-import/0.1",
            "source_files": [{"uri": base + "raw", "sha256": "1" * 64, "bytes": 1}], "report": {"uri": base + "report", "sha256": "2" * 64, "bytes": 1}, "bindings": [], "source_refs": ["봉인 parser 시험"]}


def fixture():
    """! @brief 현재 기판과 일치하는 파일 좌표/층/넷 대응을 명시한다."""
    document = pcb_document()
    layer = document["stackup"][0]["id"]
    frame = document["board"]["frame_id"]
    net = document["nets"][0]["id"]
    mapping = {"board_id": document["board"]["id"], "frame_id": frame, "layers": [{"source": "F.Cu", "target": layer}], "nets": [{"source": "0", "target": None}, {"source": "1", "target": net}], "placement": None}
    points = [[0,0], [60,0], [60,40], [0,40]]
    data = {"schema": "rfad.kicad-read/0.1", "format": "kicad_pcb", "version": "20260206", "layers": [{"name": "F.Cu"}], "nets": [{"code": 1, "name": "파일넷"}],
            "shapes": [{"id": "line", "kind": "line_path", "layer": "F.Cu", "net_code": 1, "net_name": "파일넷", "start_mm": [2,3], "end_mm": [9,3], "width_mm": .4}],
            "edges": [{"kind": "line", "start_mm": points[i], "end_mm": points[(i+1)%4]} for i in range(4)], "footprints": [], "keepouts": [], "artwork": [], "stackup": [], "losses": []}
    parsed = {"schema": "rfad.pcb-parse/0.1", "format": "kicad_pcb", "records": [{"path": "원본.kicad_pcb", "data": data}], "mapping": [], "losses": [], "raw_preservation_required": True, "manufacturing_verified": False, "physics_verified": False}
    return document, parsed, raw_record(document), mapping


def run(document, parsed, record, mapping, acknowledged=()):
    """! @brief 실제 후보 생성 진단을 테스트 실패 근거로 노출한다."""
    review, patch = import_candidate(document, parsed, record, mapping, list(acknowledged), "원문 대응 시험")
    return review, patch


class PcbImportMappingTests(unittest.TestCase):
    """! @brief 실제 원문/미정/배치/역명령을 보존하며 미지원 손실은 차단한다."""

    def test_board_line_source_and_single_inverse_preserve_before(self):
        document, parsed, record, mapping = fixture()
        originals = deepcopy((document, parsed, record, mapping))
        review, patch = run(document, parsed, record, mapping)
        self.assertTrue(review["can_apply"], review["issues"])
        changed, _, _, inverse = apply_command(document, {"command_id": str(uuid4()), "type": COMMAND, "payload": patch}, document["revision_id"])
        line = next(row for row in changed["geometry"] if row.get("source_ref", "") and row["source_ref"].startswith("pcb-import:"))
        self.assertEqual(line["start"][0]["value_si"], .002)
        self.assertTrue(line["start"][0]["source_refs"])
        self.assertIsNone(line["material_ref"])
        self.assertEqual(changed["materials"], document["materials"])
        restored, _, _, _ = apply_command(changed, {"command_id": str(uuid4()), **inverse}, changed["revision_id"])
        self.assertNotIn("pcb", restored)
        self.assertEqual(restored["geometry"], document["geometry"])
        self.assertEqual((document, parsed, record, mapping), originals)
        self.assertFalse(review["manufacturing_verified"])

    def test_explicit_mapping_board_mismatch_and_loss_ack_block(self):
        document, parsed, record, mapping = fixture()
        wrong = deepcopy(mapping); wrong["nets"] = []
        self.assertFalse(run(document, parsed, record, wrong)[0]["can_apply"])
        data = parsed["records"][0]["data"]
        data["edges"][0]["end_mm"][0] = 59
        self.assertFalse(run(document, parsed, record, mapping)[0]["can_apply"])
        document, parsed, record, mapping = fixture()
        parsed["losses"] = [{"path": "원본.kicad_pcb", "code": "unsupported_token", "raw_preserved": True}]
        review, _ = run(document, parsed, record, mapping)
        self.assertFalse(review["can_apply"])
        self.assertEqual(review["losses"][0]["id"], canonical_hash(parsed["losses"][0]))
        self.assertTrue(run(document, parsed, record, mapping, [review["losses"][0]["id"]])[0]["can_apply"])

    def test_world_footprint_pad_and_unknown_tool_are_not_transformed_twice(self):
        document, parsed, record, mapping = fixture()
        data = parsed["records"][0]["data"]
        data["footprints"] = [{"id":"owner", "library_id":"부품", "placement":{"origin_mm":[8,8],"rotation_deg":30,"side":"top"}, "properties":{"Reference":"U1"}}]
        data["shapes"] = [{"id":"pad1","kind":"pad","layer":None,"net_code":1,"net_name":"파일넷","pad_type":"thru_hole","pad_shape":"circle","number":"1","center_mm":[9.732050807568877,9],"size_mm":[2,2],"rotation_deg":30,"layers":["F.Cu"],"footprint_id":"owner","drill":{"shape":"circle","size_mm":[1,1],"offset_mm":[0,0],"plating":"plated","tool_diameter_mm":None}}]
        review, patch = run(document, parsed, record, mapping)
        self.assertTrue(review["can_apply"], review["issues"])
        changed, _, _, _ = apply_command(document, {"command_id":str(uuid4()), "type":COMMAND, "payload":patch}, document["revision_id"])
        owner = changed["pcb"]["footprints"][0]
        pad = next(row for row in changed["geometry"] if row["kind"]=="pad")
        hole = changed["pcb"]["holes"][0]
        self.assertEqual(pad["center"][0]["value_si"], 9.732050807568877e-3)
        self.assertEqual(owner["placement"]["origin"][0]["value_si"], .008)
        self.assertEqual(owner["pins"][0]["hole_id"], hole["id"])
        self.assertIsNone(hole["plating"]["thickness"]["value_si"])
        self.assertIsNone(hole["tool_diameter"]["value_si"])
        self.assertEqual(owner["edit_state"], "original")

    def test_xnc_slot_keeps_finished_geometry_and_unknown_plating(self):
        document, parsed, record, mapping = fixture()
        record["format"]="xnc"
        parsed["records"][0]["data"]={"schema":"rfad.xnc-read/0.1", "plating":"unknown", "holes":[{"kind":"slot","start_mm":[4,5],"end_mm":[7,9],"finished_width_mm":1,"tool_diameter_mm":None}]}
        review, patch=run(document,parsed,record,mapping)
        self.assertTrue(review["can_apply"],review["issues"])
        hole=next(row["replacement"]["value"] for row in patch["changes"] if row["collection"]=="pcb.holes")
        self.assertEqual(hole["shape"]["finished_length"]["value_si"], .006)
        self.assertEqual(hole["plating"]["state"],"unknown")
        self.assertIsNone(hole["tool_diameter"]["value_si"])

    def test_clear_and_unhandled_arc_region_are_blocked_without_original_mutation(self):
        document, parsed, record, mapping = fixture()
        mapping["layers"]=[{"source":"原文.gbr", "target":document["stackup"][0]["id"]}]
        mapping["nets"]=[{"source":"未定", "target":None}]
        data={"schema":"rfad.gerber-read/0.1", "file_attributes":{".FileFunction":["Copper"],".FilePolarity":["Positive"]},"objects":[{"kind":"region","polarity":"clear","attributes":{".N":["未定"]},"loops":[]}]}
        parsed["records"]=[{"path":"原文.gbr", "data":data}]
        old=deepcopy(document)
        self.assertFalse(run(document,parsed,record,mapping)[0]["can_apply"])
        data["objects"][0].update(polarity="dark",loops=[[{"kind":"arc"}]])
        self.assertFalse(run(document,parsed,record,mapping)[0]["can_apply"])
        self.assertEqual(document,old)

    def test_actual_kicad_reader_footprint_and_legacy_absence_undo(self):
        from rfad.adapters.exchange.kicad_reader import read
        document, parsed, record, mapping = fixture()
        raw = b'(footprint "Example" (version 20260206) (generator pcbnew) (layer "F.Cu") (uuid "10000000-0000-0000-0000-000000000001") (property "Reference" "U1") (pad "1" smd rect (at 2 3 45) (size 2 1) (layers "F.Cu") (uuid "10000000-0000-0000-0000-000000000002")))'
        parsed["records"][0]["data"] = read(raw)
        mapping["placement"] = {"origin":[quantity(10,"mm"),quantity(20,"mm")],"rotation":quantity(90,"deg"),"side":"top"}
        review, patch = run(document, parsed, record, mapping)
        self.assertTrue(review["can_apply"],review["issues"])
        pad = next(row["replacement"]["value"] for row in patch["changes"] if row["collection"]=="geometry")
        self.assertAlmostEqual(pad["center"][0]["value_si"], .013)
        self.assertAlmostEqual(pad["center"][1]["value_si"], .022)
        self.assertEqual(parsed["records"][0]["data"]["shapes"][0]["center_mm"], [2,-3])

    def test_keepout_explicit_artwork_and_missing_pad_margin_are_preserved(self):
        from rfad.domain.pcb_features import empty_pcb
        document, parsed, record, mapping = fixture()
        document["pcb"] = empty_pcb()
        layer = api.new_record(document,"artwork_layer")
        layer["use_state"]="used"
        document["pcb"]["artwork_layers"]=[layer]
        mapping["layers"].append({"source":"F.Mask","target":layer["id"]})
        data=parsed["records"][0]["data"]
        data["keepouts"]=[{"id":"keep","layer":"F.Cu","outer_mm":[[20,20],[22,20],[22,22],[20,22]],"holes_mm":[],"prohibit":{"tracks":True,"copperpour":True},"footprint_id":None}]
        data["artwork"]=[{"id":"mask","layer":"F.Mask","kind":"circle","center_mm":[5,5],"radius_mm":1.2,"fill":"solid","width_mm":0,"footprint_id":None}]
        data["shapes"].append({"id":"pad", "kind":"pad","net_code":0,"pad_type":"smd","pad_shape":"rect","number":"","center_mm":[5,5],"size_mm":[2,1],"rotation_deg":0,"layers":["F.Cu","F.Mask"],"footprint_id":None,"drill":None,"solder_mask_margin":None})
        review,patch=run(document,parsed,record,mapping)
        self.assertTrue(review["can_apply"], review["issues"])
        apertures=[row["replacement"]["value"] for row in patch["changes"] if row["collection"]=="pcb.apertures"]
        self.assertEqual(len(apertures),2)
        related=next(row for row in apertures if row["definition"]["mode"]=="pad_margin")
        self.assertIsNone(related["definition"]["margin"]["value_si"])
        self.assertTrue(any(row["missing"] for row in review["scene"]["pcb_features"] if row["kind"]=="aperture"))
        keep=next(row["replacement"]["value"] for row in patch["changes"] if row["collection"]=="pcb.keepouts")
        self.assertTrue(keep["prohibit"]["copper_pours"])
        self.assertFalse(keep["prohibit"]["footprints"])

    def test_actual_basic_job_profile_copper_mask_and_xnc(self):
        from rfad.adapters.exchange.cam_reader import read_gerber, read_xnc
        from rfad.domain.pcb_features import empty_pcb
        document, parsed, record, mapping=fixture()
        document["pcb"]=empty_pcb()
        layer=api.new_record(document,"artwork_layer");layer["use_state"]="used";document["pcb"]["artwork_layers"]=[layer]
        copper=document["stackup"][0]["id"]
        mapping["layers"]=[{"source":"copper.gbr","target":copper},{"source":"mask.gbr","target":layer["id"]}]
        mapping["nets"]=[{"source":"","target":None}]
        header="%FSLAX66Y66*%\n%MOMM*%\n%TF.FileFunction,{role}*%\n%TF.FilePolarity,Positive*%\n%ADD10C,{width}*%\nD10*\nG01*\n"
        profile=header.format(role="Profile,NP",width=.05)+"X0Y0D02*X60000000Y0D01*X60000000Y40000000D01*X0Y40000000D01*X0Y0D01*M02*"
        copper_raw=header.format(role="Copper,L1,Top",width=.4)+"X2000000Y3000000D02*X9000000Y3000000D01*M02*"
        mask=header.format(role="Soldermask,Top",width=2).replace("FilePolarity,Positive", "FilePolarity,Negative")+"X5000000Y5000000D03*M02*"
        drill="M48\n; #@! TF.FileFunction,NonPlated,1,2,NPTH\nMETRIC,LZ\nT01C1.000000\n%\nT01\nG05\nX5.000000Y6.000000\nM30\n"
        parsed["records"]=[{"path":path,"data":read_gerber(raw.encode())} for path,raw in (("outline.gbr",profile),("copper.gbr",copper_raw),("mask.gbr",mask))]
        parsed["records"].append({"path":"npth.drl","data":read_xnc(drill.encode())})
        review,patch=run(document,parsed,record,mapping)
        self.assertTrue(review["can_apply"],review["issues"])
        imported=next(row["replacement"]["value"] for row in patch["changes"] if row["collection"]=="pcb.imports")
        self.assertTrue(any(row["collection"]=="board" for row in imported["bindings"]))
        self.assertTrue(any(row["collection"]=="pcb.apertures" for row in patch["changes"]))
        self.assertTrue(any(row["collection"]=="pcb.holes" for row in patch["changes"]))

    def test_source_mapping_descriptors_and_copy_guard(self):
        from rfad.application.pcb_import_mapping import import_sources
        from rfad.application.sweep_copy import prepare_artifacts
        from rfad.domain.errors import ProjectError
        document, parsed, record, mapping = fixture()
        sources=import_sources(parsed)
        self.assertEqual(sources["layers"],[{"source":"F.Cu","label":"F.Cu","role":"conductor","side":None}])
        self.assertEqual(sources["nets"][0]["source"],"1")
        self.assertIn("파일넷",sources["nets"][0]["label"])
        review,patch=run(document,parsed,record,mapping)
        self.assertTrue(review["can_apply"],review["issues"])
        changed,_,_,_=apply_command(document,{"command_id":str(uuid4()),"type":COMMAND,"payload":patch},document["revision_id"])
        with self.assertRaises(ProjectError) as caught:
            prepare_artifacts(None,{},changed,"projects/copy")
        self.assertEqual(caught.exception.code,"E_UNSUPPORTED")

    def test_technical_container_preserves_child_bindings_without_component(self):
        """! @brief writer의 도형 포장을 실제 부품/핀/소유로 승격하지 않는다."""
        document, parsed, record, mapping = fixture()
        data = parsed["records"][0]["data"]
        data["footprints"] = [{"id": "container", "technical_container": True, "library_id": "TraceWave:geometry", "placement": {"origin_mm": [5, 5], "rotation_deg": 0, "side": "top"}, "properties": {"Reference": "PORT"}}]
        data["shapes"] = [{"id": "pad", "kind": "pad", "net_code": 0, "net_name": None, "pad_type": "smd", "pad_shape": "circle", "number": "1", "center_mm": [5, 5], "size_mm": [2, 2], "rotation_deg": 0, "layers": ["F.Cu"], "footprint_id": "container", "drill": None}]
        old = deepcopy((document, parsed))
        review, patch = run(document, parsed, record, mapping)
        self.assertTrue(review["can_apply"], review["issues"])
        changed, _, _, _ = apply_command(document, {"command_id": str(uuid4()), "type": COMMAND, "payload": patch}, document["revision_id"])
        self.assertEqual(changed["pcb"]["footprints"], [])
        bindings = changed["pcb"]["imports"][0]["bindings"]
        self.assertTrue(any(row["source_object_id"].endswith(":container") and row["collection"] == "geometry" for row in bindings))
        self.assertEqual((document, parsed), old)

    def test_four_copper_through_via_endpoints_and_blind_rejection(self):
        """! @brief 두 끝층의 실제 관통 의미를 보존하고 부분 적층은 추정하지 않는다."""
        document, parsed, record, mapping = fixture()
        first = document["stackup"][0]
        for index in range(1, 4):
            layer = deepcopy(first)
            layer.update(id=str(uuid4()), name="도체 " + str(index), order=index+1, z_min=quantity(1.1 + index*.1, "mm"))
            document["stackup"].append(layer)
        copper = [row for row in sorted(document["stackup"], key=lambda row: row["order"]) if row["role"] == "conductor"]
        mapping["layers"].append({"source": "B.Cu", "target": copper[-1]["id"]})
        data = parsed["records"][0]["data"]
        data["shapes"] = [{"id": "through", "kind": "via", "net_code": 1, "net_name": "파일넷", "center_mm": [8, 8], "size_mm": 2, "finished_hole_diameter_mm": 1, "layers": ["F.Cu", "B.Cu"]}]
        review, patch = run(document, parsed, record, mapping)
        self.assertTrue(review["can_apply"], review["issues"])
        hole = next(row["replacement"]["value"] for row in patch["changes"] if row["collection"] == "pcb.holes")
        self.assertEqual(len(hole["plating"]["pad_ids"]), 4)
        self.assertIsNone(hole["plating"]["thickness"]["value_si"])
        self.assertIsNone(hole["tool_diameter"]["value_si"])
        mapping["layers"][-1]["target"] = copper[2]["id"]
        self.assertFalse(run(document, parsed, record, mapping)[0]["can_apply"])

    def test_actual_kicad_and_cam_cutouts_preserve_circle_polygon_and_inverse(self):
        """! @brief 실제 writer/reader를 통과한 두 내부 절삭을 새 typed 원문으로 연결한다."""
        from rfad.adapters.exchange import kicad_writer, kicad_reader, cam_writer, cam_reader
        from test_pcb_exchange_formats import fixture as projection_fixture
        projection = projection_fixture()
        projection["board"].update(width_mm=60., height_mm=40.)
        projection["shapes"] = []
        projection["mechanical"]["cutouts"] = [{"id": str(uuid4()), "shape": {"kind": "circle", "center_mm": [10., 10.], "diameter_mm": 2.}, "surface_cut_ids": []}, {"id": str(uuid4()), "shape": {"kind": "polygon", "outer_mm": [[20., 20.], [23., 20.], [23., 22.], [20., 22.]], "holes_mm": []}, "surface_cut_ids": []}]
        before = deepcopy(projection)
        readers = [("board.kicad_pcb", kicad_reader.read(kicad_writer.write_board(projection))), ("outline.gbr", cam_reader.read_gerber(cam_writer.outline(projection)))]
        for name, data in readers:
            with self.subTest(format=name):
                document, parsed, record, mapping = fixture()
                parsed["records"] = [{"path": name, "data": data}]
                review, patch = run(document, parsed, record, mapping)
                self.assertTrue(review["can_apply"], review["issues"])
                changed, _, _, inverse = apply_command(document, {"command_id": str(uuid4()), "type": COMMAND, "payload": patch}, document["revision_id"])
                self.assertEqual({row["shape"]["kind"] for row in changed["board"]["cutouts"]}, {"circle", "polygon"})
                self.assertTrue(all(row["origin"]["import_id"] == record["id"] and row["source_refs"] for row in changed["board"]["cutouts"]))
                restored, _, _, _ = apply_command(changed, {"command_id": str(uuid4()), **inverse}, changed["revision_id"])
                self.assertNotIn("cutouts", restored["board"])
                self.assertNotIn("pcb", restored)
                self.assertFalse(run(changed, parsed, raw_record(changed), mapping)[0]["can_apply"])
        self.assertEqual(projection, before)

    def test_cutout_open_tangent_intersect_and_nested_are_blocked(self):
        """! @brief 기판/절삭 경계의 열린 선과 애매한 귀속을 자동 치유하지 않는다."""
        for extras in ([{"kind": "line", "start_mm": [2, 2], "end_mm": [3, 3]}], [{"kind": "circle", "center_mm": [1, 5], "radius_mm": 1}], [{"kind": "circle", "center_mm": [10, 10], "radius_mm": 2}, {"kind": "circle", "center_mm": [12, 10], "radius_mm": 2}], [{"kind": "circle", "center_mm": [10, 10], "radius_mm": 2}, {"kind": "circle", "center_mm": [10, 10], "radius_mm": 1}]):
            document, parsed, record, mapping = fixture()
            parsed["records"][0]["data"]["edges"].extend(extras)
            before = deepcopy(document)
            self.assertFalse(run(document, parsed, record, mapping)[0]["can_apply"])
            self.assertEqual(document, before)

    def test_actual_negative_mask_and_positive_paste_are_explicit_apertures(self):
        """! @brief 파일 음극성 mask와 객체 clear 연산을 구분하고 Paste 역할을 보존한다."""
        from rfad.adapters.exchange import cam_writer, cam_reader
        from rfad.application.pcb_import_mapping import import_sources
        from rfad.domain.pcb_features import empty_pcb
        from test_pcb_exchange_formats import fixture as projection_fixture
        document, parsed, record, mapping = fixture()
        document["pcb"] = empty_pcb()
        projection = projection_fixture()
        parsed["records"], mapping["layers"] = [], []
        for role, side in (("solder_mask", "top"), ("solder_paste", "bottom")):
            layer = api.new_record(document, "artwork_layer")
            layer.update(id=str(uuid4()), role=role, side=side, use_state="used")
            document["pcb"]["artwork_layers"].append(layer)
            source_layer = {"id": layer["id"], "name": role, "role": role, "side": side, "use_state": "used"}
            projection["artwork_layers"].append(source_layer)
            projection["apertures"].append({"id": str(uuid4()), "artwork_layer_id": layer["id"], "shape": {"kind": "circle", "center_mm": [5., 5.], "diameter_mm": 2.}})
            path = role + ".gbr"
            parsed["records"].append({"path": path, "data": cam_reader.read_gerber(cam_writer.gerber(projection, source_layer)[0])})
            mapping["layers"].append({"source": path, "target": layer["id"]})
        document["pcb"]["artwork_layers"].sort(key=lambda row: row["id"])
        self.assertEqual({row["role"] for row in import_sources(parsed)["layers"]}, {"solder_mask", "solder_paste"})
        review, patch = run(document, parsed, record, mapping)
        self.assertTrue(review["can_apply"], review["issues"])
        self.assertEqual(sum(row["collection"] == "pcb.apertures" for row in patch["changes"]), 2)
        parsed["records"][0]["data"]["objects"][0]["polarity"] = "clear"
        self.assertFalse(run(document, parsed, record, mapping)[0]["can_apply"])

    def test_raw_forty_files_and_report_bound_and_oversize_reject(self):
        document,parsed,record,mapping=fixture()
        record["source_files"]=[{"uri":f"projects/import-test/raw/{index}.gbr","sha256":"a"*64,"bytes":1} for index in range(40)]
        review,patch=run(document,parsed,record,mapping)
        self.assertTrue(review["can_apply"],review["issues"])
        record["source_files"].append({"uri":"projects/import-test/raw/extra.gbr","sha256":"b"*64,"bytes":1})
        self.assertFalse(run(document,parsed,record,mapping)[0]["can_apply"])
        record["source_files"].pop()
        record["source_files"][0]["bytes"]=16*1024*1024
        self.assertFalse(run(document,parsed,record,mapping)[0]["can_apply"])


if __name__ == "__main__":
    unittest.main()
