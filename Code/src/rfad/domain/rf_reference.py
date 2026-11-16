"""! @brief 독립 평면 도체식과 이상 반파장 패턴을 유한 형상/실측 검증과 구분한다."""

import cmath
import math

from rfad.domain.errors import ProjectError


DIPOLE_LIMITS = {"maximum_pattern_error": 0.15, "relative_directivity_error": 0.1,
                 "efficiency_error": 0.15}
DIPOLE_DIRECTIVITY = 1.6409
DIPOLE_SOURCE = "https://radiance.ece.utoronto.ca/ece422/notes/07-halfwave.pdf"
SHEET_SOURCE = "https://fab.cba.mit.edu/classes/862.25/notes/circuits.pdf"


def _number(value, *, positive=False):
    """! @brief bool, 비유한 값과 표시 범위를 넘는 정수를 거절한다."""
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and (not positive or value > 0))
    except OverflowError:
        return False


def halfwave_power_pattern(theta_deg):
    """! @brief 이상적인 가는 반파장 도선의 최대값 1인 전력 패턴을 구한다.

    @details 정현파 전류와 자유공간 원거리장 가정이다. 유한 반지름 native 형상의
    정확한 해가 아니며 양 극점은 해석적 극한 0을 사용한다.
    """
    if (type(theta_deg) is not list or not 1 <= len(theta_deg) <= 361
            or any(not _number(value) or not 0 <= value <= 180 for value in theta_deg)):
        raise ProjectError("E_SCHEMA", "반파장 참조에는 0~180 degree의 유한 theta 목록이 필요합니다.")
    result = []
    for value in theta_deg:
        if value in (0, 180):
            result.append(0.0)
            continue
        # @brief 축 근처 cos(pi/2*cos(theta))의 상쇄를 대칭적인 sin 식으로 줄인다.
        angle = math.radians(min(value, 180 - value))
        amplitude = math.sin(math.pi * math.sin(angle / 2) ** 2) / math.sin(angle)
        result.append(amplitude * amplitude)
    return result


def assess_dipole(theta_deg, normalized_power, metrics):
    """! @brief 기존 phi 첫 절단면의 초도 기준을 유지하고 전체 phi 오차는 별도 관찰한다."""
    expected = halfwave_power_pattern(theta_deg)
    if (type(normalized_power) is not list or len(normalized_power) != len(expected)
            or not normalized_power or type(normalized_power[0]) is not list
            or not 1 <= len(normalized_power[0]) <= 360):
        raise ProjectError("E_SCHEMA", "독립 패턴 비교의 theta/phi 행렬이 유효하지 않습니다.")
    width = len(normalized_power[0])
    if any(type(row) is not list or len(row) != width
           or any(not _number(value) or not 0 <= value <= 1 + 1e-12 for value in row)
           for row in normalized_power):
        raise ProjectError("E_SCHEMA", "독립 패턴 비교에는 유한 정규화 전력 행렬이 필요합니다.")
    if (type(metrics) is not dict
            or not _number(metrics.get("directivity_linear"), positive=True)
            or not _number(metrics.get("radiation_efficiency"), positive=True)):
        raise ProjectError("E_SCHEMA", "독립 참조 비교에 실제 지향성과 방사 효율이 필요합니다.")
    errors = {"maximum_pattern_error": max(abs(row[0] - ideal) for row, ideal in zip(normalized_power, expected)),
              "relative_directivity_error": abs(metrics["directivity_linear"] / DIPOLE_DIRECTIVITY - 1),
              "efficiency_error": abs(metrics["radiation_efficiency"] - 1)}
    passed = all(errors[key] <= limit for key, limit in DIPOLE_LIMITS.items())
    return {"schema": "rfad.dipole-independent-assessment/0.1", "status": "passed" if passed else "requires_review",
            "passed": passed, **errors, "acceptance": dict(DIPOLE_LIMITS),
            "pattern_comparison_phi_index": 0,
            "maximum_pattern_error_all_phi": max(abs(value - ideal) for row, ideal in zip(normalized_power, expected) for value in row),
            "reference_directivity": DIPOLE_DIRECTIVITY, "ideal_normalized_power": expected,
            "reference_source": DIPOLE_SOURCE,
            "reference_scope": "finite_radius_discretized_dipole_vs_ideal_thin_half_wave_preliminary_reference",
            "formal_convergence": "not_established", "physics_validated": False,
            "manufacturing_validated": False, "measurement_validated": False}


