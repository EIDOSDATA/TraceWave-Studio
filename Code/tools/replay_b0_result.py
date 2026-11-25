"""! @brief 복원한 B0 작업 사본에서 공개 API와 MCP의 과거 결과를 대조한다."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from struct import pack
import subprocess
import sys
from uuid import UUID

from restore_b0_proof import PROTOCOL, WORKSPACE_HASHES, check_bytes, tree_hash


def load_json(path):
    """! @brief 보존 기록을 UTF-8 JSON으로 읽는다."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def request(method, params, identity=None):
    """! @brief 요청과 초기화 알림에 같은 JSON-RPC 규약을 사용한다."""
    frame = {"jsonrpc": "2.0", "method": method, "params": params}
    if identity is not None:
        frame["id"] = identity
    return frame


def stdio(code, workspace, entry, requests, *, client=None):
    """! @brief 한 작업 사본에 실제 한 줄 JSON 서버를 띄워 응답과 ID를 대조한다."""
    payload = "".join(json.dumps(frame, ensure_ascii=False) + "\n" for frame in requests).encode("utf-8")
    env = {**os.environ, "PYTHONPATH": str(code / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    arguments = [sys.executable, "-X", "utf8", *entry, "--workspace", str(workspace)]
    if client is not None:
        arguments = [str(client), "--service-replay", "--python", sys.executable,
                     "--source", str(code / "src"), "--workspace", str(workspace)]
    child = subprocess.run(arguments,
                           input=payload, cwd=code, env=env, capture_output=True, timeout=90, check=False)
    if child.returncode:
        detail = child.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"{workspace.name} {entry} 종료 코드 {child.returncode}: {detail}")
    replies = [json.loads(line) for line in child.stdout.splitlines()]
    expected_ids = [frame["id"] for frame in requests if "id" in frame]
    if [reply.get("id") for reply in replies] != expected_ids:
        raise ValueError(f"{workspace.name} {entry} 응답 ID가 다릅니다.")
    for reply in replies:
        if reply.get("jsonrpc") != "2.0" or "error" in reply or "result" not in reply:
            raise ValueError(f"{workspace.name} {entry} 응답 오류: {reply}")
    return [reply["result"] for reply in replies]


def saved_revision(workspace, expected):
    """! @brief 고정한 저장 기준점의 문서 해시와 개정 ID를 직접 확인한다."""
    commit = UUID(load_json(workspace / "current.json")["commit_id"])
    state = load_json(workspace / "commits" / str(commit) / "state.json")
    saved = state["projects"][expected["project_id"]]["saved"]
    document = (workspace / saved["uri"]).resolve(strict=True)
    if not document.is_relative_to(workspace):
        raise ValueError(f"{workspace.name} 저장 문서가 사본 밖에 있습니다.")
    raw = document.read_bytes()
    if (saved["sha256"] != expected["saved_sha256"] or sha256(raw).hexdigest() != expected["saved_sha256"]
            or json.loads(raw)["revision_id"] != expected["saved_revision"]):
        raise ValueError(f"{workspace.name} 저장 개정 또는 문서 SHA256이 다릅니다.")


def measure(code, workspace, expected, *, client=None):
    """! @brief 원래 결과의 설명과 S11 페이지를 변경 요청 없이 두 프로토콜로 읽는다."""
    saved_revision(workspace, expected)
    contract = expected["public_api_contract"]
    protocol = expected["mcp_protocol"]
    context = {"project_id": expected["project_id"]}
    source = {"kind": "solver", "artifact_id": expected["result_artifact_id"]}
    describe = {"context": context, "input": {"source": source}}
    page = {"context": context, "input": {"source": source, "pin": expected["result_pin"],
                                         "row": 0, "column": 0, "offset": 0, "limit": 201}}
    reads = (("result.describe", describe), ("result.page", page))
    capabilities, *api = stdio(code, workspace, ["-m", "rfad", "serve"], [
        request("capabilities.get", {"contract_version": contract, "context": {}, "input": {}}, 1),
        *(request(method, {"contract_version": contract, **params}, identity)
          for identity, (method, params) in enumerate(reads, 3)),
    ], client=client)
    init, catalog, *mcp = stdio(code, workspace, ["tools/mcp_stdio.py"], [
        request("initialize", {"protocolVersion": protocol}, 1),
        request("notifications/initialized", {}),
        request("tools/list", {}, 2),
        *(request("tools/call", {"name": method, "arguments": params}, identity)
          for identity, (method, params) in enumerate(reads, 3)),
    ])
    if (capabilities["contract_version"] != contract or init["protocolVersion"] != protocol
            or len(catalog["tools"]) != expected["mcp_tools"]):
        raise ValueError(f"{workspace.name} 공개 API 계약 또는 MCP 프로토콜과 도구 수가 다릅니다.")
    if any(reply["isError"] for reply in mcp) or api != [reply["structuredContent"] for reply in mcp]:
        raise ValueError(f"{workspace.name} API와 MCP 결과가 다릅니다.")
    if any(result["source"] != source or result["pin"] != expected["result_pin"] for result in api):
        raise ValueError(f"{workspace.name} 결과 출처 또는 pin이 다릅니다.")
    return {"api_methods": capabilities["methods"], "mcp_tools": catalog["tools"],
            "result.describe": api[0], "result.page": api[1]}


def verify_samples(page, expected, header):
    """! @brief 주파수 범위와 표본 전체를 시제품의 고정 배열과 binary64로 대조한다."""
    rows = page["samples"]
    if (not rows or len(rows) != expected["samples"] or page["total"] != len(rows) or page["next_offset"] is not None
            or [rows[0]["frequency_hz"], rows[-1]["frequency_hz"]] != expected["frequency_hz"]):
        raise ValueError("B0 S11 표본 수, 주파수 범위 또는 페이지가 다릅니다.")
    text = header.read_text(encoding="utf-8")
    for array, field in (("frequenciesHz", "frequency_hz"), ("magnitudeDb", "magnitude_db")):
        values = re.search(r"\b" + array + r"\s*\{([^}]+)\}", text)
        if values is None:
            raise ValueError(f"시제품의 B0 표본 배열을 찾지 못했습니다. {array}")
        bits = [pack(">d", float(value)) for value in values[1].strip().rstrip(",").split(",")]
        if [pack(">d", row[field]) for row in rows] != bits:
            raise ValueError(f"B0 S11 표본이 다릅니다. {field}")


def replay(manifest, restored, b0_code, main_code, *, client=None):
    """! @brief 검증된 작업 사본에서 읽기 전후 파일과 두 배포본의 결과를 대조한다."""
    if b0_code.samefile(main_code):
        raise ValueError("RC10과 main에 서로 다른 Code 경로가 필요합니다.")
    record = load_json(restored / "restore-verification.json")
    hashes = dict(record["workspace_sha256"])
    if (record["archive_sha256"] != manifest["proof_archive"]["sha256"]
            or record["workspace_file_count"] != len(hashes) or len(hashes) != manifest["workspace_file_count"]):
        raise ValueError("B0 복원 결과의 보존본 SHA256 또는 파일 수가 다릅니다.")
    for member in (WORKSPACE_HASHES, *PROTOCOL):
        check_bytes((restored / member).read_bytes(), manifest["archive_members"][member], member)
    workspaces = [restored / folder for folder in ("B0", "main")]
    if any(path.resolve(strict=True) != path for path in workspaces) or workspaces[0].samefile(workspaces[1]):
        raise ValueError("B0와 main에 독립 작업 사본이 필요합니다.")

    hashes.pop(".writer.lock", None)
    results = []
    for workspace, code in zip(workspaces, (b0_code, main_code), strict=True):
        before = tree_hash(workspace)
        before.pop(".writer.lock", None)
        if before != hashes:
            raise ValueError(f"{workspace.name} 복원 직후 파일 해시가 다릅니다.")
        try:
            results.append(measure(code, workspace, manifest["replay"], client=client))
        finally:
            after = tree_hash(workspace)
            after.pop(".writer.lock", None)
            if after != before:
                raise ValueError(f"{workspace.name} 결과 조회 뒤 작업 사본이 변경됐습니다.")
    if results[0] != results[1]:
        raise ValueError("RC10과 main의 공개 API/MCP 결과 또는 정의가 다릅니다.")
    b0 = results[0]
    expected = manifest["replay"]
    verify_samples(b0["result.page"]["page"], expected, main_code / "ui/prototype/b0_samples.h")
    return {"archive_sha256": record["archive_sha256"], "project_id": expected["project_id"],
            "saved_revision": expected["saved_revision"], "saved_sha256": expected["saved_sha256"],
            "preserved_files": len(hashes), "mcp_tools": len(b0["mcp_tools"]),
            "result.describe": b0["result.describe"], "result.page": b0["result.page"]}


def main():
    """! @brief 고정 목록과 복원 경로 및 RC10 배포본 Code 경로를 사용한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("restored", type=Path)
    parser.add_argument("b0_code", type=Path)
    parser.add_argument("--client", type=Path, help="공개 API에 사용할 Windows 시제품 실행 파일")
    args = parser.parse_args()
    main_code = Path(__file__).resolve().parents[1]
    try:
        client = args.client.resolve(strict=True) if args.client is not None else None
        result = replay(load_json(args.manifest), args.restored.resolve(strict=True),
                        args.b0_code.resolve(strict=True), main_code, client=client)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"B0 결과 재생 실패: {error}\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
