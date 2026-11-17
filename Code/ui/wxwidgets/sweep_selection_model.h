/** @file @brief 후보 채택의 원문 보존 요약과 확정 응답 검사를 정의한다. */
#pragma once
#include "studio_types.h"
#include <string>

namespace SweepSelectionUi
{
std::string Issues(const Json& issues);
std::string Conditions(const Json& review);
std::string CopySummary(const Json& review);
/** @brief 다른 후보 또는 원본의 생성 응답을 현재 검토 결과로 받아들이지 않는다. */
bool MatchesCopy(const Json& result, const Json& context);
/** @brief 변경 전 확정 거절만 재검토를 허용하며 전송 불명과 구분한다. */
bool Rejected(const Json& error);
}
