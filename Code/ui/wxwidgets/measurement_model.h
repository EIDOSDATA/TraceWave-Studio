/** @file @brief 측정 폼의 표시 사전과 원문 보존 규칙을 수치 연산 없이 공유한다. */
#pragma once
#include "studio_types.h"
#include <string>
#include <vector>

namespace MeasurementUi
{
struct FieldDefinition
{
    std::string path, label, kind;
    std::vector<std::string> units;
};
const std::vector<FieldDefinition>& Fields();
Json Leaf(const Json& record, const std::string& path);
std::string Text(const Json& value);
std::string Lines(const Json& values);
Json Lines(const std::string& text);
std::string Evidence(int index);
int Evidence(const Json& leaf);
std::string Summary(const Json& record);
std::string Issues(const Json& response);
bool SameRecord(const Json& left, const Json& right);
}
