"""! @brief API-001과 제한된 NDJSON 전송의 오류 경계를 검증한다."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from rfad.application.rpc import CONTRACT_VERSION, MAX_BATCH_ITEMS, MAX_FRAME_BYTES, handle_frame, serve


def request(request_id="한국어 요청"):
    """! @brief 허용된 읽기 전용 요청 fixture를 구성한다."""
    return {"jsonrpc": "2.0", "id": request_id, "method": "capabilities.get", "params": {"contract_version": CONTRACT_VERSION, "context": {}, "input": {}}}


def encode(value):
    """! @brief UTF-8 메시지를 만든다."""
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class RpcTests(unittest.TestCase):
    """! @brief 읽기 전용 서비스와 미구현 경계를 확인한다."""

    def test_handshake_reports_implemented_without_physics_claims(self):
        result = handle_frame(encode(request()))
        self.assertEqual(result["id"], "한국어 요청")
        self.assertEqual(result["result"]["contract_version"], "rfad.api/2.0")
        self.assertFalse(result["result"]["idempotency_policy"]["mutations_enabled"])
        self.assertEqual(result["result"]["tested_envelopes"], [])
        self.assertTrue(all(item["status"] == "declared" for item in result["result"]["features"]))

    def test_mutation_is_not_silently_implemented(self):
        data = request(7)
        data["method"] = "project.open"
        self.assertEqual(handle_frame(encode(data))["error"]["code"], -32601)

    def test_contract_version_is_not_document_version(self):
        data = request(3)
        data["params"]["contract_version"] = "3.4"
        response = handle_frame(encode(data))
        self.assertEqual(response["id"], 3)
        self.assertEqual(response["error"]["data"]["domain_code"], "E_VERSION")

    def test_notifications_never_reply_to_method_or_params_errors(self):
        for method in ("capabilities.get", "project.open"):
            data = {"jsonrpc": "2.0", "method": method, "params": {}}
            self.assertIsNone(handle_frame(encode(data)))

    def test_mixed_batch_keeps_only_responses(self):
        data = request("call")
        notification = request()
        del notification["id"]
        response = handle_frame(encode([data, notification, 1]))
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["id"], "call")
        self.assertEqual(response[1]["error"]["code"], -32600)
        self.assertIsNone(handle_frame(encode([notification])))

    def test_batch_and_string_limits(self):
        self.assertEqual(handle_frame(encode([request()] * (MAX_BATCH_ITEMS + 1)))["error"]["data"]["domain_code"], "E_RESOURCE")
        self.assertEqual(handle_frame(encode(request("x" * 8193)))["error"]["data"]["domain_code"], "E_SCHEMA")

    def test_invalid_json_duplicate_keys_nonfinite_and_bad_unicode(self):
        for data in (b'{"x":1,"x":2}', b'{', b'NaN', b'Infinity', b'\xff'):
            with self.subTest(data=data):
                self.assertEqual(handle_frame(data)["error"]["code"], -32700)
        for data in (b'1e999', b'"\\ud800"'):
            self.assertEqual(handle_frame(data)["error"]["data"]["domain_code"], "E_SCHEMA")

    def test_invalid_envelopes_and_unknown_required_fields(self):
        for data in ([], {}, 1, request(True)):
            self.assertEqual(handle_frame(encode(data))["error"]["code"], -32600)
        data = request()
        data["params"]["required_future_field"] = True
        self.assertEqual(handle_frame(encode(data))["error"]["code"], -32602)
        data = request()
        data["params"]["input"]["runtime_ids"] = ["unimplemented"]
        self.assertEqual(handle_frame(encode(data))["error"]["code"], -32602)

    def test_numeric_and_null_ids_are_preserved(self):
        for request_id in (None, 0, 1.5, -7):
            self.assertEqual(handle_frame(encode(request(request_id)))["id"], request_id)

    def test_bounded_reader_closes_on_unterminated_oversized_input(self):
        source = io.BytesIO(b"x" * (MAX_FRAME_BYTES * 10))
        sink = io.BytesIO()
        log = io.StringIO()
        self.assertEqual(serve(source, sink, log), 2)
        self.assertLessEqual(source.tell(), MAX_FRAME_BYTES + 2)
        self.assertEqual(json.loads(sink.getvalue())["error"]["data"]["domain_code"], "E_RESOURCE")
        self.assertIn("Frame limit", log.getvalue())

    def test_lf_crlf_and_exact_limit(self):
        base = encode(request())
        frame = base + b" " * (MAX_FRAME_BYTES - len(base))
        for suffix in (b"\n", b"\r\n", b""):
            sink = io.BytesIO()
            self.assertEqual(serve(io.BytesIO(frame + suffix), sink, io.StringIO()), 0)
            self.assertEqual(json.loads(sink.getvalue())["id"], "한국어 요청")

    def test_batch_response_cannot_exceed_transport_limit(self):
        frame = encode([request("x" * 7900) for _ in range(8)])
        self.assertLess(len(frame), MAX_FRAME_BYTES)
        sink = io.BytesIO()
        with patch("rfad.application.rpc.MAX_FRAME_BYTES", 64 * 1024):
            self.assertEqual(serve(io.BytesIO(frame + b"\n"), sink, io.StringIO()), 0)
        self.assertLessEqual(len(sink.getvalue()) - 1, MAX_FRAME_BYTES)
        self.assertEqual(json.loads(sink.getvalue())["error"]["data"]["domain_code"], "E_RESOURCE")

    def test_subprocess_stdout_is_utf8_protocol_only(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(root / "src"))
        data = encode(request()) + b"\n"
        result = subprocess.run([sys.executable, "-m", "rfad", "serve"], input=data, capture_output=True, cwd=root, env=env, timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout)["id"], "한국어 요청")
        self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
