"""! @brief 완료 해석의 조회와 GUI 표시 DTO를 계산 실행과 분리한다."""

from copy import deepcopy
import json
import math

from rfad.application.canonical import canonical_bytes
from rfad.application.solver_requests import require_fields, require_uuid
from rfad.domain.errors import ProjectError


def open_solver_result(service, params):
    """! @brief 결과 조회는 계산을 시작하지 않고 작은 메타데이터와 파일 참조만 반환한다."""
    require_fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    require_fields(params["context"], {"project_id"})
    data = require_fields(params["input"], {"artifact_id"}, {"selection"})
    require_uuid(data["artifact_id"])
    if data.get("selection", "all") not in {"all", "normalized", "raw"}:
        raise ProjectError("E_UNSUPPORTED", "결과 선택은 all/normalized/raw를 지원합니다.")
    state = service.journal.read()
    service._project(state, params["context"])
    result = state["solver_results"].get(data["artifact_id"])
    if result is None or result["project_id"] != params["context"]["project_id"]:
        raise ProjectError("E_MISSING_ARTIFACT", "프로젝트의 봉인된 결과를 찾을 수 없습니다.")
    files = result["files"] if data.get("selection", "all") == "all" else (result["raw_files"] if data["selection"] == "raw" else [f for f in result["files"] if f["role"] == "normalized_result"])
    return {"artifact_id": result["artifact_id"], "prepared_plan_id": result["prepared_plan_id"], "metadata": deepcopy(result["metadata"]),
            "files": [{"role": f["role"], "media_type": f["media_type"], **deepcopy(f["artifact"])} for f in files]}


def latest_solver_result(service, params):
    """! @brief 프로젝트의 마지막 완료 해석만 조회하고 새 계산을 시작하지 않는다."""
    require_fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    require_fields(params["input"], set())
    state = service.journal.read()
    service._project(state, params["context"])
    candidates = [job for job in state["jobs"].values() if "solver" in job and job["kind"] == "em_analysis"
                  and job["state"] == "completed" and job["context"] == params["context"]]
    if not candidates:
        return {"profile": "rfad.solver-view/0.1", "job_id": None, "result": None}
    job = max(candidates, key=lambda item: (item["events"][-1]["timestamp"], item["job_id"]))
    return {"profile": "rfad.solver-view/0.1", "job_id": job["job_id"], "result": deepcopy(job["events"][-1]["operation_result"])}


def solver_samples(service, params):
    """! @brief 봉인된 작은 1-port 결과를 제한된 표시 DTO로 투영한다."""
    require_fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    data = require_fields(params["input"], {"artifact_id"})
    require_uuid(data["artifact_id"])
    state = service.journal.read()
    service._project(state, params["context"])
    record = state["solver_results"].get(data["artifact_id"])
    if record is None or record["project_id"] != params["context"]["project_id"]:
        raise ProjectError("E_MISSING_ARTIFACT", "프로젝트의 완료 해석 결과가 없습니다.")
    result = json.loads(service.journal.read_artifact(record["normalized"]))
    source = result.get("samples")
    if type(source) is not list or not 1 <= len(source) <= 201:
        raise ProjectError("E_RESOURCE", "현재 그래프는 최대 201개 주파수 표본을 지원합니다.")
    samples = []
    previous = 0.0
    for row in source:
        if type(row) is not dict:
            raise ProjectError("E_HASH", "봉인된 표본은 객체여야 합니다.")
        frequency = row.get("frequency_hz")
        pairs = [row.get(key) for key in ("s11", "impedance_ohm")]
        if (type(frequency) not in (int, float) or not math.isfinite(frequency) or frequency <= previous
                or any(type(pair) is not list or len(pair) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in pair) for pair in pairs)):
            raise ProjectError("E_HASH", "봉인된 표본의 주파수 또는 복소 값이 유효하지 않습니다.")
        magnitude = math.hypot(*pairs[0])
        if not math.isfinite(magnitude):
            raise ProjectError("E_HASH", "S11 크기를 유한 값으로 표시할 수 없습니다.")
        vswr = (1 + magnitude) / (1 - magnitude) if magnitude < 1 else None
        if vswr is not None and not math.isfinite(vswr):
            vswr = None
        samples.append({"frequency_hz": frequency, "s11_db": 20 * math.log10(magnitude) if magnitude > 0 else None,
            "vswr": vswr, "impedance_real_ohm": pairs[1][0], "impedance_imag_ohm": pairs[1][1]})
        previous = frequency
    snapshot = result.get("provenance", {}).get("analysis_plan", {}).get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("project_id") != params["context"]["project_id"]:
        raise ProjectError("E_HASH", "표시 결과의 원본 스냅샷을 확인할 수 없습니다.")
    dto = {"profile": "rfad.solver-chart/0.1", "artifact_id": record["artifact_id"], "snapshot": snapshot,
           "metadata": deepcopy(record["metadata"]), "samples": samples}
    if len(canonical_bytes(dto)) > 60 * 1024:
        raise ProjectError("E_RESOURCE", "해석 그래프 DTO가 전송 상한을 초과했습니다.")
    return dto
