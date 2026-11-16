"""! @brief 사용자 PCB와 구분되는 고정 RF 참조 사례의 계획과 산출물 계약을 정의한다."""

from copy import deepcopy
from fractions import Fraction
import math
from uuid import UUID, uuid4, uuid5

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.solver import PLAN_SCHEMA, RUNTIME_PROFILE, _json, _reference_source, _runtime, _uuid
from rfad.domain.errors import ProjectError


PROFILE = "rfad.openems.reference-benchmark/0.1"
RESULT_SCHEMA = "rfad.openems-reference-result/0.1"
RADIATION_SCHEMA = "rfad.reference-radiation/0.1"
CASE = "pec-dipole-nf2ff"
CASE_SCHEMA = "rfad.reference.pec-dipole/0.1"
GRIDS_MM = (3.0, 2.5, 2.0)
NAME = "reference_nf2ff"
MAX_GRID_POINTS = 1_500_000
REFERENCE_SCOPE = {
    "kind": "explicit_synthetic_reference",
    "case": CASE,
    "native_model": "PEC 60 mm dipole, radius 1 mm, 1 mm ideal lumped gap in vacuum",
    "oracle_scope": "finite_radius_native_geometry_differs_from_ideal_thin_exact_half_wave_pattern",
    "user_pcb": False,
    "manufacturing": None,
    "measurement": None,
    "physics_validated": False,
}


def fail(message, code="E_SCHEMA"):
    """! @brief 닫힌 참조 profile의 오류를 기존 작업 수명에 전달한다."""
    raise ProjectError(code, message)


def validate_settings(settings):
    """! @brief 고정 사례와 사전 지정한 세 격자 외의 실행 입력을 거절한다."""
    if type(settings) is not dict or set(settings) != {"case", "grid_mm"}:
        fail("RF 참조 설정은 case와 grid_mm 두 필드가 필요합니다.")
    if settings["case"] != CASE:
        fail("이 참조 사례의 형상/급전/독립 기준이 확정되지 않아 실행을 지원하지 않습니다.", "E_UNSUPPORTED")
    if type(settings["grid_mm"]) not in (int, float) or settings["grid_mm"] not in GRIDS_MM:
        fail("PEC 다이폴 참조의 내부 격자는 3, 2.5, 2 mm만 지원합니다.", "E_UNSUPPORTED")


def mesh_lines(grid_mm):
    """! @brief 세 수준에서 PML 계면과 물리 단자를 고정한 명시 격자를 만든다."""
    step = Fraction(grid_mm)
    values = {float(index * step) for index in range(-math.ceil(74 / step), math.ceil(74 / step) + 1)
              if abs(index * step) < 74}
    values.update(range(-90, -73, 2))
    values.update(range(74, 91, 2))
    values.update((-60, -30, -1, -0.5, 0, 0.5, 1, 30, 60))
    return {axis: sorted(values) for axis in "xyz"}


def case_spec(settings, project_id):
    """! @brief 합성 물리 치수의 출처와 미확립 범위를 명시하고 사용자 물성을 채우지 않는다."""
    validate_settings(settings)
    _uuid(project_id, "project_id")
    lines = mesh_lines(settings["grid_mm"])
    recording = {
        "schema": "rfad.nf2ff-recording/0.1", "name": NAME,
        "start_mm": [-60.0] * 3, "stop_mm": [60.0] * 3,
        "center_m": [0.0] * 3, "radius_m": 1.0, "frequency_hz": [2.4e9],
        "theta_deg": list(range(0, 181, 5)), "phi_deg": list(range(0, 360, 5)),
        "pml_separation_cells": min(len([x for x in lines[axis] if 60 < x <= 74]) for axis in "xyz"),
        "surrounding_medium": "vacuum", "field_recording": "frequency_domain", "physics_validated": False,
    }
    return {
        "case_id": CASE_SCHEMA, "source": "explicit_reference_case", "reference_case": CASE,
        "native_length_unit": "mm", "delta_unit_m": 0.001,
        "medium": {"kind": "vacuum", "epsilon_r": 1.0, "mu_r": 1.0, "electric_conductivity_s_per_m": 0.0},
        "boundary_conditions": ["PML_8"] * 6,
        "geometry": {"material": "PEC", "priority": 10, "radius_mm": 1.0,
                     "cylinders": [{"start_mm": [0.0, 0.0, -30.0], "stop_mm": [0.0, 0.0, -0.5]},
                                   {"start_mm": [0.0, 0.0, 0.5], "stop_mm": [0.0, 0.0, 30.0]}]},
        "port": {"id": str(uuid5(UUID(project_id), "reference:pec-dipole-nf2ff:port1")),
                 "number": 1, "start_mm": [-1.0, -1.0, -0.5], "stop_mm": [1.0, 1.0, 0.5],
                 "axis": "z", "resistance_ohm": 50.0, "excite": 1, "priority": 20,
                 "reference_plane": "ideal_lumped_gap_terminals"},
        "mesh": {"interior_grid_mm": float(settings["grid_mm"]), "lines_mm": lines,
                 "pml_outer_mm": [-90.0, 90.0], "pml_inner_mm": [-74.0, 74.0],
                 "pml_cells_per_side": 8, "pml_cell_width_mm": 2.0,
                 "method": "fixed_pml_and_critical_lines_union_interior_integer_multiples"},
        "frequency_hz": {"start": 2.4e9, "stop": 2.4e9, "count": 1},
        "excitation": {"kind": "gaussian", "center_hz": 2.4e9, "width_hz": 0.4e9},
        "settings": {"max_timesteps": 30000, "end_criterion": 1e-5, "exact_end_criteria": True},
        "num_threads": 2, "radiation_recording": recording,
        "manufacturing": None, "measurement": None,
    }


