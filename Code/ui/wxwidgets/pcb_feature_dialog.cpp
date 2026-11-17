/** @file @brief 목록과 전용 입력/검토/출처 탭을 기존 Studio 표시 체계로 구성한다. */
#include "pcb_feature_dialog.h"
#include "pcb_feature_form.h"
#include "pcb_feature_model.h"
#include "design_canvas.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/button.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/scrolwin.h>
#include <wx/wrapsizer.h>
#include <algorithm>

PcbFeatureDialog::PcbFeatureDialog(wxWindow* parent, const Json& context, DialogGateway gateway,
                                   std::shared_ptr<PcbFeatureRecovery> recovery)
    : ProjectSetupDialog(parent, "PCB 형상과 제조 입력", context, gateway), m_context(context), m_gateway(gateway),
      m_recovery(std::move(recovery))
{
    SetName("pcb.features.dialog");
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("PCB 형상과 제조 입력"));
    StudioTheme::Title(*title);
    layout->Add(title, 0, wxALL, FromDIP(12));
    auto* choices = new wxWrapSizer(wxHORIZONTAL);
    m_sections = {"cutout", "hole", "footprint", "artwork_layer", "aperture", "keepout"};
    m_section = new wxChoice(this, wxID_ANY);
    for (const auto& section : m_sections)
    {
        m_section->Append(Display(PcbFeatureUi::SectionLabel(section)));
    }
    choices->Add(m_section, 0, wxALL, FromDIP(4));
    m_record = new wxChoice(this, wxID_ANY);
    m_record->SetMinSize(FromDIP(wxSize(240, -1)));
    choices->Add(m_record, 1, wxALL, FromDIP(4));
    m_shape = new wxChoice(this, wxID_ANY);
    for (const auto* label : {"원형", "사각형", "직선 슬롯", "다각형"})
    {
        m_shape->Append(Display(label));
    }
    m_shape->SetSelection(0);
    choices->Add(m_shape, 0, wxALL, FromDIP(4));
    m_definition = new wxChoice(this, wxID_ANY);
    m_definition->Append(Display("개구: 명시 형상"));
    m_definition->Append(Display("개구: 패드 여유"));
    choices->Add(m_definition, 0, wxALL, FromDIP(4));
    m_envelope = new wxChoice(this, wxID_ANY);
    for (const auto* label : {"배치 외곽 미정", "외곽: 원형", "외곽: 사각형", "외곽: 직선 슬롯", "외곽: 다각형"})
    {
        m_envelope->Append(Display(label));
    }
    choices->Add(m_envelope, 0, wxALL, FromDIP(4));
    m_operation = new wxChoice(this, wxID_ANY);
    choices->Add(m_operation, 0, wxALL, FromDIP(4));
    layout->Add(choices, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_tabs = new StudioNotebook(this);
    m_form = new PcbFeatureForm(m_tabs, gateway);
    m_tabs->AddPage(m_form, Display("객체 입력"));
    auto* review =
        new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    review->SetScrollRate(0, FromDIP(16));
    auto* reviewLayout = new wxBoxSizer(wxVERTICAL);
    m_sceneChoice = new wxChoice(review, wxID_ANY);
    m_sceneChoice->Append(Display("검토 후보"));
    m_sceneChoice->Append(Display("적용 전 원본"));
    m_sceneChoice->SetSelection(0);
    reviewLayout->Add(m_sceneChoice, 0, wxALL, FromDIP(8));
    m_canvas = new DesignCanvas(review);
    m_canvas->SetEditingEnabled(false);
    m_canvas->SetMinSize(FromDIP(wxSize(320, 210)));
    reviewLayout->Add(m_canvas, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_changes =
        new wxListCtrl(review, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 135)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_changes->SetMinSize(FromDIP(wxSize(-1, 120)));
    StudioTheme::Table(*m_changes);
    for (const auto& column : std::vector<std::pair<std::string, int>>{
             {"항목", 240}, {"원래 값", 230}, {"후보 값", 230}, {"단위 / 상태", 180}})
    {
        m_changes->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    reviewLayout->Add(m_changes, 0, wxEXPAND | wxALL, FromDIP(8));
    m_changes->Bind(wxEVT_LIST_ITEM_ACTIVATED,
                    [this](wxListEvent& event)
                    {
                        const auto rows =
                            m_review.is_object() ? m_review.value("changes", Json::array()) : Json::array();
                        if (event.GetIndex() < 0 || static_cast<std::size_t>(event.GetIndex()) >= rows.size())
                        {
                            return;
                        }
                        const auto& row = rows.at(event.GetIndex());
                        wxDialog details(this, wxID_ANY, Display("변경 상세"), wxDefaultPosition,
                                         FromDIP(wxSize(780, 430)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
                        auto* detailsLayout = new wxBoxSizer(wxVERTICAL);
                        auto* text = new wxTextCtrl(
                            &details, wxID_ANY,
                            Display(row.value("label", "변경 항목") + "\n\n원래 값\n" +
                                    PcbFeatureUi::Text(row.value("before_display", Json(nullptr))) + "\n\n후보 값\n" +
                                    PcbFeatureUi::Text(row.value("after_display", Json(nullptr)))),
                            wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
                        detailsLayout->Add(text, 1, wxEXPAND | wxALL, FromDIP(12));
                        detailsLayout->Add(details.CreateButtonSizer(wxOK), 0, wxEXPAND | wxALL, FromDIP(12));
                        details.SetSizer(detailsLayout);
                        details.CentreOnParent();
                        details.ShowModal();
                    });
    m_changes->SetToolTip(
        Display("행을 두 번 클릭하거나 Enter를 누르면 변경 전후 값을 전체 문장으로 확인할 수 있습니다."));
    m_issues = new wxTextCtrl(review, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 90)),
                              wxTE_MULTILINE | wxTE_READONLY);
    reviewLayout->Add(m_issues, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    review->SetSizer(reviewLayout);
    review->Bind(wxEVT_SIZE,
                 [review](wxSizeEvent& event)
                 {
                     review->Layout();
                     review->FitInside();
                     event.Skip();
                 });
    m_tabs->AddPage(review, Display("변경 검토"));
    auto* source =
        new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    source->SetScrollRate(0, FromDIP(16));
    auto* sourceLayout = new wxBoxSizer(wxVERTICAL);
    m_conditions = new wxTextCtrl(source, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 230)),
                                  wxTE_MULTILINE | wxTE_READONLY);
    sourceLayout->Add(m_conditions, 1, wxEXPAND | wxALL, FromDIP(12));
    m_advanced = new wxCollapsiblePane(source, wxID_ANY, Display("고급 / 보존 원문"), wxDefaultPosition, wxDefaultSize,
                                       wxCP_DEFAULT_STYLE | wxCP_NO_TLW_RESIZE);
    m_advanced->GetPane()->SetSizer(new wxBoxSizer(wxVERTICAL));
    m_source = new wxTextCtrl(m_advanced->GetPane(), wxID_ANY, wxEmptyString, wxDefaultPosition,
                              FromDIP(wxSize(-1, 200)), wxTE_MULTILINE | wxTE_READONLY | wxHSCROLL);
    m_advanced->GetPane()->GetSizer()->Add(m_source, 1, wxEXPAND | wxALL, FromDIP(8));
    m_advanced->Collapse();
    sourceLayout->Add(m_advanced, 0, wxEXPAND | wxALL, FromDIP(12));
    source->SetSizer(sourceLayout);
    m_advanced->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                     [source](wxCollapsiblePaneEvent&)
                     {
                         source->Layout();
                         source->FitInside();
                     });
    m_tabs->AddPage(source, Display("출처와 적용 범위"));
    layout->Add(m_tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    auto* reason = new wxBoxSizer(wxHORIZONTAL);
    reason->Add(new wxStaticText(this, wxID_ANY, Display("변경 사유")), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT,
                FromDIP(8));
    m_reason = new wxTextCtrl(this, wxID_ANY);
    reason->Add(m_reason, 1, wxEXPAND);
    layout->Add(reason, 0, wxEXPAND | wxALL, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, Display("객체의 원문과 미정값을 확인한 뒤 변경 후보를 검토하세요."));
    layout->Add(m_status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    m_preview = new wxButton(this, wxID_ANY, Display("변경 후보 검토"));
    m_apply = new wxButton(this, wxID_APPLY, Display("검토한 변경 적용"));
    m_recover = new wxButton(this, wxID_ANY, Display("이전 적용 결과 확인"));
    for (auto* button : {m_preview, m_apply, m_recover, new wxButton(this, wxID_CANCEL, Display("닫기"))})
    {
        StudioTheme::Button(*button);
        actions->Add(button, 0, wxALL, FromDIP(4));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    SetSizer(layout);
    m_form->onChanged = [this]()
    {
        Changed();
    };
    m_form->onStatus = [this](const std::string& message)
    {
        SetStatus(message);
    };
    m_form->onStateChanged = [this]()
    {
        UpdateActions();
    };
    m_preview->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Preview();
                    });
    m_apply->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Apply();
                  });
    m_recover->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Recover();
                    });
    m_reason->Bind(wxEVT_TEXT,
                   [this](wxCommandEvent&)
                   {
                       Changed();
                   });
    m_operation->Bind(wxEVT_CHOICE,
                      [this](wxCommandEvent&)
                      {
                          ChangeOperation();
                      });
    m_sceneChoice->Bind(wxEVT_CHOICE,
                        [this](wxCommandEvent&)
                        {
                            ShowScene();
                        });
    m_section->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        if (!m_loading && ConfirmDiscard())
                        {
                            Load(m_sections.at(m_section->GetSelection()), nullptr);
                        }
                        else
                        {
                            m_section->SetSelection(static_cast<int>(
                                std::find(m_sections.begin(), m_sections.end(), m_sectionName) - m_sections.begin()));
                        }
                    });
    m_record->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       if (!m_loading && ConfirmDiscard())
                       {
                           Load(m_sectionName, m_recordIds.at(m_record->GetSelection()));
                       }
                       else
                       {
                           for (std::size_t index = 0; index < m_recordIds.size(); ++index)
                           {
                               if (m_recordIds.at(index) == m_recordId)
                               {
                                   m_record->SetSelection(static_cast<int>(index));
                               }
                           }
                       }
                   });
    m_shape->Bind(wxEVT_CHOICE,
                  [this](wxCommandEvent&)
                  {
                      Transition();
                  });
    m_definition->Bind(wxEVT_CHOICE,
                       [this](wxCommandEvent&)
                       {
                           Transition();
                       });
    m_envelope->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         Transition();
                     });
    Render(context);
    UpdateActions();
}
