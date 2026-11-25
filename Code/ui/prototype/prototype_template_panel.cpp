/** @file @brief 공개 서비스의 문헌 카드, 후보 입력, 검토 장면을 표시한다. */
#include "prototype_template_panel.h"

#include "prototype_canvas.h"
#include "prototype_project.h"

#include <algorithm>
#include <misc/cpp/imgui_stdlib.h>

namespace
{
using accessibility::Control;
using Json = nlohmann::json;

void lines(const char* caption, const Json& entries)
{
    if (entries.empty())
    {
        return;
    }
    ImGui::SeparatorText(caption);
    for (const auto& entry : entries)
    {
        ImGui::Bullet();
        ImGui::TextWrapped("%s", entry.get_ref<const std::string&>().c_str());
    }
}

/** @brief 원문, 차이와 생략 항목을 카드에서 제공한 순서대로 표시한다. */
void sources(const Json& card)
{
    const auto& source = card.at("source");
    ImGui::TextWrapped("%s", source.at("scope").get_ref<const std::string&>().c_str());
    lines("출처 원문", source.at("references"));
    if (const auto entry = card.find("evidence"); entry != card.end())
    {
        for (const auto* key : {"archive_sha256", "inner_member", "inner_sha256"})
        {
            if (entry->contains(key))
            {
                ImGui::TextWrapped("%s %s", key, entry->at(key).get_ref<const std::string&>().c_str());
            }
        }
        lines("원문 사이의 차이", entry->value("source_conflicts", Json::array()));
        lines("생략한 형상과 조건", entry->at("omitted"));
        lines("미정 조건", entry->at("unknown"));
        lines("문헌에 보고된 값", entry->at("source_reported"));
    }
    lines("형상 생성 가정", card.at("assumptions"));
    lines("적용 범위와 한계", card.at("limitations"));
}

template<typename Label>
std::size_t choose(const char* caption, const Json& options, std::size_t current, Label label, const char* empty = nullptr)
{
    const std::size_t offset = empty ? 1 : 0;
    const auto shown = current >= offset ? label(options.at(current - offset)) : std::string(empty);
    if (ImGui::BeginCombo(caption, shown.c_str()))
    {
        if (empty && ImGui::Selectable(empty, current == 0))
        {
            current = 0;
        }
        for (std::size_t index = 0; index < options.size(); ++index)
        {
            ImGui::PushID(static_cast<int>(index));
            if (ImGui::Selectable(label(options.at(index)).c_str(), current == index + offset))
            {
                current = index + offset;
            }
            ImGui::PopID();
        }
        ImGui::EndCombo();
    }
    return current;
}

/** @brief 서비스가 제공한 초기식과 사용자 가정 입력을 같은 영역에서 보여 준다. */
template<typename Input>
bool drawSeed(const Json& recipes, PrototypeTemplate::Draft& draft, const Input& input)
{
    const auto recipe = choose("초기식", recipes, draft.recipe, [](const Json& row)
    {
        return row.at("label").get<std::string>();
    });
    bool changed = draft.recipe != recipe;
    draft.recipe = recipe;
    const Json& chosen = recipes.at(recipe);
    ImGui::TextWrapped("%s / %s", chosen.at("formula").get_ref<const std::string&>().c_str(),
        chosen.at("frequency_scope").get_ref<const std::string&>().c_str());
    lines("가정이 필요한 조건", chosen.at("conditions"));
    input("초기식 주파수", draft.frequency);
    if (ImGui::BeginCombo("초기식 주파수 단위", draft.frequencyUnit.c_str()))
    {
        for (const char* unit : {"Hz", "MHz", "GHz"})
        {
            if (ImGui::Selectable(unit, draft.frequencyUnit == unit))
            {
                changed |= draft.frequencyUnit != unit;
                draft.frequencyUnit = unit;
            }
        }
        ImGui::EndCombo();
    }
    input("초기식 조건을 채택한 근거와 사유", draft.assumption);
    return changed;
}
}

void PrototypeTemplatePanel::action(PrototypeProject& project, Control control)
{
    switch (control)
    {
        case Control::templateRead: project.readTemplate(); break;
        case Control::templateInput: review_ = false; break;
        case Control::templateReview: review_ = true; break;
        case Control::templatePreview:
            review_ = true;
            project.previewTemplate();
            break;
        case Control::templateApply: project.applyTemplate(); break;
        case Control::templateDiscard:
            if (!project.busy())
            {
                project.literature().discard();
                ++fieldGeneration_;
                review_ = false;
            }
            break;
        default: break;
    }
}

