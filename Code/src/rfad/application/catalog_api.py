"""! @brief 프로젝트 변경과 분리된 읽기 전용 카탈로그 RPC 경계를 제공한다."""

from rfad.domain.errors import ProjectError


PROFILE = "rfad.catalog/0.1"
METHODS = frozenset({"catalog.status", "catalog.search", "catalog.get", "catalog.stackup_draft", "catalog.stackup_suggestions"})


def _service(catalog):
    """! @brief 요청받은 경우에만 카탈로그 모듈을 읽는다."""
    if catalog is not None:
        return catalog
    from rfad.catalog.service import CatalogService

    return CatalogService(None)


def describe(catalog=None) -> dict:
    """! @brief 프로젝트 적용이나 물리 검증을 포함하지 않는 조회 범위를 공개한다."""
    return {
        "profile": PROFILE,
        "read_only": True,
        "project_mutations": False,
        "simulation_readiness": "not_evaluated",
        "max_result_bytes": 48 * 1024,
        "status": _service(catalog).status(),
    }


def query(method: str, params: object, catalog=None) -> dict:
    """! @brief 빈 프로젝트 context와 명시적 API 버전을 가진 조회만 허용한다."""
    if type(params) is not dict or set(params) != {"contract_version", "context", "input"}:
        raise ProjectError("E_SCHEMA", "카탈로그 조회에는 contract_version, context, input이 필요합니다.")
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    if type(params["context"]) is not dict or params["context"]:
        raise ProjectError("E_SCHEMA", "카탈로그 조회의 context는 빈 객체여야 합니다.")
    if type(params["input"]) is not dict:
        raise ProjectError("E_SCHEMA", "카탈로그 input은 객체여야 합니다.")
    from rfad.catalog.models import CatalogError

    try:
        service = _service(catalog)
        if method == "catalog.status":
            if params["input"]:
                raise ProjectError("E_SCHEMA", "카탈로그 상태 조회의 input은 빈 객체여야 합니다.")
            return service.status()
        if method == "catalog.search":
            return service.search(params["input"])
        if method == "catalog.get":
            return service.get(params["input"])
        if method in ("catalog.stackup_draft", "catalog.stackup_suggestions"):
            from rfad.application.pcb_selection_build import source_draft
            from rfad.application.pcb_selection_contract import bounded, validate_source
            from rfad.catalog.selection_reader import SelectionReader

            source = params["input"]
            if method == "catalog.stackup_suggestions":
                if "source" not in source or set(source) - {"source", "offset", "limit"}:
                    raise ProjectError("E_SCHEMA", "적층 제안에는 source와 선택적 offset, limit만 허용합니다.")
                source = source["source"]
            validate_source(source)
            if source is None:
                raise ProjectError("E_SCHEMA", "적층 조회에는 명시적인 출처가 필요합니다.")
            with SelectionReader(service.repository.database, source["catalog_id"]) as reader:
                draft = source_draft(reader, source)
                if method == "catalog.stackup_suggestions":
                    from rfad.catalog.stackup_suggestions import build_stackup_suggestions

                    return bounded(build_stackup_suggestions(reader, source, draft,
                                                             offset=params["input"].get("offset", 0),
                                                             limit=params["input"].get("limit", 8)))
                return bounded(draft)
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 카탈로그 조회입니다.")
    except CatalogError as error:
        raise ProjectError(error.code, error.message, details=error.details) from error
