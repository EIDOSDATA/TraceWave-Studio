"""! @brief 동일 PCB의 방사 패턴과 전력 스펙트럼을 보간 없이 비교한다."""

import math

from rfad.application.convergence import _result
from rfad.application.pcb_radiation import validate_result, summary
from rfad.application.pcb_mesh import mesh_lines
from rfad.application.radiation_study import finite, require, validate_profile
from rfad.application.radiation_study_guards import plan_guards


VACUUM_IMPEDANCE_OHM = 4e-7 * math.pi * 299792458.0


def sphere_power(recording, row):
    """! @brief theta의 sin 가중 사다리꼴과 phi의 주기 합으로 전체 구면을 적분한다."""
    theta, phi = recording["theta_deg"], recording["phi_deg"]
    require(theta[0] == 0 and theta[-1] == 180 and phi[0] == 0 and phi[-1] < 360, "전체 구면과 중복 없는 phi 축이 필요합니다.")
    step = 360 / len(phi)
    require(all(math.isclose(value, index * step, rel_tol=0, abs_tol=1e-10) for index, value in enumerate(phi)), "구면 적분에는 균일한 주기 phi 축이 필요합니다.")
    rings = []
    for index, angle in enumerate(theta):
        field_power = math.fsum(sum(x * x for key in ("e_theta", "e_phi") for x in row[key][index][column]) for column in range(len(phi)))
        rings.append(field_power * math.radians(step) * math.sin(math.radians(angle)))
    integral = math.fsum((a + b) * 0.5 * math.radians(high - low) for a, b, low, high in zip(rings, rings[1:], theta, theta[1:]))
    result = integral * recording["radius_m"] ** 2 / (2 * VACUUM_IMPEDANCE_OHM)
    require(finite(result) and result > 0, "원방 구면 적분이 유한한 양수가 아닙니다.")
    return result


def power_audit(normalized, radiation, profile):
    """! @brief 포트 파동 항등식, 구면 적분과 수동성 예산을 독립 손실 적분과 구분한다."""
    recording = radiation["recording"]
    rows = []
    for field in radiation["frequencies"]:
        frequency = field["frequency_hz"]
        probes = [row for row in normalized["samples"] if math.isclose(row["frequency_hz"], frequency, rel_tol=0, abs_tol=1e-5)]
        require(len(probes) == 1, "전력 수지에는 같은 주파수의 직접 포트 표본이 필요합니다. 보간하지 않습니다.")
        metrics = field["metrics"]
        incident, accepted, radiated = (metrics[key] for key in ("incident_power_w_s2", "accepted_power_w_s2", "radiated_power_w_s2"))
        reflected = incident * sum(value * value for value in probes[0]["s11"])
        sphere = sphere_power(recording, field)
        port_error = abs(incident - reflected - accepted) / incident
        sphere_error = abs(sphere - radiated) / radiated
        excess = max(0.0, (radiated - accepted) / accepted, (accepted - incident) / incident)
        passed = (port_error <= profile["max_port_balance_relative_error"] and sphere_error <= profile["max_sphere_relative_error"]
                  and excess <= profile["max_passivity_excess"])
        rows.append({"frequency_hz": frequency, "incident_power_w_s2": incident, "reflected_power_w_s2": reflected,
                     "accepted_power_w_s2": accepted, "radiated_power_w_s2": radiated, "sphere_power_w_s2": sphere,
                     "inferred_loss_w_s2": accepted - radiated, "independent_absorption_power_w_s2": None,
                     "port_wave_relative_residual": port_error, "sphere_relative_error": sphere_error,
                     "passivity_excess_fraction": excess, "strict_passivity_status": metrics["power_balance_status"],
                     "status": "within_initial_numerical_budget" if passed else "outside_initial_numerical_budget"})
    return {"status": "passed" if all(row["status"] == "within_initial_numerical_budget" for row in rows) else "failed",
            "scope": "port_wave_identity_sphere_integral_and_passivity_budget", "frequencies": rows,
            "full_energy_closure": "not_evaluated", "independent_volume_and_conductor_loss_integral": "not_evaluated",
            "power_unit": "W*s^2", "absolute_power_w": None, "physics_validated": False}


