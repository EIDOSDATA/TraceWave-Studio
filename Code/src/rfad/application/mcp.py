"""! @brief MCP 2025-11-25 도구 호출을 기존 공개 API와 같은 명령 경계에 연결한다."""

import json

from rfad.application.canonical import canonical_bytes
from rfad.application.rpc import capabilities, handle_frame, PROJECT_MUTATIONS, MAX_FRAME_BYTES


PROTOCOL_VERSION = "2025-11-25"


class McpSession:
    """! @brief 연결별 초기화만 소유하고 프로젝트/작업 상태는 기존 서비스가 관리한다."""

    def __init__(self, service, catalog=None):
        """! @brief 임의 실행 인수 대신 기존 서비스와 읽기 전용 카탈로그를 주입한다."""
        self.service = service
        self.catalog = catalog
        self.initialized = False
        self.negotiated = False

    def tools(self):
        """! @brief 구현된 공개 API만 노출하고 단위/좌표/출처 입력을 원래 계약으로 전달한다."""
        methods = capabilities(self.service, self.catalog)["methods"]
        return [{"name": name, "description": "TraceWave 공개 API " + name + ". 수량과 출처는 API 계약을 따릅니다.",
                 "inputSchema": {"type": "object", "properties": {
                     "context": {"type": "object"}, "input": {"type": "object"},
                     "request_key": {"type": "string"}, "request_key_epoch": {"type": "string"}},
                     "required": ["context", "input"], "additionalProperties": False},
                 "annotations": {"readOnlyHint": name not in PROJECT_MUTATIONS,
                                 "destructiveHint": name in PROJECT_MUTATIONS,
                                 "idempotentHint": name not in PROJECT_MUTATIONS, "openWorldHint": False}}
                for name, details in sorted(methods.items()) if details["status"] == "implemented"]

    def handle(self, request):
        """! @brief MCP 응답 오류와 실제 도구 실행 실패를 구분하며 변경 요청을 재발급하지 않는다."""
        identity = request.get("id") if type(request) is dict else None
        def error(code, message):
            """! @brief 프로토콜 오류는 같은 요청 ID로 반환한다."""
            return {"jsonrpc": "2.0", "id": identity, "error": {"code": code, "message": message}}
        if type(request) is not dict or request.get("jsonrpc") != "2.0" or type(request.get("method")) is not str:
            return error(-32600, "Invalid Request")
        method, params = request["method"], request.get("params", {})
        if "id" not in request:
            if method == "notifications/initialized" and self.negotiated:
                self.initialized = True
            return None
        if type(params) is not dict:
            return error(-32602, "params must be an object")
        if method == "initialize":
            if type(params.get("protocolVersion")) is not str:
                return error(-32602, "protocolVersion required")
            self.negotiated = True
            result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "tracewave-studio", "version": "0.1.0"},
                      "instructions": "공개 API의 expected_revision, preview_hash와 request_key를 유지하십시오. 미정 물성을 채우지 마십시오."}
        elif method == "ping":
            result = {}
        elif not self.initialized:
            return error(-32000, "Session not initialized")
        elif method == "tools/list":
            if params:
                return error(-32602, "No cursor is required")
            result = {"tools": self.tools()}
        elif method == "tools/call":
            if (set(params) != {"name", "arguments"} or type(params["name"]) is not str
                    or params["name"] not in {item["name"] for item in self.tools()}):
                return error(-32602, "Unknown tool")
            arguments = params["arguments"]
            if type(arguments) is not dict or set(arguments) - {"context", "input", "request_key", "request_key_epoch"}:
                return error(-32602, "Invalid tool arguments")
            envelope = {"contract_version": "rfad.api/2.0", **arguments}
            response = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": identity,
                                    "method": params["name"], "params": envelope}), self.service, self.catalog)
            data = response.get("result", response.get("error"))
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True)}],
                      "structuredContent": data, "isError": "error" in response}
        else:
            return error(-32601, "Method not found")
        response = {"jsonrpc": "2.0", "id": identity, "result": result}
        if len(canonical_bytes(response)) > MAX_FRAME_BYTES:
            return error(-32603, "MCP response exceeds bounded transport limit")
        return response
