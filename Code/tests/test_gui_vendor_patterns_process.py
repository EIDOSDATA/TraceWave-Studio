"""! @brief 실제 Windows Studio에서 공급사 가져오기, 형상 이동 및 재열기를 검증한다."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.adapters.exchange.pcb import parse_package
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.domain.vendor_catalog import VENDOR_FORMATS
from test_exchange_service import ExchangeFixture
from test_pcb_exchange_service import prepare
from test_vendor_patterns import RENESAS


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")
EXCHANGE = os.environ.get("RFAD_EXCHANGE_PYTHON", "")


@unittest.skipUnless(sys.platform == "win32" and GUI and EXCHANGE, "Windows GUI와 교환 환경을 지정합니다.")
class GuiVendorPatternTests(unittest.TestCase):
    """! @brief 고정 공식 원본과 프로젝트에 보존한 복사본을 바이트 단위로 대조한다."""

    def exercise(self, source, format_name, x=25, y=23):
        from shapely import Polygon
        with TemporaryDirectory(prefix="TraceWave 제조사 원본 ") as directory:
            workspace = Path(directory) / "작업 영역"
            fixture = ExchangeFixture()
            try:
                prepare(fixture)
                before = deepcopy(fixture.document)
                fixture.complete("project.save", {"expected_revision": fixture.revision})
                fixture.service.close()
                shutil.copytree(fixture.workspace, workspace)
            finally:
                fixture.close()
            raw = source.read_bytes()
            (workspace / source.name).write_bytes(raw)
            parsed = parse_package({source.name: raw}, format_name, {})
            card = parsed["records"][0]["data"]
            copper = sorted((row for row in before["stackup"] if row["role"] == "conductor"), key=lambda row: row["order"])
            layers = {row["layer"]: copper[-1 if row["side"] == "top" else 0]["id"] for row in card["regions"]}
            areas = [Polygon(row["outer_mm"], row["holes_mm"]) for row in card["regions"] if row["side"] == "top"]
            pick = max(areas, key=lambda item: item.area).representative_point()
            inputs = {"vendor_format": format_name, "raw_name": source.name, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                      "layer_mapping": layers, "x": str(x), "y": str(y), "pick": [pick.x + x, pick.y + y]}
            (workspace / "pcb-exchange-smoke-fixture.json").write_bytes(canonical_bytes(inputs))
            report_path = Path(directory) / "공급사 원본 화면.json"
            process = subprocess.run([str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--exchange-python", str(Path(EXCHANGE).resolve()), "--open-project",
                "projects/원본 도면", "--pcb-exchange-smoke-test", "--smoke-report", str(report_path)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=150, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if artifact_dir := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                artifact = Path(artifact_dir) / (format_name + ".json")
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertEqual(set(report["setup_checks"]), {"vendor_original_and_explicit_placement_review",
                                                             "vendor_native_canvas_edit", "vendor_saved_and_reopened"})
            (workspace / source.name).unlink()
            with ProjectService(workspace, auto_run=False) as reopened:
                project = reopened.journal.read()["projects"][before["project_id"]]
                self.assertEqual(project["current"], project["saved"])
                document = reopened._load(project)
                for key in ("materials", "stackup", "ports", "nets", "extensions", "board"):
                    self.assertEqual(document[key], before[key], key)
                self.assertEqual(document["pcb"]["holes"], before["pcb"]["holes"])
                record, = document["pcb"]["imports"]
                member = card["card"]["sha256"]
                self.assertIn("sha256:" + member, record["source_refs"])
                self.assertEqual(reopened.journal.read_artifact(record["source_files"][0]), raw)
                self.assertEqual(json.loads(reopened.journal.read_artifact(record["report"])), parsed)
                self.assertEqual(len(record["bindings"]), len(card["regions"]))
                added = [row for row in document["geometry"] if (row.get("source_ref") or "").startswith("pcb-import:")]
                self.assertEqual(len(added), len(record["bindings"]))
                self.assertTrue(all(row["material_ref"] is None and row["net_id"] is None and not row["include_in_em"]
                                    for row in added))

    @unittest.skipIf(RENESAS is None, "공식 Renesas 원본이 필요합니다.")
    def test_renesas_archive_edit_save_and_reopen(self):
        from zipfile import ZipFile
        for key, card in VENDOR_FORMATS.items():
            if not key.startswith("vendor_renesas_"):
                continue
            with self.subTest(template=key):
                if key == "vendor_renesas_ifa_ss":
                    with TemporaryDirectory(prefix="TraceWave 공식 DXF ") as directory, ZipFile(RENESAS) as archive:
                        member = Path(directory) / card["member"]
                        member.write_bytes(archive.read(card["member"]))
                        self.exercise(member, key)
                else:
                    self.exercise(RENESAS, key)
