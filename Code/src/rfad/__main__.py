"""! @brief 환경 진단, 프로젝트 서비스와 오프라인 카탈로그 진입점을 제공한다."""

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    """! @brief 선택한 명령의 모듈만 로딩한다.
    @param argv 명령행 인수이며 생략하면 현재 프로세스 인수를 사용한다.
    @return 명령 실행 종료 코드.
    """
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] in ("floquet", "waveguide-modes"):
        from rfad.cli.em_case import main as em_case_main

        return em_case_main(arguments[1:], mode=arguments[0])
    if arguments[:1] == ["field-study"]:
        from rfad.cli.field_study import main as field_study_main

        return field_study_main(arguments[1:])
    if arguments[:1] == ["sweep-refine"]:
        from rfad.cli.sweep_refine import main as refine_main

        return refine_main(arguments[1:])
    if arguments[:1] == ["pcb-multiport"]:
        from rfad.cli.pcb_multiport import main as multiport_main

        return multiport_main(arguments[1:])
    if arguments[:1] == ["archive"]:
        from rfad.cli.archive import main as archive_main

        return archive_main(arguments[1:])
    if arguments[:1] == ["altium-drill-copy"]:
        from rfad.cli.altium_drill_copy import main as altium_drill_main

        return altium_drill_main(arguments[1:])
    parser = argparse.ArgumentParser(prog="rfad")
    parser.add_argument("command", choices=("doctor", "serve", "catalog", "archive", "altium-drill-copy", "pcb-multiport", "sweep-refine", "field-study", "floquet", "waveguide-modes"))
    args, remainder = parser.parse_known_args(arguments)
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
    serve_parser.add_argument("--exchange-python", type=Path, help="격리 도면 출력 worker의 고정 Python 실행 파일")
    serve_parser.add_argument("--openems-wsl", action="store_true", help="TraceWave-Dev의 검증된 openEMS 참조 worker 사용")
    options = serve_parser.parse_args(remainder)
    if os.name == "nt" and options.workspace is not None:
        # @brief Windows 서비스의 작은 수치 조회가 OpenBLAS 전체 코어 버퍼를 예약하지 않게 한다.
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    from rfad.application.rpc import serve

    catalog = None
    if options.catalog is not None:
        from rfad.catalog.service import CatalogService

        catalog = CatalogService(options.catalog)

    if options.workspace is None:
        if options.cad_python is not None or options.exchange_python is not None or options.openems_wsl:
            serve_parser.error("native worker 설정에는 --workspace가 필요합니다.")
        return serve(sys.stdin.buffer, sys.stdout.buffer, sys.stderr, catalog=catalog)
    from rfad.application.projects import ProjectService
    from rfad.domain.errors import ProjectError
    from rfad.application.cad_jobs import CadRuntime
    from rfad.application.solver_jobs import SolverRuntime
    from rfad.application.exchange_runtime import ExchangeRuntime
    initialized = False
    try:
        runtime = None if options.cad_python is None else CadRuntime(options.cad_python)
        exchange_runtime = None if options.exchange_python is None else ExchangeRuntime(options.exchange_python)
        solver_runtime = SolverRuntime() if options.openems_wsl else None
        with ProjectService(options.workspace, cad_runtime=runtime, exchange_runtime=exchange_runtime, solver_runtime=solver_runtime,
                            catalog_database=options.catalog) as service:
            initialized = True
            return serve(sys.stdin.buffer, sys.stdout.buffer, sys.stderr, service, catalog)
    except (ProjectError, OSError, ValueError) as error:
        print(f"{getattr(error, 'code', 'E_SCHEMA')}: {error}", file=sys.stderr)
        if not initialized:
            code = getattr(error, "code", "E_DISK" if isinstance(error, OSError) else "E_SCHEMA")
            if code in ("E_HASH", "E_DISK", "E_CONFLICT", "E_SCHEMA"):
                print(f"RFAD_WORKSPACE_START:{code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
