"""! @brief 방사 비교에서 원본, 계산 영역, PML과 실제 기록 면의 독립성을 검사한다."""

import math

from rfad.application.canonical import canonical_hash
from rfad.application.pcb_mesh import mesh_lines
from rfad.application.radiation_study import changed_settings, require


def plan_guards(left, right, axis):
    """! @brief 설정 이름 대신 재계산한 격자와 기록 면에서 단일 변화 축을 확인한다."""
    a, b = left["case"], right["case"]
    first, second = a["settings"], b["settings"]
    overrides = ({"grid_mm": second["grid_mm"]} if axis == "mesh" else
                 {key: second["radiation"][key] for key in (("box_clearance_mm",) if axis == "box" else ("theta_step_deg", "phi_step_deg"))})
    require(changed_settings(first, axis, overrides) == second, "여러 수치 설정을 동시에 바꾼 방사 결과는 비교할 수 없습니다.")
    require(left["snapshot"] == right["snapshot"] and canonical_hash(left["source_semantics"]) == canonical_hash(right["source_semantics"]), "동일 불변 PCB 입력만 비교할 수 있습니다.")
    require(left["runtime_identity"] == right["runtime_identity"], "방사 계산의 worker/설치 출처가 다릅니다.")
    r1, r2 = a["radiation_recording"], b["radiation_recording"]
    require(all(r1[key] == r2[key] for key in ("center_m", "radius_m", "frequency_hz", "surrounding_medium", "field_recording")), "공통 위상 중심/반지름/주파수/외부 매질이 필요합니다.")
    x, y = mesh_lines(a), mesh_lines(b)
    fixed_domain = all([x[key][0], x[key][8], x[key][-9], x[key][-1]] == [y[key][0], y[key][8], y[key][-9], y[key][-1]] for key in "xyz")
    pml_widths = all([x[key][i + 1] - x[key][i] for i in (*range(8), *range(len(x[key]) - 9, len(x[key]) - 1))] ==
                     [y[key][i + 1] - y[key][i] for i in (*range(8), *range(len(y[key]) - 9, len(y[key]) - 1))] for key in "xyz")
    same_box = all(r1[key] == r2[key] for key in ("start_mm", "stop_mm"))
    same_angles = all(r1[key] == r2[key] for key in ("theta_deg", "phi_deg"))
    checks = {"same_snapshot_source_runtime": True, "same_phase_center_radius_frequencies": True,
              "fixed_outer_domain_and_pml_interfaces": fixed_domain, "fixed_pml_cell_widths": pml_widths}
    if axis == "mesh":
        checks.update(recording_planes_fixed=same_box, angles_fixed=same_angles,
                      grid_setting_refines=second["grid_mm"] < first["grid_mm"],
                      actual_grid_points_increase=math.prod(map(len, y.values())) > math.prod(map(len, x.values())))
    elif axis == "box":
        checks.update(actual_mesh_fixed=x == y, angles_fixed=same_angles,
                      requested_distance_increases=r2["box_clearance_request_mm"] > r1["box_clearance_request_mm"],
                      all_recording_faces_expand=all(lo2 < lo1 and hi2 > hi1 for lo1, lo2, hi1, hi2 in zip(r1["start_mm"], r2["start_mm"], r1["stop_mm"], r2["stop_mm"])))
    else:
        checks.update(actual_mesh_fixed=x == y, recording_planes_fixed=same_box,
                      both_angle_steps_refine=all(second["radiation"][key] < first["radiation"][key] for key in ("theta_step_deg", "phi_step_deg")),
                      nested_angle_nodes=all(set(r1[key]) < set(r2[key]) for key in ("theta_deg", "phi_deg")))
    require(all(checks.values()), "실제 격자/PML/기록 면/각도의 독립 비교 조건을 충족하지 못했습니다: " + str(checks))
    return {**checks, "passed": True}
