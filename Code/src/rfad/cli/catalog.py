"""! @brief 오프라인 카탈로그 구축과 읽기 전용 조회 CLI를 제공한다."""

import argparse
import json
from pathlib import Path
import sys


MAX_QUERY_BYTES = 64 * 1024


def _unique_object(pairs):
    """! @brief 같은 입력 키가 반복되어 필터를 덮어쓰는 경우를 거절한다."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("입력 JSON에 중복 키가 있습니다.")
        value[key] = item
    return value


def _reject_constant(value):
    """! @brief JSON 비표준 상수로 전달된 비유한 값을 거절한다."""
    raise ValueError("비유한 JSON 값은 지원하지 않습니다: " + value)


def _query(options) -> dict:
    """! @brief 크기가 제한된 명시적 검색 객체를 읽는다."""
    if options.query_file is not None:
        with options.query_file.open("rb") as stream:
            encoded = stream.read(MAX_QUERY_BYTES + 1)
    else:
        encoded = (options.query or "{}").encode("utf-8")
    if len(encoded) > MAX_QUERY_BYTES:
        raise ValueError("검색 입력은 UTF-8 65536 bytes 이하여야 합니다.")
    value = json.loads(
        encoded.decode("utf-8-sig"), object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if type(value) is not dict:
        raise ValueError("검색 입력은 JSON 객체여야 합니다.")
    return value


def _write(value: dict, stream) -> None:
    """! @brief 콘솔 코드페이지와 무관하게 UTF-8 JSON 한 개를 출력한다."""
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    binary = getattr(stream, "buffer", None)
    if binary is None:
        stream.write(text)
    else:
        binary.write(text.encode("utf-8"))
        binary.flush()


def main(argv: list[str] | None = None) -> int:
    """! @brief 선택한 오프라인 빌드 또는 조회만 실행한다."""
    parser = argparse.ArgumentParser(prog="rfad catalog")
    commands = parser.add_subparsers(dest="operation", required=True)
    build = commands.add_parser("build", help="정리된 자료에서 파생 SQLite 인덱스 생성")
    build.add_argument("--source", required=True, type=Path, help="PCB 자료 패키지 루트")
    build.add_argument("--output", required=True, type=Path, help="패키지 밖의 출력 SQLite 경로")
    build.add_argument("--replace", action="store_true", help="기존 카탈로그만 원자적으로 교체")
    status = commands.add_parser("status", help="구성 여부와 자료 개정 조회")
    status.add_argument("--database", type=Path)
    search = commands.add_parser("search", help="조건과 페이지를 지정하는 읽기 전용 검색")
    search.add_argument("--database", required=True, type=Path)
    query_input = search.add_mutually_exclusive_group()
    query_input.add_argument("--query", help="검색 서비스 input JSON 객체")
    query_input.add_argument("--query-file", type=Path, help="UTF-8 검색 input JSON 파일")
    detail = commands.add_parser("get", help="한 개체와 원문 JSON 조각 조회")
    detail.add_argument("--database", required=True, type=Path)
    detail.add_argument("--entity", required=True)
    detail.add_argument("--id", required=True)
    detail.add_argument("--catalog-id", help="검색할 때 받은 자료 개정")
    detail.add_argument("--raw-offset", default=0, type=int)
    detail.add_argument("--raw-limit", default=4096, type=int)
    options = parser.parse_args(argv)
    from rfad.catalog.models import CatalogError

    try:
        if options.operation == "build":
            from rfad.catalog.build import build_catalog

            result = build_catalog(options.source, options.output, overwrite=options.replace)
        else:
            from rfad.catalog.service import CatalogService

            service = CatalogService(options.database)
            if options.operation == "status":
                result = service.status()
            elif options.operation == "search":
                result = service.search(_query(options))
            else:
                request = {
                    "entity": options.entity, "id": options.id,
                    "raw_offset": options.raw_offset, "raw_limit": options.raw_limit,
                }
                if options.catalog_id is not None:
                    request["catalog_id"] = options.catalog_id
                result = service.get(request)
        _write(result, sys.stdout)
        return 0
    except CatalogError as error:
        _write({"error": {"code": error.code, "message": error.message, "details": error.details}}, sys.stderr)
        return 1
    except (ValueError, OSError, UnicodeError, RecursionError) as error:
        _write({"error": {"code": "E_SCHEMA", "message": str(error)}}, sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