def normalization_contract(case):
    """! @brief 이상 급전 단자의 pulse Fourier 규약을 PCB 및 절대 전력과 구분한다."""
    from rfad.application.pcb_results import normalization_contract as lumped_normalization

    value = lumped_normalization(case["port"], radiation=True)
    value.update(schema="rfad.normalization.reference-dipole/0.1", start_terminal="negative_z_PEC_cylinder",
                 stop_terminal="positive_z_PEC_cylinder")
    return value


def _payload(document, snapshot, runtime, settings):
    """! @brief 빈 프로젝트의 봉인 원본과 고정 물리 사례를 서로 구분한 계획을 만든다."""
    _reference_source(document, snapshot)
    _runtime(runtime)
    case = case_spec(settings, document["project_id"])
    counts = [len(case["mesh"]["lines_mm"][axis]) for axis in "xyz"]
    points = math.prod(counts)
    if points > MAX_GRID_POINTS:
        fail("고정 참조 격자가 150만 점 상한을 초과했습니다.", "E_RESOURCE")
    return {
        "schema": PLAN_SCHEMA, "analysis_profile": PROFILE, "runtime_profile": RUNTIME_PROFILE,
        "snapshot": deepcopy(snapshot), "source_semantics": deepcopy(document), "runtime_identity": deepcopy(runtime),
        "case": case, "normalization": normalization_contract(case),
        "model_report": {"scope": "explicit_reference_case", "reference_scope": deepcopy(REFERENCE_SCOPE),
                         "user_geometry_consumed": False, "user_materials_consumed": False,
                         "source_project_required": "empty_reference_project",
                         "physical_validation_state": "not_evaluated"},
        "resource_estimate": {
            "kind": "initial_estimate_not_actual_mesh", "estimated_cells_xyz": [x - 1 for x in counts],
            "estimated_cell_count": math.prod(x - 1 for x in counts), "estimated_grid_points": points,
            "estimated_memory_bytes": 64 * 1024 * 1024 + points * 128,
            "memory_estimate_basis": "64_MiB_process_allowance_plus_128_bytes_per_point_not_measured",
            "max_grid_points": MAX_GRID_POINTS, "max_wall_time_seconds": 300.0,
            "max_output_bytes": 128 * 1024 * 1024, "max_artifact_bytes": 64 * 1024 * 1024,
            "max_memory_bytes": 1024 * 1024 * 1024, "num_threads": 2,
        },
        "outputs": ["preparation_manifest", "native_input", "raw_solver", "s_parameters", "radiation", "result_metadata"],
        "assumptions": [
            "고정 PEC/진공과 60 mm 길이/1 mm 반경/1 mm 이상 급전 간극은 합성 참조 정의다.",
            "유한 반경 다이폴은 이상적인 무한히 가는 정확한 반파장 다이폴과 같은 물리 형상이 아니다.",
            "세 격자에서 PML 물리 계면과 형상/급전/NF2FF 좌표를 고정한다.",
            "준비와 계산 종료를 독립 참조 일치, 일반 수렴, 제작 또는 실측 합격으로 표시하지 않는다.",
        ],
        "validation_policy": {"scope": "reference_evidence_assessed_in_separate_immutable_report",
                              "energy_decay_required": True, "timesteps_exhausted_is_converged": False,
                              "manufacturing_validated": False, "measurement_validated": False},
    }


def build_plan(document, snapshot, runtime, settings):
    """! @brief 새 계획 ID만 발급하고 원본 및 이전 결과를 변경하지 않는다."""
    result = _payload(document, snapshot, runtime, settings)
    result["plan_id"] = str(uuid4())
    return result


