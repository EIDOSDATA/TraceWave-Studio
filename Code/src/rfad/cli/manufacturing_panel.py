"""! @brief ODB++ 원본에서 반복 패널을 만들거나 기존 배치, 원문 해시와 제외 사유를 확인한다."""

import argparse
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from rfad.adapters.exchange.odb_panel import build
from rfad.adapters.exchange.odb_reader import MAX_EXPANDED, read
from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError


def main(argv=None):
    """! @brief 사용자 입력을 확인하고 이미 존재하는 원본이나 출력 파일을 보존한다."""
    parser = argparse.ArgumentParser(prog="rfad manufacturing-panel")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--count", nargs=2, type=int, metavar=("NX", "NY"))
    parser.add_argument("--pitch-mm", nargs=2, type=float, metavar=("DX", "DY"))
    parser.add_argument("--margin-mm", type=float)
    args = parser.parse_args(argv)
    flags = (args.output, args.count, args.pitch_mm, args.margin_mm)
    if any(value is not None for value in flags) and any(value is None for value in flags):
        parser.error("출력에는 --output, --count, --pitch-mm, --margin-mm가 모두 필요합니다.")
    try:
        with args.source.open("rb") as source:
            raw = source.read(MAX_EXPANDED + 1)
        if len(raw) > MAX_EXPANDED:
            raise ProjectError("E_RESOURCE", "ODB++ 파일이 64 MiB를 넘습니다.")
        if args.output is not None:
            raw = build(raw, args.count, args.pitch_mm, args.margin_mm)
            with TemporaryDirectory(prefix=".tracewave-panel-", dir=args.output.parent) as folder:
                staged = Path(folder) / "panel.zip"
                staged.write_bytes(raw)
                if os.name == "nt":
                    staged.rename(args.output)
                else:
                    os.link(staged, args.output)
        info = read(raw)
        sys.stdout.buffer.write(canonical_bytes({key: info[key] for key in
                                ("source_sha256", "steps", "panels", "panel_exclusions")}) + b"\n")
    except (OSError, ProjectError, ValueError) as error:
        print(f"{getattr(error, 'code', 'E_SCHEMA')}: {error}", file=sys.stderr)
        return 1
    return 0
