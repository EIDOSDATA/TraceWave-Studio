"""! @brief 명시적인 재료 손실 표현과 목적별 필수 소비 물성을 정의한다."""

from rfad.domain.errors import ProjectError


LEGACY_MODEL = "isotropic_constant"
TOTAL_TAN_DELTA_MODEL = "isotropic_constant_total_tan_delta"
MATERIAL_MODELS = frozenset({LEGACY_MODEL, TOTAL_TAN_DELTA_MODEL})


def validate_material_model(model, field="material.model"):
    """! @brief 지원 모델을 검사하며 알 수 없는 선택을 기존 모델로 대체하지 않는다."""
    if type(model) is not str or model not in MATERIAL_MODELS:
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 명시적 재료 모델입니다.", details={"field_path": field})


def material_input_fields(*, model=LEGACY_MODEL, conductor_only=False, volume_conductor=False, field="material.model"):
    """! @brief 총 손실 탄젠트 모델은 독립 전도도를 소비하지 않으며 도체에 적용하지 않는다."""
    validate_material_model(model, field)
    if model == TOTAL_TAN_DELTA_MODEL:
        if conductor_only or volume_conductor:
            raise ProjectError("E_UNSUPPORTED", "총 손실 탄젠트 모델은 유전체 전용이며 유한 전도 도체에 사용할 수 없습니다.",
                               details={"field_path": field})
        return (("epsilon_r", "dimensionless"), ("tan_delta", "dimensionless"))
    fields = (("conductivity", "conductivity"),)
    if not conductor_only or volume_conductor:
        fields += (("epsilon_r", "dimensionless"),)
    if not conductor_only:
        fields += (("tan_delta", "dimensionless"),)
    return fields
