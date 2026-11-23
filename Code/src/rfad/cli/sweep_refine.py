"""! @brief 명령행에서 보존한 연구의 목표 기반 후속 탐색을 실행한다."""

import argparse
import json
from pathlib import Path
import sys

from rfad.application.sweep_refinement import refine
from rfad.domain.errors import ProjectError


def main(argv=None):
    """! @brief 독점 작업 공간에서 실행 횟수를 명시한 탐색을 수행한다."""
    parser = argparse.ArgumentParser(prog="rfad sweep-refine", description="봉인된 연구에서 반복 구간 탐색")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--rounds", required=True, type=int)
    parser.add_argument("--resume", action="store_true", help="중단한 후속 연구를 이어서 실행")
    parser.add_argument("--until-target", action="store_true", help="모든 목표 표본이 통과한 후보에서 종료")
    parser.add_argument("--openems-wsl", action="store_true")
    parser.add_argument("--startup-seconds", type=int, default=60, help="WSL 시작 및 소스 전송 제한 시간")
    args = parser.parse_args(argv)
    from rfad.application.projects import ProjectService
    from rfad.application.solver_runtime import SolverRuntime

    from rfad.application.wsl_process import WslRuntime

    try:
        if args.openems_wsl:
            runtime = SolverRuntime(transport=WslRuntime(startup_timeout_seconds=args.startup_seconds))
        else:
            runtime = SolverRuntime.installed_windows() if sys.platform == "win32" else None
        with ProjectService(args.workspace, solver_runtime=runtime) as service:
            report = refine(service, args.project, args.study, args.rounds, resume=args.resume, until_target=args.until_target)
    except (OSError, ProjectError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True))
    return int(report["stop_reason"] in {"failed", "blocked", "interrupted", "cancelled", "incomplete_bracket", "invalid_bracket"})
