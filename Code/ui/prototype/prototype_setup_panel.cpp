/** @file @brief 기판 설정 검토와 물리 구성 및 규칙 편집 화면을 제공한다. */
#include "prototype_setup_panel.h"
#include "prototype_project.h"

#include <algorithm>
#include <charconv>
#include <span>
#include <utility>
#include <misc/cpp/imgui_stdlib.h>

namespace
{
using accessibility::Control;
using Json = nlohmann::json;
using Page = PrototypeSetup::Page;
using Request = PrototypeSetup::Request;

constexpr std::array inclusion{"all", "em", "export"};
constexpr std::array physicalKeys{"stack", "surface", "activation", "scenario", "part"};
constexpr std::array physicalLabels{"기본 적층", "표면층과 개구", "활성 시나리오", "설치 조건", "외부 물체"};
constexpr std::array ruleKeys{"target", "parameter", "connection", "manufacturing_profile"};
constexpr std::array ruleLabels{"기판 제약", "매개변수 제약", "기대 연결과 분리", "제조 규칙"};

std::string display(const Json& value)
{
    if (value.is_number_float())
    {
        char buffer[48];
        const auto result = std::to_chars(buffer, buffer + sizeof(buffer), value.get<double>(), std::chars_format::general, 10);
        if (result.ec == std::errc{})
        {
            return {buffer, result.ptr};
        }
    }
    return value.is_string() ? value.get<std::string>() : value.is_null() ? "미정" : value.dump();
}

std::string selectId(const char* caption, const Json& options, const std::string& id,
    const char* key, const char* label, const char* empty = nullptr)
{
    std::string shown = options.empty() ? "선택 없음" : "선택";
    if (const auto row = std::ranges::find_if(options, [&](const Json& item) { return item.at(key) == id; });
        row != options.end())
    {
        shown = display(row->contains(label) ? row->at(label) : row->at(key));
    }
    else if (empty)
    {
        shown = empty;
    }
    auto result = id;
    if (ImGui::BeginCombo(caption, shown.c_str()))
    {
        if (empty && ImGui::Selectable(empty, id.empty()))
        {
            result.clear();
        }
        for (const auto& option : options)
        {
            const auto& value = option.at(key).get_ref<const std::string&>();
            ImGui::PushID(value.c_str());
            const auto caption = display(option.contains(label) ? option.at(label) : option.at(key));
            if (ImGui::Selectable(caption.c_str(), value == id))
            {
                result = value;
            }
            ImGui::PopID();
        }
        ImGui::EndCombo();
    }
    return result;
}

/** @brief 원래 선택 서비스의 후보 내역과 차단 사유를 확인한다. */
std::string boardReview(const Json& review)
{
    const auto& changes = review.at("changes");
    std::string result = "층 " + std::to_string(changes.at("stackup").at("changed").size()) + "건, 포트 " +
        std::to_string(changes.at("ports").at("changed").size()) + "건 변경";
    result += "\n기판 외곽 " + std::string(changes.at("board_preserved") == true ? "동일" : "변경") +
        " / 형상 " + (changes.at("geometry_preserved") == true ? "동일" : "변경");
    result += "\n층 두께 합계 (mm) " + display(review.at("modeled_total_thickness_mm")) +
        "\n미리보기 SHA-256 " + review.at("preview_hash").get<std::string>();
    for (const auto& issue : review.at("issues"))
    {
        result += "\n" + issue.at("code").get<std::string>() + " " + issue.at("message").get<std::string>();
    }
    return result;
}
}

void PrototypeSetupPanel::select(PrototypeProject& project, Page page, std::string section,
    std::string record, std::string target, std::string parameter)
{
    auto& model = project.setup();
    if (!project.writable() || model.dirty())
    {
        return;
    }
    model.page = page;
    model.section = std::move(section);
    model.record = std::move(record);
    model.target = std::move(target);
    model.parameter = std::move(parameter);
    model.context = nullptr;
    model.board.reset();
    model.report = nullptr;
    model.fields.clear();
    issue_ = 0;
    remove_ = false;
    ++fieldGeneration_;
    project.readSetup();
}

const Json* PrototypeSetupPanel::finding(const PrototypeSetup& model) const
{
    if (!model.report.is_object())
    {
        return nullptr;
    }
    const auto& rows = model.report.at(showAll_ ? "checks" : "issues");
    return issue_ < rows.size() ? &rows.at(issue_) : nullptr;
}

