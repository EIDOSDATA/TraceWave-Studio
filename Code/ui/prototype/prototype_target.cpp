/** @file @brief 서비스가 허용한 목표 입력 중 사용자가 바꾼 활성 필드만 전달한다. */
#include "prototype_target.h"

#include <algorithm>
#include <sstream>
#include <stdexcept>

namespace
{
using Json = nlohmann::json;

std::string fieldText(const Json& value, bool multiline)
{
    if (!multiline)
    {
        return value.get<std::string>();
    }
    if (!value.is_array())
    {
        throw std::runtime_error("목표의 여러 줄 값은 배열이어야 합니다.");
    }
    std::string text;
    for (std::size_t index = 0; index < value.size(); ++index)
    {
        if (index)
        {
            text += '\n';
        }
        text += value.at(index).get<std::string>();
    }
    return text;
}
}

void PrototypeTarget::accept(const Json& reply, const std::string& project, const std::string& revision,
    const std::string& saved, const std::string& id, const std::string& preset)
{
    const auto& selection = reply.at("selection");
    const auto& fields = selection.at("fields");
    if (reply.at("profile") != "rfad.target-editor/0.1" || reply.at("project_id") != project ||
        reply.at("revision_id") != revision || reply.at("saved_revision") != saved ||
        !fields.is_array() || !reply.at("items").is_array() || !reply.at("band_presets").is_array() ||
        selection.at("id") != (id.empty() ? Json(nullptr) : Json(id)) ||
        selection.at("preset_id") != (preset.empty() ? Json(nullptr) : Json(preset)))
    {
        throw std::runtime_error("목표 응답의 프로젝트, 개정 또는 선택이 다릅니다.");
    }
    PrototypeTarget next;
    next.loaded = true;
    next.summary = reply.at("input_status").at("summary").get<std::string>();
    for (const auto& item : reply.at("items"))
    {
        const auto label = item.at("label").get<std::string>() + " / " + item.at("summary").get<std::string>();
        next.items.push_back({item.at("id").get<std::string>(), label});
    }
    for (const auto& item : reply.at("band_presets"))
    {
        next.presets.push_back({item.at("id").get<std::string>(), item.at("name").get<std::string>(),
            item.at("scope").get<std::string>(), item.at("version").get<std::string>()});
    }
    for (const auto& item : fields)
    {
        const auto key = item.at("key").get<std::string>();
        const auto editor = item.at("editor").get<std::string>();
        if (editor != "text" && editor != "choice" && editor != "string_lines")
        {
            throw std::runtime_error("지원하지 않는 목표 편집 필드입니다.");
        }
        const bool readonly = item.at("readonly").get<bool>();
        const bool multiline = editor == "string_lines";
        const auto text = fieldText(item.at("value"), multiline);
        const auto page = readonly ? Page::sources :
            key.starts_with("criteria.") || key.starts_with("observation.") ? Page::criteria : Page::band;
        Field field{key, item.at("label").get<std::string>(), item.value("help", std::string{}),
            text, text, {}, page, readonly, multiline};
        for (const auto& choice : item.at("choices"))
        {
            field.choices.push_back({choice.at("value").get<std::string>(), choice.at("label").get<std::string>()});
        }
        next.fields.push_back(std::move(field));
    }
    for (const auto& field : next.fields)
    {
        next.available(field);
    }
    *this = std::move(next);
}

void PrototypeTarget::discard()
{
    for (auto& field : fields)
    {
        field.draft = field.original;
    }
    reason.clear();
}

const std::string& PrototypeTarget::value(const std::string& key) const
{
    const auto field = std::ranges::find(fields, key, &Field::key);
    if (field == fields.end())
    {
        throw std::runtime_error("목표의 입력 방식 필드가 없습니다.");
    }
    return field->draft;
}

bool PrototypeTarget::available(const Field& field) const
{
    if (field.readonly)
    {
        return false;
    }
    if (field.key == "sampling.count")
    {
        return value("sampling.kind") == "linear";
    }
    if (field.key == "sampling.explicit")
    {
        return value("sampling.kind") == "explicit";
    }
    if (field.key.ends_with(".value"))
    {
        return value(field.key.substr(0, field.key.size() - 5) + "mode") == "value";
    }
    return true;
}

bool PrototypeTarget::dirty() const
{
    return !reason.empty() || std::ranges::any_of(fields, [](const Field& field)
    {
        return field.draft != field.original;
    });
}

bool PrototypeTarget::hasChanges() const
{
    return std::ranges::any_of(fields, [this](const Field& field)
    {
        return field.draft != field.original && available(field);
    });
}

Json PrototypeTarget::changes() const
{
    auto result = Json::object();
    for (const auto& field : fields)
    {
        if (field.draft == field.original || !available(field))
        {
            continue;
        }
        if (field.multiline)
        {
            auto lines = Json::array();
            std::istringstream input(field.draft);
            for (std::string line; std::getline(input, line);)
            {
                if (line.ends_with('\r'))
                {
                    line.pop_back();
                }
                if (!line.empty())
                {
                    lines.push_back(std::move(line));
                }
            }
            result[field.key] = std::move(lines);
        }
        else
        {
            result[field.key] = field.draft;
        }
    }
    return result;
}
