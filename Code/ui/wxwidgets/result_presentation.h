/** @file @brief 봉인된 결과의 이름/미정/수치 상태를 원문 변경 없이 표시한다. */
#pragma once
#include "studio_types.h"
#include <string>

namespace ResultUi
{
std::string Number(const Json& value, int precision = 8);
std::string Text(const Json& value);
std::string State(const Json& value);
std::string SourceKind(const Json& value);
std::string PortName(const Json& descriptor, std::size_t index);
std::string Complex(const Json& value, const std::string& state = "finite");
std::string SampleValue(const Json& point, const std::string& key);
std::string ConditionSummary(const Json& description);
/** @brief source와 pin이 모두 일치한 응답만 같은 표시 세대로 받아들인다. */
bool Matches(const Json& response, const Json& description);
}
