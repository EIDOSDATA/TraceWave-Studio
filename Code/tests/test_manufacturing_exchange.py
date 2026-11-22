"""! @brief 실제 KiCad가 받은 원호 및 IFA 제조 출력과 불변 원본을 검사한다."""

from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from xml.etree import ElementTree
from zipfile import ZipFile
from uuid import uuid4

from rfad.application.canonical import canonical_hash
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.pcb_import_service import read as read_import
from rfad.application.projects import ProjectService
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture, request
from test_pcb_ifa import ifa_document
from test_pcb_import_service import begin, upload
from test_pcb_solver import fixture_document, quantity

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from export_manufacturing_exchange import export_package


KICAD = os.environ.get("RFAD_TEST_KICAD")
EXCHANGE = os.environ.get("RFAD_EXCHANGE_PYTHON")


@unittest.skipUnless(KICAD and EXCHANGE, "KiCad와 실제 TraceWave 출력 worker가 필요합니다.")
class ManufacturingExchangeTests(unittest.TestCase):
    """! @brief PCB 개정부터 외부 CAM 파일의 물리 외곽까지 지원 범위를 확인한다."""

    def test_external_ipc_and_odb_handoff_preserves_published_arc_and_ifa(self):
        """! @brief 공개 경로로 봉인한 패키지를 내보내고 외곽, 해시와 기존 파일 보호를 검사한다."""
        arc = fixture_document(arc=True)
        bottom = deepcopy(arc["stackup"][-1])
        bottom.update(id=str(uuid4()), order=0, name="시험 하부 도체", z_min=quantity(-35, "um"))
        for layer in arc["stackup"]:
            layer["order"] += 1
        arc["stackup"].insert(0, bottom)
        for source in (arc, ifa_document()):
            with self.subTest(name=source["metadata"]["name"]), TemporaryDirectory() as directory:
                folder = Path(directory)
                recipient = folder / "manufacturing.zip"
                runtime = ExchangeRuntime(Path(EXCHANGE))
                with ProjectService(folder / "workspace", auto_run=False, exchange_runtime=runtime) as service:
                    document, snapshot = register_fixture(service, source)
                    project_id = document["project_id"]
                    args = {"snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
                            "profile": "rfad.exchange.kicad-board/0.1", "format": "kicad_pcb", "options": {}}
                    task = service.mutate("export.preview", request(service, project_id, args))
                    self.assertTrue(service.run_next())
                    job = service.journal.read()["jobs"][task["job_id"]]
                    preview = job["events"][-1]["operation_result"]
                    self.assertTrue(preview["can_build"], preview.get("issues"))
                    task = service.mutate("export.build", request(service, project_id,
                                                                   {**args, "review_hash": preview["review_hash"]}))
                    self.assertTrue(service.exchange.run_next())
                    job = service.journal.read()["jobs"][task["job_id"]]
                    self.assertEqual(job["state"], "completed", job["events"][-1])
                    assets = job["events"][-1]["operation_result"]["artifacts"]
                    package = folder / "package"
                    package.mkdir()
                    originals = {Path(row["uri"]).name: service.journal.read_artifact(row) for row in assets}
                    for name, raw in originals.items():
                        (package / name).write_bytes(raw)
                executable = Path(KICAD) / "kicad-cli.exe"
                report = export_package(package, recipient, executable, ["ipc2581", "odb"])
                self.assertEqual(report["source_snapshot"], snapshot)
                self.assertEqual(report["recipient_roundtrip"], "not_verified")
                expected = [Quantity(**source["board"]["outline"][key]).as_unit("mm") for key in ("width", "height")]
                with ZipFile(recipient) as result:
                    self.assertEqual(json.loads(result.read("report.json")), report)
                    for name, raw in originals.items():
                        self.assertEqual(result.read("source/" + name), raw)
                        self.assertEqual((package / name).read_bytes(), raw)
                    ipc_bytes = result.read("board.xml")
                    xml = ElementTree.fromstring(ipc_bytes)
                    ns = xml.tag.rsplit("}", 1)[0] + "}"
                    profile, = xml.iter(ns + "Profile")
                    xy = [(float(row.get("x")), float(row.get("y"))) for row in profile.iter() if row.get("x") is not None]
                    self.assertEqual([max(axis) - min(axis) for axis in zip(*xy)], expected)
                    with ZipFile(BytesIO(result.read("board-odb.zip"))) as odb:
                        profile = odb.read("steps/pcb/profile").decode("utf-8")
                        coordinates = [tuple(map(float, row.split()[1:3])) for row in profile.splitlines()
                                       if row.startswith(("OB ", "OS "))]
                        self.assertIn("UNITS=MM", profile)
                        self.assertEqual([max(axis) - min(axis) for axis in zip(*coordinates)], expected)
                        eda = odb.read("steps/pcb/eda/data").decode("utf-8")
                        self.assertIn("LYR f.cu", eda)
                        self.assertIn("NET ", eda)
                with ProjectService(folder / "workspace", auto_run=False, exchange_runtime=runtime) as service:
                    fixture = SimpleNamespace(service=service, request=lambda data: request(service, project_id, data))
                    name = "board.xml"
                    source_id = begin(fixture, ipc_bytes, name, "ipc2581_revc")
                    upload(fixture, source_id, ipc_bytes, name)
                    service.mutate("pcb.import.parse", fixture.request({"upload_id": source_id}))
                    self.assertTrue(service.exchange.run_next())
                    context = {"project_id": project_id}
                    def read(method, value):
                        """! @brief 실제 봉인한 제조 원문 조회와 적용 미리보기를 호출한다."""
                        return read_import(service, method, {"contract_version": "rfad.api/2.0",
                                                             "context": context, "input": value})
                    original = read("pcb.import.get", {"upload_id": source_id})
                    self.assertTrue(original["mapping_sources"]["ipc_profile_available"], original)
                    inputs = {"upload_id": source_id, "expected_revision": document["revision_id"],
                              "mapping": {"board_id": document["board"]["id"], "frame_id": document["board"]["frame_id"],
                                          "layers": [], "nets": [], "placement": None},
                              "acknowledged_losses": [canonical_hash(row) for row in original["parsed"]["losses"]],
                              "reason": "독립 수신 보드 외곽 재검토"}
                    review = read("pcb.import.preview", inputs)
                    self.assertTrue(review["can_apply"], review.get("issues"))
                    applied = service.mutate("pcb.import.apply", fixture.request(
                        {**inputs, "command_id": str(uuid4()), "review_hash": review["review_hash"]}))
                    self.assertNotEqual(applied["new_revision"], document["revision_id"])
                    after = service._load(service.journal.read()["projects"][project_id])
                    for key in ("geometry", "stackup", "ports", "connections", "materials"):
                        self.assertEqual(after[key], document[key])
                    self.assertEqual(after["board"], document["board"])
                    self.assertEqual(service.journal.read_artifact(original["result"]["source_files"][0]["artifact"]), ipc_bytes)
                before = recipient.read_bytes()
                with self.assertRaisesRegex(ValueError, "기존 파일"):
                    export_package(package, recipient, executable, ["odb"])
                self.assertEqual(recipient.read_bytes(), before)
                changed = package / "board.kicad_pcb"
                changed.write_bytes(originals[changed.name] + b" ")
                rejected = folder / "changed.zip"
                with self.assertRaisesRegex(ValueError, "해시"):
                    export_package(package, rejected, executable, ["ipc2581"])
                self.assertFalse(rejected.exists())
