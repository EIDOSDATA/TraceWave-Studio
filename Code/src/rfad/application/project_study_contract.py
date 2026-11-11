"""! @brief 일반 프로젝트 연구의 유한 입력과 원본 보존 계획을 정의한다."""

from copy import deepcopy
import math

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import build_pcb_plan, validate_settings
from rfad.application.solver_requests import require_fields, require_uuid
from rfad.application.radiation_study import validate_profile
from rfad.application.radiation_study_guards import plan_guards
from rfad.domain.errors import ProjectError


MUTATIONS = {"study.create", "study.start", "study.cancel", "study.resume"}
READS = {"study.context", "study.list", "study.get"}
ACTIVE = {"running", "cancel_requested", "resuming"}
MAX_STUDIES = 32


def initial_specification():
    """! @brief 물성을 채우지 않는 명시적 초기 수치 제안을 화면에 제공한다."""
    return {"name": "PCB 격자 연구", "grid_levels_mm": [0.5, 0.45, 0.4],
            "settings": {"frequency_hz": {"start": 2.4e9, "stop": 2.4835e9, "count": 201},
                         "grid_mm": 0.4, "air_padding_mm": 90, "curve_tolerance_mm": 0.025,
                         "max_timesteps": 100000, "end_criterion": 1e-5,
                         "mesh_policy": {"kind": "graded_air", "air_cell_mm": 6, "growth_ratio": 1.5}},
            "port_profile": {"id": "project-mesh-initial/0.1", "minimum_levels": 3,
                             "max_s11_complex_delta": 0.02, "max_resonance_relative_shift": 0.01},
            "radiation_profile": {"id": "project-radiation-mesh-initial/0.1", "minimum_levels": 3,
                                  "max_pattern_delta": 0.02, "max_radiated_relative_delta": 0.02,
                                  "max_directivity_delta_db": 0.1, "max_gain_delta_db": 0.1,
                                  "max_efficiency_delta": 0.02, "max_s11_complex_delta": 0.02,
                                  "max_sphere_relative_error": 0.03, "max_passivity_excess": 0.01,
                                  "max_port_balance_relative_error": 1e-8}}


def validate_specification(spec):
    """! @brief 계산 완료와 수렴 판정을 구분하며 모든 설정/기준을 생성 시 고정한다."""
    require_fields(spec, {"name", "grid_levels_mm", "settings", "port_profile", "radiation_profile"})
    if type(spec["name"]) is not str or not 1 <= len(spec["name"].strip()) <= 120:
        raise ProjectError("E_SCHEMA", "연구 이름은 1~120자여야 합니다.")
    levels = spec["grid_levels_mm"]
    if (type(levels) is not list or not 1 <= len(levels) <= 6
            or any(type(value) not in (int, float) or not 0.05 <= value <= 5 for value in levels)
            or any(a <= b for a, b in zip(levels, levels[1:]))):
        raise ProjectError("E_SCHEMA", "격자 수준은 1~6개, 0.05~5 mm 범위의 감소하는 값이어야 합니다.")
    validate_settings(spec["settings"])
    if spec["settings"]["grid_mm"] != levels[-1]:
        raise ProjectError("E_SCHEMA", "기준 격자는 마지막 수준과 같아야 합니다.")
    from rfad.application.convergence import _profile

    try:
        _profile(spec["port_profile"])
        validate_profile(spec["radiation_profile"])
    except ValueError as error:
        raise ProjectError("E_SCHEMA", str(error)) from error
    return deepcopy(spec)


def validate_input(method, context, data):
    """! @brief 연구 명령은 소유 프로젝트와 정규 식별자로만 접근한다."""
    require_fields(context, {"project_id"})
    require_uuid(context["project_id"])
    if method == "study.create":
        require_fields(data, {"expected_revision", "specification"})
        require_uuid(data["expected_revision"])
        validate_specification(data["specification"])
    elif method in {"study.context", "study.list"}:
        require_fields(data, set())
    else:
        require_fields(data, {"study_id"})
        require_uuid(data["study_id"])


def build_cases(document, snapshot, identity, spec):
    """! @brief 수식/출처 원문을 그대로 사용해 모든 실제 계획을 실행 전에 검사한다."""
    plans = []
    for level in spec["grid_levels_mm"]:
        settings = deepcopy(spec["settings"])
        settings["grid_mm"] = level
        plans.append(build_pcb_plan(document, snapshot, identity, settings))
    guards = []
    for a, b in zip(plans, plans[1:]):
        if "radiation" in spec["settings"]:
            try:
                guards.append(plan_guards(a, b, "mesh"))
            except ValueError as error:
                raise ProjectError("E_GEOMETRY", str(error)) from error
        else:
            from rfad.application.pcb_mesh import mesh_lines

            x, y = mesh_lines(a["case"]), mesh_lines(b["case"])
            fixed = all([x[key][0], x[key][8], x[key][-9], x[key][-1]] == [y[key][0], y[key][8], y[key][-9], y[key][-1]] for key in "xyz")
            if not fixed:
                raise ProjectError("E_GEOMETRY", "격자 연구는 외곽/PML 시작면을 고정해야 합니다. graded air 설정을 확인하십시오.")
            guards.append({"fixed_outer_domain_and_pml_interfaces": True})
    if any(canonical_hash(plan["source_semantics"]) != snapshot["content_hash"] for plan in plans):
        raise ProjectError("E_HASH", "연구 계획에서 원본 매개변수/출처가 바뀌었습니다.")
    return plans, guards
