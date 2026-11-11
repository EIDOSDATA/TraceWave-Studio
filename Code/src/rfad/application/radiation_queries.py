"""! @brief 봉인된 PCB 방사 결과를 계산 없이 페이지 단위로 조회한다."""

from copy import deepcopy
import json

from rfad.application.canonical import canonical_bytes
from rfad.application.pcb_radiation import validate_result, summary
from rfad.application.solver_requests import require_fields, require_uuid
from rfad.domain.errors import ProjectError


def radiation_chart(service, params):
    """! @brief 한 주파수의 최대 5개 theta 행만 반환하고 복소 필드를 보존한다."""
    require_fields(params, {"contract_version", "context", "input"})
    if params["contract_version"] != "rfad.api/2.0":
        raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
    require_fields(params["context"], {"project_id"})
    data = require_fields(params["input"], {"artifact_id"}, {"frequency_index", "theta_offset", "theta_limit"})
    require_uuid(data["artifact_id"])
    frequency, offset, limit = (data.get(key, default) for key, default in (("frequency_index", 0), ("theta_offset", 0), ("theta_limit", 5)))
    if any(type(value) is not int for value in (frequency, offset, limit)) or not 0 <= frequency < 3 or offset < 0 or not 1 <= limit <= 5:
        raise ProjectError("E_RESOURCE", "주파수 인덱스와 theta 페이지 범위를 확인하십시오.")
    state = service.journal.read()
    service._project(state, params["context"])
    record = state["solver_results"].get(data["artifact_id"])
    if record is None or record["project_id"] != params["context"]["project_id"]:
        raise ProjectError("E_MISSING_ARTIFACT", "프로젝트의 완료 해석 결과가 없습니다.")
    artifact = next((item["artifact"] for item in record["files"] if item["role"] == "radiation_result"), None)
    if artifact is None:
        raise ProjectError("E_MISSING_ARTIFACT", "이 결과에는 NF2FF 기록이 없습니다. 방사 기록을 선택한 새 해석이 필요합니다.")
    normalized = json.loads(service.journal.read_artifact(record["normalized"]))
    plan = normalized["provenance"]["analysis_plan"]
    value = json.loads(service.journal.read_artifact(artifact))
    validate_result(plan, value)
    snapshot = plan["snapshot"]
    if snapshot["project_id"] != params["context"]["project_id"] or normalized.get("radiation_summary") != summary(value):
        raise ProjectError("E_HASH", "방사 결과의 스냅샷 또는 요약이 다릅니다.")
    recording = value["recording"]
    count = len(recording["theta_deg"])
    if frequency >= len(value["frequencies"]) or offset >= count:
        raise ProjectError("E_RESOURCE", "기록한 주파수 또는 각도 범위를 벗어났습니다.")
    row = value["frequencies"][frequency]
    stop = min(offset + limit, count)
    result = {"profile": "rfad.radiation-chart/0.1", "artifact_id": record["artifact_id"], "snapshot": deepcopy(snapshot),
              "frequency_hz": recording["frequency_hz"], "frequency_index": frequency, "theta_offset": offset,
              "theta_count": count, "returned_count": stop - offset, "next_offset": stop if stop < count else None,
              "theta_deg": recording["theta_deg"][offset:stop], "phi_deg": recording["phi_deg"],
              "metrics": deepcopy(row["metrics"]), "radius_m": recording["radius_m"], "center_m": recording["center_m"],
              "power_unit": value["power_unit"], "electric_field_unit": value["electric_field_unit"],
              "absolute_power_w": None, "physics_validated": False, "status": "computed_unvalidated"}
    for key in ("e_theta", "e_phi", "normalized_power", "directivity"):
        result[key] = row[key][offset:stop]
    if len(canonical_bytes(result)) > 128 * 1024:
        raise ProjectError("E_RESOURCE", "방사 패턴 페이지가 전송 상한을 초과했습니다.")
    return result
