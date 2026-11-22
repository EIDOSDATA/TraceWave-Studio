"""! @brief 실행 작업을 접수하기 전에 같은 PCB 계획 코드로 자원을 예상한다."""

from rfad.application.project_contract import _fields, _uuid
from rfad.domain.errors import ProjectError


METHOD = "solver.preview"


def read(service, params):
    """! @brief 영속 스냅샷을 쓰지 않고 현재 개정의 예상치를 반환한다."""
    from rfad.application.pcb_solver import build_pcb_plan

    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    data = _fields(params["input"], {"expected_revision", "settings"})
    expected = _uuid(data["expected_revision"])
    state = service.journal.read()
    project = service._project(state, params["context"])
    raw, document = service.repository.read(project["current"])
    if document["revision_id"] != expected:
        raise ProjectError("E_CONFLICT", "해석 입력이 바뀌었습니다. 조건을 다시 확인하세요.")
    runtime = service.solver.runtime
    if runtime is None:
        raise ProjectError("E_UNSUPPORTED", "openEMS 실행 환경의 연결을 확인하세요.")
    snapshot = service.operations.prepare_snapshot(state, project, document, raw, {})
    plan = build_pcb_plan(document, snapshot, runtime.identity, data["settings"])
    return {"revision_id": expected, "estimated": plan["resource_estimate"],
            "omissions": plan.get("physical_setup_omissions", {}),
            "outputs": plan.get("outputs", []), "settings": plan["case"]["settings"]}
