/** @file @brief 공개 기판, 설치와 규칙 서비스에 검토한 변경만 전달한다. */
#include "prototype_setup.h"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <stdexcept>

namespace
{
using Json = nlohmann::json;
using Request = PrototypeSetup::Request;

Json nullable(const std::string& text)
{
    return text.empty() ? Json(nullptr) : Json(text);
}

Json coordinate(const std::string& text)
{
    if (text.empty())
    {
        return nullptr;
    }
    double value{};
    const auto* end = text.data() + text.size();
    const auto result = std::from_chars(text.data(), end, value);
    if (result.ec != std::errc{} || result.ptr != end || !std::isfinite(value))
    {
        throw std::runtime_error("포트 좌표는 유한한 mm 숫자 또는 빈 값이어야 합니다.");
    }
    return value;
}
}

const char* PrototypeSetup::method(Request request)
{
    static constexpr auto names = std::array{"pcb.selection.context", "pcb.selection.preview", "pcb.selection.apply",
        "physical.setup.get", "physical.setup.apply", "design.rules.get", "design.rules.apply", "design.rules.check",
        "catalog.connect", "catalog.search", "catalog.get"};
    return names.at(static_cast<std::size_t>(request));
}

bool PrototypeSetup::mutation(Request request)
{
    return request == Request::boardApply || request == Request::physicalApply || request == Request::rulesApply;
}

bool PrototypeSetup::catalogRequest(Request request)
{
    return request == Request::catalogConnect || request == Request::catalogSearch || request == Request::catalogDetail;
}

Json PrototypeSetup::catalogInput(Request request) const
{
    if (request == Request::catalogConnect)
    {
        return {{"database", catalogPath}};
    }
    if (request == Request::catalogDetail)
    {
        return {{"catalog_id", catalogId}, {"entity", catalogEntity},
            {"id", catalogRows.at("items").at(catalogItem).at("id")}, {"raw_limit", 1}};
    }
    Json filters = Json::object();
    if (!catalogPublisher.empty())
    {
        filters["publisher"] = catalogPublisher;
    }
    return {{"entity", catalogEntity}, {"catalog_id", catalogId}, {"query", catalogQuery},
        {"filters", std::move(filters)}, {"offset", catalogOffset}, {"limit", 12}, {"include_total", true}};
}

/** @brief 조회한 자료만 화면에 올리고 기판의 편집 초안은 건드리지 않는다. */
void PrototypeSetup::acceptCatalog(Request request, const Json& reply, const Json& input)
{
    if (request == Request::catalogConnect)
    {
        if (reply.at("available") != true)
        {
            const auto diagnostic = reply.value("diagnostic", Json::object());
            status = diagnostic.value("message", "카탈로그 인덱스를 연결할 수 없습니다.");
            return;
        }
        catalogId = reply.at("catalog_id").get<std::string>();
        catalogOffset = catalogItem = 0;
        catalogRows = catalogDetail = nullptr;
        status = "읽기 전용 카탈로그를 연결했습니다.";
        return;
    }
    if (reply.at("entity") != input.at("entity") || reply.at("catalog_id") != input.at("catalog_id"))
    {
        throw std::runtime_error("카탈로그 결과의 개정 또는 자료 종류가 요청과 다릅니다.");
    }
    if (request == Request::catalogSearch)
    {
        if (reply.at("offset") != input.at("offset") || !reply.at("items").is_array())
        {
            throw std::runtime_error("카탈로그 검색 페이지가 요청과 다릅니다.");
        }
        catalogRows = reply;
        catalogDetail = nullptr;
        catalogItem = 0;
    }
    else
    {
        if (reply.at("item").at("id") != input.at("id"))
        {
            throw std::runtime_error("선택한 제조업체 자료와 응답이 다릅니다.");
        }
        catalogDetail = reply;
    }
    status.clear();
}

Json PrototypeSetup::ruleSelection() const
{
    return {{"section", section}, {"record_id", nullable(record)}, {"target_id", nullable(target)},
        {"parameter_id", nullable(parameter)}};
}

Json PrototypeSetup::readInput() const
{
    if (page == Page::board)
    {
        return Json::object();
    }
    return page == Page::physical ? Json{{"section", section}, {"record_id", nullable(record)}} :
        Json{{"selection", ruleSelection()}};
}

