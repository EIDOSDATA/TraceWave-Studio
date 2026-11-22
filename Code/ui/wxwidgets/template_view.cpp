/** @file @brief 카드 입력과 읽기 전용 형상 검토를 나란히 배치한다. */
#include "template_dialog.h"
#include "design_canvas.h"
#include "editor_panel.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/msgdlg.h>
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
    selectors->Add(new wxStaticText(this, wxID_ANY, Display("후보 방식")), 0, wxALIGN_CENTER_VERTICAL);
    m_mode = new wxChoice(this, wxID_ANY);
    m_mode->SetName("template.mode");
    selectors->Add(m_mode, 1, wxEXPAND);
    selectors->Add(new wxStaticText(this, wxID_ANY, Display("적용할 도체층")), 0, wxALIGN_CENTER_VERTICAL);
    m_binding = new wxChoice(this, wxID_ANY);
    m_binding->SetName("template.layer");
    selectors->Add(m_binding, 1, wxEXPAND);
    selectors->Add(new wxStaticText(this, wxID_ANY, Display("연결할 설계 목표")), 0, wxALIGN_CENTER_VERTICAL);
    m_target = new wxChoice(this, wxID_ANY);
    m_target->SetName("template.target");
    auto* targetRow = new wxBoxSizer(wxHORIZONTAL);
    targetRow->Add(m_target, 1, wxEXPAND);
    m_goalLayoutNote = new wxButton(this, wxID_ANY, Display("목표 치수 참고"));
    m_goalLayoutNote->SetName("template.target_layout_note");
    StudioTheme::Button(*m_goalLayoutNote);
    targetRow->Add(m_goalLayoutNote, 0, wxEXPAND | wxLEFT, FromDIP(StudioTheme::InputGap));
    selectors->Add(targetRow, 1, wxEXPAND);
    layout->Add(selectors, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    auto* content = new wxBoxSizer(wxHORIZONTAL);
    auto* inputs = new wxBoxSizer(wxVERTICAL);
    m_inputs = new EditorPanel(this);
    m_inputs->SetName("template.inputs");
    m_inputs->SetMinSize(FromDIP(wxSize(360, 180)));
    inputs->Add(m_inputs, 1, wxEXPAND);
    BuildSeedControls(inputs);
    content->Add(inputs, 1, wxEXPAND | wxRIGHT, FromDIP(StudioTheme::PanelPadding));
    auto* review = new wxBoxSizer(wxVERTICAL);
    auto* previewTitle = new wxStaticText(this, wxID_ANY, Display("후보 형상 / 새로 생성할 도체 강조 (mm)"));
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
    StudioTheme::Button(*m_previewButton);
    actions->Add(m_previewButton, 0);
    actions->AddStretchSpacer();
    m_applyButton = new wxButton(this, wxID_ANY, Display("검토한 형상 적용"));
    m_applyButton->SetName("template.apply");
    StudioTheme::Button(*m_applyButton, true);
    actions->Add(m_applyButton, 0, wxRIGHT, FromDIP(StudioTheme::InputGap));
    m_cancel = new wxButton(this, wxID_CANCEL, Display("닫기"));
    StudioTheme::Button(*m_cancel);
    actions->Add(m_cancel, 0);
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    SetSizer(layout);
    m_cards->Bind(wxEVT_CHOICE,
                  [this](wxCommandEvent& event)
                  {
                      SelectCard(event.GetSelection());
                  });
    m_mode->Bind(wxEVT_CHOICE,
                 [this](wxCommandEvent& event)
                 {
                     SelectMode(event.GetSelection());
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
    m_goalLayoutNote->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        ShowGoalLayoutNote();
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

void TemplateDialog::ShowGoalLayoutNote()
{
    const int index = m_target->GetSelection() - 1;
    if (index < 0)
    {
        return;
    }
    const auto& target = m_context.at("targets").at(index);
    const auto layout = target.value("layout_note", Json());
    if (!layout.is_object())
    {
        return;
    }
    const auto source = layout.at("frequency_source") == "target_reference" ? "목표 기준 주파수" : "목표 대역 중앙";
    auto text = wxString::Format(Display("%s %.6g GHz\n자유공간 1/4 파장 기준의 초기 기하 참고값\n"),
                                 Display(source), layout.at("frequency_hz").get<double>() / 1e9);
    for (const auto& row : layout.at("candidates"))
    {
        const auto label = row.at("size_kind") == "semicircle_radius_mm" ? "180도 원호 반경" : "IFA 전체 가지 경로";
        text += wxString::Format(Display("\n%s %.5g mm"), Display(label), row.at("size_mm").get<double>());
        const auto state = row.at("outside_ideal_envelope");
        if (!row.value("board_supported", true))
        {
            text += Display(" / 현재 보드 종류 미지원");
        }
        else if (state.is_null())
        {
            text += Display(" / 보드 외곽 적합성 미확인");
        }
        else if (state.get<bool>())
        {
            text += Display(" / 이상 형상도 보드 외곽 초과");
        }
        else
        {
            text += Display(" / 보드 외곽 한도 안");
        }
    }
    text += Display("\n\n선폭, 접지·단락·급전, 설치 여유와 유전체 영향은 실제 형상과 해석에서 확인합니다.");
    wxMessageDialog dialog(this, text, Display("원호·IFA 초기 치수"), wxOK | wxICON_INFORMATION);
    dialog.ShowModal();
}
