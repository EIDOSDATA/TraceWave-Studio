#pragma once

#include <nlohmann/json.hpp>
#include <map>
#include <string>

/** @brief 위젯 없이 필드 표시 규칙과 진단 경로를 해석하는 presentation 정책이다. */
namespace EditorPresentation
{
using Json = nlohmann::json;

/** @brief 원래 descriptor를 복제하지 않고 한 번 읽은 현재 입력을 평가한다. */
struct Field
{
    const Json* descriptor;
    Json value;
    bool enabled;
};
using Fields = std::map<std::string, Field>;

struct Availability
{
    bool enabled;
    bool visible;
};

bool RequiresCurrentValue(const std::string& key);
Availability Evaluate(const std::string& key, const Fields& fields, bool showDetails);
std::string ResolveDiagnosticField(const std::string& path, const Json& selection, const Fields& fields);
std::string ValueLabel(const std::string& key, const Fields& fields);
std::string InputNotice(const Fields& fields);
}