def case_data(case):
    """! @brief 봉인 조회가 공급한 두 결과를 교차 검증하고 기존 시간 종료 검사도 적용한다."""
    normalized, radiation = case["normalized_result"], case["radiation_result"]
    data = _result(normalized)
    validate_result(data["plan"], radiation)
    require(normalized.get("radiation_summary") == summary(radiation), "방사 요약과 필드 산출물이 다릅니다.")
    require(case["settings"] == data["settings"], "사례의 명시 설정과 결과가 다릅니다.")
    require(data["lines"] == mesh_lines(data["plan"]["case"]), "실행한 격자와 계획의 격자가 다릅니다.")
    return data


def compare_cases(left, right, profile):
    """! @brief 동일 주파수와 공통 각도 노드의 패턴 및 절대 수치 변화를 보존한다."""
    selected = validate_profile(profile)
    a, b = case_data(left), case_data(right)
    require(left["axis"] == right["axis"], "같은 연구 축만 비교할 수 있습니다.")
    guards = plan_guards(a["plan"], b["plan"], left["axis"])
    r1, r2 = left["radiation_result"], right["radiation_result"]
    first, second = r1["recording"], r2["recording"]
    theta = sorted(set(first["theta_deg"]) & set(second["theta_deg"]))
    phi = sorted(set(first["phi_deg"]) & set(second["phi_deg"]))
    require(len(theta) >= 7 and len(phi) >= 12, "직접 비교할 공통 각도 표본이 부족합니다.")
    indices = [(first["theta_deg"].index(t), first["phi_deg"].index(p), second["theta_deg"].index(t), second["phi_deg"].index(p)) for t in theta for p in phi]
    rows = []
    for row1, row2 in zip(r1["frequencies"], r2["frequencies"]):
        m1, m2 = row1["metrics"], row2["metrics"]
        metrics = {"pattern_max_delta": max(abs(row1["normalized_power"][i][j] - row2["normalized_power"][k][l]) for i, j, k, l in indices),
                   "radiated_relative_delta": abs(m2["radiated_power_w_s2"] - m1["radiated_power_w_s2"]) / max(m1["radiated_power_w_s2"], m2["radiated_power_w_s2"]),
                   "directivity_delta_db": abs(m1["directivity_dbi"] - m2["directivity_dbi"]),
                   "gain_delta_db": abs(m1["gain_dbi"] - m2["gain_dbi"]),
                   "realized_gain_delta_db": abs(m1["realized_gain_dbi"] - m2["realized_gain_dbi"]),
                   "efficiency_delta": abs(m1["radiation_efficiency"] - m2["radiation_efficiency"])}
        checks = {"pattern": metrics["pattern_max_delta"] <= selected["max_pattern_delta"],
                  "radiated": metrics["radiated_relative_delta"] <= selected["max_radiated_relative_delta"],
                  "directivity": metrics["directivity_delta_db"] <= selected["max_directivity_delta_db"],
                  "gain": max(metrics["gain_delta_db"], metrics["realized_gain_delta_db"]) <= selected["max_gain_delta_db"],
                  "efficiency": metrics["efficiency_delta"] <= selected["max_efficiency_delta"]}
        rows.append({"frequency_hz": row1["frequency_hz"], "metrics": metrics, "checks": checks, "passed": all(checks.values())})
    require(a["frequencies"] == b["frequencies"], "서로 다른 포트 주파수 격자는 비교하지 않습니다.")
    delta = max(abs(x - y) for x, y in zip(a["s11"], b["s11"]))
    passed = all(row["passed"] for row in rows) and delta <= selected["max_s11_complex_delta"]
    return {"left": left["label"], "right": right["label"], "status": "passed" if passed else "failed", "guards": guards,
            "common_angle_count": len(indices), "interpolation_used": False, "max_s11_complex_delta": delta,
            "frequencies": rows, "physics_validated": False}
