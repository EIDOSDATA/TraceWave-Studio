"""! @brief 저장된 사용자 PCB와 해석 조건에서 2~8포트의 복소 S 행렬을 계산한다."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from rfad.domain.errors import ProjectError


def read_input(path):
    """! @brief 일반 개정 또는 Studio 교환 ZIP의 검증된 현재 개정을 읽는다."""
    if path.name.lower().endswith(".rfad.zip"):
        from rfad.application.project_archive import MAX_ARCHIVE_BYTES, read_verified

        with path.open("rb") as stream:
            raw = stream.read(MAX_ARCHIVE_BYTES + 1)
        with read_verified(raw) as (archive, _, index):
            relative = index["project"]["current"]["uri"]
            return {"document": json.loads(archive.read("workspace/" + relative))}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("프로젝트 JSON에 개정 객체가 필요합니다.")
    return value


def main(argv=None):
    """! @brief 작성된 프로젝트와 별도 설정 또는 함께 저장한 해석 입력을 읽는다."""
    parser = argparse.ArgumentParser(prog="rfad pcb-multiport")
    parser.add_argument("project", type=Path, help="Studio .rfad.zip, 개정 JSON 또는 document/settings가 있는 JSON")
    parser.add_argument("--settings", type=Path, help="계산 조건 JSON")
    parser.add_argument("--output", required=True, type=Path, help="원본, 파형, S 행렬을 저장할 새 디렉터리")
    args = parser.parse_args(argv)
    try:
        from rfad.adapters.solvers.openems.pcb_multiport import run

        value = read_input(args.project)
        settings = json.loads(args.settings.read_text(encoding="utf-8-sig")) if args.settings else value.get("settings")
        if settings is None:
            parser.error("--settings 또는 입력 JSON의 settings가 필요합니다.")
        result = run(value.get("document", value), settings, args.output)
        print(str(result))
        return 0
    except (ProjectError, OSError, ValueError, ImportError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
