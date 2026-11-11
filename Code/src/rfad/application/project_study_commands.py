"""! @brief 연구 생성/명시적 재개와 조회를 journal transaction에 결합한다."""

from copy import deepcopy
import json
from uuid import uuid4

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_study_contract import ACTIVE, MAX_STUDIES, build_cases, initial_specification
from rfad.application.project_study_results import view
from rfad.domain.errors import ProjectError


def owned(service, state, context, identity):
    """! @brief 다른 프로젝트의 연구를 조회/제어하지 못하게 한다."""
    service._project(state, context)
    study = state.get("studies", {}).get(identity)
    if study is None or study["project_id"] != context["project_id"]:
        raise ProjectError("E_SCHEMA", "현재 프로젝트의 연구를 찾을 수 없습니다.")
    return study


def create(service, state, context, data):
    """! @brief 현재 원본 바이트의 snapshot과 모든 계획을 원자 등록하며 설계를 수정하지 않는다."""
    runtime = service.solver.runtime
    if runtime is None:
        raise ProjectError("E_UNSUPPORTED", "연구 생성에는 --openems-wsl 런타임이 필요합니다.")
    if len(state["studies"]) >= MAX_STUDIES:
        raise ProjectError("E_RESOURCE", "연구 보존 상한 32개에 도달했습니다.")
    project = service._project(state, context)
    raw, document = service.repository.read(project["current"])
    if document["revision_id"] != data["expected_revision"]:
        raise ProjectError("E_CONFLICT", "연구를 작성한 프로젝트 개정이 바뀌었습니다.")
    spec = deepcopy(data["specification"])
    snapshot = service.operations.snapshot(state, project, document, raw, {"description": "일반 프로젝트 연구: " + spec["name"]})
    plans, guards = build_cases(document, snapshot, runtime.identity, spec)
    identity = str(uuid4())
    cases = []
    for index, plan in enumerate(plans):
        artifact = service.journal.put_immutable(f"{project['path']}/studies/{identity}/plan-{index}.json", canonical_bytes(plan))
        ref = {"plan_id": plan["plan_id"], "content_hash": canonical_hash(plan), "artifact": artifact}
        state["analysis_plans"][plan["plan_id"]] = {"project_id": context["project_id"], "reference": ref}
        cases.append({"settings": plan["case"]["settings"], "analysis_plan": ref, "phase": "prepare", "attempts": [],
                      "resource_estimate": plan["resource_estimate"]})
    definition = {"schema": "rfad.project-study-definition/0.1", "study_id": identity,
                  "snapshot": snapshot, "specification": spec, "preflight_guards": guards,
                  "plans": [case["analysis_plan"] for case in cases], "runtime_identity": runtime.identity}
    ref = service.journal.put_immutable(f"{project['path']}/studies/{identity}/definition.json", canonical_bytes(definition))
    study = {"study_id": identity, "project_id": context["project_id"], "name": spec["name"], "state": "ready",
             "snapshot": snapshot, "specification": spec, "runtime_identity": deepcopy(runtime.identity),
             "definition": ref, "cases": cases, "created_at": service._now(), "current_job_id": None,
             "message": "스냅샷과 모든 계획을 고정했습니다. 실행을 선택하십시오."}
    state["studies"][identity] = study
    return {"study_id": identity, "state": study["state"], "snapshot": snapshot}


def control(service, state, method, context, data):
    """! @brief 실패 작업 교체는 명시적 재개에서만 허용하고 이전 시도를 보존한다."""
    if method == "study.create":
        return create(service, state, context, data)
    study = owned(service, state, context, data["study_id"])
    if method == "study.cancel":
        if study["state"] in ACTIVE:
            study["state"] = "cancel_requested"
            job = state["jobs"].get(study["current_job_id"])
            if job is not None:
                service.solver.cancel_job(job, "일반 프로젝트 연구의 명시적 취소")
            study["message"] = "현재 작업의 실제 종료를 확인한 뒤 멈춥니다."
    else:
        permitted = {"ready"} if method == "study.start" else {"cancelled", "interrupted", "failed", "blocked"}
        if study["state"] not in permitted:
            raise ProjectError("E_CONFLICT", "현재 연구 상태에서 실행/재개할 수 없습니다.")
        if any(row["study_id"] != study["study_id"] and row["state"] in ACTIVE for row in state["studies"].values()):
            raise ProjectError("E_RESOURCE", "다른 연구가 실행 중입니다.")
        if service.solver.runtime is None or service.solver.runtime.identity != study["runtime_identity"]:
            raise ProjectError("E_VERSION", "연구를 고정한 worker와 다릅니다. 원본을 보존하고 새 연구를 만드십시오.")
        if any(len(case["attempts"]) >= 24 for case in study["cases"]):
            raise ProjectError("E_RESOURCE", "사례별 24개 시도 상한에 도달했습니다.")
        study["state"] = "resuming" if method == "study.resume" else "running"
        study["message"] = "원래 snapshot/설정과 완료 결과를 보존하며 진행합니다."
    return {"study_id": study["study_id"], "state": study["state"]}


def query(service, method, context, data):
    """! @brief 계산 환경 없이도 프로젝트 소유 연구와 완료 전력을 읽는다."""
    state = service.journal.read()
    project = service._project(state, context)
    if method == "study.context":
        document = service._load(project)
        return {"project_id": context["project_id"], "revision_id": document["revision_id"],
                "runtime_configured": service.solver.runtime is not None,
                "initial_specification": initial_specification(), "material_defaults_supplied": False}
    if method == "study.list":
        return {"studies": [{key: row[key] for key in ("study_id", "name", "state", "created_at")}
                            for row in sorted(state.get("studies", {}).values(), key=lambda row: row["created_at"], reverse=True)
                            if row["project_id"] == context["project_id"]]}
    study = owned(service, state, context, data["study_id"])
    definition = json.loads(service.journal.read_artifact(study["definition"]))
    if any(definition[key] != study[key] for key in ("study_id", "snapshot", "specification", "runtime_identity")):
        raise ProjectError("E_HASH", "연구 정의의 불변 내용이 변경되었습니다.")
    return view(service, state, study)