/** @brief 개정과 대상이 일치하는 응답만 입력과 검사 결과에 반영한다. */
void PrototypeSetup::accept(Request request, const Json& reply, const Json& input, const std::string& project,
    const std::string& revision, const std::string& newSelection)
{
    if (catalogRequest(request))
    {
        acceptCatalog(request, reply, input);
        return;
    }
    if (reply.at("project_id") != project)
    {
        throw std::runtime_error("설정 응답의 프로젝트가 다릅니다.");
    }
    if (request == Request::boardPreview)
    {
        if (!board || !board->AcceptPreview(boardToken, reply))
        {
            throw std::runtime_error("기판 미리보기와 요청이 일치하지 않습니다.");
        }
        status = board->CanApply() ? "기판 변경을 검토했습니다." : "차단 사유가 있는 기판 변경입니다.";
        return;
    }
    if (mutation(request))
    {
        if (reply.at("new_revision") == revision ||
            (request == Request::boardApply && (!board || !board->AcceptApply(boardToken, reply))))
        {
            throw std::runtime_error("설정 적용 결과의 개정 또는 검토 자료가 다릅니다.");
        }
        if (request == Request::physicalApply)
        {
            const auto& id = reply.at("record_id");
            record = id.is_null() ? "" : id.get<std::string>();
        }
        if (request == Request::rulesApply)
        {
            const auto& selection = reply.at("selection");
            if (selection.at("section") != input.at("selection").at("section"))
            {
                throw std::runtime_error("적용된 설계 규칙의 종류가 다릅니다.");
            }
            const auto& id = selection.at("record_id");
            record = id.is_null() ? "" : id.get<std::string>();
        }
        reason.clear();
        fields.clear();
        ports.clear();
        materials.clear();
        context = nullptr;
        report = nullptr;
        board.reset();
        status = "설정 변경을 적용했습니다.";
        return;
    }
    if (reply.at("revision_id") != revision)
    {
        throw std::runtime_error("현재 개정과 다른 설정 응답입니다.");
    }
    if (request == Request::check)
    {
        if (reply.at("profile") != "rfad.design-checks/0.1" || reply.at("scope").at("inclusion") != input.at("inclusion") ||
            !reply.at("issues").is_array() || !reply.at("checks").is_array())
        {
            throw std::runtime_error("검사 범위나 결과 형식이 요청과 다릅니다.");
        }
        report = reply;
        status.clear();
        return;
    }
    if (request == Request::board)
    {
        std::vector<std::string> assignments;
        std::vector<Port> coordinates;
        for (const auto& layer : reply.at("layers"))
        {
            const auto& value = layer.at("material_id");
            assignments.push_back(value.is_null() ? "" : value.get<std::string>());
        }
        for (const auto& row : reply.at("ports"))
        {
            Port port{row.at("id").get<std::string>(), row.at("name").get<std::string>(), {}, {}, {},
                row.at("parameter_bound").get<bool>()};
            for (std::size_t index = 0; index < 6; ++index)
            {
                const auto& endpoint = row.at(index < 3 ? "start_mm" : "stop_mm");
                if (!endpoint.is_null() && !endpoint.at(index % 3).is_null())
                {
                    port.original[index] = endpoint.at(index % 3).dump();
                }
            }
            port.value = port.original;
            coordinates.push_back(std::move(port));
        }
        board.emplace(reply, newSelection);
        materials = std::move(assignments);
        ports = std::move(coordinates);
    }
    else
    {
        const bool physical = request == Request::physical;
        if (physical ? reply.at("profile") != "rfad.physical-setup/0.1" ||
                reply.at("section") != input.at("section") || reply.at("record_id") != input.at("record_id") :
                reply.at("profile") != "rfad.design-rules-editor/0.1" || reply.at("selection") != input.at("selection"))
        {
            throw std::runtime_error("설정 폼의 선택 대상이 요청과 다릅니다.");
        }
        std::vector<Field> parsed;
        for (const auto& row : reply.at("fields"))
        {
            const auto kind = row.at(physical ? "kind" : "editor").get<std::string>();
            const auto unit = row.value("unit", "");
            const auto caption = row.at("label").get<std::string>() + (unit.empty() ? "" : " (" + unit + ")");
            parsed.push_back({row.at("key").get<std::string>(), caption, kind, row.at("value"), row.at("value"),
                row.value("choices", Json::array()), row.value("readonly", false)});
        }
        fields = std::move(parsed);
    }
    context = reply;
    report = nullptr;
    reason.clear();
    status.clear();
}

void PrototypeSetup::invalidate(const std::string& revision)
{
    if (context.is_object() && context.at("revision_id") != revision)
    {
        context = nullptr;
        report = nullptr;
        board.reset();
        status = "개정이 바뀌었습니다. 설정을 다시 읽으세요.";
    }
}

bool PrototypeSetup::fieldEnabled(const Field& field) const
{
    if (field.readonly)
    {
        return false;
    }
    if (page == Page::rules && field.key.ends_with(".value"))
    {
        const auto mode = field.key.substr(0, field.key.size() - 5) + "mode";
        const auto found = std::ranges::find(fields, mode, &Field::key);
        return found != fields.end() && found->value == "value";
    }
    return true;
}

Json PrototypeSetup::changes() const
{
    auto result = Json::object();
    for (const auto& field : fields)
    {
        if (field.value != field.original && fieldEnabled(field))
        {
            result[field.key] = field.value;
        }
    }
    return result;
}

