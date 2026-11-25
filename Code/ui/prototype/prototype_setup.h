#pragma once

#include "../wxwidgets/pcb_selection_model.h"

#include <array>
#include <optional>
#include <string>
#include <vector>

/** @brief 기판 검토와 물리 구성, 규칙의 입력 및 읽기 결과를 따로 유지한다. */
class PrototypeSetup
{
public:
    enum class Request
    {
        board, boardPreview, boardApply, physical, physicalApply, rules, rulesApply, check,
        catalogConnect, catalogSearch, catalogDetail
    };
    enum class Page { board, physical, rules };
    using Json = nlohmann::json;

    struct Field
    {
        std::string key;
        std::string caption;
        std::string kind;
        Json original;
        Json value;
        Json choices;
        bool readonly;
    };

    struct Port
    {
        std::string id;
        std::string name;
        std::array<std::string, 6> original;
        std::array<std::string, 6> value;
        std::string reason;
        bool bound;
    };

    void accept(Request request, const Json& reply, const Json& input, const std::string& project,
        const std::string& revision, const std::string& newSelection);
    void invalidate(const std::string& revision);
    void discard();
    void edited();
    void failed(Request request, std::string message);
    Json readInput() const;
    Json formInput(const std::string& command, bool remove) const;
    Json boardPreview();
    Json boardApply(const std::string& command);
    Json checkInput(const char* inclusion) const;
    bool dirty() const;
    bool canSet() const;
    bool canRemove() const;
    bool fieldEnabled(const Field& field) const;
    const Json& recordChoices() const;

    static const char* method(Request request);
    static bool mutation(Request request);
    static bool catalogRequest(Request request);
    Json catalogInput(Request request) const;
    void acceptCatalog(Request request, const Json& reply, const Json& input);

    Page page = Page::board;
    std::string section = "stack";
    std::string record;
    std::string target;
    std::string parameter;
    std::string reason;
    std::string status;
    Json context;
    Json report;
    std::string catalogPath;
    std::string catalogId;
    std::string catalogQuery;
    std::string catalogPublisher;
    std::string catalogEntity = "native_templates";
    std::size_t catalogOffset = 0;
    std::size_t catalogItem = 0;
    Json catalogRows;
    Json catalogDetail;
    std::vector<Field> fields;
    std::vector<std::string> materials;
    std::vector<Port> ports;
    std::optional<Studio::PcbSelectionModel> board;
    Studio::PcbSelectionModel::Token boardToken = 0;

private:
    Json ruleSelection() const;
    Json changes() const;
    Json boardSpecification() const;
};
