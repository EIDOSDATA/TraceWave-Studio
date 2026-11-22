"""! @brief 이름 있는 조건과 원래 해석 결과를 현재 개정에 결합해 조회한다."""

from copy import deepcopy

from rfad.application.pcb_solver import PROFILE as PCB_PROFILE, validate_settings
from rfad.application.solver_evidence import pcb_result_plan
from rfad.application.project_contract import _fields, _uuid
from rfad.domain import solver_conditions as domain
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import display_names

READ = "solver.conditions"
SAVE = "solver.conditions.save"


def validate_save(context, data):
    """! @brief 저장 요청에는 현재 개정과 명시 입력만 허용한다."""
    _fields(context, {"project_id"})
    _uuid(context["project_id"])
    _fields(data, {"expected_revision", "command_id", "name", "settings"})
    _uuid(data["expected_revision"])
    _uuid(data["command_id"])
    domain.name(data["name"])
    validate_settings(data["settings"])


def current(service, state, context, expected):
    """! @brief 현재 프로젝트와 개정의 소유를 확인한다."""
    document = service._load(service._project(state, context))
    if document["revision_id"] != expected:
        raise ProjectError("E_CONFLICT", "해석 조건 조회 또는 저장의 기준 개정이 바뀌었습니다.")
    return document


def save(service, state, context, data):
    """! @brief 숫자 설정과 당시 설계 조건을 기존 개정/영수증에 같은 변경으로 기록한다."""
    document = current(service, state, context, data["expected_revision"])
    record = {"id": data["command_id"], "name": data["name"], "revision_id": document["revision_id"],
              "settings": data["settings"], "design": domain.design_context(document)}
    return service._apply(state, context, {"expected_revision": document["revision_id"], "command_id": data["command_id"],
                        "type": domain.INSERT, "payload": {"record": record}})


def _result_settings(service, state, project_id, result_id):
    """! @brief 결과가 가리키는 봉인된 사용자 PCB 계획에서만 실행 당시 조건을 읽는다."""
    _, plan = pcb_result_plan(service, state, project_id, result_id)
    source = plan["source_semantics"]
    return {"id": result_id, "revision_id": source["revision_id"], "settings": plan["case"]["settings"],
            "design": domain.design_context(source)}


def read(service, params):
    """! @brief 조건 목록과 과거 원본의 읽기 조회는 상태나 계산 작업을 만들지 않는다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    data = _fields(params["input"], {"expected_revision"}, {"artifact_id"})
    expected = _uuid(data["expected_revision"])
    context = _fields(params["context"], {"project_id"})
    project_id = _uuid(context["project_id"])
    state = service.journal.read()
    document = current(service, state, context, expected)
    if "artifact_id" in data:
        return _result_settings(service, state, project_id, _uuid(data["artifact_id"]))
    results = [{"id": row["artifact_id"], "revision_id": row["snapshot"]["revision_id"],
                "name": row["metadata"].get("installation_name", "PCB 해석"),
                "snapshot_time": row["snapshot"]["sealed_at"]}
               for row in state["solver_results"].values()
               if row["project_id"] == project_id and row["metadata"]["profile"] == PCB_PROFILE]
    results.sort(key=lambda row: (row["snapshot_time"], row["id"]), reverse=True)
    names = display_names(document)
    targets = [{"kind": "port", "id": row["id"], "name": row["name"]} for row in document["ports"]]
    targets.extend({"kind": "via", "id": row["id"], "name": names[row["id"]]}
                   for row in document["geometry"] if row["kind"] == "via" and row["include_in_em"])
    return {"revision_id": expected, "design": domain.design_context(document),
            "saved": deepcopy(domain.records(document)), "results": results, "local_mesh_targets": targets}
