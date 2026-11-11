/** @file @brief PCB 화면 DTO의 형식 확인을 상태 전이에서 분리한다. */
#pragma once

#include <nlohmann/json.hpp>
#include <string>

namespace Studio::PcbSelectionData
{
using Json = nlohmann::json;
void Require(bool condition, const std::string& message);
void Uuid(const Json& value);
void Source(const Json& value);
void Context(const Json& value);
void Specification(const Json& value);
void Draft(const Json& source, const Json& value);
void Preview(const Json& value);
void Bounded(const Json& value);
}
