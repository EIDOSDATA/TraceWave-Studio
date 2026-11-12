/** @file @brief 목표 편집 요청과 개정/선택 문맥을 관리한다. */
#include "target_editor_dialog.h"
#include "editor_panel.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/listbox.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <stdexcept>

TargetEditorDialog::TargetEditorDialog(wxWindow* parent, const Json& context, DialogGateway gateway)
    : ProjectSetupDialog(parent, "RF 목표 / 대역과 성능 기준", context, std::move(gateway))
{
    SetName("target.dialog");
    BuildInterface();
    RenderContext(context);
}

void TargetEditorDialog::RenderContext(const Json& context)
{
    if (context.at("profile") != "rfad.target-editor/0.1" || context.at("project_id") != m_projectId ||
        context.at("revision_id") != m_revision)
    {
        throw std::runtime_error("목표 조회의 프로젝트 또는 개정이 일치하지 않습니다.");
    }
    m_loading = true;
    m_reloadingContext = false;
    m_context = context;
    m_targetId = context.at("selection").at("id");
    m_targets->Clear();
    int selected = wxNOT_FOUND;
    int row = 0;
    for (const auto& item : context.at("items"))
    {
        m_targets->Append(Display(item.at("label").get<std::string>() + " / " + item.value("summary", "")));
        if (item.at("id") == m_targetId)
        {
            selected = row;
        }
        ++row;
    }
    m_targets->SetSelection(selected);
    m_fields->SetFields(context.at("selection").at("fields"),
                        Json{{"kind", "target"}, {"id", m_targetId.is_null() ? "" : m_targetId.get<std::string>()}});
    m_reason->ChangeValue(wxEmptyString);
    const std::string summary = context.at("input_status").value("summary", "미평가");
    m_summary->SetLabel(Display((m_targetId.is_null() ? "새 목표 / " : "선택한 목표 / ") + summary));
    m_summary->Wrap(std::max(200, GetClientSize().x - FromDIP(280)));
    SetStatus("목표 저장은 해석 실행이나 성능 합격을 뜻하지 않습니다. 미정 입력과 원래 출처를 보존합니다.");
    m_loading = false;
    UpdateActions();
}

void TargetEditorDialog::Load(const Json& targetId)
{
    Request("target.editor.get", Json{{"expected_revision", m_revision}, {"target_id", targetId}}, false,
            [this, targetId](const Json& result)
            {
                if (result.at("selection").at("id") != targetId)
                {
                    throw std::runtime_error("목표 선택 응답이 요청과 일치하지 않습니다.");
                }
                RenderContext(result);
            });
}

bool TargetEditorDialog::HasDraft() const
{
    return !m_reloadingContext && (m_fields->IsDirty() || !m_reason->GetValue().empty());
}

void TargetEditorDialog::RestoreSelection()
{
    m_targets->SetSelection(wxNOT_FOUND);
    int index = 0;
    for (const auto& item : m_context.at("items"))
    {
        if (item.at("id") == m_targetId)
        {
            m_targets->SetSelection(index);
            break;
        }
        ++index;
    }
}

void TargetEditorDialog::Apply(bool remove)
{
    if (!Editable() || m_reloadingContext || m_pending || (remove && m_targetId.is_null()))
    {
        return;
    }
    try
    {
        const Json input{{"expected_revision", m_revision},
                         {"command_id", Uuid()},
                         {"operation", remove ? "remove" : "set"},
                         {"target_id", m_targetId},
                         {"values", remove ? Json::object() : m_fields->Changes()},
                         {"reason", Utf8(m_reason->GetValue())}};
        SetStatus(remove ? "목표 삭제를 적용하고 있습니다." : "목표 입력을 확인하고 적용하고 있습니다.");
        Request("target.editor.apply", input, true,
                [this, remove](const Json& result)
                {
                    AcceptMutation(result);
                    m_targetId = remove ? Json(nullptr) : result.at("target_id");
                    m_reloadingContext = true;
                    Load(m_targetId);
                });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}

void TargetEditorDialog::UpdateActions()
{
    const bool editable = Editable() && !m_reloadingContext;
    m_targets->Enable(editable && !m_pending);
    m_add->Enable(editable && !m_pending);
    m_fields->Enable(editable && !m_pending);
    m_reason->Enable(editable && !m_pending);
    wxString reason = m_reason->GetValue();
    const bool explained = !reason.Trim(true).Trim(false).empty();
    m_apply->Enable(editable && !m_pending && explained && (m_targetId.is_null() || m_fields->IsDirty()));
    m_remove->Enable(editable && !m_pending && explained && !m_targetId.is_null());
    m_cancel->Enable(!m_mutating);
}

void TargetEditorDialog::ShowRequestFailure(const Json& error)
{
    RestoreSelection();
    if (m_reloadingContext)
    {
        m_needsReload = true;
        SetStatus("변경은 적용했지만 최신 입력을 다시 읽지 못했습니다. 닫은 뒤 프로젝트를 다시 확인하세요.\n" +
                  DiagnosticMessage(error));
        return;
    }
    std::string field;
    for (const auto& diagnostic : error.value("data", Json::object()).value("diagnostics", Json::array()))
    {
        field = diagnostic.value("details", Json::object()).value("field_path", std::string());
        if (!field.empty())
        {
            break;
        }
    }
    SetStatus(m_fields->ShowDiagnostic(field, DiagnosticMessage(error)));
}
