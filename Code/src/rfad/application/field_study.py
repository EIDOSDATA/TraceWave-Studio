"""! @brief 가장 최근 봉인 전계의 물리 구간에서 다음 PCB 국부 격자와 종료 근거를 구한다."""

from copy import deepcopy
import json
from uuid import uuid4

from rfad.application import field_study_geometry as geometry, result_fields
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.project_study_contract import MAX_STUDIES, initial_specification
from rfad.application.result_field_refine import propose
from rfad.application.result_sources import resolve, validate_source, validate_pin
from rfad.application.solver_requests import require_fields, require_uuid
from rfad.domain.errors import ProjectError


def validate(data):
    """! @brief 주파수, 성분, 영역, 허용값, 반복과 자원 상한을 명시적으로 받는다."""
    require_fields(data, {"expected_revision", "name", "source", "pin", "selection", "limits"})
    require_uuid(data["expected_revision"])
    validate_source(data["source"])
    validate_pin(data["pin"])
    if not isinstance(data["name"], str) or not 1 <= len(data["name"].strip()) <= 120:
        raise ProjectError("E_SCHEMA", "연구 이름은 1~120자여야 합니다.")
    require_fields(data["selection"], {"monitor_id", "frequency_index", "component", "plane", "roi"})
    limits = data["limits"]
    require_fields(limits, {"threshold_fraction", "max_rules", "memory_limit_mib", "max_rounds", "max_s11_complex_delta"})
    valid = all(type(limits[key]) is int and lo <= limits[key] <= hi for key, lo, hi in
                (("max_rounds", 1, 5), ("max_rules", 1, 16), ("memory_limit_mib", 128, 16384)))
    if not valid or any(type(limits[key]) not in (int, float) or not 0 < limits[key] <= 2 for key in
                        ("threshold_fraction", "max_s11_complex_delta")):
        raise ProjectError("E_SCHEMA", "반복(1~5), 규칙(1~16), 메모리(128~16384 MiB), 복소 변화와 허용값(0 초과~2)을 확인하십시오.")


def register_plan(service, state, study, index, plan):
    """! @brief 이전 전계가 도착한 뒤에만 다음 계획을 영속 큐에 등록한다."""
    path = state["projects"][study["project_id"]]["path"] + "/studies/" + study["study_id"]
    artifact = service.journal.put_immutable(f"{path}/plan-{index}.json", canonical_bytes(plan))
    ref = {"plan_id": plan["plan_id"], "content_hash": canonical_hash(plan), "artifact": artifact}
    # @brief 재사용한 기존 계획은 다른 영수증이 가리키는 원본 저장 위치를 유지한다.
    known = state["analysis_plans"].get(plan["plan_id"])
    if known is None:
        state["analysis_plans"][plan["plan_id"]] = {"project_id": study["project_id"], "reference": ref}
    elif known["project_id"] != study["project_id"] or known["reference"]["content_hash"] != ref["content_hash"]:
        raise ProjectError("E_HASH", "기존 계획의 소유자 또는 내용 해시가 다릅니다.")
    return {"settings": plan["case"]["settings"], "analysis_plan": ref, "phase": "prepare", "attempts": [],
            "resource_estimate": plan["resource_estimate"]}


