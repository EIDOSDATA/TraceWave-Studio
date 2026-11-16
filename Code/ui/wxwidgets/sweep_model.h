/** @file @brief 설계 연구 응답을 계산 없이 읽기 쉬운 이름과 상태로 표시한다. */
#pragma once
#include "studio_types.h"
#include <string>

namespace SweepUi
{
std::string Text(const Json& value);
std::string Status(const std::string& value);
std::string Type(const std::string& value);
std::string Quantity(const Json& value);
std::string Diagnostics(const Json& values);
std::string CandidateValues(const Json& candidate);
/** @brief 실제 표본의 숫자는 읽기용 유효 자릿수로만 줄이고 특이 상태를 보존한다. */
std::string SampleValue(const Json& sample, const std::string& key);
/** @brief 결과 조건과 당시 목표의 미평가 이유를 원문 변경 없이 요약한다. */
std::string ResultConditions(const Json& result);
/** @brief 사용자 선택에 사용할 지원 변수만 원문 수량과 함께 복사한다. */
Json Variables(const Json& context, const std::string& type, const std::string& circuitId);
/** @brief 명시 값 또는 범위 입력의 원문을 요약하며 후보를 생성하지 않는다. */
std::string VariableSummary(const Json& variable);
}
