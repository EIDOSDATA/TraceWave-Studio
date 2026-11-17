/** @file @brief 가져오기 응답이 보존한 원래 요청에 속하는지 표시층에서 대조한다. */
#pragma once
#include "studio_types.h"

namespace PcbImportUi
{
/** @brief 권위 영수증도 다른 원문이나 검토 해시이면 수용하지 않는다. */
bool MatchesResponse(const Json& request, const Json& response, const std::string& project);
}
