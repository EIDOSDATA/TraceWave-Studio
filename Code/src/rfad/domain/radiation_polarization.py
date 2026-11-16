"""! @brief 원본 구면 복소 전계에서 명시한 편파 기저와 표시 좌표를 계산한다."""

import cmath
from fractions import Fraction
import math


CONVENTION = {
    "profile": "rfad.polarization.openems/0.1",
    "phasor": "exp(+j*omega*t)",
    "spherical_basis": "right_handed_e_theta_e_phi_e_r",
    "propagation": "outward_e_r",
    "circular_basis": "openEMS_0.37.0_E_cprh_E_cplh",
    "rh_formula": "exp(+j*phi)*(Etheta+j*Ephi)/sqrt(2)",
    "lh_formula": "exp(-j*phi)*(Etheta-j*Ephi)/sqrt(2)",
    "definition_source": "https://docs.openems.de/en/latest/python/openEMS/nf2ff.html",
    "inspected_source_sha256": "f9efb634b16439e92ec398df8e92571374fc28ad0cc65237d10bd461255142e2",
    "angle_policy": "original_requested_degrees_double_precision",
    "native_angle_precision": "HDF5_phi_and_native_sin_cos_float32_roundoff_is_preserved_in_original",
    "physics_validated": False,
}


def pair(value):
    """! @brief JSON에 복소수 대신 유한 실수/허수 쌍을 반환한다."""
    return [value.real, value.imag]


def polarization(e_theta, e_phi, phi_deg):
    """! @brief 원형 성분과 축비를 구하되 영전계와 무한 축비를 숫자 0으로 바꾸지 않는다."""
    theta, phi = complex(*e_theta), complex(*e_phi)
    factor = cmath.exp(1j * math.radians(phi_deg))
    rh = factor * (theta / math.sqrt(2) + 1j * phi / math.sqrt(2))
    lh = factor.conjugate() * (theta / math.sqrt(2) - 1j * phi / math.sqrt(2))
    scale = max(abs(theta), abs(phi))
    relative = None
    if abs(theta) > 0 and abs(phi) > 0:
        relative = math.degrees(cmath.phase((phi / abs(phi)) * (theta / abs(theta)).conjugate()))
    result = {"rhcp_ri": pair(rh), "lhcp_ri": pair(lh), "relative_phase_deg": relative,
              "relative_phase_state": "defined" if relative is not None else "undefined_zero_component",
              "axial_ratio": None, "axial_ratio_db": None, "axial_ratio_state": "undefined_zero_field"}
    if scale == 0:
        return result
    # @brief 크기 배율을 제거하여 작은 펄스 스펙트럼에서도 축비를 안정적으로 구한다.
    t, p = theta / scale, phi / scale
    right, left = abs(t + 1j * p), abs(t - 1j * p)
    cross = t * p.conjugate()
    # @brief 거의 직선인 타원에서도 두 원형 진폭의 뺄셈으로 작은 축을 소거하지 않는다.
    # @details 두 실수 축 행렬의 큰 특이값 제곱을 행렬식으로 나누면 큰 축/작은 축 비가 된다.
    theta_power, phi_power = abs(t) ** 2, abs(p) ** 2
    major_squared = (theta_power + phi_power + math.hypot(theta_power - phi_power, 2 * cross.real)) / 2
    # @brief 작은 비영 행렬식도 정규화/곱셈 반올림에 손상될 수 있어 원본 float의 정확한 차를 쓴다.
    exact = abs(Fraction(theta.real) * Fraction(phi.imag) - Fraction(theta.imag) * Fraction(phi.real))
    if exact == 0:
        result["axial_ratio_state"] = "infinite_linear"
        return result
    try:
        ratio = float(Fraction(major_squared) * Fraction(scale) ** 2 / exact)
    except OverflowError:
        ratio = math.inf
    if not math.isfinite(ratio):
        result["axial_ratio_state"] = "overflow"
        return result
    result.update(axial_ratio=ratio, axial_ratio_db=20 * math.log10(ratio),
                  axial_ratio_state="circular" if min(right, left) == 0 else "elliptical")
    return result


def projection(amplitude, theta_deg, phi_deg, display_scale, floor_db):
    """! @brief 실제 정규화 진폭과 dB를 보존하고 시각화의 바닥값만 별도로 적용한다."""
    db = 20 * math.log10(amplitude) if amplitude > 0 else None
    if display_scale == "db_amplitude":
        visible = max(floor_db, db) if db is not None else floor_db
        radius = (visible - floor_db) / -floor_db
        color = visible
    else:
        radius, color = amplitude, amplitude
    theta, phi = math.radians(theta_deg), math.radians(phi_deg)
    return {"xyz": [radius * math.sin(theta) * math.cos(phi), radius * math.sin(theta) * math.sin(phi),
                    radius * math.cos(theta)], "radius": radius, "color": color,
            "amplitude": amplitude, "db": db, "db_state": "finite" if db is not None else "negative_infinity",
            "clipped": display_scale == "db_amplitude" and (db is None or db < floor_db)}
