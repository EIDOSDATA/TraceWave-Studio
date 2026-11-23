"""! @brief 정규 JSON 입력에서 독립 전자기 해석을 실행한다."""

import argparse
import json
import os
from pathlib import Path
import sys

from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError


def main(argv=None, *, mode="floquet"):
    """! @brief 원본 파일을 읽고 정규 결과를 stdout으로 내보낸다."""
    if mode == "waveguide-modes":
        from rfad.domain.waveguide_modes import solve
        description = "직사각형 도파관 폭 불연속의 TE 모드 결합"
    elif mode == "waveguide-section":
        from rfad.domain.waveguide_section import solve
        description = "공통 삼각 단면을 가진 PEC 도파관의 TE/TM 모드 결합"
    elif mode == "pcb-floquet":
        from rfad.domain.pcb_floquet import solve
        description = "동박 적층 단위셀의 X/Y Floquet 회절과 흡수"
    else:
        from rfad.domain.floquet import solve
        description = "일차원 유전체 주기셀의 Floquet 회절"
    parser = argparse.ArgumentParser(prog=f"rfad {mode}", description=description)
    parser.add_argument("input", type=Path, help="JSON 입력 파일")
    if mode == "pcb-floquet":
        parser.add_argument("--settings", type=Path, help="저장 개정 또는 교환 ZIP의 주기 해석 설정 JSON")
    args = parser.parse_args(argv)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    try:
        settings_path = getattr(args, "settings", None)
        if settings_path is None:
            limit = 4 * 1024 * 1024 if mode == "waveguide-section" else 64 * 1024
            result = solve(_read_json(args.input, limit))
        else:
            from rfad.application.pcb_periodic import project_case
            from rfad.cli.pcb_multiport import read_input

            revision = read_input(args.input)
            case, provenance = project_case(revision.get("document", revision), _read_json(settings_path))
            result = {**solve(case), "project_source": provenance}
        sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    except (OSError, ValueError, ProjectError) as error:
        print(f"{getattr(error, 'code', 'E_SCHEMA')}: {error}", file=sys.stderr)
        return 1
    return 0

def _read_json(path, limit=64 * 1024):
    """! @brief 작은 독립 해석 입력의 원문 JSON을 읽는다."""
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"해석 입력은 {limit // 1024} KiB까지 지원합니다.")
    return json.loads(raw)
