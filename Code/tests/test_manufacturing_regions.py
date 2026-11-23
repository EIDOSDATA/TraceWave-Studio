"""! @brief KiCad가 작성한 두 층의 채움 동박을 제조 원본에서 적용하고 다시 KiCad로 검수한다."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from rfad.adapters.exchange import ipc2581_reader, manufacturing_regions, pcb_verification
from rfad.adapters.exchange.kicad_writer import write_board
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_exchange_projection import exchange_projection
from rfad.application.pcb_import_mapping import import_sources
from rfad.domain.pcb_features import COMMAND
from rfad.domain.project import apply_command
from test_cad_projection import snapshot_for
from test_manufacturing_contacts import FORMATS, KICAD, export_files
from test_pcb_ifa import ifa_document
from test_pcb_import_mapping import raw_record, run


KICAD_NATIVE = """
import json, pcbnew as k, sys
b = k.LoadBoard(sys.argv[1])
if len(sys.argv) == 3:
    def rectangle(x1,y1,x2,y2):
        c = k.SHAPE_LINE_CHAIN()
        for x,y in [(x1,y1),(x2,y1),(x2,y2),(x1,y2)]:
            c.Append(k.VECTOR2I(k.FromMM(x),k.FromMM(-y)))
        c.SetClosed(True)
        return c
    z = k.ZONE(b)
    z.SetLayer(k.B_Cu)
    z.SetNetCode(list(b.Zones())[0].GetNetCode())
    z.SetZoneName("Receiver-copper")
    z.SetMinThickness(k.FromMM(.001))
    z.Outline().AddOutline(rectangle(5,6,25,21))
    z.Outline().AddHole(rectangle(9,10,13,14),0)
    filled = k.SHAPE_POLY_SET()
    for box in [(5,6,25,10),(5,14,25,21),(5,10,9,14),(13,10,25,14)]:
        filled.AddOutline(rectangle(*box))
    z.SetFilledPolysList(k.B_Cu, filled)
    z.SetIsFilled(True)
    z.SetNeedRefill(False)
    b.Add(z)
    k.SaveBoard(sys.argv[2], b)
    b = k.LoadBoard(sys.argv[2])
def xy(chain):
    return sorted([round(chain.CPoint(i).x/1e6,6), round(-chain.CPoint(i).y/1e6,6)] for i in range(chain.PointCount()))
rows=[]
for z in b.Zones():
    o=z.Outline()
    assert o.OutlineCount()==1
    rows.append(dict(layer=b.GetLayerName(z.GetLayer()),net=z.GetNetname(),outer=xy(o.COutline(0)),
                     holes=[xy(o.CHole(0,i)) for i in range(o.HoleCount(0))],
                     area=round(z.GetFilledPolysList(z.GetLayer()).Area()/1e12,6)))
