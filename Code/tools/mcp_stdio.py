"""! @brief 내부 EDA 연계를 위한 한 줄 JSON MCP stdio 서버를 실행한다."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.application.canonical import canonical_bytes
from rfad.application.mcp import McpSession
from rfad.application.projects import ProjectService
from rfad.application.rpc import MAX_FRAME_BYTES, _unique_object
from rfad.catalog.service import CatalogService


def main():
    """! @brief stdout에는 프로토콜만 쓰고 GUI와 같은 workspace writer 잠금을 사용한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--cad-python", type=Path)
    parser.add_argument("--openems-wsl", action="store_true")
    options = parser.parse_args()
    from rfad.application.cad_runtime import CadRuntime
    from rfad.application.solver_runtime import SolverRuntime
    with ProjectService(options.workspace, catalog_database=options.catalog,
                        cad_runtime=CadRuntime(options.cad_python) if options.cad_python else None,
                        solver_runtime=SolverRuntime() if options.openems_wsl else None) as service:
        session = McpSession(service, CatalogService(options.catalog))
        while True:
            line = sys.stdin.buffer.readline(MAX_FRAME_BYTES + 2)
            if not line:
                break
            if len(line.rstrip(b"\r\n")) > MAX_FRAME_BYTES:
                return 2
            try:
                request = json.loads(line, object_pairs_hook=_unique_object)
                response = session.handle(request)
            except (ValueError, TypeError, RecursionError):
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            if response is not None:
                sys.stdout.buffer.write(canonical_bytes(response) + b"\n")
                sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
