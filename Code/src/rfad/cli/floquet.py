"""! @brief JSON 입력에서 Floquet 단위셀 회절 해석을 실행한다."""

import argparse
import json
import os
from pathlib import Path
import sys

from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError
from rfad.domain.floquet import solve


def main(argv=None):
    """! @brief 원본 파일을 읽고 정규 결과를 stdout으로 내보낸다."""
    parser = argparse.ArgumentParser(prog="rfad floquet")
    parser.add_argument("input", type=Path, help="일차원 유전체 주기셀 JSON")
    args = parser.parse_args(argv)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    try:
        with args.input.open("rb") as stream:
            raw = stream.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise ValueError("Floquet 입력은 64 KiB까지 지원합니다.")
        result = solve(json.loads(raw))
        sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    except (OSError, ValueError, ProjectError) as error:
        print(f"{getattr(error, 'code', 'E_SCHEMA')}: {error}", file=sys.stderr)
        return 1
    return 0
