"""! @brief 현재 프로젝트의 봉인된 PCB 준비 자료에서 체크포인트 전용 입력을 확인한다."""

import json
from pathlib import PurePosixPath

from rfad.application.pcb_solver import PROFILE
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.errors import ProjectError


METHOD = "solver.checkpoint.sources"


def eligibility(plan):
    """! @brief 실제 준비에 사용한 사례와 계산 예산으로 전용 엔진 실행 가능 여부를 판정한다."""
    case = plan["case"]
    if plan["analysis_profile"] != PROFILE or not case.get("port") or len(case.get("ports", [case["port"]])) != 1:
        return "단일 급전 사용자 PCB 준비 입력이 필요합니다."
    if case.get("num_threads") != 1:
        return "계산 예산에서 스레드 1개를 지정하고 다시 준비하십시오."
    if any(k in case for k in ("field_recording", "radiation_recording")) or any(k in case["settings"] for k in ("field_probe", "radiation", "power_balance")):
        return "방사, 필드 및 전력 수지 기록을 끄고 다시 준비하십시오."
    return ""


def source(service, state, project_id, identity):
    """! @brief 등록한 준비/해석 계획과 원래 준비 manifest의 동일한 XML 참조를 연결한다."""
    record = state["prepared_plans"].get(identity)
    if not record or record["project_id"] != project_id:
        raise ProjectError("E_MISSING_ARTIFACT", "이 프로젝트의 준비 계획을 찾을 수 없습니다.")
    _, prepared = service.solver._record(state, "prepared_plans", record["reference"], "prepared_plan_id", project_id)
    _, plan = service.solver._record(state, "analysis_plans", prepared["analysis_plan"], "plan_id", project_id)
    if (prepared["prepared_plan_id"] != identity or prepared["analysis_plan"]["plan_id"] != record["analysis_plan_id"]
            or prepared["snapshot"] != plan["snapshot"] or plan["snapshot"]["project_id"] != project_id
            or record["preparation_artifact"] != prepared["preparation_artifact"]):
        raise ProjectError("E_HASH", "준비 자료의 설계 개정이나 소유 프로젝트가 다릅니다.")
    reason = eligibility(plan)
    row = {"prepared_plan_id": identity, "project_id": project_id, "revision_id": plan["snapshot"]["revision_id"], "reason": reason}
    if reason:
        return row
    prep = json.loads(service.journal.read_artifact(prepared["preparation_artifact"]))
    native = [f for f in record["files"] if f["role"] == "native_input"]
    if len(native) != 1 or prep.get("analysis_plan_hash") != prepared["analysis_plan"]["content_hash"]:
        raise ProjectError("E_HASH", "준비 manifest에서 원래 입력을 확인할 수 없습니다.")
    item = native[0]
    descriptor = {k: v for k, v in item.items() if k != "artifact"}
    artifact = item["artifact"]
    expected_uri = PurePosixPath(prepared["preparation_artifact"]["uri"]).with_name("pcb.xml").as_posix()
    if (descriptor not in prep["files"] or item["path"] != "output/prepared/pcb.xml" or artifact["uri"] != expected_uri
            or artifact["bytes"] != item["bytes"] or artifact["sha256"] != item["sha256"]):
        raise ProjectError("E_HASH", "준비 manifest와 게시된 XML 참조가 다릅니다.")
    service.journal.read_artifact(artifact)
    engines = [f for f in prep["runtime_identity"]["native_files"] if f["path"].endswith("/openems/0.37.0/bin/openEMS")]
    if len(engines) != 1:
        raise ProjectError("E_VERSION", "원래 준비에 사용한 openEMS 실행 파일을 확인할 수 없습니다.")
    return {**row, "xml": artifact, "engine": engines[0]["sha256"]}


def read(service, params):
    """! @brief 결과 또는 준비 번호를 현재 프로젝트에 한정하고 확인할 수 있는 준비 기록을 반환한다."""
    _fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    context = _fields(params["context"], {"project_id"})
    project_id = _uuid(context["project_id"])
    data = _fields(params["input"], set(), {"prepared_plan_id", "artifact_id"})
    state = service.journal.read()
    service._project(state, context)
    if "artifact_id" in data:
        _fields(data, {"artifact_id"})
        result = state["solver_results"].get(_uuid(data["artifact_id"]))
        if not result or result["project_id"] != project_id:
            raise ProjectError("E_MISSING_ARTIFACT", "이 프로젝트의 결과를 찾을 수 없습니다.")
        ids = [result["prepared_plan_id"]]
    elif "prepared_plan_id" in data:
        ids = [_uuid(data["prepared_plan_id"])]
    else:
        ids = [k for k, r in state["prepared_plans"].items() if r["project_id"] == project_id]
        return {"plans": ids}
    return {"sources": [source(service, state, project_id, k) for k in ids]}
