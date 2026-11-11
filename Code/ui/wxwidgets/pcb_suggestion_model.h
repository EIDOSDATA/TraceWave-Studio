/** @file @brief 서버의 적층 물성 제안과 기존 직접 입력 사이의 표시 및 채택 경계를 정의한다. */
#pragma once

#include <nlohmann/json.hpp>
#include <string>

namespace Studio::PcbSuggestions
{
using Json = nlohmann::json;

/** @brief 출처 개정, 층 대응과 상태를 검사하며 물성값을 생성하거나 환산하지 않는다. */
void Validate(const Json& source, const Json& response);
/** @brief 내부 상태를 공개값, 미정, 근사 필요 등 사용자용 표기로 바꾼다. */
std::string StateLabel(const std::string& state);
/** @brief 기존 층 재료 또는 작성한 재료를 덮어쓰지 않는 명시적 채택 입력만 반환한다. */
Json PrepareUse(const Json& source, const Json& response, std::size_t index, const Json& layers, const Json& materials);
}