print(json.dumps(sorted(rows,key=lambda r:r["layer"])))
"""


def native(source, destination=None):
    """! @brief 제품 parser와 독립인 수신 KiCad Python으로 파일의 실제 채움 면적과 고리를 읽는다."""
    args = [str(Path(KICAD) / "python.exe"), "-c", KICAD_NATIVE, str(source)]
    if destination is not None:
        args.append(str(destination))
    result = subprocess.run(args, capture_output=True, timeout=90)
    if result.returncode:
        raise AssertionError(result.stderr.decode("utf-8", "replace"))
    return json.loads(result.stdout)


def corners(x1, y1, x2, y2):
    """! @brief 독립 시험의 직사각형 정의에서 기대하는 네 꼭짓점을 만든다."""
    return sorted([[x1,y1], [x2,y1], [x2,y2], [x1,y2]])


class RegionParsingTests(unittest.TestCase):
    """! @brief 명시한 IPC 구멍과 단위를 유지하고 불분명한 배치 또는 극성을 제외한다."""

    def test_direct_cutout_and_rejections(self):
        """! @brief 인치 원문 외곽과 구멍을 확인하고 보간 곡선/음극성/미정 넷을 채움으로 단정하지 않는다."""
        ns = ipc2581_reader.NS
        step = ET.Element(ns + "Step")
        layer = ET.Element(ns + "Layer", name="L", layerFunction="CONDUCTOR", polarity="POSITIVE")
        feature = ET.SubElement(step, ns + "LayerFeature", layerRef="L")
        group = ET.SubElement(feature, ns + "Set", net="RF")
        special = ET.SubElement(ET.SubElement(group, ns + "Features"), ns + "UserSpecial")
        contour = ET.SubElement(special, ns + "Contour")
        for tag, size in (("Polygon", 1.), ("Cutout", .25)):
            ring = ET.SubElement(contour, ns + tag)
            for i,(x,y) in enumerate([(-size,-size),(size,-size),(size,size),(-size,size),(-size,-size)]):
                ET.SubElement(ring, ns + ("PolyBegin" if i == 0 else "PolyStepSegment"), x=str(x), y=str(y))
        read = lambda: manufacturing_regions.ipc(step, [layer], Decimal("25.4"), ns)
        areas, excluded = read()
        self.assertFalse(excluded)
        self.assertAlmostEqual(areas[0]["area_mm2"], (4-.25) * 25.4**2)
        self.assertEqual(len(areas[0]["holes_mm"]), 1)
        for key, value in (("polarity", "NEGATIVE"), ("net", "")):
            original = dict(group.attrib)
            group.set(key, value)
            omitted = read()
            self.assertEqual(omitted[0], [])
            self.assertTrue(omitted[1][0]["reason"])
            group.attrib.clear()
            group.attrib.update(original)
        contour[0][1].tag = ns + "PolyStepCurve"
        self.assertTrue(read()[1])


    def test_odb_surface_cutout_and_feature_numbers(self):
        """! @brief 실패한 앞 표면이 뒤 표면의 FID 번호를 움직이지 않고 음극성은 층 전체에서 제외한다."""
        matrix = "LAYER {\nNAME=top\nCONTEXT=BOARD\nTYPE=SIGNAL\nPOLARITY=POSITIVE\n}"
        eda = "LYR top\nNET N\nSNT PLN S E 0\nFID C 0 0\nFID C 0 1\n"
        features = ("UNITS=INCH\nS P 0\nOB 0 0 I\nOS 0 1\n"
                    "S P 0\nOB 0 0 I\nOS 1 0\nOS 1 1\nOS 0 1\nOS 0 0\nOE\n"
                    "OB .2 .2 H\nOS .2 .4\nOS .4 .4\nOS .4 .2\nOS .2 .2\nOE\nSE\n")
        def parse(body, links, layer_matrix=matrix):
            """! @brief 메모리 제조 자료에 실제 matrix, EDA 및 층 특성 멤버를 작성한다."""
            stream = BytesIO()
            with ZipFile(stream, "w") as archive:
                archive.writestr("step/eda/data", links)
                archive.writestr("step/layers/top/features", body)
            with ZipFile(stream) as archive:
                return manufacturing_regions.odb(archive, set(archive.namelist()), "step/", layer_matrix)
        areas, excluded = parse(features, eda)
        self.assertEqual(len(excluded), 1)
        self.assertEqual(areas[0]["source_features"], ["region:top:1"])
        self.assertAlmostEqual(areas[0]["area_mm2"], .96 * 25.4**2)
        self.assertEqual(len(areas[0]["holes_mm"]), 1)
        self.assertFalse(parse(features + "P 0 0 0 N 0\n", eda)[0])
        self.assertFalse(parse(features, eda + "NET OTHER\nSNT TRC\nFID C 0 1\n")[0])
        self.assertFalse(parse(features, eda, matrix + "\n" + matrix)[0])


@unittest.skipUnless(KICAD, "수신 KiCad의 pcbnew와 제조 내보내기가 필요합니다.")
class ManufacturingRegionTests(unittest.TestCase):
    """! @brief 두 제조 형식을 실제 보드에 반영하고 수신자의 넷, 면적, 경계와 구멍을 대조한다."""

    def test_independent_copper_holes_and_cross_export(self):
        """! @brief 원본 삼각/사각 채움을 조립해 기존 윗면과 새 아랫면 동박을 보존한다."""
        import test_manufacturing_contacts as contacts
        initial = ifa_document()
        net = initial["nets"][0]
        layers = sorted((r for r in initial["stackup"] if r["role"] == "conductor"), key=lambda r:r["order"])
        targets = {"f.cu":layers[-1]["id"], "b.cu":layers[0]["id"]}
        expected = [{"layer":"B.Cu","net":net["name"],"outer":corners(5,6,25,21),
                     "holes":[corners(9,10,13,14)],"area":284.},
                    {"layer":"F.Cu","net":net["name"],"outer":corners(0,0,40,50),
                     "holes":[corners(30,10,34,14)],"area":1984.}]
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            base, supplied = folder/"initial.kicad_pcb", folder/"supplied.kicad_pcb"
            base.write_bytes(write_board(exchange_projection(initial, snapshot_for(initial))))
            self.assertEqual(native(base, supplied), expected)
            for key, data in export_files(folder, "external", supplied.read_bytes()).items():
                with self.subTest(format=key):
                    filename = "external." + FORMATS[key][1]
                    raw = (folder/filename).read_bytes()
                    record = raw_record(initial)
                    record["format"] = key
                    record["source_files"][0].update(sha256=sha256(raw).hexdigest(), bytes=len(raw))
                    parsed = {"schema":"rfad.pcb-parse/0.1","format":key,"records":[{"path":filename,"data":data}],
                              "raw_preservation_required":True,"losses":data["losses"]}
                    sources = import_sources(parsed)
                    self.assertEqual(sources["region_count"], 2)
                    self.assertFalse(data["region_exclusions"])
                    mapping = {"board_id":initial["board"]["id"],"frame_id":initial["board"]["frame_id"],"placement":None,
                               "include_regions":True,"layers":[{"source":r["source"],"target":targets[r["source"].casefold()]}
                               for r in sources["layers"] if not r.get("contacts_only") or r.get("regions_only")],
                               "nets":[{"source":r["source"],"target":net["id"]} for r in sources["nets"]
                                       if not r.get("contacts_only") or r.get("regions_only")]}
                    acknowledged = [canonical_hash(row) for row in data["losses"]]
                    review, patch = run(initial,parsed,record,mapping,acknowledged)
                    self.assertTrue(review["can_apply"], review["issues"])
                    changed, _, _, undo = apply_command(initial, {"command_id":str(uuid4()),"type":COMMAND,"payload":patch},initial["revision_id"])
                    reopened = json.loads(json.dumps(changed))
                    restored, *_ = apply_command(reopened, {"command_id": str(uuid4()), **undo}, reopened["revision_id"])
                    self.assertEqual(restored["geometry"], initial["geometry"])
                    self.assertEqual(len(reopened["geometry"]), len(initial["geometry"]) + 1)
                    area = next(r for r in reopened["geometry"] if r["kind"]=="planar_region" and r["layer_id"]==targets["b.cu"])
                    self.assertEqual((len(area["holes"]),area["net_id"]),(1,net["id"]))
                    next_record = {**record,"id":str(uuid4())}
                    repeated, another = run(reopened,parsed,next_record,mapping,acknowledged)
                    self.assertTrue(repeated["can_apply"],repeated["issues"])
                    repeated_doc, *_ = apply_command(reopened,{"command_id":str(uuid4()),"type":COMMAND,"payload":another},reopened["revision_id"])
                    self.assertEqual(reopened["geometry"], repeated_doc["geometry"])
                    incompatible = deepcopy(reopened)
                    next(r for r in incompatible["geometry"] if r["id"]==area["id"])["holes"].clear()
                    blocked, _ = run(incompatible,parsed,next_record,mapping,acknowledged)
                    self.assertFalse(blocked["can_apply"])
                    projected = exchange_projection(reopened,snapshot_for(reopened),kicad_board=True)
                    board = write_board(projected)
                    pcb_verification.kicad(board,projected,"kicad_pcb",{})
                    if os.environ.get("RFAD_EXCHANGE_PYTHON"):
                        board = contacts.ManufacturingContactsTests.apply_service(self,folder,initial,{"mapping":mapping},key,raw)
                    final = folder/(key + ".kicad_pcb")
                    final.write_bytes(board)
                    self.assertEqual(native(final),expected)
                    for fmt, answer in export_files(folder, key, board).items():
                        with self.subTest(output=fmt):
                            metal = sorted(answer["editable_regions"],key=lambda a:a["layer"].casefold())
                            self.assertEqual(len(metal), 2)
                            for actual, wanted in zip(metal, expected):
                                self.assertEqual(actual["layer"].casefold(), wanted["layer"].casefold())
                                self.assertEqual(actual["net"], net["name"] if fmt=="ipc2581_revc" else net["name"].replace(" ","_"))
                                self.assertAlmostEqual(actual["area_mm2"],wanted["area"])
                                self.assertEqual(sorted(actual["outer_mm"]),wanted["outer"])
                                self.assertEqual([sorted(h) for h in actual["holes_mm"]],wanted["holes"])
