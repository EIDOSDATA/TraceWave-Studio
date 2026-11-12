/** @file @brief 고정 카드/개정/입력과 일치하는 후보만 적용한다. */
#include "template_dialog.h"
#include "design_canvas.h"
#include "editor_panel.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/textctrl.h>
#include <stdexcept>

TemplateDialog::TemplateDialog(wxWindow* parent, const Json& context, DialogGateway gateway)
    : ProjectSetupDialog(parent, "패턴 템플릿 / 명시 치수로 형상 만들기", context, std::move(gateway))
{
    SetName("template.dialog");
    BuildInterface();
    RenderContext(context);
}

void TemplateDialog::RenderContext(const Json& context)
{
    if (context.at("project_id") != m_projectId || context.at("expected_revision") != m_revision)
    {
        throw std::runtime_error("템플릿 조회의 프로젝트 또는 개정이 일치하지 않습니다.");
    }
    m_loading = true;
    m_reloadingContext = false;
    m_context = context;
    m_card = nullptr;
    m_cards->Clear();
    for (const auto& card : context.at("cards"))
    {
        m_cards->Append(Display(card.at("name").get<std::string>()));
    }
    m_binding->Clear();
    for (const auto& binding : context.at("bindings"))
    {
        m_binding->Append(Display(binding.at("label").get<std::string>()));
    }
    m_binding->SetSelection(wxNOT_FOUND);
    m_target->Clear();
    m_target->Append(Display("연결하지 않음"));
    for (const auto& target : context.at("targets"))
    {
        m_target->Append(Display(target.at("name").get<std::string>()));
    }
    m_target->SetSelection(0);
    m_loading = false;
    if (!context.at("cards").empty())
    {
        m_cards->SetSelection(0);
        SelectCard(0);
    }
    else
    {
        UpdateActions();
    }
}

void TemplateDialog::SelectCard(int index)
{
    if (index < 0 || !Editable())
    {
        return;
    }
    StoreDraft();
    m_loading = true;
    m_card = m_context.at("cards").at(static_cast<std::size_t>(index));
    Json fields = Json::array();
    for (const auto& field : m_card.at("input_fields"))
    {
        fields.push_back(Json{
            {"key", field.at("key")},
            {"label", field.at("label").get<std::string>() + " (" + field.at("display_unit").get<std::string>() + ")"},
            {"editor", "text"},
            {"value", ""},
            {"readonly", false}});
    }
    m_inputs->SetFields(fields);
    const auto found = m_drafts.find(m_card.at("template_id").get<std::string>());
    if (found != m_drafts.end())
    {
        for (const auto& field : found.value().items())
        {
            m_inputs->SetFieldValue(field.key(), field.value());
        }
    }
    m_loading = false;
    Changed();
}

std::string TemplateDialog::CardDescription() const
{
    if (m_card.is_null())
    {
        return "지원 카드가 없습니다.";
    }
    std::string text = m_card.at("description");
    text += "\n지원 PCB: ";
    for (const auto& kind : m_card.value("board_kinds", Json::array()))
    {
        text += kind == "circle" ? "원형 " : "직사각형 ";
    }
    for (const auto& limitation : m_card.value("limitations", Json::array()))
    {
        text += "\n- " + limitation.get<std::string>();
    }
    return text + "\n\n형상만 생성합니다. 급전 포트와 실제 물성, 정합/방사 성능은 자동 확정하지 않습니다.";
}

void TemplateDialog::Changed()
{
    if (m_loading || !Editable())
    {
        return;
    }
    InvalidateRead();
    m_reviewedInput = nullptr;
    m_preview = nullptr;
    m_canvas->Hide();
    m_notes->ChangeValue(Display(CardDescription()));
    SetStatus("필요한 치수와 도체층을 직접 지정하고 형상 미리보기를 확인하세요. 미리보기 전에는 적용할 수 없습니다.");
    UpdateActions();
    Layout();
}

Json TemplateDialog::Specification() const
{
    const int bindingIndex = m_binding->GetSelection();
    if (m_card.is_null() || bindingIndex < 0 || m_context.at("board").is_null())
    {
        throw std::runtime_error("현재 프로젝트의 기판과 적용할 도체층을 선택하세요.");
    }
    Json quantities = Json::object();
    for (const auto& field : m_card.at("input_fields"))
    {
        const std::string key = field.at("key");
        const std::string value = m_inputs->FieldValue(key).get<std::string>();
        if (value.empty())
        {
            throw std::runtime_error(field.at("label").get<std::string>() + ": 값을 직접 입력하세요.");
        }
        const std::string unit = field.at("display_unit");
        quantities[key] = Json{{"value", value}, {"unit", unit}};
    }
    const auto& binding = m_context.at("bindings").at(static_cast<std::size_t>(bindingIndex));
    Json targets = Json::array();
    if (m_target->GetSelection() > 0)
    {
        const auto& target = m_context.at("targets").at(static_cast<std::size_t>(m_target->GetSelection() - 1));
        targets.push_back(Json{{"id", target.at("id")}, {"revision_id", target.at("revision_id")}});
    }
    return Json{{"expected_revision", m_revision},
                {"mode", "explicit_geometry"},
                {"template", Json{{"template_id", m_card.at("template_id")},
                                  {"version", m_card.at("version")},
                                  {"content_hash", m_card.at("content_hash")}}},
                {"instance_id", m_context.at("new_instance_id")},
                {"target_refs", targets},
                {"binding", Json{{"board_id", m_context.at("board").at("id")},
                                 {"frame_id", m_context.at("frame_id")},
                                 {"layer_id", binding.at("layer_id")},
                                 {"material_id", binding.at("material_id")}}},
                {"explicit_inputs", quantities},
                {"port", nullptr}};
}

