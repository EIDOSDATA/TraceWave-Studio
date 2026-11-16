/** @file @brief 검증 기록의 판정을 재계산하지 않는 읽기 전용 표시 모델이다. */
#pragma once
#include "studio_types.h"
#include <string>
#include <vector>

namespace RfValidationUi
{
std::string State(const Json& value);
std::string Axis(const Json& value);
std::string Reason(const Json& value);
std::string Time(const Json& value);
std::string Notes(const Json& value);
std::string Resources(const Json& value);
std::string Criteria(const Json& value);
std::vector<std::vector<std::string>> Cases(const Json& record);
std::vector<std::vector<std::string>> States(const Json& record);
std::vector<std::vector<std::string>> Metrics(const Json& record);
bool HasSource(const Json& item);
}
