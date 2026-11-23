"""! @brief IPC-2581C와 ODB++ 실장의 참조 번호, 면, 각도와 위치를 실제 KiCad 배치표에서 확인한다."""
from copy import deepcopy
import csv
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.adapters.exchange import pcb_verification
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


def positions(folder, label, raw):
    """! @brief KiCad 자체 배치표의 위쪽 기준 mm와 deg를 직접 읽는다."""
    source, output = folder / (label + ".kicad_pcb"), folder / (label + ".csv")
    source.write_bytes(raw)
    subprocess.run([str(Path(KICAD) / "kicad-cli.exe"), "pcb", "export", "pos", "--format", "csv", "--units", "mm",
                    "--output", str(output), str(source)], capture_output=True, check=True, timeout=90)
    with output.open(encoding="utf-8", newline="") as stream:
        return {r["Ref"]: (r["Side"], float(r["PosX"]), float(r["PosY"]), float(r["Rot"])) for r in csv.DictReader(stream)}


@unittest.skipUnless(KICAD, "원문 작성 및 독립 배치표 검증에 KiCad가 필요합니다.")
class ManufacturingPlacementTests(unittest.TestCase):
    """! @brief 배치만 채택하거나 실제 단자를 함께 반영한 경우의 각 원본과 변경 이력을 검증한다."""

    def test_both_sides_and_position_only(self):
        """! @brief 명시한 두 실장을 두 제조 원본에서 수신하고 양방향 제조 재출력과 배치표를 대조한다."""
        initial = ifa_document()
        net = initial["nets"][0]
        base = write_board(exchange_projection(initial, snapshot_for(initial))).decode().rstrip()[:-1]
        expected = {"R17": ("top",12.,23.,30.), "U4": ("bottom",32.,18.,-45.)}
        for designator, (side, x, y, angle) in expected.items():
            face = "F" if side == "top" else "B"
            value = "10k" if side == "top" else "sense"
            base += (f'(footprint "{designator}_package" (layer "{face}.Cu") (at {x} {-y} {angle}) (attr smd) '
                     f'(property "Reference" "{designator}" (at 0 0) (layer "{face}.Fab")) '
                     f'(property "Value" "{value}" (at 0 0) (layer "{face}.Fab")) '
                     f'(pad "1" smd circle (at 0.7 0) (size 1.4 1.4) (layers "{face}.Cu") '
                     f'(net 1 "{net["name"]}")))\n')
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            original = (base + ")").encode("utf-8")
            independent = positions(folder, "source", original)
            self.assertEqual(independent, expected)
            sources = export_files(folder, "external", original)
            for key, data in sources.items():
                self.assertEqual({r["reference"] for r in data["editable_components"]}, set(expected))
                for include_pads in (False, True):
                    with self.subTest(format=key, include_pads=include_pads):
                        filename = "external." + FORMATS[key][1]
                        raw = (folder / filename).read_bytes()
                        digest = sha256(raw).hexdigest()
                        record = raw_record(initial)
                        record.update(format=key)
                        record["source_files"][0].update(sha256=digest, bytes=len(raw))
                        parsed = {"schema": "rfad.pcb-parse/0.1", "format": key, "records": [{"path": filename, "data": data}],
                                  "raw_preservation_required": True, "losses": data["losses"]}
                        options = import_sources(parsed)
                        self.assertEqual(options["component_count"], 2)
                        mapping = {"board_id": initial["board"]["id"], "frame_id": initial["board"]["frame_id"],
                                   "layers": [], "nets": [], "placement": None, "include_components": True,
                                   "include_contacts": include_pads}
                        if include_pads:
                            mapping["layers"] = [{"source": row["source"], "target": initial["stackup"]
                                                  [-1 if row["source"].casefold() == "f.cu" else 0]["id"]} for row in options["layers"]]
                            mapping["nets"] = [{"source": row["source"], "target": net["id"]} for row in options["nets"]]
                        accepted = [canonical_hash(r) for r in data["losses"]]
                        preview, patch = run(initial, parsed, record, mapping, accepted)
                        self.assertTrue(preview["can_apply"], preview["issues"])
                        changed, _, _, inverse = apply_command(initial, {"command_id": str(uuid4()), "type": COMMAND,
                                                                        "payload": patch}, initial["revision_id"])
                        folder.joinpath("model.json").write_text(json.dumps(changed), "utf-8")
                        reopened = json.loads(folder.joinpath("model.json").read_bytes())
                        self.assertEqual(len(reopened["pcb"]["footprints"]), 2)
                        for footprint in reopened["pcb"]["footprints"]:
                            self.assertIsNone(footprint["placement_envelope"])
                            self.assertIsNone(footprint["library_id"])
                            self.assertEqual(len(footprint["members"]), int(include_pads))
                            if include_pads:
                                self.assertEqual([pin["number"] for pin in footprint["pins"]], ["1"])
                        wrong = deepcopy(reopened)
                        wrong["pcb"]["footprints"][0]["placement"]["side"] = "bottom" if wrong["pcb"]["footprints"][0]["placement"]["side"] == "top" else "top"
                        new_record = {**record, "id": str(uuid4())}
                        blocked, _ = run(wrong, parsed, new_record, mapping, accepted)
                        self.assertFalse(blocked["can_apply"])
                        repeat, _ = run(reopened, parsed, new_record, mapping, accepted)
                        self.assertTrue(repeat["can_apply"], repeat["issues"])
                        result = exchange_projection(reopened, snapshot_for(reopened), kicad_board=True)
                        board = write_board(result)
                        pcb_verification.kicad(board, result, "kicad_pcb", {})
                        if include_pads and os.environ.get("RFAD_EXCHANGE_PYTHON"):
                            import test_manufacturing_contacts as contacts
                            board = contacts.ManufacturingContactsTests.apply_service(
                                self, folder, initial, {"mapping": mapping}, key, raw)
                        actual = positions(folder, key + str(include_pads), board)
                        self.assertEqual({ref: actual[ref] for ref in expected}, expected)
                        if include_pads:
                            original_pads = {v["source_id"]: v for v in data["editable_pads"]}
                            original_xy = {c["reference"]: original_pads[c["pins"][0]["source_id"]]["center_mm"]
                                           for c in data["editable_components"]}
                            for out in export_files(folder, key, board).values():
                                by_ref = {v["reference"]: v for v in out["editable_components"]}
                                self.assertEqual(set(by_ref), set(expected))
                                for ref, (side,x,y,angle) in expected.items():
                                    comp = by_ref[ref]
                                    self.assertEqual((comp["side"],*comp["origin_mm"]), (side,x,y))
                                    self.assertAlmostEqual(math.remainder(comp["rotation_deg"]-angle,360), 0.)
                                    self.assertEqual([p["number"] for p in comp["pins"]], ["1"])
                                    exported = next(p for p in out["editable_pads"] if p["source_id"] == comp["pins"][0]["source_id"])
                                    self.assertLess(math.dist(exported["center_mm"], original_xy[ref]), 3e-6)
                        restored, *_ = apply_command(reopened, {"command_id": str(uuid4()), **inverse}, reopened["revision_id"])
                        self.assertEqual(restored["geometry"], initial["geometry"])
                        self.assertEqual(restored.get("pcb"), initial.get("pcb"))
                        self.assertEqual(digest, sha256((folder / filename).read_bytes()).hexdigest())
