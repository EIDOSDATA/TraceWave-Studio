"""! @brief 봉인된 목표 평가를 이용해 공통 예산 안에서 반복적으로 구간을 좁힌다."""

from copy import deepcopy
import time
from uuid import uuid4

from rfad.application import design_sweep_service as sweep
from rfad.application.design_sweep_store import ACTIVE
from rfad.domain.design_sweep import _indices
from rfad.domain.errors import ProjectError


def bracket(study, proposal):
    """! @brief 한 축의 검증된 양 끝과 새 중점을 같은 개정에서 다시 계산한다."""
    spec = deepcopy(proposal["specification"])
    original = study["specification"]
    axis = next(i for i, var in enumerate(original["variables"])
                if all(var[key] == proposal["axis"][key] for key in ("kind", "id")))
    values = original["variables"][axis]["values"]
    ends = [values[_indices(original, proposal[key])[axis]] for key in ("basis_ordinal", "neighbor_ordinal")]
    middle, = spec["variables"][axis]["values"]
    spec["variables"][axis]["values"] = sorted([*ends, middle], key=lambda item: item["value_si"])
    return spec


def refine(service, project_id, seed_id, rounds, *, resume=False, until_target=False, wait=time.sleep, preview_only=False):
    """! @brief 기존 후속 연구를 찾아 이어가며 각 회차의 후보, 계산, 디스크, 시간을 누적한다."""
    if type(rounds) is not int or not 1 <= rounds <= 42:
        raise ProjectError("E_RESOURCE", "탐색 횟수는 1~42회여야 합니다.")

    context = service if preview_only else service.host_calculation_context

    def call(method, data, *, mutation=False):
        """! @brief 같은 프로젝트 소유권 및 변경 영수증 경계를 사용한다."""
        params = {"contract_version": "rfad.api/2.0", "context": {"project_id": project_id}, "input": data}
        if mutation:
            if preview_only:
                raise RuntimeError("검토 중 변경 요청을 보낼 수 없습니다.")
            params.update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
            return service.mutate("sweep." + method, params)
        return sweep.read(context, "sweep." + method, params)

    def get(identity):
        """! @brief 연구 상태와 사용 예산의 일관된 사본을 읽는다."""
        return call("get", {"study_id": identity})

    seed = get(seed_id)
    if seed["state"] != "completed" or not seed["specification"]["target_ids"]:
        raise ProjectError("E_CONFLICT", "목표 표본을 계산한 완료 연구를 선택하십시오.")
    def meets_goals(identity):
        """! @brief 봉인된 후보 하나가 모든 선택 목표의 유효 표본을 통과했는지 확인한다."""
        rows = call("rank", {"study_id": identity})["items"]
        return any(row["target_scores"] and all(score == 1 for score in row["target_scores"]) for row in rows)

    budget = deepcopy(seed["specification"]["budget"])
    current = seed
    history = []
    outcome = {"seed_study_id": seed_id, "iterations": history, "stop_reason": "round_limit"}
    if until_target and meets_goals(seed_id):
        return {**outcome, "stop_reason": "sample_targets_met"}
    for iteration in range(1, rounds + 1):
        if budget["max_candidates"] < 3 or budget["disk_bytes"] <= 0 or budget["wall_seconds"] <= 0:
            outcome["stop_reason"] = "budget_exhausted"
            break
        if seed["type"] != "circuit_sweep" and budget["max_native_solves"] < 3:
            outcome["stop_reason"] = "native_solve_budget"
            break
        parent = current["study_id"]
        ranked = call("rank", {"study_id": parent, "suggest_next": True})
        proposal = ranked["next_candidate"]
        if proposal["status"] != "proposed":
            outcome["stop_reason"] = proposal["status"]
            break
        spec = bracket(current, proposal)
        spec["name"] = f"구간 탐색 {iteration} / {parent}"
        spec["source_refs"] = [*seed["specification"]["source_refs"],
                               f"TraceWave 탐색 원본 {seed_id} / 부모 {parent}",
                               *proposal["assessment_sha256"]]
        spec["budget"] = {**budget, "max_candidates": 3}
        existing = [item for item in call("list", {})["studies"] if item["name"] == spec["name"]]
        children = [child for item in existing if (child := get(item["study_id"]))["original_specification"] == spec]
        if len(children) > 1:
            raise ProjectError("E_CONFLICT", "같은 입력의 후속 연구가 여러 개입니다.")
        if children:
            child, = children
        else:
            if current["stop_reason"]:
                raise ProjectError("E_VERSION", current["stop_reason"])
            if not current["source_revision_matches_current"]:
                raise ProjectError("E_CONFLICT", "설계가 바뀌었습니다. 원본 개정을 복원한 뒤 탐색을 계속하십시오.")
            inputs = {"expected_revision": proposal["revision_id"], "specification": spec}
            review = call("preview", inputs)
            if review["counts"]["valid"] != 3 or review["counts"]["duplicates"]:
                outcome["stop_reason"] = "invalid_bracket"
                break
            create_input = {**inputs, "review_hash": review["review_hash"]}
            if preview_only:
                return {**outcome, "stop_reason": "create", "input": create_input}
            child = get(call("create", create_input, mutation=True)["study_id"])
        ref = {"study_id": child["study_id"]}
        record = {**ref, "parent_id": parent, "assessment_sha256": proposal["assessment_sha256"],
                  "axis": proposal["axis"], "midpoint": proposal["text"], "unit": proposal["unit"]}
        history.append(record)
        if preview_only and child["state"] != "completed":
            if child["state"] == "ready":
                action = "start"
            elif child["state"] in ACTIVE:
                action = "wait"
            elif resume and child["allowed_actions"]["resume"]:
                action = "resume"
            else:
                action = child["state"]
            return {**outcome, "stop_reason": action, "input": ref}
        try:
            if child["state"] == "ready":
                call("start", ref, mutation=True)
            elif resume and child["allowed_actions"]["resume"]:
                call("resume", ref, mutation=True)
            child = get(ref["study_id"])
            while child["state"] in ACTIVE:
                wait(0.3)
                child = get(ref["study_id"])
        except KeyboardInterrupt:
            child = get(ref["study_id"])
            if child["allowed_actions"]["cancel"]:
                call("cancel", ref, mutation=True)
            raise
        record.update(state=child["state"], usage=child["budget_usage"])
        if child["state"] != "completed":
            outcome["stop_reason"] = child["state"]
            break
        if child["counts"]["completed"] != 3:
            outcome["stop_reason"] = "incomplete_bracket"
            break
        if until_target and meets_goals(child["study_id"]):
            outcome["stop_reason"] = "sample_targets_met"
            break
        budget["max_candidates"] -= child["counts"]["total"]
        for key, used in (("wall_seconds", "wall_seconds"), ("disk_bytes", "disk_bytes"),
                          ("max_native_solves", "native_solves")):
            budget[key] -= child["budget_usage"][used]
        current = child
    return outcome
