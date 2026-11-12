"""! @brief 외측 도체 sheet가 인접 유전체와 공유하는 유일한 면을 찾는다."""

import math

from rfad.domain.errors import ProjectError


def single_dielectric_contact(lower, thickness, dielectrics, *, tolerance, field):
    """! @brief 같은 길이 단위의 도체/유전체 구간에서 위/아래 접면을 구분한다.

    @param lower 도체 하부 좌표.
    @param thickness 도체의 양수 두께.
    @param dielectrics 유전체의 (하부 좌표, 두께) 목록.
    @param tolerance 호출자가 지정한 길이 단위의 접면 공차.
    @return 외측 도체와 정확히 하나의 유전체가 공유하는 좌표.
    """
    surfaces = []
    for dielectric_lower, dielectric_thickness in dielectrics:
        if math.isclose(lower, dielectric_lower + dielectric_thickness, abs_tol=tolerance):
            surfaces.append(lower)
        if math.isclose(lower + thickness, dielectric_lower, abs_tol=tolerance):
            surfaces.append(dielectric_lower)
    if len(surfaces) != 1:
        raise ProjectError("E_UNSUPPORTED", "외측 동박이 한 유전체 경계와 접하는 sheet 모델만 지원합니다.", details={"field_path": field})
    return surfaces[0]