bool PrototypeSetup::dirty() const
{
    if (page == Page::board && board)
    {
        for (std::size_t i = 0; i < materials.size(); ++i)
        {
            if (nullable(materials[i]) != context.at("layers").at(i).at("material_id"))
            {
                return true;
            }
        }
        return std::ranges::any_of(ports, [](const Port& port)
        {
            return port.original != port.value || !port.reason.empty();
        });
    }
    return !reason.empty() || std::ranges::any_of(fields, [](const Field& field)
    {
        return field.value != field.original;
    });
}

void PrototypeSetup::discard()
{
    if (page == Page::board && board)
    {
        for (std::size_t i = 0; i < materials.size(); ++i)
        {
            const auto& id = context.at("layers").at(i).at("material_id");
            materials[i] = id.is_null() ? "" : id.get<std::string>();
        }
        for (auto& port : ports)
        {
            port.value = port.original;
            port.reason.clear();
        }
    }
    for (auto& field : fields)
    {
        field.value = field.original;
    }
    reason.clear();
    edited();
}

void PrototypeSetup::edited()
{
    if (board && board->CurrentStage() != Studio::PcbSelectionModel::Stage::Applying)
    {
        board->Invalidate();
    }
    report = nullptr;
    status.clear();
}

void PrototypeSetup::failed(Request request, std::string message)
{
    if (board && request == Request::boardPreview)
    {
        board->Fail(boardToken, Json{{"message", message}});
    }
    if (board && request == Request::boardApply)
    {
        const auto selection = board->SelectionId();
        board.emplace(context, selection);
    }
    status = std::move(message);
}

bool PrototypeSetup::canSet() const
{
    return context.is_object() && !reason.empty() && std::ranges::any_of(fields, [this](const Field& field)
    {
        return field.value != field.original && fieldEnabled(field);
    });
}

bool PrototypeSetup::canRemove() const
{
    return context.is_object() && context.value("exists", false) && section != "activation";
}

Json PrototypeSetup::formInput(const std::string& command, bool remove) const
{
    if (command.empty() || reason.empty() || !(remove ? canRemove() : canSet()))
    {
        throw std::runtime_error("설정 변경과 사유를 확인하세요.");
    }
    auto input = readInput();
    input["operation"] = remove ? "remove" : "set";
    input["command_id"] = command;
    input["reason"] = reason;
    if (page == Page::physical)
    {
        input["changes"] = remove ? Json::object() : changes();
        input["step_token"] = nullptr;
    }
    else
    {
        input["values"] = remove ? Json::object() : changes();
    }
    return input;
}

Json PrototypeSetup::boardSpecification() const
{
    Json assignments = Json::object();
    for (std::size_t i = 0; i < materials.size(); ++i)
    {
        const auto& row = context.at("layers").at(i);
        if (auto current = nullable(materials[i]); current != row.at("material_id"))
        {
            assignments[row.at("id").get<std::string>()] = std::move(current);
        }
    }
    Json updates = Json::array();
    for (const auto& port : ports)
    {
        if (port.value == port.original && port.reason.empty())
        {
            continue;
        }
        if (port.reason.empty())
        {
            throw std::runtime_error("포트 좌표를 바꾸는 이유를 입력하세요.");
        }
        Json endpoints[] = {Json::array(), Json::array()};
        for (std::size_t index = 0; index < port.value.size(); ++index)
        {
            endpoints[index / 3].push_back(coordinate(port.value[index]));
        }
        updates.push_back({{"id", port.id}, {"start_mm", endpoints[0]}, {"stop_mm", endpoints[1]}, {"reason", port.reason}});
    }
    return {{"source", nullptr}, {"materials", Json::array()},
        {"material_assignments", std::move(assignments)}, {"port_updates", std::move(updates)}};
}

Json PrototypeSetup::boardPreview()
{
    board->SetSpecification(boardSpecification());
    boardToken = board->BeginRequest("preview");
    return board->PreviewInput();
}

Json PrototypeSetup::boardApply(const std::string& command)
{
    if (board->Specification() != boardSpecification())
    {
        throw std::runtime_error("기판 입력을 다시 검토하세요.");
    }
    const auto input = board->ApplyInput(command);
    boardToken = board->BeginRequest("apply");
    return input;
}

Json PrototypeSetup::checkInput(const char* inclusion) const
{
    const auto targets = target.empty() ? Json(nullptr) : Json::array({target});
    return {{"inclusion", inclusion}, {"target_ids", targets},
        {"manufacturing_profile_id", section == "manufacturing_profile" ? nullable(record) : Json(nullptr)}};
}

const Json& PrototypeSetup::recordChoices() const
{
    if (page != Page::physical)
    {
        return context.at("records");
    }
    static const auto empty = Json::array();
    const auto& records = context.at("records");
    return records.contains(section) ? records.at(section) : empty;
}
