"""! @brief 공식 MCP 클라이언트와 실제 KiCad 사이의 고정 보드 출력을 검증한다."""

import asyncio
import base64
from datetime import timedelta
from hashlib import sha256
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_hash
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
    """! @brief 동일 저장소를 번갈아 열어 외부 클라이언트로 접수한 결과를 실제 수신 및 재수입한다."""

    def setUp(self):
        """! @brief 원본과 미정 홀을 고정한 뒤 외부 MCP 프로세스에 writer 권한을 넘긴다."""
        self.fixture = ExchangeFixture()
        self.addCleanup(self.fixture.close)
        self.hole = prepare(self.fixture)
        self.source = request(self.fixture)
        self.fixture.complete("project.save", {"expected_revision": self.fixture.revision})
        self.fixture.service.close()

    async def test_native_kicad_and_mcp_board_round_trip(self):
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

        with_exchange = StdioServerParameters(command=runner, args=args + ["--exchange-python", EXCHANGE])
        without_exchange = StdioServerParameters(command=runner, args=args)
        async with stdio_client(with_exchange) as (receive, send), ClientSession(receive, send, timeout) as client:
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
            export_selection = {"job_id": task["job_id"]}
            record = await call(client, "export.get", export_selection)
            self.assertFalse(record["report"]["manufacturing_verified"])
            self.assertFalse(record["report"]["physics_verified"])
            checked = await call(client, "export.verify", {**export_selection, "manifest_sha256": record["manifest_sha256"]},
                                 keys={"request_key_epoch": epoch, "request_key": str(uuid4())})
            await complete(client, checked)

        async with stdio_client(without_exchange) as (receive, send), ClientSession(receive, send, timeout) as client:
            await client.initialize()
            caps = await call(client, "capabilities.get", {}, context={})
            self.assertFalse(caps["exchange_profile"]["runtime_configured"])
            self.assertEqual(await call(client, "export.get", export_selection), record)
            rejected = await client.call_tool("export.get", {"context": {"project_id": str(uuid4())}, "input": export_selection})
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
        edited = received.with_name("키캐드에서 다시 저장.kicad_pcb")
        script = """import json, pcbnew, sys
board = pcbnew.LoadBoard(sys.argv[1])
if not pcbnew.SaveBoard(sys.argv[2], board):
    raise RuntimeError("KiCad save failed")
print(json.dumps({"version": pcbnew.GetBuildVersion(), "layers": board.GetCopperLayerCount(),
                  "tracks": len(board.GetTracks()),
                  "holes": [list(pad.GetDrillSize()) for part in board.GetFootprints() for pad in part.Pads()]}))"""
        result = await asyncio.to_thread(subprocess.run, [str(Path(KICAD) / "python.exe"), "-c", script, str(received), str(edited)],
                                          capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
        readback = json.loads(result.stdout)
        self.assertTrue(readback["version"], readback)
        self.assertEqual(readback["layers"], 2)
        self.assertEqual(readback["tracks"], len(fixture.document["geometry"]))
        self.assertEqual(readback["holes"], [[1000000, 1000000]])
        self.assertEqual(received.read_bytes(), raw)

        incoming = edited.read_bytes()
        chunk_size = 1024
        self.assertGreater(len(incoming), chunk_size)
        async with stdio_client(with_exchange) as (receive, send), ClientSession(receive, send, timeout) as client:
            await client.initialize()
            caps = await call(client, "capabilities.get", {}, context={})
            epoch = caps["idempotency_policy"]["request_key_epoch"]

            def request_key():
                """! @brief 상태를 바꾸는 각 요청에 현재 세션의 영수증 키를 발행한다."""
                return {"request_key_epoch": epoch, "request_key": str(uuid4())}

            descriptor = {"path": edited.name, "bytes": len(incoming), "sha256": sha256(incoming).hexdigest()}
            transfer = await call(client, "pcb.import.begin", {"format": "kicad_pcb", "files": [descriptor]},
                                  keys=request_key())
            import_selection = {"upload_id": transfer["upload_id"]}
            for offset in range(0, len(incoming), chunk_size):
                payload = base64.b64encode(incoming[offset:offset + chunk_size]).decode("ascii")
                await call(client, "pcb.import.chunk", {**import_selection, "path": edited.name, "offset": offset,
                                                        "content_base64": payload}, keys=request_key())
            await complete(client, await call(client, "pcb.import.parse", import_selection, keys=request_key()))
            imported = await call(client, "pcb.import.get", import_selection)
            self.assertEqual(imported["parse_state"], "completed")
            self.assertFalse(imported["parsed"]["manufacturing_verified"])
            parsed_board = imported["parsed"]["records"][0]["data"]
            copper = sorted((row for row in fixture.document["stackup"] if row["role"] == "conductor"),
                            key=lambda row: row["order"])
            nets = {row["name"]: row["id"] for row in fixture.document["nets"]}
            mapping = {
                "board_id": fixture.document["board"]["id"],
                "frame_id": fixture.document["board"]["frame_id"],
                "layers": [{"source": "F.Cu", "target": copper[-1]["id"]},
                           {"source": "B.Cu", "target": copper[0]["id"]}],
                "nets": [{"source": str(row["code"]), "target": nets[row["name"]] if row["code"] != 0 else None}
                         for row in parsed_board["nets"]],
                "placement": None,
            }
            review_input = {
                **import_selection, "expected_revision": fixture.revision, "mapping": mapping,
                "acknowledged_losses": [canonical_hash(row) for row in imported["parsed"]["losses"]],
                "reason": "KiCad 재저장 합성 기판의 명시적 층과 넷 대응 검증",
            }
            review = await call(client, "pcb.import.preview", review_input)
            self.assertTrue(review["can_apply"], review)
            apply_input = {**review_input, "command_id": str(uuid4()), "review_hash": review["review_hash"]}
            keys = request_key()
            applied = await call(client, "pcb.import.apply", apply_input, keys=keys)
            self.assertEqual(await call(client, "pcb.import.apply", apply_input, keys=keys), applied)
            save = await call(client, "project.save", {"expected_revision": applied["new_revision"]},
                              keys=request_key())
            await complete(client, save)
            imported = await call(client, "pcb.import.get", import_selection)

        async with stdio_client(without_exchange) as (receive, send), ClientSession(receive, send, timeout) as client:
            await client.initialize()
            self.assertEqual(await call(client, "pcb.import.get", import_selection), imported)

        def compare_saved_source():
            """! @brief 새 세션이 연 파일과 미정값의 원본을 비교한다."""
            with ProjectService(fixture.workspace, auto_run=False) as service:
                registered = service.journal.read()["projects"][fixture.project]
                self.assertEqual(registered["saved"], registered["current"])
                updated = service._load(registered)
                self.assertEqual(updated["revision_id"], applied["new_revision"])
                self.assertEqual(updated["materials"], fixture.document["materials"])
                self.assertEqual(updated["stackup"], fixture.document["stackup"])
                self.assertTrue(updated["pcb"]["imports"])
                original_hole = next(item for item in updated["pcb"]["holes"] if item["id"] == self.hole["id"])
                self.assertEqual(original_hole, self.hole)
                sealed_input = imported["result"]["source_files"][0]["artifact"]
                self.assertEqual(service.journal.read_artifact(sealed_input), incoming)
                original = service._load({"current": registered["revisions"][fixture.revision]})
                self.assertEqual(original, fixture.document)

        await asyncio.to_thread(compare_saved_source)