bool PrototypeSetupPanel::action(PrototypeProject& project, Control control)
{
    auto& model = project.setup();
    switch (control)
    {
        case Control::setupBoard: select(project, Page::board, ""); break;
        case Control::setupPhysical: select(project, Page::physical, "stack"); break;
        case Control::setupRules: select(project, Page::rules, "target"); break;
        case Control::setupRead: project.readSetup(); break;
        case Control::setupReview: project.reviewBoardSetup(); break;
        case Control::setupApply:
            project.applySetup(remove_);
            if (project.busy())
            {
                remove_ = false;
            }
            break;
        case Control::setupRemove:
            if (project.writable() && model.canRemove())
            {
                remove_ = !remove_;
            }
            break;
        case Control::setupDiscard:
            if (!project.busy())
            {
                model.discard();
                remove_ = false;
                ++fieldGeneration_;
            }
            break;
        case Control::catalogConnect:
            if (!model.catalogPath.empty())
            {
                project.readCatalog(Request::catalogConnect);
            }
            break;
        case Control::catalogSearch:
            if (!model.catalogId.empty() && project.writable())
            {
                model.catalogOffset = 0;
                project.readCatalog(Request::catalogSearch);
            }
            break;
        case Control::catalogNext:
            if (project.writable() && model.catalogRows.is_object() && model.catalogRows.at("has_more") == true)
            {
                model.catalogOffset = model.catalogRows.at("next_offset").get<std::size_t>();
                project.readCatalog(Request::catalogSearch);
            }
            break;
        case Control::catalogDetail:
            if (model.catalogRows.is_object() && model.catalogItem < model.catalogRows.at("items").size())
            {
                project.readCatalog(Request::catalogDetail);
            }
            break;
        case Control::setupCheck:
            issue_ = 0;
            project.checkRules(inclusion.at(static_cast<std::size_t>(scope_)));
            break;
        case Control::setupPrevious:
            if (issue_ > 0)
            {
                --issue_;
            }
            break;
        case Control::setupNext:
            if (model.report.is_object() && issue_ + 1 < model.report.at(showAll_ ? "checks" : "issues").size())
            {
                ++issue_;
            }
            break;
        case Control::setupJump:
            if (const auto* row = finding(model); row && project.view())
            {
                auto* view = project.view();
                for (const auto& id : row->at("object_ids"))
                {
                    const auto& value = id.get_ref<const std::string&>();
                    if (view->canvas.Find(value))
                    {
                        view->selection = value;
                        return true;
                    }
                }
            }
            break;
        default: break;
    }
    return false;
}

bool PrototypeSetupPanel::takeJump()
{
    return std::exchange(jump_, false);
}

/** @brief 로컬 제조업체 인덱스의 개정, 검색과 원문 참조를 읽는다. */
bool PrototypeSetupPanel::drawCatalog(PrototypeProject& project, accessibility::Bridge& access, Control& focus)
{
    if (!ImGui::CollapsingHeader("제조업체 자료 검색"))
    {
        return false;
    }
    auto& model = project.setup();
    bool textActive = false;
    const auto input = [&](const char* label, std::string& value)
    {
        const bool changed = ImGui::InputText(label, &value);
        textActive |= ImGui::IsItemActive();
        return changed;
    };
    const auto button = [&](Control control, const char* label, bool enabled)
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
        access.item(control, Control::board, enabled);
        ImGui::EndDisabled();
    };
    input("SQLite 카탈로그 전체 경로", model.catalogPath);
    button(Control::catalogConnect, "카탈로그 연결", !model.catalogPath.empty());
    if (model.catalogId.empty())
    {
        return textActive;
    }
    auto text = "카탈로그 개정 " + model.catalogId;
    ImGui::TextWrapped("%s", text.c_str());
    bool changed = input("자료 검색어", model.catalogQuery);
    changed |= input("제조업체 이름", model.catalogPublisher);
    int entity = model.catalogEntity == "native_templates" ? 0 : 1;
    if (ImGui::Combo("자료 종류", &entity, "공개 적층\0물성 관측\0"))
    {
        model.catalogEntity = entity == 0 ? "native_templates" : "observations";
        changed = true;
    }
    if (changed)
    {
        model.catalogRows = model.catalogDetail = nullptr;
    }
    button(Control::catalogSearch, "자료 검색", true);
    if (model.catalogRows.is_object())
    {
        const auto& rows = model.catalogRows.at("items");
        text = "검색 " + display(model.catalogRows.at("total_count")) + "건 / 표시 " +
            std::to_string(rows.size()) + "건 / 시작 " + display(model.catalogRows.at("offset"));
        ImGui::SameLine();
        button(Control::catalogNext, "다음 페이지", model.catalogRows.at("has_more") == true);
        ImGui::TextWrapped("%s", text.c_str());
        access.text(Control::catalogSummary, Control::board, text);
        if (!rows.empty())
        {
            auto id = rows.at(model.catalogItem).at("id").get<std::string>();
            const auto key = model.catalogEntity == "native_templates" ? "template_key" : "product";
            const auto selected = selectId("검색 결과", rows, id, "id", key);
            if (selected != id)
            {
                const auto it = std::ranges::find_if(rows, [&](const Json& row) { return row.at("id") == selected; });
                model.catalogItem = static_cast<std::size_t>(it - rows.begin());
                model.catalogDetail = nullptr;
            }
            button(Control::catalogDetail, "자료 상세 읽기", true);
        }
    }
    if (model.catalogDetail.is_object())
    {
        const auto& item = model.catalogDetail.at("item");
        for (const auto& [key, label] : std::array<std::pair<const char*, const char*>, 7>{{
            {"id", "자료 ID"}, {"publisher", "공개 주체"}, {"template_key", "공개 적층"}, {"product", "제품"},
            {"source_id", "원문 ID"}, {"source_url", "원문 주소"}, {"raw_sha256", "원문 SHA-256"}}})
        {
            if (item.contains(key) && !item.at(key).is_null())
            {
                ImGui::TextWrapped("%s %s", label, display(item.at(key)).c_str());
            }
        }
    }
    return textActive;
}

