"""! @brief MCP와 기존 공개 API의 발견/오류 및 변경 영수증 경계를 검사한다."""

import tempfile
import unittest
import subprocess
import sys
import json
from pathlib import Path
from uuid import uuid4

from rfad.application.mcp import McpSession
from rfad.application.projects import ProjectService


class McpTests(unittest.TestCase):
    """! @brief 별도 MCP 저장소를 만들지 않고 같은 서비스로 요청을 전달한다."""

    def test_real_stdio_discovery_emits_only_protocol(self):
        """! @brief EDA 클라이언트가 연결할 실제 프로세스로 초기화와 조회를 확인한다."""
        with tempfile.TemporaryDirectory() as directory:
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}]
            process = subprocess.run([sys.executable, "tools/mcp_stdio.py", "--workspace", directory],
                                     input=b''.join(json.dumps(value).encode() + b'\n' for value in messages),
                                     capture_output=True, timeout=15, check=True)
            responses = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual(len(responses), 2)
            self.assertEqual(responses[1]['id'], 2)
            self.assertIn('tools', responses[1]['result'])

    def test_discovery_and_mutation_replay_use_the_same_receipt(self):
        """! @brief 반복 도구 호출은 같은 request_key의 기존 작업을 반환한다."""
        with tempfile.TemporaryDirectory() as directory, ProjectService(Path(directory), auto_run=False) as service:
            session = McpSession(service)
            def send(method, params):
                """! @brief 실제 MCP 요청 형태를 사용한다."""
                return session.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            self.assertIn("error", send("tools/list", {}))
            self.assertEqual(send("initialize", {"protocolVersion": "2025-11-25"})["result"]["protocolVersion"], "2025-11-25")
            self.assertIsNone(session.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
            names = {item["name"] for item in send("tools/list", {})["result"]["tools"]}
            self.assertTrue({"catalog.stackup_suggestions", "pcb.selection.preview", "pcb.selection.apply"} <= names)
            params = {"name": "project.open", "arguments": {"context": {}, "input": {
                "path": "projects/mcp", "open_mode": "create", "name": "MCP 시험"},
                "request_key": str(uuid4()), "request_key_epoch": service.policy()["request_key_epoch"]}}
            first = send("tools/call", params)
            second = send("tools/call", params)
            self.assertFalse(first["result"]["isError"])
            self.assertEqual(first, second)
            invalid = send("tools/call", {"name": "project.apply_command", "arguments": {"context": {}, "input": {}}})
            self.assertTrue(invalid["result"]["isError"])
            self.assertIn("error", send("tools/call", {"name": "shell.execute", "arguments": {}}))
