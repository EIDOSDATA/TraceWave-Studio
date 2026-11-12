/** @file @brief 대화상자가 공개 서비스만 사용하는 비동기 전송 경계이다. */
#pragma once

#include "studio_types.h"
#include <functional>
#include <string>

/** @brief 물리 원본과 파일 경로를 대화상자에 노출하지 않는 요청 함수이다. */
using DialogGateway = std::function<void(const std::string&, const Json&, bool, std::function<void(const Json&)>,
                                         std::function<void(const Json&)>)>;
