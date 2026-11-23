"""! @brief 독립 KiCad에서 생성한 도금/비도금 관통 홀, 원형 패드와 적층을 왕복한다."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from uuid import uuid4

from rfad.adapters.exchange import ipc2581_reader, odb_reader, pcb_verification
from rfad.adapters.exchange.kicad_writer import write_board
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_exchange_projection import exchange_projection, scalar
from rfad.application.pcb_import_mapping import import_sources
from rfad.domain.pcb_features import COMMAND
from rfad.domain.project import apply_command
from test_cad_projection import snapshot_for
from test_pcb_ifa import ifa_document
from test_pcb_import_mapping import raw_record, run
from test_pcb_solver import quantity


KICAD = os.environ.get("RFAD_TEST_KICAD")
FORMATS = {"ipc2581_revc": ("ipc2581", "xml", ipc2581_reader), "odbpp_zip": ("odb", "zip", odb_reader)}


def export_files(folder, label, board):
    """! @brief 같은 수신 보드를 공개 KiCad CLI에서 두 제조 형식으로 재출력한다."""
    source = folder / (label + ".kicad_pcb")
    source.write_bytes(board)
    files = {}
    for key, (format_name, suffix, reader) in FORMATS.items():
        output = folder / (label + "." + suffix)
        options = ["--version", "C"] if format_name == "ipc2581" else ["--compression", "zip"]
        cmd = [str(Path(KICAD) / "kicad-cli.exe"), "pcb", "export", format_name, "--units", "mm",
               "--precision", "6", *options, "--output", str(output), str(source)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=90)
        files[key] = reader.read(output.read_bytes())
    return files


@unittest.skipUnless(KICAD, "원본 생성과 독립 제조 재출력에 KiCad CLI가 필요합니다.")
class ManufacturingContactsTests(unittest.TestCase):
    """! @brief 서로 다른 넷 표기와 실제 원형 패드/홀 연결을 모델 편집부터 재출력까지 확인한다."""

    def check_data(self, data, net):
        """! @brief 시험 위치/지름/바깥 구리층과 실제 서브넷만 대조한다."""
        pads = {(p["layer"].casefold(), tuple(p["center_mm"])): p for p in data["editable_pads"]}
        original = pads.pop(("f.cu", (9, 53)))
        self.assertEqual(original["pad_shape"], "rectangle")
        self.assertEqual(original["rotation_deg"], 0)
        self.assertEqual(set(pads), {("f.cu", (17,18)), ("b.cu", (17,18)), ("f.cu", (27,24))})
        for (_, xy), pad in pads.items():
            self.assertAlmostEqual(pad["diameter_mm"], 1.8 if xy == (17,18) else 1.4)
            self.assertEqual(pad["net"].replace("_", " "), net)
        holes = {tuple(h["center_mm"]): h for h in data["editable_holes"]}
        self.assertEqual(set(holes), {(17,18), (23,21)})
        plated, plain = holes[(17,18)], holes[(23,21)]
        self.assertEqual((plated["plating"], plated["diameter_mm"]), ("plated", .6))
        self.assertEqual(plated["net"].replace("_", " "), net)
        self.assertEqual(set(plated["pads"]), {p["source_id"] for (_, xy), p in pads.items() if xy == (17,18)})
        self.assertEqual((plain["plating"], plain["diameter_mm"], plain["pads"]), ("unplated", 1.1, []))
        self.assertEqual([v["thickness_mm"] for v in data["editable_stack"]], [.035, .93, .035])

    def apply_service(self, folder, document, data, key, raw):
        """! @brief 실제 봉인 원문을 GUI의 서비스 경로로 등록하고 게시한 원본 해시를 확인한다."""
        from rfad.application.exchange_runtime import ExchangeRuntime
        from rfad.application.pcb_import_service import read as read_original
        from rfad.application.projects import ProjectService
        from test_cad_worker_process import register_fixture, request
        from test_pcb_import_service import begin, upload
        import test_manufacturing_exchange as exchange
        file_name = "external." + FORMATS[key][1]
        with ProjectService(folder / ("workspace-" + key), auto_run=False,
                            exchange_runtime=ExchangeRuntime(Path(os.environ["RFAD_EXCHANGE_PYTHON"]))) as service:
            original, _ = register_fixture(service, document)
            project = original["project_id"]
            endpoint = SimpleNamespace(service=service, request=lambda value: request(service, project, value))
            handle = begin(endpoint, raw, file_name, key)
            upload(endpoint, handle, raw, file_name)
            service.mutate("pcb.import.parse", endpoint.request({"upload_id": handle}))
            self.assertTrue(service.exchange.run_next())
            def read(method, value):
                """! @brief 동일 현재 프로젝트와 업로드에 묶인 조회를 사용한다."""
                return read_original(service, method, {"contract_version": "rfad.api/2.0", "context": {"project_id": project},
                                                       "input": value})
            record = read("pcb.import.get", {"upload_id": handle})
            args = {**data, "upload_id": handle, "expected_revision": original["revision_id"],
                    "acknowledged_losses": [canonical_hash(row) for row in record["parsed"]["losses"]],
                    "reason": "원형 패드 관통 홀 원문 채택"}
            review = read("pcb.import.preview", args)
            self.assertTrue(review["can_apply"], review.get("issues"))
            applied = service.mutate("pcb.import.apply", endpoint.request(
                {**args, "command_id": str(uuid4()), "review_hash": review["review_hash"]}))
            self.assertEqual(service.journal.read_artifact(record["result"]["source_files"][0]["artifact"]), raw)
            task = service.mutate("snapshot.create", endpoint.request(
                {"expected_revision": applied["new_revision"], "description": "제조 패드와 홀의 원본 재출력"}))
            self.assertTrue(service.run_next())
            snap = service.journal.read()["jobs"][task["job_id"]]["events"][-1]["operation_result"]
            published = exchange.ManufacturingExchangeTests.publish(self, service, project, snap, folder / ("published-" + key))
            return published["board.kicad_pcb"]

    def test_physical_contacts_and_stack_roundtrip(self):
        """! @brief 외부 원본 두 종류의 적용, 역명령, 재열기와 양방향 교차 재출력을 검증한다."""
        document = ifa_document()
        net = document["nets"][0]
        source = write_board(exchange_projection(document, snapshot_for(document))).decode().rstrip()[:-1]
        terminal = '(net "' + net["name"] + '")'
        source += ('(footprint "contacts" (layer "F.Cu") (at 0 0) (attr through_hole)'
                   '(pad "1" thru_hole circle (at 17 -18) (size 1.8 1.8) (drill 0.6) (layers "*.Cu" "*.Mask")'
                   + terminal + ') (pad "" np_thru_hole circle (at 23 -21) (size 1.1 1.1) (drill 1.1)'
                   ' (layers "*.Cu" "*.Mask")) (pad "2" smd circle (at 27 -24) (size 1.4 1.4) (layers "F.Cu")'
                   + terminal + ')))')
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            inputs = export_files(folder, "external", source.encode())
            before = deepcopy(document)
            bottom, core, top = before["stackup"]
            core["thickness"] = quantity(.83, "mm")
            top["z_min"] = quantity(scalar(document, document["stackup"][-1]["z_min"]) - .1, "mm")
            for key, data in inputs.items():
                with self.subTest(format=key):
                    self.check_data(data, net["name"])
                    parsed = {"schema": "rfad.pcb-parse/0.1", "format": key, "records": [{"path": "board." + FORMATS[key][1], "data": data}],
                              "mapping": [], "losses": data["losses"], "raw_preservation_required": True}
                    sources = import_sources(parsed)
                    record = raw_record(before)
                    record["format"] = key
                    mapping = {"board_id": before["board"]["id"], "frame_id": before["board"]["frame_id"],
                               "layers": [{"source": row["source"], "target": (top if row["source"].casefold() == "f.cu" else bottom)["id"]}
                                          for row in sources["layers"]], "nets": [{"source": row["source"], "target": net["id"]}
                                          for row in sources["nets"]], "placement": None, "adopt_stack": True, "include_contacts": True}
                    acknowledged = [canonical_hash(row) for row in parsed["losses"]]
                    wrong = deepcopy(mapping)
                    wrong["layers"][0]["target"] = wrong["layers"][1]["target"]
                    rejected, _ = run(before, parsed, record, wrong, acknowledged)
                    self.assertFalse(rejected["can_apply"])
                    review, patch = run(before, parsed, record, mapping, acknowledged)
                    self.assertTrue(review["can_apply"], review["issues"])
                    changed, _, _, undo = apply_command(before, {"command_id": str(uuid4()), "type": COMMAND,
                                                                  "payload": patch}, before["revision_id"])
                    restored, *_ = apply_command(changed, {"command_id": str(uuid4()), **undo}, changed["revision_id"])
                    for field in ("geometry", "materials", "stackup", "ports", "connections"):
                        self.assertEqual(restored[field], before[field])
                    saved = folder / (key + ".json")
                    saved.write_text(json.dumps(changed), "utf-8")
                    reopened = json.loads(saved.read_text("utf-8"))
                    self.assertEqual(reopened["materials"], before["materials"])
                    self.assertEqual(len(reopened["geometry"]), len(before["geometry"]) + 3)
                    for hole in reopened["pcb"]["holes"]:
                        self.assertIsNone(scalar(reopened, hole["tool_diameter"]))
                        self.assertIsNone(scalar(reopened, hole["plating"]["thickness"]))
                    projection = exchange_projection(reopened, snapshot_for(reopened), kicad_board=True)
                    board = write_board(projection)
                    pcb_verification.kicad(board, projection, "kicad_pcb", {})
                    if os.environ.get("RFAD_EXCHANGE_PYTHON"):
                        # @brief 전용 worker가 있으면 실제 게시 스냅샷의 독립 수신을 끝까지 검사한다.
                        raw = (folder / ("external." + FORMATS[key][1])).read_bytes()
                        board = self.apply_service(folder, before, {"mapping": mapping}, key, raw)
                    for output in export_files(folder, key, board).values():
                        self.check_data(output, net["name"])