def validate_plan(plan):
    """! @brief 닫힌 물리 사례의 모든 입력과 source/runtime/snapshot을 재현 대조한다."""
    _json(plan, "analysis_plan")
    if type(plan) is not dict or plan.get("schema") != PLAN_SCHEMA or plan.get("analysis_profile") != PROFILE:
        fail("지원하는 고정 RF 참조 계획이 아닙니다.", "E_VERSION")
    _uuid(plan.get("plan_id"), "analysis_plan.plan_id")
    case = plan.get("case")
    if type(case) is not dict or type(case.get("mesh")) is not dict or type(plan.get("source_semantics")) is not dict:
        fail("RF 참조 계획의 원본/사례/격자 입력이 없습니다.")
    expected = _payload(plan["source_semantics"], plan.get("snapshot"), plan.get("runtime_identity"),
                        {"case": case.get("reference_case"), "grid_mm": case["mesh"].get("interior_grid_mm")})
    expected["plan_id"] = plan["plan_id"]
    if plan["plan_id"] in {plan["snapshot"][key] for key in ("snapshot_id", "project_id", "revision_id")}:
        fail("계획 ID는 프로젝트/개정/스냅샷과 달라야 합니다.")
    if canonical_bytes(plan) != canonical_bytes(expected):
        fail("고정 RF 참조의 조건이나 계획 원문이 변경되었습니다.", "E_UNSUPPORTED")


def raw_names(plan):
    """! @brief 단일 여기와 여섯 면의 실제 원시 파일만 요구한다."""
    return ("port_ut_1", "port_it_1", "openEMS_stats.txt", "openEMS_run_stats.txt", "native.log", "reference.xml",
            *(f"{plan['case']['radiation_recording']['name']}_{field}_{index}.h5" for field in ("E", "H") for index in range(6)))


def validate_preparation(plan, preparation):
    """! @brief 실제 native 격자와 소비 보고가 고정 계획과 같은지 확인한다."""
    validate_plan(plan)
    mesh, consumption = preparation.get("mesh_statistics", {}), preparation.get("consumption_report", {})
    lines = plan["case"]["mesh"]["lines_mm"]
    counts = [len(lines[axis]) for axis in "xyz"]
    if (preparation.get("schema") != "rfad.preparation-artifact/0.1"
            or preparation.get("analysis_plan_id") != plan["plan_id"]
            or preparation.get("analysis_plan_hash") != canonical_hash(plan)
            or preparation.get("profile") != PROFILE
            or mesh.get("lines_mm") != lines or mesh.get("line_counts") != counts
            or mesh.get("native_grid_points") != math.prod(counts)
            or mesh.get("interval_counts") != [x - 1 for x in counts]
            or mesh.get("yee_interval_cells") != math.prod(x - 1 for x in counts)
            or mesh.get("fdtd_executed") is not False or mesh.get("native_preprocessing_executed") is not False
            or mesh.get("delta_unit_m") != 0.001 or mesh.get("native_length_unit") != "mm"
            or preparation.get("normalization") != plan["normalization"]
            or preparation.get("radiation_recording") != plan["case"]["radiation_recording"]
            or consumption.get("analysis_plan_id") != plan["plan_id"]
            or consumption.get("consumed_case") != plan["case"] or consumption.get("source") != "explicit_reference_case"
            or consumption.get("project_geometry_consumed") is not False
            or consumption.get("project_materials_consumed") is not False
            or consumption.get("fdtd_executed") is not False or consumption.get("physics_validated") is not False):
        fail("고정 RF 참조의 실제 준비 격자/소비/단위가 계획과 다릅니다.", "E_HASH")


def validate_radiation(plan, value):
    """! @brief 공통 복소 전계 검사에 명시한 참조 schema를 전달한다."""
    from rfad.application.pcb_radiation import validate_result as validate_field

    validate_field(plan, value, expected_schema=RADIATION_SCHEMA)


def radiation_summary(value):
    """! @brief 참조 방사 요약의 profile을 사용자 PCB로 바꾸지 않는다."""
    from rfad.application.pcb_radiation import summary

    result = summary(value)
    result["profile"] = RADIATION_SCHEMA
    return result


def validate_result(plan, result, prepared=None):
    """! @brief 참조 정규화 결과의 출처와 유한 표본을 확인하고 물리 합격을 만들지 않는다."""
    from rfad.application.pcb_results import validate_result as validate_lumped_result

    validate_plan(plan)
    if result.get("reference_scope") != REFERENCE_SCOPE:
        fail("정규화 결과의 고정 참조 범위가 다릅니다.", "E_HASH")
    validate_lumped_result(plan, result, prepared, expected_schema=RESULT_SCHEMA)
    if result.get("radiation_summary", {}).get("profile") != RADIATION_SCHEMA:
        fail("참조 방사 요약을 사용자 PCB 결과로 대체할 수 없습니다.", "E_HASH")
