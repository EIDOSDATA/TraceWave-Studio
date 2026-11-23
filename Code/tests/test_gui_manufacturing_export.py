"""! @brief Windows 프로그램의 선택한 게시 기록에서 IPC-2581C 및 ODB++ 후보 ZIP을 생성한다."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from rfad.adapters.exchange.manufacturing_export import export_package
from rfad.adapters.exchange.ipc2581_reader import read as ipc
from rfad.adapters.exchange.odb_reader import read as odb
from test_gui_pcb_exchange_process import EXCHANGE, GUI, ROOT, fixture


KICAD = os.environ.get("RFAD_TEST_KICAD")


@unittest.skipUnless(sys.platform == "win32" and GUI and KICAD and EXCHANGE, "Windows GUI, KiCad, 교환 worker가 필요합니다.")
class GuiManufacturingExportTests(unittest.TestCase):
    """! @brief 실제 창에서 별도 설치의 KiCad를 실행하고 변환/원본 이력/덮어쓰기 차단을 검증한다."""

    def test_export_and_preserve_record(self):
        """! @brief 완성 ZIP의 두 형식과 각 원본 파일의 해시를 실제 게시 값과 비교한다."""
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            workspace, output = folder / "workspace", folder / "한글 교환 후보.zip"
            _, state, _, _ = fixture(workspace)
            job, = [j for j in state["jobs"].values() if j["operation_method"] == "export.build"]
            cli = Path(KICAD) / "kicad-cli.exe"
            data = {"manufacturing_export": {"job_id": job["job_id"], "cli": str(cli), "output": str(output)}}
            (workspace / "pcb-exchange-smoke-fixture.json").write_text(json.dumps(data), "utf-8")
            report = folder / "smoke.json"
            process = subprocess.run([str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                                      "--workspace", str(workspace), "--exchange-python", str(Path(EXCHANGE).resolve()),
                                      "--open-project", "projects/원본 도면", "--pcb-exchange-smoke-test", "--smoke-report",
                                      str(report)], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=300)
            self.assertTrue(report.exists(), (process.returncode, process.stderr))
            result = json.loads(report.read_bytes())
            self.assertEqual(process.returncode, 0, result)
            self.assertIn("manufacturing_export_from_published_board", result["setup_checks"])
            published = job["events"][-1]["operation_result"]["artifacts"]
            manifest, = [a for a in published if a["role"] == "manifest"]
            package = (workspace / manifest["uri"]).parent
            with ZipFile(output) as combined:
                self.assertTrue(ipc(combined.read("board.xml"))["steps"])
                self.assertTrue(odb(combined.read("board-odb.zip"))["steps_with_eda"])
                handoff = json.loads(combined.read("report.json"))
                self.assertEqual(handoff["source_manifest_sha256"], manifest["sha256"])
                for artifact in published:
                    path = workspace / artifact["uri"]
                    self.assertEqual(combined.read("source/" + path.name), path.read_bytes())
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"])
            before = output.read_bytes()
            with self.assertRaises(ValueError):
                export_package(package, output, cli, ["odb"], manifest_sha256=manifest["sha256"])
            self.assertEqual(output.read_bytes(), before)
            for path, sha in ((folder / "wrong.zip", "0" * 64), (package / "inside.zip", manifest["sha256"])):
                with self.assertRaises(ValueError):
                    export_package(package, path, cli, ["ipc2581"], manifest_sha256=sha)
                self.assertFalse(path.exists())
