/** @file @brief PCB 편집 폼의 값과 검토 정체성을 물리 원본에서 분리한다. */
#pragma once
#include "studio_types.h"
#include <string>

namespace PcbFeatureUi
{
std::string SectionLabel(const std::string& section);
std::string Text(const Json& value, const std::string& missing = "미정");
std::string Issues(const Json& issues);
std::string Conditions(const Json& context);
/** @brief 서비스가 허용한 폼 경로의 원문만 교체하며 다른 필드와 미정값을 보존한다. */
void ReplaceField(Json& record, const Json& path, const Json& value);
Json Field(const Json& record, const Json& path);
/** @brief 같은 프로젝트/개정의 유한 후보만 적용할 수 있다. */
bool MatchesReview(const Json& review, const Json& input, const std::string& project);
/** @brief 변경 후 개정과 원본 소유권을 갖춘 권위 응답만 편집 성공으로 수용한다. */
bool MatchesApplied(const Json& response, const std::string& project);
}
