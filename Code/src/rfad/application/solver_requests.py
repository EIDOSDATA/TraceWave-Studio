"""! @brief 해석 명령의 입력 계약과 참조 검증을 실행 수명에서 분리한다."""

import math
from uuid import UUID

from rfad.application.solver import PROFILE, RUNTIME_PROFILE
from rfad.domain.errors import ProjectError

PCB_PROFILE = "rfad.openems.pcb-single-port/0.1"
SOLVER_METHODS = {"solver.plan", "solver.prepare", "job.submit"}


def require_fields(value, required, optional=()):
    """! @brief 알 수 없는 입력을 실행 옵션으로 전달하지 않는다."""
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ProjectError("E_SCHEMA", "해석 요청 필드가 유효하지 않습니다.")
    return value


def require_uuid(value):
    """! @brief 실행 식별자는 정규 UUID로 한정한다."""
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise ProjectError("E_SCHEMA", "정규 UUID가 필요합니다.") from error


def validate_reference(value, id_key):
    """! @brief 클라이언트는 등록된 ID와 내용 해시로만 입력을 선택한다."""
    require_fields(value, {id_key, "content_hash"})
    require_uuid(value[id_key])
    digest = value["content_hash"]
    if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ProjectError("E_HASH", "SHA256 참조가 유효하지 않습니다.")


def validate_solver_input(method, context, data):
    """! @brief 초기 도파관 profile과 명시적 준비 계획만 허용한다."""
    require_fields(context, {"project_id"})
    require_uuid(context["project_id"])
    if method == "solver.plan":
        require_fields(data, {"snapshot", "analysis_profile", "runtime_profile"}, {"grid_mm", "settings"})
        validate_reference(data["snapshot"], "snapshot_id")
        if data["analysis_profile"] not in (PROFILE, PCB_PROFILE) or data["runtime_profile"] != RUNTIME_PROFILE:
            raise ProjectError("E_UNSUPPORTED", "지원하는 해석 profile을 지정하십시오.")
        if data["analysis_profile"] == PROFILE:
            if "settings" in data or type(data.get("grid_mm")) not in (int, float) or data["grid_mm"] not in (1.0, 0.75):
                raise ProjectError("E_UNSUPPORTED", "참조 격자는 1.0 또는 0.75 mm입니다.")
        elif "grid_mm" in data or type(data.get("settings")) is not dict:
            raise ProjectError("E_SCHEMA", "사용자 PCB 해석에는 명시적인 settings가 필요합니다.")
    else:
        require_fields(data, {"analysis_plan", "budget"} if method == "solver.prepare" else {"task_plan", "budget"})
        require_fields(data["budget"], {"timeout_seconds"})
        timeout = data["budget"]["timeout_seconds"]
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ProjectError("E_RESOURCE", "실행 제한은 0초 초과 300초 이하여야 합니다.")
        if method == "solver.prepare":
            validate_reference(data["analysis_plan"], "plan_id")
        else:
            task = require_fields(data["task_plan"], {"kind", "prepared_plan", "execution_mode"}, {"raw_result_id"})
            validate_reference(task["prepared_plan"], "prepared_plan_id")
            if task["kind"] != "em_analysis" or task["execution_mode"] not in {"solve_and_postprocess", "postprocess_only"}:
                raise ProjectError("E_UNSUPPORTED", "지원하는 em_analysis 실행 모드를 지정하십시오.")
            if task["execution_mode"] == "postprocess_only":
                require_uuid(task.get("raw_result_id"))
            elif "raw_result_id" in task:
                raise ProjectError("E_SCHEMA", "원시 결과는 후처리 전용 작업에서만 지정합니다.")
