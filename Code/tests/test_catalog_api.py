"""! @brief 실제 CLI/RPC와 기존 직접 입력 사이의 독립성을 검증한다."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from rfad.application.projects import ProjectService
from rfad.application.rpc import MAX_FRAME_BYTES, handle_frame, serve
from rfad.catalog.build import build_catalog
from rfad.catalog.service import CatalogService
from test_catalog_build import make_package
from test_design import build_design


CODE = Path(__file__).resolve().parents[1]


def request(method, value=None, *, context=None, identity="자료 조회"):
    """! @brief 조회용 API envelope를 만든다."""
    return {"jsonrpc": "2.0", "id": identity, "method": method, "params": {
        "contract_version": "rfad.api/2.0", "context": context or {}, "input": value or {},
    }}


def encoded(value):
    """! @brief 실제 stdio와 같은 UTF-8 바이트를 만든다."""
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class CatalogApiTests(unittest.TestCase):
    """! @brief 카탈로그가 없어도 기존 저장과 직접 입력이 유지되는지 확인한다."""

    @classmethod
    def setUpClass(cls):
        """! @brief 읽기만 하는 시험들이 공유할 작은 실제 인덱스를 만든다."""
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name) / "카탈로그 시험 & #"
        cls.package = cls.root / "source"
        cls.records = make_package(cls.package)
        cls.database = cls.root / "catalog.sqlite"
        build_catalog(cls.package, cls.database)
        cls.catalog = CatalogService(cls.database)

    @classmethod
    def tearDownClass(cls):
        """! @brief 열린 저장 핸들이 없는 임시 시험 자료를 회수한다."""
        cls.temporary.cleanup()

    def cli(self, arguments, *, stdin=None):
        """! @brief 설치 환경과 독립적으로 실제 명령행 프로세스를 실행한다."""
        environment = dict(os.environ, PYTHONPATH=str(CODE / "src"))
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "rfad", *arguments],
                              input=stdin, capture_output=True, cwd=CODE, env=environment, timeout=30)

    def test_cli_build_search_detail_and_no_native_imports(self):
        output = self.root / "CLI output.sqlite"
        result = self.cli(["catalog", "build", "--source", str(self.package), "--output", str(output)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"]["observations"], 2)
        result = self.cli(["catalog", "search", "--database", str(output), "--query",
                           json.dumps({"entity": "observations", "filters": {"publisher": "Example"}})])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["returned_count"], 2)
        detail = self.cli(["catalog", "get", "--database", str(output), "--entity", "observations",
                           "--id", "PCB000001"])
        self.assertEqual(detail.returncode, 0, detail.stderr)
        self.assertNotIn("df", json.loads(json.loads(detail.stdout)["raw"]["text"]))
        environment = dict(os.environ, PYTHONPATH=str(CODE / "src"))
        script = "from rfad.catalog.service import CatalogService; import sys; CatalogService(None).status(); print([m for m in sys.modules if m.split('.')[0] in {'cadquery','OCP','vtk','openEMS','numpy'}])"
        probe = subprocess.run([sys.executable, "-c", script], capture_output=True, cwd=CODE,
                               env=environment, check=True, timeout=10)
        self.assertEqual(probe.stdout.strip(), b"[]")

    def test_cli_rejects_invalid_json_and_duplicate_filter_keys(self):
        for query in ('{"entity":"sources","entity":"observations"}', '[]',
                      '{"entity":"observations","filters":{"frequency_ghz":NaN}}'):
            with self.subTest(query=query):
                result = self.cli(["catalog", "search", "--database", str(self.database), "--query", query])
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertIn("error", json.loads(result.stderr))

    def test_standalone_stdio_and_capabilities(self):
        payloads = [request("capabilities.get"), request("catalog.status"),
                    request("catalog.search", {"entity": "observations", "limit": 1})]
        result = self.cli(["serve", "--catalog", str(self.database)],
                          stdin=b"\n".join(encoded(item) for item in payloads) + b"\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        replies = [json.loads(line)["result"] for line in result.stdout.splitlines()]
        self.assertTrue(replies[0]["catalog_profile"]["read_only"])
        self.assertFalse(replies[0]["catalog_profile"]["project_mutations"])
        self.assertFalse(replies[0]["idempotency_policy"]["mutations_enabled"])
        self.assertEqual(replies[1]["state"], "ready")
        self.assertEqual(replies[2]["returned_count"], 1)

    def test_envelope_rejections_notifications_and_response_size(self):
        invalid = request("catalog.search", {"entity": "observations"}, context={"project_id": str(uuid4())})
        self.assertEqual(handle_frame(encoded(invalid), catalog=self.catalog)["error"]["data"]["domain_code"], "E_SCHEMA")
        invalid = request("catalog.status")
        invalid["params"]["contract_version"] = "wrong"
        self.assertEqual(handle_frame(encoded(invalid), catalog=self.catalog)["error"]["data"]["domain_code"], "E_VERSION")
        notification = request("catalog.search", {"entity": "not_a_table"})
        del notification["id"]
        self.assertIsNone(handle_frame(encoded(notification), catalog=self.catalog))
        payload = request("catalog.get", {"entity": "observations", "id": "PCB000001"}, identity="x" * 8192)
        output = io.BytesIO()
        self.assertEqual(serve(io.BytesIO(encoded(payload) + b"\n"), output, io.StringIO(), catalog=self.catalog), 0)
        self.assertLessEqual(len(output.getvalue()) - 1, MAX_FRAME_BYTES)
        result = json.loads(output.getvalue())["result"]
        self.assertEqual(result["properties"]["properties"]["df"]["frequency"]["point_ghz"], 1)

    def test_broken_catalog_preserves_manual_material_save_undo_and_snapshot(self):
        broken = self.root / "broken.sqlite"
        broken.write_bytes(b"not sqlite")
        catalog = CatalogService(broken)
        workspace = self.root / "workspace"
        material = build_design(known_material=True)["materials"][0]
        project_id = None
        with ProjectService(workspace, auto_run=False) as service:
            def mutate(method, data, context=None):
                """! @brief 기존 공개 변경 명령을 같은 RPC 경계로 실행한다."""
                envelope = request(method, data, context=context)
                envelope["params"].update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
                response = handle_frame(encoded(envelope), service, catalog)
                self.assertNotIn("error", response, response)
                return response["result"]

            def finish(task):
                """! @brief 기존 비동기 명령을 실제 저장소에서 완료한다."""
                self.assertTrue(service.run_next())
                job = service.status(request("job.status", {"job_id": task["job_id"]})["params"])
                self.assertEqual(job["state"], "completed", job)
                return job["events"][-1]["operation_result"]

            opened = finish(mutate("project.open", {"path": "projects/manual", "name": "직접 입력", "open_mode": "create"}))
            project_id = opened["project_id"]
            context = {"project_id": project_id}
            changed = mutate("project.apply_command", {"expected_revision": opened["revision_id"],
                             "command_id": str(uuid4()), "type": "material.set", "payload": {"material": material}}, context)
            before = service.journal.read()
            self.assertEqual(handle_frame(encoded(request("catalog.status")), service, catalog)["result"]["state"], "invalid")
            self.assertIn("error", handle_frame(encoded(request("catalog.search", {"entity": "observations"})), service, catalog))
            self.assertEqual(service.journal.read(), before)
            undone = mutate("project.undo", {"expected_revision": changed["new_revision"], "command_id": str(uuid4())}, context)
            redone = mutate("project.redo", {"expected_revision": undone["new_revision"], "command_id": str(uuid4())}, context)
            finish(mutate("project.save", {"expected_revision": redone["new_revision"]}, context))
            snapshot = finish(mutate("snapshot.create", {"expected_revision": redone["new_revision"]}, context))
            self.assertTrue(snapshot)
        with ProjectService(workspace, auto_run=False) as service:
            project = service.journal.read()["projects"][project_id]
            self.assertEqual(service.repository.load(project)["materials"], [material])


if __name__ == "__main__":
    unittest.main()