bool PrototypeSetupPanel::drawContext(PrototypeProject& project, accessibility::Bridge& access, Control& focus)
{
    auto& model = project.setup();
    const auto& context = model.context;
    bool textActive = false;
    bool edited = false;
    const auto input = [&](const char* label, std::string& value, bool multiline = false)
    {
        edited |= multiline ? ImGui::InputTextMultiline(label, &value, {ImGui::CalcItemWidth(), ImGui::GetTextLineHeight() * 4}) :
            ImGui::InputText(label, &value);
        textActive |= ImGui::IsItemActive();
    };
    if (model.page == Page::board)
    {
        textActive = drawCatalog(project, access, focus);
        ImGui::Text("기판 외형 %s", context.at("board").is_null() ? "미정" : display(context.at("board").at("kind")).c_str());
        if (const auto& selected = context.at("selection"); selected.is_object())
        {
            ImGui::TextWrapped("이전에 적용한 기판 자료 %s", display(selected.at("id")).c_str());
        }
        ImGui::SeparatorText("층과 재료 대응");
        ImGui::BeginDisabled(!project.writable());
        for (std::size_t index = 0; index < model.materials.size(); ++index)
        {
            const auto& layer = context.at("layers").at(index);
            ImGui::PushID(static_cast<int>(index));
            const auto text = display(layer.at("name")) + " / " + display(layer.at("role")) + " / 두께 " +
                display(layer.at("thickness_mm")) + " mm / Z " + display(layer.at("z_min_mm")) + " mm";
            ImGui::TextWrapped("%s", text.c_str());
            auto value = selectId("재료", context.at("materials"), model.materials[index], "id", "name", "미정");
            edited |= value != model.materials[index];
            model.materials[index] = std::move(value);
            ImGui::PopID();
        }
        ImGui::SeparatorText("기존 급전 좌표 (mm)");
        if (model.ports.empty())
        {
            ImGui::TextUnformatted("등록된 포트가 없습니다.");
        }
        for (auto& port : model.ports)
        {
            ImGui::PushID(port.id.c_str());
            ImGui::TextWrapped("%s%s", port.name.c_str(), port.bound ? " / 매개변수 참조" : "");
            constexpr std::array labels{"시작 X", "시작 Y", "시작 Z", "끝 X", "끝 Y", "끝 Z"};
            for (std::size_t index = 0; index < port.value.size(); ++index)
            {
                input(labels[index], port.value[index]);
            }
            input("급전 좌표 변경 사유", port.reason);
            ImGui::PopID();
        }
        ImGui::EndDisabled();
    }
    else
    {
        const bool physical = model.page == Page::physical;
        ImGui::BeginDisabled(!project.writable() || model.dirty());
        auto record = model.record;
        if (!model.recordChoices().empty())
        {
            record = selectId("기존 항목", model.recordChoices(), model.record, "id",
                physical ? "name" : "label", "새 항목");
        }
        auto target = model.target;
        auto parameter = model.parameter;
        if (!physical && (model.section == "target" || model.section == "parameter"))
        {
            target = selectId("목표", context.at("targets"), model.target, "id", "name", "선택");
            if (model.section == "parameter")
            {
                parameter = selectId("매개변수", context.at("parameters"), model.parameter, "id", "name", "선택");
            }
        }
        ImGui::EndDisabled();
        if (record != model.record || target != model.target || parameter != model.parameter)
        {
            select(project, model.page, model.section, std::move(record), std::move(target), std::move(parameter));
            return false;
        }
        if (physical)
        {
            const auto& stack = context.at("stack_review");
            const auto mm = [](const Json& value)
            {
                return value.is_number() ? std::to_string(value.get<double>() * 1000.0) + " mm" : "미정";
            };
            const auto text = "층 두께 합계 " + mm(stack.at("base_sum_si")) + " / 기본 범위 " +
                mm(stack.at("base_extent_si")) + " / 표면층 포함 " + mm(stack.at("full_extent_si")) +
                " / 명목값 차이 " + mm(stack.at("nominal_difference_si")) + " / 해석 제외 " +
                std::to_string(context.at("em_status").size()) + "건";
            ImGui::TextWrapped("%s", text.c_str());
            access.text(Control::setupSummary, Control::board, text);
            if (const auto& step = context.at("step"); step.is_object())
            {
                ImGui::TextWrapped("원본 STEP %s / SHA-256 %s", display(step.at("name")).c_str(),
                    display(step.at("sha256")).c_str());
            }
        }
        ImGui::BeginDisabled(!project.writable());
        input("설정 변경 사유", model.reason);
        ImGui::EndDisabled();
        if (remove_)
        {
            ImGui::TextUnformatted("선택한 항목을 삭제하려면 변경 사유를 입력하고 삭제 적용을 누르세요.");
        }
        for (auto& field : model.fields)
        {
            if (field.readonly)
            {
                continue;
            }
            ImGui::PushID(field.key.c_str());
            ImGui::BeginDisabled(!project.writable() || remove_ || !model.fieldEnabled(field));
            if (field.kind == "bool")
            {
                auto value = field.value.get<bool>();
                if (ImGui::Checkbox(field.caption.c_str(), &value))
                {
                    field.value = value;
                    edited = true;
                }
            }
            else if (field.kind == "choice")
            {
                const auto& previous = field.value.get_ref<const std::string&>();
                auto value = selectId(field.caption.c_str(), field.choices, previous, "value", "label");
                edited |= value != previous;
                field.value = std::move(value);
            }
            else
            {
                input(field.caption.c_str(), field.value.get_ref<std::string&>(), field.kind == "lines");
            }
            ImGui::EndDisabled();
            ImGui::PopID();
        }
        if (ImGui::CollapsingHeader("보존한 출처와 입력 상태"))
        {
            if (physical)
            {
                for (const auto& line : context.at("source_refs"))
                {
                    ImGui::TextWrapped("%s", display(line).c_str());
                }
            }
            for (const auto& field : model.fields)
            {
                if (!field.readonly || field.original.empty() || field.original == "")
                {
                    continue;
                }
                ImGui::TextWrapped("%s", field.caption.c_str());
                if (field.original.is_array())
                {
                    for (const auto& line : field.original)
                    {
                        ImGui::TextWrapped("%s", display(line).c_str());
                    }
                }
                else
                {
                    ImGui::TextWrapped("%s", display(field.original).c_str());
                }
            }
        }
    }
    if (edited)
    {
        model.edited();
    }
    return textActive;
}

