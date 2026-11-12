/** @file @brief 카드 입력과 읽기 전용 형상 검토를 나란히 배치한다. */
#include "template_dialog.h"
#include "design_canvas.h"
#include "editor_panel.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>

void TemplateDialog::BuildInterface()
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("직접 입력 / 문헌 형상 카드"));
    StudioTheme::Heading(*title);
    layout->Add(title, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
    auto* help = new wxStaticText(
        this, wxID_ANY, Display("문헌 치수와 수정값, 생략 항목을 확인합니다. 형상 생성은 RF/제조/실측 검증과 구분합니다."));
    StudioTheme::BindSecondary(*help);
    layout->Add(help, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    auto* selectors = new wxFlexGridSizer(2, FromDIP(StudioTheme::InputGap), FromDIP(StudioTheme::InputGap));
    selectors->AddGrowableCol(1);
    selectors->Add(new wxStaticText(this, wxID_ANY, Display("패턴 카드")), 0, wxALIGN_CENTER_VERTICAL);
    m_cards = new wxChoice(this, wxID_ANY);
    m_cards->SetName("template.card");
    selectors->Add(m_cards, 1, wxEXPAND);
    selectors->Add(new wxStaticText(this, wxID_ANY, Display("적용할 도체층")), 0, wxALIGN_CENTER_VERTICAL);
    m_binding = new wxChoice(this, wxID_ANY);
    m_binding->SetName("template.layer");
    selectors->Add(m_binding, 1, wxEXPAND);
    selectors->Add(new wxStaticText(this, wxID_ANY, Display("연결할 설계 목표")), 0, wxALIGN_CENTER_VERTICAL);
    m_target = new wxChoice(this, wxID_ANY);
    m_target->SetName("template.target");
    selectors->Add(m_target, 1, wxEXPAND);
    layout->Add(selectors, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    auto* content = new wxBoxSizer(wxHORIZONTAL);
    m_inputs = new EditorPanel(this);
    m_inputs->SetName("template.inputs");
    m_inputs->SetMinSize(FromDIP(wxSize(360, 180)));
    content->Add(m_inputs, 1, wxEXPAND | wxRIGHT, FromDIP(StudioTheme::PanelPadding));
    auto* review = new wxBoxSizer(wxVERTICAL);
    auto* previewTitle = new wxStaticText(this, wxID_ANY, Display("형상 미리보기 / mm"));
    StudioTheme::Heading(*previewTitle);
    review->Add(previewTitle, 0, wxBOTTOM, FromDIP(StudioTheme::InputGap));
    m_canvas = new DesignCanvas(this);
    m_canvas->SetEditingEnabled(false);
    m_canvas->SetMinSize(FromDIP(wxSize(260, 200)));
    review->Add(m_canvas, 1, wxEXPAND | wxBOTTOM, FromDIP(StudioTheme::InputGap));
    m_canvas->Hide();
    m_notes = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 160)),
                             wxTE_MULTILINE | wxTE_READONLY);
    m_notes->SetName("template.review");
    review->Add(m_notes, 0, wxEXPAND);
    content->Add(review, 1, wxEXPAND);
    layout->Add(content, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(StudioTheme::PanelPadding));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::PanelPadding));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_previewButton = new wxButton(this, wxID_ANY, Display("형상 미리보기"));
    m_previewButton->SetName("template.preview");
    actions->Add(m_previewButton, 0);
    actions->AddStretchSpacer();
    m_applyButton = new wxButton(this, wxID_ANY, Display("검토한 형상 적용"));
    m_applyButton->SetName("template.apply");
    actions->Add(m_applyButton, 0, wxRIGHT, FromDIP(StudioTheme::InputGap));
    m_cancel = new wxButton(this, wxID_CANCEL, Display("닫기"));
    actions->Add(m_cancel, 0);
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    SetSizer(layout);
    m_cards->Bind(wxEVT_CHOICE,
                  [this](wxCommandEvent& event)
                  {
                      SelectCard(event.GetSelection());
                  });
    for (auto* choice : {m_binding, m_target})
    {
        choice->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         Changed();
                     });
    }
    m_inputs->Bind(wxEVT_RFAD_EDITOR_CHANGED,
                   [this](wxCommandEvent&)
                   {
                       Changed();
                   });
    m_previewButton->Bind(wxEVT_BUTTON,
                          [this](wxCommandEvent&)
                          {
                              Preview();
                          });
    m_applyButton->Bind(wxEVT_BUTTON,
                        [this](wxCommandEvent&)
                        {
                            Apply();
                        });
}
