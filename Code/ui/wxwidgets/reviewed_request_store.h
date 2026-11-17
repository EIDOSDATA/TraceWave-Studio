/** @file @brief 검토된 편집 요청의 원문과 ledger 정체성을 기능별로 보존한다. */
#pragma once
#include "studio_types.h"
#include <set>

namespace ReviewedRequestStore
{
/** @brief 경로 별칭을 정규화하되 작업공간 원문과 요청 입력은 변경하지 않는다. */
Json Read(const std::string& scope, const std::string& workspace, const std::string& project,
          const std::set<std::string>& methods);
/** @brief 영속 보존에 성공한 뒤에만 서버에 변경 요청을 보낼 수 있다. */
void Write(const std::string& scope, const std::string& workspace, const std::string& project,
           const std::set<std::string>& methods, const Json& request);
/** @brief 변경 전 확정 거절 또는 권위 영수증을 확인한 요청만 회수한다. */
void Clear(const std::string& scope, const std::string& workspace, const std::string& project);
}