def create(service, state, context, data):
    """! @brief 과거 결과의 설계/조건을 고정하며 worker가 달라졌으면 기준 격자부터 실제로 다시 푼다."""
    runtime = service.solver.runtime
    if runtime is None:
        raise ProjectError("E_UNSUPPORTED", "전계 반복 연구에 openEMS 런타임이 필요합니다.")
    if len(state["studies"]) >= MAX_STUDIES:
        raise ProjectError("E_RESOURCE", "연구 보존 상한 32개에 도달했습니다.")
    resolved = resolve(service, context, data["source"], data["pin"])
    if resolved["current_document"]["revision_id"] != data["expected_revision"]:
        raise ProjectError("E_CONFLICT", "연구를 여는 동안 현재 개정이 바뀌었습니다.")
    if not resolved.get("normalized") or not resolved.get("solver_result_id"):
        raise ProjectError("E_UNSUPPORTED", "선택한 자료에 연결된 PCB 해석 원문이 없습니다.")
    original = resolved["normalized"]["provenance"]["analysis_plan"]
    region = geometry.anchor(resolved, data["selection"])
    monitor = region["monitor_id"]
    field = result_fields._model(resolved, monitor)
    _, slab, _ = result_fields._selection(field, {**data["selection"], "stride": 1})
    _, region_ref = result_fields._read(service, resolved, field, monitor, slab)
    settings = original["case"]["settings"]
    limits = data["limits"]
    reuse = original["runtime_identity"] == runtime.identity
    plan = original if reuse else build_pcb_plan(original["source_semantics"], original["snapshot"], runtime.identity, settings)
    size = plan["resource_estimate"]["estimated_memory_bytes"]
    if size > limits["memory_limit_mib"] * 1024 ** 2:
        raise ProjectError("E_RESOURCE", "첫 격자의 예상 메모리가 지정 상한을 초과합니다.")
    spec = {"name": data["name"].strip(), "settings": deepcopy(settings),
            "port_profile": {**initial_specification()["port_profile"], "max_s11_complex_delta": limits["max_s11_complex_delta"]},
            "field_adaptive": {"seed": data["source"], "pin": data["pin"], "seed_field": region_ref,
                               "physical_region": region, "limits": deepcopy(limits), "baseline_reused": reuse}}
    identity = str(uuid4())
    study = {"study_id": identity, "project_id": context["project_id"], "name": spec["name"], "state": "ready",
             "snapshot": original["snapshot"], "specification": spec, "runtime_identity": deepcopy(runtime.identity),
             "created_at": service._now(), "current_job_id": None, "message": "기준 전계와 조건을 고정했습니다."}
    case = register_plan(service, state, study, 0, plan)
    if reuse:
        case.update(phase="done", result_id=resolved["solver_result_id"])
    definition = {key: study[key] for key in ("study_id", "snapshot", "specification", "runtime_identity")}
    definition.update(schema="rfad.field-study-definition/0.1", initial_plan=case["analysis_plan"])
    path = resolved["project"]["path"] + "/studies/" + identity
    study.update(cases=[case], definition=service.journal.put_immutable(path + "/definition.json", canonical_bytes(definition)))
    state["studies"][identity] = study
    return {"study_id": identity, "state": study["state"], "snapshot": study["snapshot"], "baseline_reused": reuse}


def _put(service, study, name, data):
    """! @brief 취소/재개의 경합에서 다른 원문을 덮어쓰지 않는 내용 주소를 사용한다."""
    return service.journal.put_immutable(f"study-artifacts/{study['study_id']}/{name}-{canonical_hash(data)}.json", canonical_bytes(data))


def _summary(pair, index, artifact):
    """! @brief 큰 주파수 표는 별도 봉인하고 연구 조회에는 최악 표본과 판정만 담는다."""
    return {"left": index-1, "right": index, "comparison": artifact, "sample_count": pair["sample_count"],
            "max_s11_complex_delta": pair["metrics"]["max_s11_complex_delta"],
            "worst_frequency_hz": pair["metrics"]["worst_s11_frequency_hz"], "passed": pair["complex_s11_passed"]}


def load_pair(service, study, index):
    """! @brief 실제 인접 결과와 원래 기준에 연결한 봉인 표본을 반환한다."""
    evidence = study["cases"][index].get("sample_evidence")
    if not evidence:
        raise ProjectError("E_CONFLICT", "두 결과의 비교가 끝나지 않았습니다.")
    pair = json.loads(service.journal.read_artifact(evidence["comparison"]))
    ids = [case["result_id"] for case in study["cases"][index-1:index+1]]
    if pair["study_id"] != study["study_id"] or pair["result_ids"] != ids or pair["source_revision"] != study["snapshot"]["revision_id"]:
        raise ProjectError("E_HASH", "격자 쌍의 원본 결과 참조가 다릅니다.")
    return pair


