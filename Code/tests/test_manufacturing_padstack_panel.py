"""! @brief 외부 KiCad의 층별 랜드와 ODB++ 패널 배치의 원본 보존을 확인한다."""

from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4
from zipfile import ZipFile

from rfad.adapters.exchange import kicad_reader, odb_panel, odb_reader, pcb_verification
from rfad.adapters.exchange.kicad_writer import write_board
from rfad.adapters.exchange.manufacturing_contacts import _odb_pads
from rfad.adapters.exchange.manufacturing_export import verify_padstacks
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_exchange_projection import exchange_projection
from rfad.application.pcb_import_mapping import import_sources
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_features import COMMAND
from rfad.domain.project import apply_command
from test_cad_projection import snapshot_for
from test_manufacturing_contacts import KICAD, FORMATS, ManufacturingContactsTests, export_files
from test_pcb_ifa import ifa_document
from test_pcb_import_mapping import raw_record, run


KICAD_SCRIPT = """
import json
import sys
import pcbnew as p
b=p.LoadBoard(sys.argv[1])
if len(sys.argv)==4:
    f=p.FOOTPRINT(b)
    f.SetReference("J9")
    f.SetPosition(p.VECTOR2I(p.FromMM(17),p.FromMM(-18)))
    b.Add(f)
    pad=p.PAD(f)
    pad.SetNumber("1")
    pad.SetAttribute(p.PAD_ATTRIB_PTH)
    pad.SetPosition(f.GetPosition())
    pad.SetDrillSize(p.VECTOR2I(p.FromMM(.6),p.FromMM(.6)))
    pad.SetOrientationDegrees(30)
    pad.SetLayerSet(p.LSET.AllCuMask(2))
    pad.SetNetCode(int(sys.argv[3]))
    s=pad.Padstack()
    s.SetMode(p.PADSTACK.MODE_CUSTOM)
    for layer,shape,x,y in ((p.F_Cu,p.PAD_SHAPE_RECT,1.8,1.1),(p.B_Cu,p.PAD_SHAPE_CIRCLE,1.4,1.4)):
        s.SetSize(p.VECTOR2I(p.FromMM(x),p.FromMM(y)),layer)
        s.SetShape(shape,layer)
    f.Add(pad)
    p.SaveBoard(sys.argv[2],b)
    b=p.LoadBoard(sys.argv[2])
pad,= [pad for f in b.GetFootprints() for pad in f.Pads() if pad.GetAttribute()==p.PAD_ATTRIB_PTH and pad.GetPosition().x==p.FromMM(17)]
assert pad.GetShape(p.F_Cu) == p.PAD_SHAPE_RECT
assert pad.GetShape(p.B_Cu) == p.PAD_SHAPE_CIRCLE
print(json.dumps([pad.GetSize(p.F_Cu).x, pad.GetSize(p.F_Cu).y, pad.GetSize(p.B_Cu).x,
                  pad.GetDrillSize().x, pad.GetOrientationDegrees(), pad.GetNetname()]))
"""


class PanelHeaderTests(unittest.TestCase):
    def test_centered_rectangle_mirrors_after_rotation(self):
        """! @brief ODB++의 X 반사가 회전각의 부호를 뒤집는지 확인한다."""
        text = "UNITS=MM\n$0 rect1800x1100\nP 17 18 0 P 0 8 330\nP 17 18 0 P 0 9 330\n"
        first, second = [shape for _, _, shape in _odb_pads(text)]
        self.assertEqual(first["rotation_deg"], 30)
        self.assertEqual(second["rotation_deg"], -30)

    def test_documented_units_and_rotation_values(self):
        """! @brief 단위환산, 반복 개수, 뒤집기와 반사를 원문 그대로 확인한다."""
        header = ("UNITS=INCH\nX_DATUM=0\nY_DATUM=1\nSTEP-REPEAT {\n"
                  "NAME=TOP\nX=2\nY=3\nDX=4\nDY=5\nNX=3\nNY=2\nANGLE=90\nFLIP=YES\nMIRROR=NO\n}")
        datum, [info] = odb_panel.header(header)
        self.assertEqual(datum, [0, 25.4])
        self.assertEqual(info["origin_mm"], [50.8, 3*25.4])
        self.assertEqual(info["count"], [3, 2])
        self.assertEqual((info["angle_deg"], info["flip"], info["mirror"]), (90, True, False))
        with self.assertRaises(ProjectError):
            odb_panel.header(header.replace("NX=3", "NX=3\nNX=7"))


