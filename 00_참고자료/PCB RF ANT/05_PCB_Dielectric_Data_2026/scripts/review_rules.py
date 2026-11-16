"""! @brief 공개 물성 관측의 검토 조건을 입력 변경 없이 판정한다."""

from typing import Any, Mapping


MISSING_TOKENS = frozenset(
    {"", "not stated", "not specified", "unknown", "unspecified", "n/a"}
)

REVIEW_MEANING = (
    "Flags describe published observations. Counts are not unique materials, "
    "independent measurements, usable layer stacks or solver-ready cases. "
    "Flags overlap. No readiness is granted."
)

FLAG_DESCRIPTIONS = {
    "scalar_dk_missing": "원문 관측의 단일 수치 Dk가 없다. 범위의 중간값을 만들지 않는다.",
    "scalar_df_missing": "원문 관측의 단일 수치 Df가 없다. 무손실로 대체하지 않는다.",
    "dk_point_frequency_missing": "frequency_ghz의 점 주파수가 없다. 범위나 미기재를 보간하지 않는다.",
    "test_method_missing": "원문 시험법이 없거나 미기재라고 표시되어 있다.",
    "measurement_axis_missing": "원문 측정 방향이 없거나 미기재라고 표시되어 있다.",
    "published_source_conflict": "기존 수집 자료에서 출처 충돌로 표시한 관측이다.",
    "source_specific_quality_flags": "원 수집 자료의 quality_flags를 별도로 검토해야 한다.",
    "local_source_file_unavailable": "관측에 보관된 원문 파일 경로가 없다. 출처 상태와 URL을 확인한다.",
    "dk_df_frequency_not_shared": "별도 Df 주파수가 공통 주파수와 다르거나 공통 주파수가 없다.",
    "invalid_nonpositive_source_ply_value": "원문 ply 두께가 0 이하로 보고되어 정규 두께가 미정이다.",
    "group_thickness_not_individual_ply_thickness": "PCBWay의 여러 ply가 합계 두께만 공유하고 개별 두께는 없다.",
    "individual_layer_thickness_missing": "stackup 관측에 개별 층의 수치 두께가 없다.",
    "nonunit_relative_permeability": "상대 투자율이 1이 아닌 값으로 보고되어 있다.",
    "method_scope_note_present": "시험법의 적용 범위를 설명하는 별도 주의가 있다.",
    "value_comparison_qualifier_present": "비교 연산자나 한계 표기가 있어 단순 명목값 채택을 검토해야 한다.",
    "fabricator_planning_observation_not_as_built_measurement": "PCB 업체의 공개 계획 파라미터이며 제작된 기판의 실측값이 아니다.",
}


def missing(value: Any) -> bool:
    """! @brief 빈 값과 명시적 미기재 문자열을 판정한다."""
    if value is None:
        return True
    return str(value).strip().casefold() in MISSING_TOKENS


def flags(record: Mapping[str, Any]) -> list[str]:
    """! @brief 관측의 검토 조건만 반환하며 해석 가능 여부를 승인하지 않는다.

    @param record 원래 키와 값이 보존된 공개 관측이다. 이 함수는 입력을 변경하지 않는다.
    @return 중첩 가능한 검토 플래그의 새 목록이다. 빈 목록도 물성 채택 승인이 아니다.
    """
    result = []
    if record.get("dk") is None:
        result.append("scalar_dk_missing")
    if record.get("df") is None:
        result.append("scalar_df_missing")
    if record.get("frequency_ghz") is None:
        result.append("dk_point_frequency_missing")
    if missing(record.get("method")):
        result.append("test_method_missing")
    if missing(record.get("axis")):
        result.append("measurement_axis_missing")
    if record.get("data_conflict"):
        result.append("published_source_conflict")
    if record.get("quality_flags"):
        result.append("source_specific_quality_flags")
    if not record.get("source_file"):
        result.append("local_source_file_unavailable")
    if (
        record.get("df_frequency_ghz") is not None
        and record.get("df_frequency_ghz") != record.get("frequency_ghz")
    ):
        result.append("dk_df_frequency_not_shared")
    if record.get("thickness_status") == "invalid_nonpositive_source_ply_value":
        result.append("invalid_nonpositive_source_ply_value")
    if (
        record.get("manufacturer") == "PCBWay"
        and (record.get("laminated_group_rows") or 0) > 1
        and record.get("thickness_mm") is None
    ):
        result.append("group_thickness_not_individual_ply_thickness")
    if record.get("stackup_id") and record.get("thickness_mm") is None:
        result.append("individual_layer_thickness_missing")
    if record.get("relative_permeability") not in (None, 1, 1.0):
        result.append("nonunit_relative_permeability")
    if record.get("method_scope_note"):
        result.append("method_scope_note_present")
    if (
        record.get("df_comparison")
        or record.get("df_limit_operator")
        or record.get("dk_comparison")
    ):
        result.append("value_comparison_qualifier_present")
    if record.get("dataset_role") == "fabricator_published_parameter":
        result.append("fabricator_planning_observation_not_as_built_measurement")
    return result