def advance(service, study):
    """! @brief 직전 실제 해석이 끝난 뒤 같은 mm 범위에서 국부 세분화와 다음 진행을 결정한다."""
    from rfad.application.project_study_results import read_case

    cases = study["cases"]
    if cases[-1]["phase"] != "done":
        return False
    index = len(cases) - 1
    spec = study["specification"]
    config = spec["field_adaptive"]
    limits = config["limits"]
    latest = cases[-1]
    current = read_case(service, study, latest)[0]
    if not index:
        from rfad.application.convergence import _result

        _result(current)
    mesh_hash = canonical_hash(current["mesh_statistics"]["lines_mm"])
    if index and mesh_hash != latest["refinement"]["next_mesh_sha256"]:
        raise ProjectError("E_HASH", "실제 계산에 사용한 격자와 이전 전계로 선택한 격자가 다릅니다.")
    evidence, reason = None, None
    if index:
        previous = read_case(service, study, cases[-2])[0]
        pair = geometry.compare(previous, current, spec["port_profile"])
        detail = {"study_id": study["study_id"], "source_revision": study["snapshot"]["revision_id"],
                  "result_ids": [case["result_id"] for case in cases[-2:]], "grid_mm": [case["settings"]["grid_mm"] for case in cases[-2:]],
                  "max_s11_complex_delta": limits["max_s11_complex_delta"], "rows": pair["frequency_rows"],
                  "pair_status": "passed" if pair["complex_s11_passed"] else "failed"}
        evidence = _summary(pair, index, _put(service, study, "samples", detail))
        if evidence["passed"]:
            reason = "stability_reached"
        elif index >= limits["max_rounds"]:
            reason = "round_limit"
    proposal, plan, detail = None, None, None
    if reason is None:
        source = {"kind": "solver", "artifact_id": latest["result_id"]}
        resolved = resolve(service, {"project_id": study["project_id"]}, source)
        options = {key: limits[key] for key in ("threshold_fraction", "max_rules", "memory_limit_mib")}
        actual = None
        try:
            selection, actual = geometry.selection_for(resolved, config["physical_region"])
            proposal = propose(service, resolved, {**selection, **options})
        except ProjectError as error:
            if error.code != "E_RESOURCE":
                raise
            proposal = {"status": "solver_resource_limit", "source": source, "pin": resolved["pin"],
                        "source_mesh_sha256": mesh_hash, "message": str(error), "limits": limits}
        detail = _put(service, study, "field", {**proposal, "physical_selection": actual})
        if proposal["status"] == "refined":
            original = current["provenance"]["analysis_plan"]
            plan = build_pcb_plan(original["source_semantics"], study["snapshot"], study["runtime_identity"], proposal["settings"])
        else:
            reason = proposal["status"]
    def publish(state):
        """! @brief 취소 경합은 기존 경우를 보존하고 중복 접수와 완료 승격을 피한다."""
        active = state["studies"][study["study_id"]]
        if active["state"] not in {"running", "resuming"} or len(active["cases"]) != len(cases):
            return
        if evidence is not None:
            active["cases"][-1]["sample_evidence"] = evidence
        if detail is not None:
            active["cases"][-1]["field_decision"] = detail
        if plan is not None:
            following = register_plan(service, state, active, index+1, plan)
            following["refinement"] = {"previous_result": latest["result_id"], "field": proposal["source_ref"],
                "next_mesh_sha256": proposal["next_mesh_sha256"], "source_mesh_sha256": mesh_hash,
                "rules_added": len(proposal["added_rules"]), "decision": detail}
            active["cases"].append(following)
            active["message"] = f"직전 전계로 선택한 {index+1}회차 실제 국부 격자를 해석합니다."
            return
        reasons = {"stability_reached": "모든 공통 주파수에서 복소 S11 변화 허용값 충족", "round_limit": "지정 반복 횟수 소진",
                   "memory_limit": "다음 격자 예상 메모리 초과", "rule_limit": "국부 규칙 상한 도달",
                   "no_eligible_change": "선택 영역에 변화 기준을 넘은 구간 없음", "unchanged_mesh": "추가 규칙 적용 후 격자 증가 없음",
                   "solver_resource_limit": "기록 표본 또는 해석 격자의 자원 상한 도달"}
        result = {"schema": "rfad.field-study-assessment/0.1", "study_id": active["study_id"], "snapshot": active["snapshot"],
                  "definition": active["definition"], "port_stability": "passed" if reason == "stability_reached" else "not_established",
                  "radiation_mesh_stability": "not_evaluated", "reference_energy_closure": "not_evaluated", "reference_radiation_budget": None,
                  "adaptive_mesh_decision": {"reason": reason, "completed_levels": len(cases), "max_rounds": limits["max_rounds"]},
                  "comparisons": [case["sample_evidence"] for case in active["cases"] if "sample_evidence" in case],
                  "physical_region": config["physical_region"], "scope": "observed_single_drive_s11_on_common_frequencies",
                  "physics_validated": False, "fabrication_validated": False, "measurement_validated": False}
        active.update(state="completed", assessment=_put(service, active, "assessment", result), message=reasons[reason])
    service.journal.transaction(publish)
    return True
