/** @file @brief 공개 문헌 후보의 입력, 원본 표시 장면과 적용 해시를 관리한다. */
#include "prototype_template.h"

#include <algorithm>
#include <stdexcept>

namespace
{
using Json = nlohmann::json;
constexpr auto profile = "rfad.template-candidate/0.2";

const Json& cardModes(const Json& card)
{
    static const auto explicitMode = Json::array({"explicit_geometry"});
    return card.contains("modes") ? card.at("modes") : explicitMode;
}
}

bool PrototypeTemplate::Draft::dirty() const
{
    return recipe != 0 || !frequency.empty() || frequencyUnit != "GHz" || !assumption.empty() || goalDimension ||
        std::ranges::any_of(fields, [](const Field& field)
        {
            return field.value != field.original;
        });
}

bool PrototypeTemplate::dirty() const
{
    return std::ranges::any_of(drafts_, [](const auto& pair)
    {
        return pair.second.dirty();
    });
}

const Json& PrototypeTemplate::card() const
{
    return context_.at("cards").at(card_);
}

const Json& PrototypeTemplate::modes() const
{
    return cardModes(card());
}

PrototypeTemplate::Key PrototypeTemplate::draftKey() const
{
    return {card().at("template_id").get<std::string>(), card().at("content_hash").get<std::string>(), mode_};
}

PrototypeTemplate::Draft& PrototypeTemplate::draft()
{
    const auto [entry, inserted] = drafts_.try_emplace(draftKey());
    if (inserted)
    {
        const auto references = card().value("reference_inputs", Json::object());
        for (const auto& field : card().at("input_fields"))
        {
            const auto key = field.at("key").get<std::string>();
            const bool found = references.contains(key);
            const auto original = found ? references.at(key).at("display_value").get<std::string>() : std::string{};
            entry->second.fields.push_back({key, field.at("label").get<std::string>(), field.at("display_unit").get<std::string>(),
                original, original, found});
        }
    }
    return entry->second;
}

void PrototypeTemplate::clearReview()
{
    review_.reset();
    reviewed_ = nullptr;
}

void PrototypeTemplate::discard()
{
    drafts_.clear();
    clearReview();
    status.clear();
}

void PrototypeTemplate::invalidate(const std::string& revision)
{
    if (hasContext() && context_.at("expected_revision") != revision)
    {
        context_ = nullptr;
        clearReview();
        status.clear();
    }
}

void PrototypeTemplate::acceptContext(const Json& reply, const std::string& project, const std::string& revision)
{
    if (reply.at("profile") != profile || reply.at("project_id") != project || reply.at("expected_revision") != revision ||
        !reply.at("cards").is_array() || reply.at("cards").empty() || !reply.at("bindings").is_array() ||
        !reply.at("targets").is_array() || reply.at("new_instance_id").get<std::string>().empty())
    {
        throw std::runtime_error("문헌 카드 조회의 프로젝트, 개정 또는 적용 대상이 다릅니다.");
    }
    for (const auto& item : reply.at("cards"))
    {
        if (!item.at("input_fields").is_array() || !cardModes(item).is_array() || cardModes(item).empty())
        {
            throw std::runtime_error("문헌 카드의 입력 또는 후보 방식이 올바르지 않습니다.");
        }
    }
    context_ = reply;
    card_ = std::min(card_, reply.at("cards").size() - 1);
    mode_ = std::min(mode_, modes().size() - 1);
    layer_ = target_ = 0;
    clearReview();
    status.clear();
}

void PrototypeTemplate::selectCard(std::size_t index)
{
    card_ = index;
    mode_ = 0;
    clearReview();
    status.clear();
}

void PrototypeTemplate::selectMode(std::size_t index)
{
    mode_ = index;
    clearReview();
    status.clear();
}

void PrototypeTemplate::selectLayer(std::size_t index)
{
    layer_ = index;
    clearReview();
    status.clear();
}

void PrototypeTemplate::selectTarget(std::size_t index)
{
    target_ = index;
    clearReview();
    status.clear();
}

bool PrototypeTemplate::ready() const
{
    return hasContext() && !context_.at("board").is_null() && layer_ > 0 &&
        layer_ <= context_.at("bindings").size();
}

