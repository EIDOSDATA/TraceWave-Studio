"""! @brief 공식 MCP 클라이언트와 실제 KiCad 사이의 고정 보드 출력을 검증한다."""

import asyncio
from datetime import timedelta
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from rfad.application.projects import ProjectService
from test_exchange_service import ExchangeFixture
from test_pcb_exchange_service import prepare, request


CODE = Path(__file__).resolve().parents[1]
EXCHANGE = os.environ.get("RFAD_EXCHANGE_PYTHON")
KICAD = os.environ.get("RFAD_TEST_KICAD")


@unittest.skipUnless(
    sys.platform == "win32" and EXCHANGE and KICAD and find_spec("mcp"),
    "명시한 Windows 교환 worker, KiCad와 공식 MCP Python SDK가 필요합니다.",
)
class McpPcbExchangeTests(unittest.IsolatedAsyncioTestCase):
    """! @brief 동일 저장소를 번갈아 열어 외부 클라이언트로 접수한 결과를 실제 수신한다."""

    def setUp(self):
        """! @brief 원본과 미정 홀을 고정한 뒤 외부 MCP 프로세스에 writer 권한을 넘긴다."""
        self.fixture = ExchangeFixture()
        self.addCleanup(self.fixture.close)
        self.hole = prepare(self.fixture)
        self.source = request(self.fixture)
        self.fixture.complete("project.save", {"expected_revision": self.fixture.revision})
        self.fixture.service.close()

    async def test_review_export_replay_reopen_and_native_kicad_load(self):
        """! @brief 운송 메타데이터와 영수증을 분리하고 원문/미정을 보존한다."""
        from mcp import ClientSession, StdioServerParameters, types
        from mcp.client.stdio import stdio_client

        fixture = self.fixture
        project = {"project_id": fixture.project}
        args = [str(CODE / "tools/mcp_stdio.py"), "--workspace", str(fixture.workspace)]
        timeout = timedelta(seconds=20)
        runner = os.environ.get("RFAD_MCP_SERVER_PYTHON", sys.executable)

        async def call(client, name, data, *, context=None, keys=None):
            """! @brief 공식 SDK가 만든 _meta를 서비스 payload 밖에서 전송한다."""
            arguments = {"context": project if context is None else context, "input": data}
            result = await client.call_tool(name, {**arguments, **(keys or {})}, meta={"progressToken": "pcb-test"})
            self.assertFalse(result.isError, result)
            self.assertEqual(json.loads(result.content[0].text), result.structuredContent)
            return result.structuredContent

        async def complete(client, task):
            """! @brief 작업 완료까지 기존 영속 상태를 읽고 실패한 상태도 시험에 반영한다."""
            cursor = 0
            async with asyncio.timeout(40):
                while True:
                    status = await call(client, "job.status", {"job_id": task["job_id"], "cursor": cursor}, context={})
                    if status["state"] == "completed":
                        return status
                    self.assertIn(status["state"], ("queued", "running", "preparing", "verifying"), status)
                    cursor = status["events_cursor"]
                    await asyncio.sleep(0.1)

        transport = StdioServerParameters(command=runner, args=args + ["--exchange-python", EXCHANGE])
        async with stdio_client(transport) as (receive, send), ClientSession(receive, send, timeout) as client:
            handshake = await client.initialize()
            self.assertEqual(handshake.protocolVersion, "2025-11-25")
            tools = await client.list_tools(params=types.PaginatedRequestParams(_meta={"progressToken": "list"}))
            by_name = {tool.name: tool for tool in tools.tools}
            self.assertTrue(by_name["export.get"].annotations.readOnlyHint)
            self.assertTrue(by_name["export.build"].annotations.destructiveHint)
            caps = await call(client, "capabilities.get", {}, context={})
            self.assertTrue(caps["exchange_profile"]["runtime_configured"])
            self.assertTrue(caps["pcb_import_profile"]["runtime_configured"])
            epoch = caps["idempotency_policy"]["request_key_epoch"]
            review_task = await call(client, "export.preview", self.source,
                                     keys={"request_key_epoch": epoch, "request_key": str(uuid4())})
            status = await complete(client, review_task)
            review = status["events"][-1]["operation_result"]
            self.assertTrue(review["can_build"], review)
            self.assertIsNone(review["pcb_preview"]["holes"][0]["tool_diameter_mm"])
            build = {**self.source, "review_hash": review["review_hash"]}
            keys = {"request_key_epoch": epoch, "request_key": str(uuid4())}
            task = await call(client, "export.build", build, keys=keys)
            self.assertEqual(await call(client, "export.build", build, keys=keys), task)
            await complete(client, task)
            selection = {"job_id": task["job_id"]}
            record = await call(client, "export.get", selection)
            self.assertFalse(record["report"]["manufacturing_verified"])
            self.assertFalse(record["report"]["physics_verified"])
            checked = await call(client, "export.verify", {**selection, "manifest_sha256": record["manifest_sha256"]},
                                 keys={"request_key_epoch": epoch, "request_key": str(uuid4())})
            await complete(client, checked)

        transport = StdioServerParameters(command=runner, args=args)
        async with stdio_client(transport) as (receive, send), ClientSession(receive, send, timeout) as client:
            await client.initialize()
            caps = await call(client, "capabilities.get", {}, context={})
            self.assertFalse(caps["exchange_profile"]["runtime_configured"])
            self.assertEqual(await call(client, "export.get", selection), record)
            rejected = await client.call_tool("export.get", {"context": {"project_id": str(uuid4())}, "input": selection})
            self.assertTrue(rejected.isError)

        def read_output():
            """! @brief MCP 종료 후 영속 원본과 봉인 산출물을 독립적으로 대조한다."""
            with ProjectService(fixture.workspace, auto_run=False) as service:
                registered = service.journal.read()["projects"][fixture.project]
                self.assertEqual(registered["saved"], registered["current"])
                self.assertEqual(service._load(registered), fixture.document)
                artifacts = record["result"]["artifacts"]
                mapped = next(item for item in artifacts if item["uri"].endswith("/board.kicad_pcb"))
                source = next(item for item in artifacts if item["role"] == "source")
                self.assertEqual(json.loads(service.journal.read_artifact(source))["source_semantics"], fixture.document)
                self.assertEqual(fixture.document["pcb"]["holes"][0], self.hole)
                return service.journal.read_artifact(mapped)

        raw = await asyncio.to_thread(read_output)

        received = Path(fixture.temporary.name) / "수신 보드.kicad_pcb"
        received.write_bytes(raw)
        script = """import json, pcbnew, sys
board = pcbnew.LoadBoard(sys.argv[1])
print(json.dumps({"version": pcbnew.GetBuildVersion(), "layers": board.GetCopperLayerCount(),
                  "tracks": len(board.GetTracks()),
                  "holes": [list(pad.GetDrillSize()) for part in board.GetFootprints() for pad in part.Pads()]}))"""
        result = await asyncio.to_thread(subprocess.run, [str(Path(KICAD) / "python.exe"), "-c", script, str(received)],
                                          capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
        readback = json.loads(result.stdout)
        self.assertTrue(readback["version"], readback)
        self.assertEqual(readback["layers"], 2)
        self.assertEqual(readback["tracks"], len(fixture.document["geometry"]))
        self.assertEqual(readback["holes"], [[1000000, 1000000]])
        self.assertEqual(received.read_bytes(), raw)