@unittest.skipUnless(KICAD, "독립 생성 및 수신에 KiCad가 필요합니다.")
class ManufacturingPadstackPanelTests(unittest.TestCase):
    def test_kicad_odb_and_panel(self):
        """! @brief 실제 층별 패드와 보드 패널의 독립 왕복, 원문과 PCB 개정을 대조한다."""
        before = ifa_document()
        net, = before["nets"]
        layers = [row for row in sorted(before["stackup"], key=lambda row: row["order"]) if row["role"] == "conductor"]
        with TemporaryDirectory() as folder:
            root = Path(folder)
            board_before, source = root / "before.kicad_pcb", root / "origin.kicad_pcb"
            executable = Path(KICAD)
            board_before.write_bytes(write_board(exchange_projection(before, snapshot_for(before), kicad_board=True)))
            net_code = next(row["code"] for row in kicad_reader.read(board_before.read_bytes())["nets"] if row["name"] == net["name"])
            command = [str(executable / "python.exe"), "-c", KICAD_SCRIPT]
            args = [str(board_before), str(source), str(net_code)]
            def receive(arguments):
                """! @brief 실제 수신 오류는 KiCad 진단 원문으로 확인한다."""
                result = subprocess.run(command + arguments, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf8", "replace"))
                return json.loads(result.stdout)

            native = receive(args)
            self.assertEqual(native, [1800000, 1100000, 1400000, 600000, 30, net["name"]])
            sources = export_files(root, "origin", source.read_bytes())
            raw = (root / "origin.zip").read_bytes()
            odb = sources["odbpp_zip"]
            before_board = kicad_reader.read(source.read_bytes())
            verify_padstacks(before_board, odb, "odb")
            with self.assertRaisesRegex(ValueError, "ipc2581"):
                verify_padstacks(before_board, sources["ipc2581_revc"], "ipc2581")
            raw_source = {"schema": "rfad.pcb-parse/0.1", "format": "odbpp_zip",
                          "records": [{"path": "board." + FORMATS["odbpp_zip"][1], "data": odb}],
                          "mapping": [], "losses": odb["losses"], "raw_preservation_required": True}
            record = raw_record(before)
            record["format"] = "odbpp_zip"
            available = import_sources(raw_source)
            mapping = {"board_id": before["board"]["id"], "frame_id": before["board"]["frame_id"],
                       "layers": [{"source": row["source"], "target": layers[int(row["source"].casefold()=="f.cu")]["id"]}
                                  for row in available["layers"]],
                       "nets": [{"source": row["source"], "target": net["id"]} for row in available["nets"]],
                       "placement": None, "include_contacts": True}
            review, payload = run(before, raw_source, record, mapping, [canonical_hash(row) for row in odb["losses"]])
            self.assertTrue(review["can_apply"], review["issues"])
            after, *_, undo = apply_command(before, {"command_id": str(uuid4()), "type": COMMAND, "payload": payload},
                                          before["revision_id"])
            after = json.loads(json.dumps(after))
            reverted, *_ = apply_command(after, {"command_id": str(uuid4()), **undo}, after["revision_id"])
            for key in ("geometry", "ports", "connections", "pcb"):
                self.assertEqual(before.get(key), reverted.get(key))
            projection = exchange_projection(after, snapshot_for(after), kicad_board=True)
            regenerated = write_board(projection)
            pcb_verification.kicad(regenerated, projection, "kicad_pcb", {})
            (root / "finished.kicad_pcb").write_bytes(regenerated)
            observed = receive([str(root / "finished.kicad_pcb")])
            self.assertEqual(observed, native)
            if os.environ.get("RFAD_EXCHANGE_PYTHON"):
                board = ManufacturingContactsTests.apply_service(self, root, before, {"mapping": mapping}, "odbpp_zip", raw)
                verify_padstacks(before_board, export_files(root, "service-export", board)["odbpp_zip"], "odb")
            revised = export_files(root, "finished-export", regenerated)
            verify_padstacks(before_board, revised["odbpp_zip"], "odb")
            panel_raw = odb_panel.build(raw, [2, 3], [45, 65], 3)
            self.assertEqual(panel_raw, odb_panel.build(raw, [2, 3], [45, 65], 3))
            summary = odb_reader.read(panel_raw)
            repeat, = summary["panels"][0]["repeats"]
            self.assertEqual(repeat["count"], [2, 3])
            self.assertEqual(repeat["pitch_mm"], [45, 65])
            self.assertIsNone(summary["editable_profile"])
            with ZipFile(BytesIO(raw)) as original, ZipFile(BytesIO(panel_raw)) as panel:
                for path in original.namelist():
                    if path != "matrix/matrix":
                        self.assertEqual(original.read(path), panel.read(path))
                self.assertEqual(panel.testzip(), None)
                outline = panel.read("steps/tw_panel/profile").decode()
                self.assertIn("OS 91 196", outline)
                self.assertIn("NAME=PCB", panel.read("steps/tw_panel/stephdr").decode())
            invalid = BytesIO()
            with ZipFile(BytesIO(panel_raw)) as archive, ZipFile(invalid, "w") as writer:
                for path in archive.namelist():
                    data = archive.read(path)
                    writer.writestr(path, data.replace(b"NAME=PCB", b"NAME=TW_PANEL") if path.endswith("/tw_panel/stephdr") else data)
            rejected = odb_reader.read(invalid.getvalue())
            self.assertEqual(rejected["panels"], [])
            self.assertEqual(rejected["panel_exclusions"][0]["code"], "E_UNSUPPORTED")
            self.assertIsNone(rejected["editable_profile"])
            with self.assertRaises(ProjectError):
                odb_panel.build(raw, [2, 3], [39, 65], 3)
