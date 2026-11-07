"""! @brief 환경 진단과 읽기 전용 서비스 진입점을 제공한다."""

import argparse


def main(argv: list[str] | None = None) -> int:
    """! @brief 선택한 명령의 모듈만 로딩한다.
    @param argv 명령행 인수이며 생략하면 현재 프로세스 인수를 사용한다.
    @return 명령 실행 종료 코드.
    """
    parser = argparse.ArgumentParser(prog="rfad")
    parser.add_argument("command", choices=("doctor", "serve"))
    args, remainder = parser.parse_known_args(argv)
    if args.command == "doctor":
        from rfad.cli.doctor import main as doctor_main

        return doctor_main(remainder)
    from pathlib import Path
    serve_parser = argparse.ArgumentParser(prog="rfad serve")
    serve_parser.add_argument("--workspace", type=Path, help="프로젝트 journal을 관리할 작업 영역")
    options = serve_parser.parse_args(remainder)
    from rfad.application.rpc import serve
    import sys

    if options.workspace is None:
        return serve(sys.stdin.buffer, sys.stdout.buffer, sys.stderr)
    from rfad.application.projects import ProjectService
    from rfad.domain.errors import ProjectError
    try:
        with ProjectService(options.workspace) as service:
            return serve(sys.stdin.buffer, sys.stdout.buffer, sys.stderr, service)
    except ProjectError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
