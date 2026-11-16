"""! @brief 반복 연구의 실행 입력을 불변 참조로 저장하고 실행 직전에 검증한다."""

from copy import deepcopy
import json

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError


PROFILE = "rfad.solver-capture/0.1"


def compact_capture(journal, base, job, *, prepared_reference=None, preparation_artifact=None):
    """! @brief 기존 실행 본문과 같은 입력을 작은 journal 참조로 치환한다."""
    captured = deepcopy(job["solver"])
    if job["operation_method"] == "solver.plan":
        raise ProjectError("E_UNSUPPORTED", "연구 실행 캡처는 이미 봉인한 계획만 받습니다.")
    captured.pop("analysis_plan")
    if "prepared_plan" in captured:
        captured.pop("prepared_plan")
        captured.pop("preparation")
        captured["prepared_plan_ref"] = deepcopy(prepared_reference)
        captured["preparation_artifact"] = deepcopy(preparation_artifact)
    payload = {"schema": PROFILE, "job_id": job["job_id"], "run_id": job["run_id"],
               "context": deepcopy(job["context"]), "kind": job["kind"],
               "operation_method": job["operation_method"], "input_hash": canonical_hash(job["input"]),
               "captured": captured}
    reference = journal.put_immutable(base + "/capture.json", canonical_bytes(payload))
    return {"capture_profile": PROFILE, "capture": reference, "nonce": captured["nonce"],
            "runtime_identity_hash": canonical_hash(captured["runtime"]),
            "runtime_transport": deepcopy(captured["runtime"]["transport"]),
            "resource_reserved": captured["resource_reserved"]}


def _read(journal, reference):
    """! @brief 파일 해시와 정규 JSON 바이트를 모두 확인한다."""
    raw = journal.read_artifact(reference)
    try:
        value = json.loads(raw)
        if canonical_bytes(value) != raw:
            raise ValueError("noncanonical")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ProjectError("E_HASH", "해석 실행 입력의 정규 JSON을 확인할 수 없습니다.") from error


def _plan(journal, reference, identity_key):
    """! @brief 계획의 파일 해시와 식별자 및 정규 내용 해시를 구분해 검증한다."""
    value = _read(journal, reference["artifact"])
    if value.get(identity_key) != reference[identity_key] or canonical_hash(value) != reference["content_hash"]:
        raise ProjectError("E_HASH", "실행 계획의 식별자 또는 내용 해시가 다릅니다.")
    return value


def hydrate_job(journal, job):
    """! @brief 구형 inline 작업을 유지하고 새 참조 작업만 메모리에서 복원한다."""
    current = job["solver"]
    if "capture_profile" not in current:
        return deepcopy(job)
    if current["capture_profile"] != PROFILE:
        raise ProjectError("E_VERSION", "지원하지 않는 실행 입력 참조 profile입니다.")
    payload = _read(journal, current["capture"])
    expected = {"schema": PROFILE, "job_id": job["job_id"], "run_id": job["run_id"],
                "context": job["context"], "kind": job["kind"],
                "operation_method": job["operation_method"], "input_hash": canonical_hash(job["input"])}
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ProjectError("E_HASH", "실행 입력 참조와 작업 소유 정보가 다릅니다.")
    captured = payload["captured"]
    if (captured["nonce"] != current["nonce"]
            or canonical_hash(captured["runtime"]) != current["runtime_identity_hash"]
            or captured["runtime"]["transport"] != current["runtime_transport"]):
        raise ProjectError("E_HASH", "실행 입력의 nonce 또는 runtime 식별자가 다릅니다.")
    plan = _plan(journal, captured["analysis_plan_ref"], "plan_id")
    if plan["snapshot"]["project_id"] != job["context"]["project_id"] or plan["runtime_identity"] != captured["runtime"]:
        raise ProjectError("E_HASH", "실행 계획의 소유 프로젝트 또는 runtime이 다릅니다.")
    snapshot = _read(journal, plan["snapshot"]["artifact"])
    if canonical_hash(snapshot) != plan["snapshot"]["content_hash"] or snapshot["revision_id"] != plan["snapshot"]["revision_id"]:
        raise ProjectError("E_HASH", "실행 계획의 원본 스냅샷이 변경되었습니다.")
    captured["analysis_plan"] = plan
    if job["operation_method"] == "solver.prepare":
        requested = job["input"]["analysis_plan"]
        if any(captured["analysis_plan_ref"][key] != requested[key] for key in ("plan_id", "content_hash")):
            raise ProjectError("E_HASH", "준비 요청과 실행 계획이 다릅니다.")
    else:
        prepared = _plan(journal, captured["prepared_plan_ref"], "prepared_plan_id")
        if (prepared.get("analysis_plan") != captured["analysis_plan_ref"]
                or prepared.get("snapshot") != plan["snapshot"]
                or prepared.get("preparation_artifact") != captured["preparation_artifact"]
                or prepared.get("runtime_identity") != captured["runtime"]):
            raise ProjectError("E_HASH", "준비 계획의 원본/해석 계획/runtime 결합이 다릅니다.")
        requested = job["input"]["task_plan"]["prepared_plan"]
        if any(captured["prepared_plan_ref"][key] != requested[key] for key in ("prepared_plan_id", "content_hash")):
            raise ProjectError("E_HASH", "계산 요청과 준비 계획이 다릅니다.")
        preparation = _read(journal, captured["preparation_artifact"])
        if (preparation.get("analysis_plan_id") != plan["plan_id"]
                or preparation.get("analysis_plan_hash") != captured["analysis_plan_ref"]["content_hash"]):
            raise ProjectError("E_HASH", "준비 산출물과 해석 계획이 다릅니다.")
        captured.update(prepared_plan=prepared, preparation=preparation)
    captured.update(current)
    result = deepcopy(job)
    result["solver"] = captured
    return result