Json PrototypeTemplate::specification() const
{
    if (!ready())
    {
        throw std::runtime_error("후보를 적용할 기판과 도체층을 선택하세요.");
    }
    const auto& current = drafts_.at(draftKey());
    const auto& binding = context_.at("bindings").at(layer_ - 1);
    const auto mode = modes().at(mode_).get<std::string>();
    Json inputs = Json::object();
    Json targets = Json::array();
    if (target_ > 0)
    {
        const auto& row = context_.at("targets").at(target_ - 1);
        targets.push_back({{"id", row.at("id")}, {"revision_id", row.at("revision_id")}});
    }
    for (const auto& field : current.fields)
    {
        const bool fromTarget = current.goalDimension && target_ > 0 &&
            ((card().at("template_id") == "builtin.explicit_arc" && field.key == "radius") ||
             (card().at("template_id") == "builtin.explicit_planar_ifa" && field.key == "radiator_length"));
        if (fromTarget)
        {
            inputs[field.key] = {{"source", "target_quarter_wave"}};
        }
        else if (mode == "initial_estimate" && field.key == "length")
        {
            inputs[field.key] = {{"source", "initial_estimate"}};
        }
        else if (field.value.empty())
        {
            throw std::runtime_error(field.label + " 값을 입력하세요.");
        }
        else
        {
            inputs[field.key] = field.fromCard && field.value == field.original ?
                Json{{"source", "card"}} : Json{{"value", field.value}, {"unit", field.unit}};
        }
    }
    Json result{{"expected_revision", context_.at("expected_revision")}, {"mode", mode},
        {"template", {{"template_id", card().at("template_id")}, {"version", card().at("version")},
                      {"content_hash", card().at("content_hash")}}},
        {"instance_id", context_.at("new_instance_id")}, {"target_refs", targets},
        {"binding", {{"board_id", context_.at("board").at("id")}, {"frame_id", context_.at("frame_id")},
                     {"layer_id", binding.at("layer_id")}, {"material_id", binding.at("material_id")}}},
        {"explicit_inputs", std::move(inputs)}, {"port", nullptr}};
    if (mode == "initial_estimate")
    {
        const auto& recipe = card().at("seed_recipes").at(current.recipe);
        result["seed"] = {{"recipe_id", recipe.at("id")}, {"frequency", {{"value", current.frequency},
            {"unit", current.frequencyUnit}}}, {"assumption", current.assumption}};
    }
    return result;
}

void PrototypeTemplate::acceptPreview(const Json& reply, const std::string& project, const Json& input)
{
    if (reply.at("profile") != profile || reply.at("project_id") != project ||
        reply.at("expected_revision") != input.at("expected_revision") || input != specification())
    {
        throw std::runtime_error("현재 문헌 입력과 미리보기 응답이 다릅니다.");
    }
    Review next;
    if (reply.at("can_apply").get<bool>())
    {
        next.hash = reply.at("preview_hash").get<std::string>();
        if (next.hash.size() != 64 || next.hash.find_first_not_of("0123456789abcdef") != std::string::npos)
        {
            throw std::runtime_error("후보 검토 해시의 형식이 올바르지 않습니다.");
        }
        next.scene = CanvasScene::Model::Parse(reply.at("scene"));
        next.generated = reply.at("generated_ids").at("geometry").get<std::vector<std::string>>();
        next.notes = reply.at("generation").at("summary").get<std::string>();
    }
    for (const auto& row : reply.at("issues"))
    {
        next.notes += "\n" + row.at("code").get<std::string>() + " " + row.at("message").get<std::string>();
    }
    if (const auto& checks = reply.at("input_checks"); checks.is_object())
    {
        next.notes += "\n해석 입력 검사 " + std::to_string(checks.at("diagnostic_count").get<std::size_t>()) + "건";
        for (const auto& issue : checks.at("diagnostics"))
        {
            next.notes += "\n" + issue.at("message_ko").get<std::string>();
        }
    }
    reviewed_ = input;
    review_ = std::move(next);
    status = canApply() ? "형상 검토 완료" : "차단된 후보입니다. 입력을 확인하세요.";
}

bool PrototypeTemplate::canApply() const
{
    return review_ && !review_->hash.empty() && ready();
}

Json PrototypeTemplate::application(const std::string& command) const
{
    if (!canApply() || command.empty() || reviewed_ != specification())
    {
        throw std::runtime_error("현재 입력의 미리보기를 다시 검토하세요.");
    }
    auto request = reviewed_;
    request["preview_hash"] = review_->hash;
    request["command_id"] = command;
    return request;
}

void PrototypeTemplate::acceptApply(const Json& reply, const std::string& project, const Json& input)
{
    if (reply.at("project_id") != project || reply.at("instance_id") != input.at("instance_id") ||
        reply.at("preview_hash") != input.at("preview_hash") || reply.at("new_revision") == input.at("expected_revision"))
    {
        throw std::runtime_error("문헌 적용 응답의 프로젝트, 개정 또는 후보가 다릅니다.");
    }
    drafts_.erase(draftKey());
    context_ = nullptr;
    clearReview();
    status = "검토한 형상을 적용했습니다.";
}
