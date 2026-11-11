#include "editor_presentation.h"
#include <vector>

namespace EditorPresentation
{
namespace
{
/** @brief 표시 원문을 유지하며 null 입력만 빈 문자열로 나타낸다. */
std::string Text(const Json& value)
{
    return value.is_string() ? value.get<std::string>() : (value.is_null() ? "" : value.dump());
}
}

/** @brief 표시 정책과 관계없는 grid 초안을 읽거나 확정하지 않는다. */
bool RequiresCurrentValue(const std::string& key)
{
    const auto separator = key.rfind('.');
    const std::string suffix = separator == std::string::npos ? key : key.substr(separator + 1);
    return suffix == "mode" || suffix == "value" || suffix == "unit";
}

/** @brief 입력 모드와 고급 정보 선택에 따라 가용 상태를 계산한다. */
Availability Evaluate(const std::string& key, const Fields& fields, bool showDetails)
{
    const Json& descriptor = *fields.at(key).descriptor;
    bool enabled = !descriptor.value("readonly", false);
    bool visible = !descriptor.value("advanced", false) || showDetails;
    if (key.size() >= 12 && key.substr(key.size() - 12) == "display_note" &&
        descriptor.at("value") == "")
    {
        visible = false;
    }
    const auto parameterMode = fields.find("mode");
    if (parameterMode != fields.end())
    {
        const std::string mode = parameterMode->second.value.get<std::string>();
        if (key == "value")
        {
            enabled = enabled && mode == "value";
            visible = visible && mode != "missing";
        }
        else if (key == "expression" || key == "bindings")
        {
            enabled = enabled && mode == "expression";
            visible = visible && mode == "expression";
        }
    }
    const std::size_t separator = key.rfind('.');
    if (separator != std::string::npos)
    {
        const std::string prefix = key.substr(0, separator);
        const std::string suffix = key.substr(separator + 1);
        const auto modeField = fields.find(prefix + ".mode");
        if (modeField != fields.end())
        {
            const std::string mode = modeField->second.value.get<std::string>();
            if (suffix == "value")
            {
                enabled = enabled && mode == "value";
                visible = visible && mode != "missing";
            }
            else if (suffix == "unit")
            {
                enabled = enabled && mode != "parameter";
            }
            else if (suffix == "parameter_id")
            {
                enabled = enabled && mode == "parameter";
                visible = visible && mode == "parameter";
            }
        }
    }
    return {enabled, visible};
}

/** @brief 서비스의 객체 경로와 배열 경로를 현재 폼의 안정된 필드 키로 해석한다. */
std::string ResolveDiagnosticField(const std::string& path, const Json& selection, const Fields& fields)
{
    std::string key;
    for (const char character : path)
    {
        if (character == '[')
        {
            key += '.';
        }
        else if (character != ']')
        {
            key += character;
        }
    }
    if (key.compare(0, 7, "values.") == 0)
    {
        key.erase(0, 7);
    }
    const std::string kind = selection.value("kind", "");
    const std::string identity = selection.value("id", "");
    const std::map<std::string, std::string> collections = {
        {"parameter", "parameters"}, {"new_parameter", "parameters"}, {"material", "materials"},
        {"layer", "stackup"}, {"geometry", "geometry"}, {"port", "ports"}, {"net", "nets"}
    };
    auto collection = collections.find(kind);
    std::vector<std::string> prefixes;
    if (collection != collections.end() && !identity.empty())
    {
        prefixes.push_back(collection->second + "." + identity + ".");
        if (kind == "parameter" || kind == "new_parameter")
        {
            prefixes.push_back("parameters.input.");
        }
    }
    if (kind == "board")
    {
        prefixes.push_back("board.");
    }
    for (const auto& prefix : prefixes)
    {
        if (key.compare(0, prefix.size(), prefix) == 0)
        {
            key.erase(0, prefix.size());
            break;
        }
    }
    if (key == "quantity.value_si")
    {
        key = "value";
    }
    else if (key == "quantity.display_unit")
    {
        key = "unit";
    }
    if (fields.count(key) != 0)
    {
        return key;
    }
    for (const auto& item : fields)
    {
        if (item.second.descriptor->at("editor") == "coordinate_table" &&
            key.compare(0, item.first.size() + 1, item.first + ".") == 0)
        {
            return item.first;
        }
    }
    for (const auto& suffix : {".value", ".parameter_id", ".mode"})
    {
        const auto found = fields.find(key + suffix);
        if (found != fields.end() && found->second.enabled)
        {
            return found->first;
        }
    }
    return "";
}

/** @brief 평가값과 단위가 한 행에 표시될 때 입력 모드에 맞는 라벨을 만든다. */
std::string ValueLabel(const std::string& key, const Fields& fields)
{
    const bool rootValue = key == "value";
    if (!rootValue && (key.size() <= 6 || key.substr(key.size() - 6) != ".value"))
    {
        return "";
    }
    const std::string prefix = rootValue ? "" : key.substr(0, key.size() - 5);
    const auto unit = fields.find(prefix + "unit");
    const auto mode = fields.find(prefix + "mode");
    if (unit == fields.end() || mode == fields.end())
    {
        return "";
    }
    const std::string inputMode = mode->second.value.get<std::string>();
    return inputMode == "missing" ? unit->second.descriptor->at("label").get<std::string>() :
        ((rootValue && inputMode == "expression" ? std::string("마지막 적용값") :
            fields.at(key).descriptor->at("label").get<std::string>() + (inputMode == "parameter" ? " (마지막 적용값)" : "")) + " / 단위");
}

/** @brief 단위만 변경된 초안의 환산 안내를 실제 변경 상태에서 생성한다. */
std::string InputNotice(const Fields& fields)
{
    std::vector<std::string> notices;
    for (const auto& item : fields)
    {
        const std::string& key = item.first;
        const bool rootUnit = key == "unit";
        if (!rootUnit && (key.size() <= 5 || key.substr(key.size() - 5) != ".unit"))
        {
            continue;
        }
        const std::string prefix = rootUnit ? "" : key.substr(0, key.size() - 4);
        const auto number = fields.find(prefix + "value");
        const auto mode = fields.find(prefix + "mode");
        if (number == fields.end() || mode == fields.end() ||
            item.second.value == item.second.descriptor->at("value"))
        {
            continue;
        }
        const std::string inputMode = mode->second.value.get<std::string>();
        const std::string original = Text(number->second.descriptor->at("value"));
        if (original.empty() || inputMode == "missing" || inputMode == "parameter" ||
            (inputMode == "value" && number->second.value != number->second.descriptor->at("value")))
        {
            continue;
        }
        notices.push_back(number->second.descriptor->at("label").get<std::string>() +
            ": 단위만 변경한 숫자는 적용 후 환산됩니다. 마지막 적용값: " + original + " " +
            Text(item.second.descriptor->at("value")) + ". 값도 함께 수정하면 새 값과 단위를 사용합니다.");
    }
    std::string text = notices.empty() ? "" : notices.front();
    if (notices.size() > 1)
    {
        text += " 같은 상태의 다른 항목 " + std::to_string(notices.size() - 1) + "개.";
    }
    return text;
}
}
