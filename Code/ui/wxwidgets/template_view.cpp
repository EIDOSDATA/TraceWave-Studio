/** @file @brief 카드 입력과 읽기 전용 형상 검토를 나란히 배치한다. */
#include "template_dialog.h"
#include "design_canvas.h"
#include "editor_panel.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/checkbox.h>
#include <wx/choicdlg.h>
#include <array>
#include <cmath>
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
    m_proposeLayout = new wxButton(this, wxID_ANY, Display("설치 조건으로 구조 제안"));
    m_proposeLayout->SetName("template.layout.propose");
    m_proposeLayout->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        ProposeLayouts();
    });
    targetRow->Add(m_proposeLayout, 0, wxEXPAND | wxLEFT, FromDIP(StudioTheme::InputGap));
    selectors->Add(targetRow, 1, wxEXPAND);
    layout->Add(selectors, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    m_goalSize = new wxCheckBox(this, wxID_ANY, Display("목표 주파수로 원호 반경 또는 IFA 방사 길이 계산"));
    m_goalSize->SetName("template.target_dimension");
    layout->Add(m_goalSize, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    m_goalSize->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&)
    {
        Changed();
    });
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
    m_setupButton = new wxButton(this, wxID_ANY, Display("기판과 도체층 설정"));
    StudioTheme::Button(*m_setupButton);
    actions->Add(m_setupButton, 0, wxLEFT, FromDIP(8));
    m_requirements = new wxStaticText(this, wxID_ANY, wxEmptyString);
    StudioTheme::BindSecondary(*m_requirements);
    layout->Add(m_requirements, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    m_setupButton->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        const bool boardMissing = m_context.at("board").is_null();
        if (!boardMissing && m_binding->GetCount() > 0)
        {
            m_binding->SetFocus();
            return;
        }
        if (Editable() && !m_pending && ConfirmDiscard())
        {
            m_nextSetup = boardMissing ? Setup::Board : Setup::Layer;
            CloseDialog(true);
        }
    });
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

void TemplateDialog::ProposeLayouts()
{
    const int target = m_target->GetSelection() - 1;
    const int layer = m_binding->GetSelection();
    if (target < 0 || layer < 0 || m_pending || !Editable())
    {
        return;
    }
    wxDialog form(this, wxID_ANY, Display("설치 영역과 인쇄 도체 치수"));
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* fields = new wxFlexGridSizer(2, FromDIP(6), FromDIP(12));
    fields->AddGrowableCol(1);
    const std::array<const char*, 9> labels = {"설치 최소 X", "설치 최소 Y", "설치 최대 X", "설치 최대 Y",
        "접지 영역 높이", "도체 선폭과 정사각 패드 폭", "급전 간극", "IFA 단락과 급전 사이 간격", "기존 도체와의 최소 여유"};
    std::array<wxTextCtrl*, 9> inputs;
    for (std::size_t i = 0; i < labels.size(); ++i)
    {
        fields->Add(new wxStaticText(&form, wxID_ANY, Display(labels[i]) + " (mm)"), 0, wxALIGN_CENTER_VERTICAL);
        inputs[i] = new wxTextCtrl(&form, wxID_ANY);
        fields->Add(inputs[i], 1, wxEXPAND);
    }
    layout->Add(fields, 1, wxEXPAND | wxALL, FromDIP(12));
    auto* warning = new wxStaticText(&form, wxID_ANY, " ");
    layout->Add(warning, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    layout->Add(form.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, FromDIP(12));
    std::array<double, 9> values;
    form.Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        for (std::size_t i = 0; i < inputs.size(); ++i)
        {
            if (!inputs[i]->GetValue().ToDouble(&values[i]) || !std::isfinite(values[i]))
            {
                warning->SetLabel(Display("이 칸에 밀리미터 단위의 숫자를 입력하세요."));
                inputs[i]->SetFocus();
                return;
            }
        }
        form.EndModal(wxID_OK);
    }, wxID_OK);
    form.SetSizerAndFit(layout);
    form.CentreOnParent();
    if (form.ShowModal() != wxID_OK)
    {
        return;
    }
    const auto& binding = m_context.at("bindings").at(layer);
    Json input = {{"expected_revision", m_revision}, {"instance_id", m_context.at("new_instance_id")},
                  {"target_id", m_context.at("targets").at(target).at("id")},
                  {"region_mm", {values[0], values[1], values[2], values[3]}}, {"ground_height_mm", values[4]},
                  {"width_mm", values[5]}, {"feed_gap_mm", values[6]}, {"branch_pitch_mm", values[7]}, {"clearance_mm", values[8]},
                  {"binding", {{"board_id", m_context.at("board").at("id")}, {"frame_id", m_context.at("frame_id")},
                               {"layer_id", binding.at("layer_id")}, {"material_id", binding.at("material_id")}}}};
    Request("template.layout_candidates", input, false, [this](const Json& result)
    {
        wxArrayString allowed;
        std::vector<Json> candidates;
        wxString details;
        for (const auto& row : result.at("candidates"))
        {
            const auto name = Display(row.at("name").get<std::string>());
            if (row.at("available").get<bool>())
            {
                allowed.Add(name + wxString::Format(" / %.6g mm", row.at("size_mm").get<double>()));
                candidates.push_back(row);
            }
            else
            {
                details += name + " / " + Display(row.at("reason").get<std::string>()) + "\n";
            }
        }
        if (allowed.empty())
        {
            SetStatus(Utf8(details));
            return;
        }
        wxSingleChoiceDialog choose(this, details + Display("실제 도체 경계를 검사한 구조를 골라 치수를 검토하세요."),
                                    Display("설치 가능한 후보"), allowed);
        if (choose.ShowModal() != wxID_OK)
        {
            return;
        }
        const auto selected = candidates.at(choose.GetSelection());
        const auto card = selected.at("template_id").get<std::string>();
        const auto& cards = m_context.at("cards");
        for (std::size_t i = 0; i < cards.size(); ++i)
        {
            if (cards[i].at("template_id") == card)
            {
                m_cards->SetSelection(static_cast<int>(i));
                SelectCard(static_cast<int>(i));
                m_layoutCandidates[card] = selected;
                m_loading = true;
                for (const auto& field : selected.at("display_values").items())
                {
                    m_inputs->SetFieldValue(field.key(), field.value());
                }
                m_goalSize->SetValue(true);
                m_loading = false;
                Changed();
                Preview();
                return;
            }
        }
    });
}