bool PrototypeSetupPanel::draw(PrototypeProject& project, accessibility::Bridge& access, Control& focus)
{
    auto& model = project.setup();
    const bool ready = project.writable();
    const auto button = [&](Control control, const char* name, bool enabled, bool checked = false)
    {
        ImGui::BeginDisabled(!enabled);
        if (focus == control)
        {
            ImGui::SetKeyboardFocusHere();
            focus = Control::root;
        }
        if (ImGui::SmallButton(name))
        {
            action(project, control);
        }
        access.item(control, Control::board, enabled, checked);
        ImGui::EndDisabled();
    };
    button(Control::setupBoard, "기판 설정", ready && !model.dirty(), model.page == Page::board);
    ImGui::SameLine();
    button(Control::setupPhysical, "적층과 설치", ready && !model.dirty(), model.page == Page::physical);
    ImGui::SameLine();
    button(Control::setupRules, "설계 규칙", ready && !model.dirty(), model.page == Page::rules);
    ImGui::SameLine();
    button(Control::setupRead, "다시 읽기", ready && !model.dirty());
    if (model.page != Page::board)
    {
        ImGui::BeginDisabled(!ready || model.dirty());
        const auto options = model.page == Page::physical ? std::span(physicalLabels.data(), physicalLabels.size()) :
            std::span(ruleLabels.data(), ruleLabels.size());
        const auto keys = model.page == Page::physical ? std::span(physicalKeys.data(), physicalKeys.size()) :
            std::span(ruleKeys.data(), ruleKeys.size());
        auto index = static_cast<int>(std::ranges::find(keys, model.section) - keys.begin());
        if (ImGui::Combo("항목", &index, options.data(), static_cast<int>(options.size())))
        {
            select(project, model.page, keys[static_cast<std::size_t>(index)]);
        }
        ImGui::EndDisabled();
    }
    if (model.page == Page::board)
    {
        button(Control::setupReview, "변경 미리보기", ready && model.context.is_object() && model.dirty());
        ImGui::SameLine();
    }
    if (model.page == Page::rules)
    {
        if (ImGui::Combo("검사 범위", &scope_, "전체\0해석 포함\0출력 포함\0"))
        {
            model.report = nullptr;
            issue_ = 0;
        }
        button(Control::setupCheck, "설계 규칙 검사", ready && model.context.is_object() && !model.dirty());
        ImGui::SameLine();
    }
    const bool applicable = model.page == Page::board ? model.board && model.board->CanApply() :
        remove_ ? model.canRemove() && !model.reason.empty() : model.canSet();
    button(Control::setupApply, remove_ ? "삭제 적용" : "설정 적용", ready && applicable);
    if (model.page != Page::board)
    {
        ImGui::SameLine();
        button(Control::setupRemove, "삭제 확인", ready && model.canRemove(), remove_);
    }
    ImGui::SameLine();
    button(Control::setupDiscard, "초안 취소", !project.busy() && (model.dirty() || remove_));
    const auto& status = model.status.empty() ? project.message() : model.status;
    if (!status.empty())
    {
        ImGui::TextWrapped("%s", status.c_str());
        access.text(Control::setupStatus, Control::board, status);
    }
    if (!model.context.is_object() || project.busy())
    {
        return false;
    }
    if (model.board && model.board->Preview().is_object())
    {
        const auto text = boardReview(model.board->Preview());
        ImGui::TextWrapped("%s", text.c_str());
        access.text(Control::setupSummary, Control::board, text);
    }
    if (model.report.is_object())
    {
        const auto& counts = model.report.at("counts");
        auto text = "충족 " + display(counts.at("passed")) + " / 위반 " + display(counts.at("failed")) +
            " / 미평가 " + display(counts.at("not_evaluated")) + " / 적용 안 함 " + display(counts.at("not_applicable"));
        if (model.report.at("issues_truncated") == true)
        {
            text += " / 일부 표시";
        }
        ImGui::TextWrapped("%s", text.c_str());
        access.text(Control::setupSummary, Control::board, text);
        if (ImGui::Checkbox("충족 및 적용 안 함 포함", &showAll_))
        {
            issue_ = 0;
        }
        const auto& rows = model.report.at(showAll_ ? "checks" : "issues");
        button(Control::setupPrevious, "이전 검사", issue_ > 0);
        ImGui::SameLine();
        button(Control::setupNext, "다음 검사", issue_ + 1 < rows.size());
        if (const auto* row = finding(model))
        {
            const auto detail = display(row->at("rule")) + " / " + display(row->at("status")) + " / " +
                display(row->at("message")) + " / 측정 " + display(row->at("measured")) +
                " / 한계 " + display(row->at("limit")) + " " + display(row->at("unit"));
            ImGui::TextWrapped("%s", detail.c_str());
            access.text(Control::setupFinding, Control::board, detail);
            const bool found = project.view() && std::ranges::any_of(row->at("object_ids"), [&](const Json& id)
            {
                return project.view()->canvas.Find(id.get_ref<const std::string&>()) != nullptr;
            });
            ImGui::BeginDisabled(!found);
            if (focus == Control::setupJump)
            {
                ImGui::SetKeyboardFocusHere();
                focus = Control::root;
            }
            if (ImGui::SmallButton("기판 검사 위치"))
            {
                jump_ = action(project, Control::setupJump);
            }
            access.item(Control::setupJump, Control::board, found);
            ImGui::EndDisabled();
        }
    }
    const auto height = std::max(ImGui::GetContentRegionAvail().y, ImGui::GetTextLineHeightWithSpacing() * 12.0f);
    bool active = false;
    ImGui::PushID(fieldGeneration_);
    if (ImGui::BeginChild("###setup-fields", {0.0f, height}, ImGuiChildFlags_Borders))
    {
        active = drawContext(project, access, focus);
    }
    ImGui::EndChild();
    ImGui::PopID();
    return active;
}