void TemplateDialog::Preview()
{
    if (!Editable())
    {
        return;
    }
    try
    {
        const Json input = Specification();
        Changed();
        SetStatus("입력한 치수의 형상을 확인하고 있습니다.");
        Request("template.synthesize", input, false,
                [this, input](const Json& result)
                {
                    m_preview = result;
                    m_reviewedInput = input;
                    std::string notes = CardDescription();
                    for (const auto& issue : result.value("issues", Json::array()))
                    {
                        notes += "\n- " + (issue.is_string() ? issue.get<std::string>() : DiagnosticMessage(issue));
                    }
                    const Json checks = result.value("input_checks", Json(nullptr));
                    if (checks.is_object())
                    {
                        notes += "\n\n해석 입력 검사: " + checks.value("input_status", std::string("미확인"));
                        for (const auto& diagnostic : checks.value("diagnostics", Json::array()))
                        {
                            notes += "\n- " + DiagnosticMessage(diagnostic);
                        }
                        const auto total = checks.value("diagnostic_count", std::size_t(0));
                        if (total > checks.value("diagnostics", Json::array()).size())
                        {
                            notes += "\n전체 " + std::to_string(total) +
                                     "개 중 일부를 표시합니다. 전체 검사는 프로젝트 입력 점검을 사용하세요.";
                        }
                    }
                    m_notes->ChangeValue(Display(notes));
                    if (result.contains("scene") && !result.at("scene").is_null())
                    {
                        m_canvas->SetScene(result.at("scene"));
                        m_canvas->Show();
                        m_canvas->FitView();
                    }
                    SetStatus(result.value("can_apply", false)
                                  ? "형상 미리보기 완료 / 적용하면 한 명령으로 추가합니다. 제조/RF 성능 검증은 "
                                    "수행하지 않았습니다."
                                  : "적용할 수 없습니다. 카드 조건과 입력 문제를 확인하세요.");
                    Layout();
                });
    }
    catch (const std::exception& error)
    {
        Changed();
        SetStatus(error.what());
    }
}

void TemplateDialog::Apply()
{
    if (!Editable() || m_pending || m_preview.is_null() || !m_preview.value("can_apply", false))
    {
        return;
    }
    Json input = m_reviewedInput;
    input["command_id"] = Uuid();
    input["preview_hash"] = m_preview.at("preview_hash");
    Request("template.apply", input, true,
            [this](const Json& result)
            {
                AcceptMutation(result);
                m_drafts.erase(m_card.at("template_id").get<std::string>());
                m_preview = nullptr;
                m_reviewedInput = nullptr;
                m_reloadingContext = true;
                Request("template.context", Json{{"expected_revision", m_revision}}, false,
                        [this](const Json& context)
                        {
                            RenderContext(context);
                            SetStatus(
                                "형상을 적용했습니다. 닫은 뒤 2D/3D와 속성에서 확인하거나 실행 취소할 수 있습니다.");
                        });
            });
}

void TemplateDialog::UpdateActions()
{
    const bool editable = Editable() && !m_reloadingContext;
    m_cards->Enable(editable);
    m_binding->Enable(editable);
    m_target->Enable(editable);
    m_inputs->Enable(editable);
    m_previewButton->Enable(editable && !m_pending && !m_card.is_null());
    m_applyButton->Enable(editable && !m_pending && !m_preview.is_null() && m_preview.value("can_apply", false));
    m_cancel->Enable(!m_mutating);
}

void TemplateDialog::StoreDraft()
{
    if (!m_card.is_null())
    {
        m_drafts[m_card.at("template_id").get<std::string>()] = m_inputs->Changes();
    }
}

bool TemplateDialog::HasDraft() const
{
    if (!m_reloadingContext && m_inputs->IsDirty())
    {
        return true;
    }
    for (const auto& draft : m_drafts.items())
    {
        if (!draft.value().empty())
        {
            return true;
        }
    }
    return false;
}

void TemplateDialog::ShowRequestFailure(const Json& error)
{
    if (m_reloadingContext)
    {
        m_needsReload = true;
        SetStatus("형상은 적용했지만 새 문맥을 다시 읽지 못했습니다. 닫은 뒤 프로젝트를 다시 확인하세요.\n" +
                  DiagnosticMessage(error));
        return;
    }
    ProjectSetupDialog::ShowRequestFailure(error);
}
