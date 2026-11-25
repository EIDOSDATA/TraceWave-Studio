#pragma once

#include <nlohmann/json.hpp>

#include <string>
#include <vector>

/** @brief 대역, 성능과 출처의 서비스 표시 필드로부터 초안과 변경값을 관리한다. */
class PrototypeTarget
{
public:
    enum class Page { band, criteria, sources };
    struct Option
    {
        std::string value;
        std::string label;
    };
    struct Field
    {
        std::string key;
        std::string label;
        std::string help;
        std::string original;
        std::string draft;
        std::vector<Option> choices;
        Page page;
        bool readonly;
        bool multiline;
    };
    struct Preset
    {
        std::string id;
        std::string name;
        std::string scope;
        std::string version;
    };

    void accept(const nlohmann::json& reply, const std::string& project, const std::string& revision,
        const std::string& saved, const std::string& id, const std::string& preset);
    void discard();
    bool available(const Field& field) const;
    bool dirty() const;
    bool hasChanges() const;
    nlohmann::json changes() const;

    bool loaded = false;
    std::string summary;
    std::string reason;
    std::vector<Option> items;
    std::vector<Preset> presets;
    std::vector<Field> fields;

private:
    const std::string& value(const std::string& key) const;
};