bool PrototypeTemplatePanel::draw(PrototypeProject& project, accessibility::Bridge& access, Control& focus)
{
    auto& model = project.literature();
    if (!model.hasContext() && project.writable() && model.status.empty())
    {
        project.readTemplate();
    }

    const auto button = [&](Control control, const char* label, bool enabled, bool checked = false)
    {
        ImGui::BeginDisabled(!enabled);
        if (focus == control)
        {
            ImGui::SetKeyboardFocusHere();
            focus = Control::root;
        }
        if (ImGui::SmallButton(label))
        {
            action(project, control);
        }
        access.item(control, Control::board, enabled, checked);
        ImGui::EndDisabled();
    };
    button(Control::templateInput, "카드와 입력", true, !review_);
    ImGui::SameLine();
    button(Control::templateReview, "후보 검토", true, review_);
    ImGui::SameLine();
    button(Control::templateRead, "다시 읽기", project.writable());
    if (model.hasContext())
    {
        button(Control::templatePreview, "형상 미리보기", project.writable() && model.ready());
        ImGui::SameLine();
        button(Control::templateApply, "검토한 형상 적용", project.writable() && model.canApply());
        ImGui::SameLine();
        button(Control::templateDiscard, "초안 취소", !project.busy() && (model.dirty() || model.review().has_value()));
    }
    const auto& status = model.status.empty() ? project.message() : model.status;
    if (!status.empty())
    {
        ImGui::TextWrapped("%s", status.c_str());
        access.text(Control::templateStatus, Control::board, status);
    }
    if (!model.hasContext())
    {
        return false;
    }

    bool textActive = false;
    const auto& context = model.context();
    const auto height = std::max(ImGui::GetContentRegionAvail().y, ImGui::GetTextLineHeightWithSpacing() * 12.0f);
    if (ImGui::BeginChild("###template-body", {0.0f, height}, ImGuiChildFlags_Borders))
    {
        const auto named = [](const Json& row) { return row.at("name").get<std::string>(); };
        if (review_)
        {
            if (const auto& review = model.review())
            {
                if (review->scene)
                {
                    ImGui::TextUnformatted("후보 형상 (새 도체 강조, mm)");
                    drawCandidateCanvas(*review->scene, review->generated, ImGui::GetTextLineHeight() * 10.0f);
                }
                const auto text = review->notes + "\n기준 개정 " + context.at("expected_revision").get<std::string>() +
                    (review->hash.empty() ? "" : "\n후보 SHA-256 " + review->hash);
                ImGui::TextWrapped("%s", text.c_str());
                access.text(Control::templateSummary, Control::board, text);
            }
            else
            {
                ImGui::TextUnformatted("카드 입력을 확인한 뒤 형상 미리보기를 실행하세요.");
            }
        }
        else
        {
            ImGui::BeginDisabled(!project.writable());
            if (const auto value = choose("문헌 카드", context.at("cards"), model.cardIndex(), named); value != model.cardIndex())
            {
                model.selectCard(value);
                ++fieldGeneration_;
            }
            if (const auto value = choose("후보 방식", model.modes(), model.modeIndex(), [](const Json& row)
                {
                    return row == "initial_estimate" ? std::string("근거가 있는 초기 길이 추정") : "원문과 명시 치수";
                }); value != model.modeIndex())
            {
                model.selectMode(value);
                ++fieldGeneration_;
            }
            if (const auto value = choose("적용할 도체층", context.at("bindings"), model.layerIndex(), [](const Json& row)
                {
                    return row.at("label").get<std::string>();
                }, "선택"); value != model.layerIndex())
            {
                model.selectLayer(value);
            }
            if (const auto value = choose("연결할 설계 목표", context.at("targets"), model.targetIndex(), named,
                "연결하지 않음"); value != model.targetIndex())
            {
                model.selectTarget(value);
            }
            const auto& card = model.card();
            auto& draft = model.draft();
            const bool estimate = model.modes().at(model.modeIndex()) == "initial_estimate";
            const auto goalField = card.at("template_id") == "builtin.explicit_arc" ? "radius" :
                card.at("template_id") == "builtin.explicit_planar_ifa" ? "radiator_length" : "";
            bool changed = false;
            const auto input = [&](const char* label, std::string& value)
            {
                changed |= ImGui::InputText(label, &value);
                textActive |= ImGui::IsItemActive();
            };
            ImGui::PushID(fieldGeneration_);
            if (*goalField && model.targetIndex() > 0)
            {
                changed |= ImGui::Checkbox("목표 주파수로 형상 치수 계산", &draft.goalDimension);
            }
            if (estimate)
            {
                const bool seedChanged = drawSeed(card.at("seed_recipes"), draft, input);
                changed |= seedChanged;
            }
            for (auto& field : draft.fields)
            {
                ImGui::PushID(field.key.c_str());
                const auto label = field.label + " (" + field.unit + ")" + (field.fromCard ? " / 원문" : "");
                if ((estimate && field.key == "length") ||
                    (model.targetIndex() > 0 && draft.goalDimension && field.key == goalField))
                {
                    ImGui::TextWrapped("%s / 후보에서 계산", label.c_str());
                }
                else
                {
                    input(label.c_str(), field.value);
                }
                ImGui::PopID();
            }
            ImGui::PopID();
            ImGui::EndDisabled();
            if (changed)
            {
                model.clearReview();
                model.status.clear();
            }
            if (!model.ready())
            {
                ImGui::TextUnformatted(context.at("board").is_null() ? "기판을 설정한 뒤 적용할 도체층을 선택하세요." :
                    context.at("bindings").empty() ? "현재 기판에 적용 가능한 도체층이 없습니다." : "적용할 도체층을 선택하세요.");
            }
            const auto& description = card.at("description").get_ref<const std::string&>();
            ImGui::TextWrapped("%s", description.c_str());
            access.text(Control::templateCard, Control::board, description);
            if (ImGui::CollapsingHeader("원문 출처, 가정과 생략"))
            {
                sources(card);
            }
        }
    }
    ImGui::EndChild();
    return textActive;
}
