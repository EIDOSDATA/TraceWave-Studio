"""! @brief 대형 설계의 표시 페이지와 실제 Windows 재열기를 검증한다."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application.canonical import canonical_bytes
from rfad.application.edit_view_pages import PROFILE, MAX_PAGE_BYTES, MAX_ROWS
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from test_cad_worker_process import CODE_ROOT, register_fixture
from test_design import build_design
from test_f1_project import f1_project


def read(service, document, method, **input_data):
    """! @brief 클라이언트와 같은 JSON-RPC 경계에서 페이지를 요청한다."""
    envelope = {"jsonrpc": "2.0", "id": "F1", "method": method,
                "params": {"contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]},
                           "input": {"expected_revision": document["revision_id"], **input_data}}}
    return handle_frame(canonical_bytes(envelope), service)


class F1ViewTests(unittest.TestCase):
    """! @brief 누락 없는 전송과 실제 Windows 열기, 저장, 재열기 경계를 시험한다."""

    def collect(self, service, document, method, rows, **selection):
        """! @brief 합산 행 수와 실제 전송 크기를 확인하고 개정별 순서로 연결한다."""
        output = {key: [] for key in rows}
        offset = 0
        while offset is not None:
            reply = read(service, document, method, offset=offset, **selection)
            self.assertEqual(reply["id"], "F1")
            self.assertIn("result", reply, reply)
            result = reply["result"]
            count = 0
            for key in rows:
                output[key].extend(result[key])
                count += len(result[key])
            self.assertLessEqual(count, MAX_ROWS)
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), MAX_PAGE_BYTES)
            self.assertEqual(result["revision_id"], document["revision_id"])
            page = result["page"]
            self.assertEqual(page["profile"], PROFILE)
            self.assertEqual(page["offset"], offset)
            if page["next"] is None:
                self.assertEqual(page["total"], offset + count)
            else:
                self.assertGreater(page["next"], offset)
                self.assertEqual(page["next"], offset + count)
            offset = page["next"]
        return output

    def test_pages_return_all_geometry_parameters_and_port_choices(self):
        """! @brief 큰 선택 목록도 한 응답 크기로 제한하지 않고 원래 순서로 보낸다."""
        with TemporaryDirectory(prefix="rfad F1 pages ") as temporary, ProjectService(Path(temporary), auto_run=False) as service:
            fixture = f1_project()
            port = build_design()["ports"][0]
            port["positive_geometry_id"] = fixture["geometry"][0]["id"]
            port["reference_geometry_id"] = fixture["geometry"][1]["id"]
            fixture["ports"] = [port]
            document, _ = register_fixture(service, fixture)
            before = service.journal.read()
            editor = self.collect(service, document, "editor.page", ("items", "view_choices"))
            self.assertEqual(sum(row["kind"] == "parameter" for row in editor["items"]), 1000)
            shapes = self.collect(service, document, "canvas.page", ("shapes", "omissions"))
            identities = [row["id"] for row in fixture["geometry"]]
            self.assertEqual([row["id"] for row in shapes["shapes"]], identities)
            self.assertEqual(shapes["omissions"], [])
            self.assertEqual([row["id"] for row in editor["items"] if row["kind"] == "geometry"], identities)
            port_only = self.collect(service, document, "editor.page", ("items", "view_choices"), include_items=False,
                                     selection={"kind": "port", "id": port["id"]})
            self.assertEqual(port_only["items"], [])
            identity_set = set(identities)
            chosen = {}
            for index, item in port_only["view_choices"]:
                if item["value"] in identity_set:
                    chosen.setdefault(index, []).append(item["value"])
            self.assertEqual(list(chosen.values()), [identities, identities])
            stale = read(service, document, "canvas.page", offset=0, expected_revision=fixture["frames"]["board"]["id"])
            self.assertEqual(stale["error"]["data"]["domain_code"], "E_CONFLICT")
            end = read(service, document, "canvas.page", offset=10000)
            self.assertEqual(end["error"]["data"]["domain_code"], "E_SCHEMA")
            self.assertEqual(service.journal.read(), before)

    @unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_GUI_EXE"), "실제 Windows Studio가 필요합니다.")
    def test_windows_saves_and_reopens_all_rows(self):
        """! @brief 실제 Studio의 두 서비스 세션에서 큰 설계와 출처를 대조한다."""
        with TemporaryDirectory(prefix="TraceWave F1 Windows ") as temporary:
            directory = Path(temporary)
            workspace = directory / "한글 대형 설계"
            with ProjectService(workspace, auto_run=False) as service:
                document, _ = register_fixture(service, f1_project())
                path = service.journal.read()["projects"][document["project_id"]]["path"]
            artifact = directory / "studio.json"
            executable = Path(os.environ["RFAD_GUI_EXE"]).resolve()
            process = subprocess.run([str(executable), "--python", sys.executable, "--source", str(CODE_ROOT / "src"),
                "--workspace", str(workspace), "--open-project", path, "--smoke-test", "--smoke-report", str(artifact)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=125, check=False)
            self.assertTrue(artifact.is_file(), (process.returncode, process.stderr))
            report = json.loads(artifact.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"] and report["snapshot_id"])
            self.assertEqual(report["service_sessions"], 2)
            self.assertEqual(report["revision_id"], report["saved_revision"])
            self.assertEqual(report["canvas_shapes"], 10_000)
            self.assertEqual(report["canvas_omissions"], 0)
            self.assertEqual(report["editor_parameters"], 1_000)
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                item = state["projects"][document["project_id"]]
                saved = service.repository.load(item)
                self.assertEqual(saved["revision_id"], report["saved_revision"])
                for key in ("board", "geometry", "parameters", "materials", "stackup", "ports", "extensions"):
                    self.assertEqual(document[key], saved[key], key)
                self.assertEqual(state["snapshots"][report["snapshot_id"]]["artifact"]["sha256"], item["current"]["sha256"])
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                (Path(output) / "f1-save-reopen.json").write_bytes(artifact.read_bytes())
