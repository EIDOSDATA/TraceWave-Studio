/** @file @brief 이름을 안정 ID와 분리하여 기존 편집 서비스에 적용한다. */
#include "object_rename_dialog.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/wx.h>

ObjectRenameDialog::ObjectRenameDialog(wxWindow* parent, const Json& context, DialogGateway gateway)
    : ProjectSetupDialog(parent, "이름 바꾸기", context, std::move(gateway)),
      m_selection(context.at("selection")), m_original(context.at("name"))
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display(context.at("label").get<std::string>()));
    StudioTheme::Heading(*title);
    layout->Add(title, 0, wxALL, FromDIP(12));
    layout->Add(new wxStaticText(this, wxID_ANY, Display("이름")), 0, wxLEFT | wxRIGHT, FromDIP(12));
    m_name = new wxTextCtrl(this, wxID_ANY, Display(m_original), wxDefaultPosition, FromDIP(wxSize(430, -1)), wxTE_PROCESS_ENTER);
    m_name->SetName("rename.name");
    layout->Add(m_name, 0, wxEXPAND | wxALL, FromDIP(12));
    const std::string temporary = m_original.empty() ? "현재 이름은 임시 표시입니다. 저장할 이름을 입력하세요.\n" : "";
    auto* hint = new wxStaticText(this, wxID_ANY, Display(temporary + "같은 종류의 목록 안에서는 이름을 중복할 수 없습니다.\n식별자, 치수, 연결과 출처 사본은 유지됩니다."));
    layout->Add(hint, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    actions->AddStretchSpacer();
    auto* cancel = new wxButton(this, wxID_CANCEL, Display("닫기"));
    m_apply = new wxButton(this, wxID_APPLY, Display("적용"));
    m_apply->SetDefault();
    actions->Add(cancel, 0, wxRIGHT, FromDIP(8));
    actions->Add(m_apply);
    layout->Add(actions, 0, wxEXPAND | wxALL, FromDIP(12));
    SetSizerAndFit(layout);
    SetMinSize(GetSize());
    CentreOnParent();
    const auto apply = [this](wxCommandEvent&)
    {
        if (!Editable() || !HasDraft())
        {
            return;
        }
        const std::string name = Utf8(m_name->GetValue());
        Request("editor.apply", {{"expected_revision", m_revision}, {"command_id", Uuid()},
                {"selection", m_selection}, {"values", {{"name", name}}}}, true,
                [this, name](const Json& result)
                {
                    AcceptMutation(result);
                    m_original = name;
                    CloseDialog();
                });
    };
    m_apply->Bind(wxEVT_BUTTON, apply);
    m_name->Bind(wxEVT_TEXT_ENTER, apply);
    m_name->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { UpdateActions(); });
    cancel->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { CloseDialog(); });
    m_name->SetFocus();
    m_name->SelectAll();
    UpdateActions();
}

bool ObjectRenameDialog::HasDraft() const
{
    return m_name && Utf8(m_name->GetValue()) != m_original;
}

void ObjectRenameDialog::UpdateActions()
{
    if (m_apply)
    {
        m_name->Enable(Editable());
        m_apply->Enable(Editable() && HasDraft());
    }
}