def symmetric_sheet_impedance(frequency_hz, conductivity_s_per_m, thickness_m, permeability_h_per_m):
    """! @brief 좋은 도체의 양면 대칭 평면 slab에서 총 표면 전류에 대한 복소 Z를 구한다.

    @details exp(+j*omega*t), 균질/등방/선형 도체, 변위 전류 무시와 slab 중심의
    대칭 조건을 전제로 한다. 실제 여기/경계가 이 가정을 충족하는지는 계산하지 않는다.
    """
    values = (frequency_hz, conductivity_s_per_m, thickness_m, permeability_h_per_m)
    if not all(_number(value, positive=True) for value in values):
        raise ProjectError("E_SCHEMA", "평면 도체식에는 주파수/전도도/두께/투자율의 명시적 양수가 필요합니다.")
    try:
        omega = 2 * math.pi * frequency_hz
        depth = math.sqrt(2 / (omega * permeability_h_per_m * conductivity_s_per_m))
        gamma = (1 + 1j) / depth
        argument = gamma * thickness_m / 2
        if abs(argument) < 1e-4:
            # @brief gamma*coth의 큰 실수항 곱에서 작은 유도성 성분이 상쇄되지 않게 한다.
            impedance = (1 + argument ** 2 / 3 - argument ** 4 / 45
                         + 2 * argument ** 6 / 945) / (conductivity_s_per_m * thickness_m)
        else:
            if argument.real > 350:
                coth = 1 + 0j
            else:
                decay = cmath.exp(-2 * argument)
                coth = (1 + decay) / (1 - decay)
            impedance = gamma * coth / (2 * conductivity_s_per_m)
        if not all(math.isfinite(value) for value in (depth, impedance.real, impedance.imag)) or depth <= 0 or impedance.real <= 0:
            raise ValueError()
    except (OverflowError, ZeroDivisionError, ValueError) as error:
        raise ProjectError("E_RESOURCE", "평면 도체 참조식의 유한 수치 범위를 벗어났습니다.") from error
    return impedance


def sheet_reference(frequency_hz, conductivity_s_per_m, thickness_m, permeability_h_per_m):
    """! @brief 독립 식의 값과 가정을 반환하고 native/실측 합격을 만들어 채우지 않는다."""
    impedance = symmetric_sheet_impedance(frequency_hz, conductivity_s_per_m, thickness_m, permeability_h_per_m)
    depth = math.sqrt(2 / (2 * math.pi * frequency_hz * permeability_h_per_m * conductivity_s_per_m))
    return {"schema": "rfad.symmetric-sheet-reference/0.1", "frequency_hz": frequency_hz,
            "conductivity_s_per_m": conductivity_s_per_m, "thickness_m": thickness_m,
            "permeability_h_per_m": permeability_h_per_m, "skin_depth_m": depth,
            "sheet_impedance_ohm": [impedance.real, impedance.imag],
            "phasor_convention": "exp(+j*omega*t)", "current_definition": "total_peak_surface_current_density_A_per_m",
            "power_density_formula": "0.5*Re(Z_sheet)*abs(K_peak)^2",
            "assumptions": ["homogeneous_isotropic_linear_planar_slab", "good_conductor_displacement_current_neglected",
                            "symmetric_two_sided_excitation", "no_roughness_or_contact_model"],
            "reference_source": SHEET_SOURCE,
            "derivation": "Maxwell_diffusion_equation_with_symmetric_slab_boundary_not_direct_source_quote",
            "applicability": "requires_explicit_excitation_and_boundary_validation",
            "native_executed": False, "physics_validated": False, "measurement_validated": False}
