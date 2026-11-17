/** @file @brief 결과 불명 출력의 실제 요청 키를 프로젝트 원본 밖에 보존한다. */
#pragma once
#include "studio_types.h"
#include <string>

namespace OutputPendingStore
{
Json Read(const std::string& workspace, const std::string& project);
void Write(const std::string& workspace, const std::string& project, const Json& request);
void Clear(const std::string& workspace, const std::string& project);
}
