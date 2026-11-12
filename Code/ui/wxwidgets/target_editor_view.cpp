/** @file @brief 다중 목표 목록과 기본/고급 입력을 읽기 쉬운 두 영역으로 배치한다. */
#include "target_editor_dialog.h"
#include "editor_panel.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/listbox.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>

void TargetEditorDialog::BuildInterface()
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("설계 목표"));
    StudioTheme::Heading(*title);
    layout->Add(title, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
    auto* help = new wxStaticText(
        this, wxID_ANY,
        Display("떨어진 대역은 목표를 각각 추가합니다. 기준 주파수 / 임피던스 / 급전은 미정으로 둘 수 있습니다."));
    StudioTheme::BindSecondary(*help);
    layout->Add(help, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    auto* content = new wxBoxSizer(wxHORIZONTAL);
    auto* left = new wxBoxSizer(wxVERTICAL);
    m_targets = new wxListBox(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(250, -1)), 0, nullptr, wxLB_HSCROLL);
    m_targets->SetName("target.list");
    left->Add(m_targets, 1, wxEXPAND | wxBOTTOM, FromDIP(StudioTheme::InputGap));
    m_add = new wxButton(this, wxID_ANY, Display("목표 추가"));
    m_add->SetName("target.add");
    left->Add(m_add, 0, wxEXPAND);
    content->Add(left, 0, wxEXPAND | wxRIGHT, FromDIP(StudioTheme::PanelPadding));
    auto* right = new wxBoxSizer(wxVERTICAL);
    m_summary = new wxStaticText(this, wxID_ANY, wxEmptyString);
    StudioTheme::Heading(*m_summary);
    right->Add(m_summary, 0, wxEXPAND | wxBOTTOM, FromDIP(StudioTheme::InputGap));
    m_fields = new EditorPanel(this);
    m_fields->SetName("target.fields");
    right->Add(m_fields, 1, wxEXPAND);
    content->Add(right, 1, wxEXPAND);
    layout->Add(content, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(StudioTheme::PanelPadding));
    auto* reasonRow = new wxBoxSizer(wxHORIZONTAL);
    reasonRow->Add(new wxStaticText(this, wxID_ANY, Display("추가 / 수정 / 삭제 사유")), 0,
                   wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(StudioTheme::InputGap));
    m_reason = new wxTextCtrl(this, wxID_ANY);
    m_reason->SetName("target.reason");
    reasonRow->Add(m_reason, 1, wxEXPAND);
    layout->Add(reasonRow, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::PanelPadding));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_remove = new wxButton(this, wxID_ANY, Display("선택 목표 삭제"));
    m_remove->SetName("target.remove");
    actions->Add(m_remove, 0);
    actions->AddStretchSpacer();
    m_apply = new wxButton(this, wxID_ANY, Display("목표 적용"));
    m_apply->SetName("target.apply");
    actions->Add(m_apply, 0, wxRIGHT, FromDIP(StudioTheme::InputGap));
    m_cancel = new wxButton(this, wxID_CANCEL, Display("닫기"));
    actions->Add(m_cancel, 0);
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    SetSizer(layout);
    m_add->Bind(wxEVT_BUTTON,
                [this](wxCommandEvent&)
                {
                    if (ConfirmDiscard())
                    {
                        Load(nullptr);
                    }
                });
    m_targets->Bind(wxEVT_LISTBOX,
                    [this](wxCommandEvent& event)
                    {
                        if (!m_loading && event.GetSelection() >= 0)
                        {
                            if (ConfirmDiscard())
                            {
                                Load(m_context.at("items").at(static_cast<std::size_t>(event.GetSelection())).at("id"));
                            }
                            else
                            {
                                RestoreSelection();
                            }
                        }
                    });
    m_fields->Bind(wxEVT_RFAD_EDITOR_CHANGED,
                   [this](wxCommandEvent&)
                   {
                       if (!m_loading)
                       {
                           UpdateActions();
                       }
                   });
    m_reason->Bind(wxEVT_TEXT,
                   [this](wxCommandEvent&)
                   {
                       UpdateActions();
                   });
    m_apply->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Apply(false);
                  });
    m_remove->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Apply(true);
                   });
}
