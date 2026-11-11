"""! @brief 환경 진단, 프로젝트 서비스와 오프라인 카탈로그 진입점을 제공한다."""

import argparse


def main(argv: list[str] | None = None) -> int:
    """! @brief 선택한 명령의 모듈만 로딩한다.
    @param argv 명령행 인수이며 생략하면 현재 프로세스 인수를 사용한다.
    @return 명령 실행 종료 코드.
    """
    parser = argparse.ArgumentParser(prog="rfad")
    parser.add_argument("command", choices=("doctor", "serve", "catalog"))
    args, remainder = parser.parse_known_args(argv)
    if args.command == "doctor":
        from rfad.cli.doctor import main as doctor_main

        return doctor_main(remainder)
    if args.command == "catalog":
        from rfad.cli.catalog import main as catalog_main

        return catalog_main(remainder)
    from pathlib import Path
    serve_parser = argparse.ArgumentParser(prog="rfad serve")
    serve_parser.add_argument("--workspace", type=Path, help="프로젝트 journal을 관리할 작업 영역")
    serve_parser.add_argument("--catalog", type=Path, help="선택적으로 연결할 읽기 전용 PCB 카탈로그 SQLite 파일")
    serve_parser.add_argument("--cad-python", type=Path, help="격리 CAD worker의 고정 Python 실행 파일")
    serve_parser.add_argument("--openems-wsl", action="store_true", help="TraceWave-Dev의 검증된 openEMS 참조 worker 사용")
    options = serve_parser.parse_args(remainder)
    from rfad.application.rpc import serve
    import sys

    catalog = None
    if options.catalog is not None:
        from rfad.catalog.service import CatalogService

        catalog = CatalogService(options.catalog)

    if options.workspace is None:
        if options.cad_python is not None or options.openems_wsl:
            serve_parser.error("native worker 설정에는 --workspace가 필요합니다.")
        return serve(sys.stdin.buffer, sys.stdout.buffer, sys.stderr, catalog=catalog)
    from rfad.application.projects import ProjectService
    from rfad.domain.errors import ProjectError
    from rfad.application.cad_jobs import CadRuntime
    from rfad.application.solver_jobs import SolverRuntime
    try:
        runtime = None if options.cad_python is None else CadRuntime(options.cad_python)
        solver_runtime = SolverRuntime() if options.openems_wsl else None
        with ProjectService(options.workspace, cad_runtime=runtime, solver_runtime=solver_runtime) as service:
            return serve(sys.stdin.buffer, sys.stdout.buffer, sys.stderr, service, catalog)
    except (ProjectError, OSError, ValueError) as error:
        print(f"{getattr(error, 'code', 'E_SCHEMA')}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
