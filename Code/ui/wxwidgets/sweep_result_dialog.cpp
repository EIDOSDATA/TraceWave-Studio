/** @file @brief 실제 후보 표본과 당시 목표 판정을 표시하고 영구 원본을 수정하지 않는다. */
#include "sweep_result_dialog.h"
#include "network_chart.h"
#include "frequency_display.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include "sweep_model.h"
#include <wx/wx.h>
#include <wx/listctrl.h>
#include <wx/wrapsizer.h>
#include <wx/collpane.h>
#include <wx/scrolwin.h>
#include <array>

SweepResultDialog::SweepResultDialog(wxWindow* parent, const Json& context, const std::string& studyId, int index,
                                     DialogGateway gateway)
    : ProjectSetupDialog(parent, "연구 후보 / 실제 복소 결과", context, std::move(gateway)), m_studyId(studyId),
      m_index(index)
{
    SetName("sweep.result.dialog");
    auto* root = new wxBoxSizer(wxVERTICAL);
    auto* title =
        new wxStaticText(this, wxID_ANY, Display("후보 " + std::to_string(index + 1) + " / 저장된 결과 읽기"));
    StudioTheme::Title(*title);
    root->Add(title, 0, wxALL, FromDIP(12));
    auto* choices = new wxWrapSizer(wxHORIZONTAL);
    choices->Add(new wxStaticText(this, wxID_ANY, Display("응답 포트")), 0, wxALL | wxALIGN_CENTER_VERTICAL,
                 FromDIP(4));
    m_row = new wxChoice(this, wxID_ANY);
    choices->Add(m_row, 0, wxALL, FromDIP(4));
    choices->Add(new wxStaticText(this, wxID_ANY, Display("입력 포트")), 0, wxALL | wxALIGN_CENTER_VERTICAL,
                 FromDIP(4));
    m_column = new wxChoice(this, wxID_ANY);
    choices->Add(m_column, 0, wxALL, FromDIP(4));
    m_metric = new wxChoice(this, wxID_ANY);
    for (const auto* label : {"크기 (dB)", "크기", "위상 (deg)", "실수부", "허수부", "VSWR"})
    {
        m_metric->Append(Display(label));
    }
    m_metric->SetSelection(0);
    choices->Add(m_metric, 0, wxALL, FromDIP(4));
    root->Add(choices, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    auto* tabs = new StudioNotebook(this);
    m_tabs = tabs;
    m_chart = new NetworkChart(tabs);
    tabs->AddPage(m_chart, Display("실제 표본 곡선"));
    m_samples =
        new wxListCtrl(tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    m_samples->SetName("sweep.result.samples");
    StudioTheme::Table(*m_samples);
    for (const auto& item : std::vector<std::pair<std::string, int>>{{"주파수", 170},
                                                                     {"실수부", 160},
                                                                     {"허수부", 160},
                                                                     {"크기 (dB)", 140},
                                                                     {"위상 (deg)", 140},
                                                                     {"VSWR", 140},
                                                                     {"상태 / 출처", 220}})
    {
        m_samples->AppendColumn(Display(item.first), wxLIST_FORMAT_LEFT, FromDIP(item.second));
    }
    tabs->AddPage(m_samples, Display("표본 표"));
    auto* conditionsPage =
        new wxScrolledWindow(tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    conditionsPage->SetScrollRate(0, FromDIP(16));
    auto* conditionsLayout = new wxBoxSizer(wxVERTICAL);
    m_conditions = new wxTextCtrl(conditionsPage, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                                  wxTE_MULTILINE | wxTE_READONLY | wxTE_WORDWRAP);
    m_conditions->SetMinSize(FromDIP(wxSize(-1, 240)));
    conditionsLayout->Add(m_conditions, 1, wxEXPAND | wxALL, FromDIP(8));
    m_advanced = new wxCollapsiblePane(conditionsPage, wxID_ANY, Display("고급 상세 / 보존된 원문 (읽기 전용)"),
                                       wxDefaultPosition, wxDefaultSize, wxCP_NO_TLW_RESIZE);
    auto* advancedLayout = new wxBoxSizer(wxVERTICAL);
    m_source = new wxTextCtrl(m_advanced->GetPane(), wxID_ANY, wxEmptyString, wxDefaultPosition,
                              FromDIP(wxSize(-1, 190)), wxTE_MULTILINE | wxTE_READONLY | wxTE_WORDWRAP);
    advancedLayout->Add(m_source, 1, wxEXPAND);
    m_advanced->GetPane()->SetSizer(advancedLayout);
    m_advanced->Collapse(true);
    conditionsLayout->Add(m_advanced, 0, wxEXPAND | wxALL, FromDIP(8));
    conditionsPage->SetSizer(conditionsLayout);
    m_advanced->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                     [conditionsPage](wxCollapsiblePaneEvent&)
                     {
                         conditionsPage->Layout();
                         conditionsPage->FitInside();
                     });
    conditionsPage->Bind(wxEVT_SIZE,
                         [conditionsPage](wxSizeEvent& event)
                         {
                             conditionsPage->Layout();
                             conditionsPage->FitInside();
                             event.Skip();
                         });
    tabs->AddPage(conditionsPage, Display("조건 / 목표 판정"));
    root->Add(tabs, 1, wxEXPAND | wxALL, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, Display("저장된 후보 결과를 조회합니다. 새 계산은 실행하지 않습니다."));
    root->Add(m_status, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_previous = new wxButton(this, wxID_ANY, Display("이전 201개"));
    m_next = new wxButton(this, wxID_ANY, Display("다음 201개"));
    actions->Add(m_previous, 0, wxALL, FromDIP(4));
    actions->Add(m_next, 0, wxALL, FromDIP(4));
    actions->AddStretchSpacer();
    actions->Add(new wxButton(this, wxID_CANCEL, Display("닫기")), 0, wxALL, FromDIP(4));
    root->Add(actions, 0, wxEXPAND | wxALL, FromDIP(8));
    SetSizer(root);
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         Load(std::max(0, m_offset - 201));
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (m_nextOffset >= 0)
                     {
                         Load(m_nextOffset);
                     }
                 });
    for (auto* choice : {m_row, m_column})
    {
        choice->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         Load(0);
                     });
    }
    m_metric->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       ChangeMetric();
                   });
    m_samples->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [this](wxListEvent& event)
                    {
                        m_chart->SetMarker(static_cast<int>(event.GetIndex()));
                    });
    CallAfter(
        [this]()
        {
            Load(0);
        });
}

void SweepResultDialog::Load(int offset)
{
    if (!Editable() || m_pending)
    {
        return;
    }
    const int row = std::max(0, m_row->GetSelection());
    const int column = std::max(0, m_column->GetSelection());
    SetStatus("요청한 채널의 실제 표본을 읽고 있습니다. 이전 표본은 마지막 확인한 결과입니다.");
    Request("sweep.result",
            {{"study_id", m_studyId},
             {"index", m_index},
             {"offset", offset},
             {"limit", 201},
             {"row", row},
             {"column", column}},
            false,
            [this, row, column, offset](const Json& result)
            {
                if (result.at("study_id") != m_studyId || result.at("index") != m_index ||
                    result.at("page").at("channel").at("row") != row ||
                    result.at("page").at("channel").at("column") != column || result.at("page").at("offset") != offset)
                {
                    ShowRequestFailure({{"message", "선택 후보와 다른 결과 응답입니다."}});
                    throw std::runtime_error("선택 후보와 다른 결과 응답입니다.");
                }
                Render(result);
            });
}

void SweepResultDialog::Render(const Json& result)
{
    m_result = result;
    const auto& page = result.at("page");
    const auto& descriptor = result.at("descriptor");
    if (m_row->GetCount() == 0)
    {
        const auto names = descriptor.value("port_names", Json::array());
        const auto count = descriptor.at("port_ids").size();
        for (std::size_t index = 0; index < count; ++index)
        {
            const auto original = index < names.size() ? names.at(index) : Json(nullptr);
            const auto name = original.is_string() && !original.get<std::string>().empty()
                                  ? original.get<std::string>()
                                  : "자료 포트 " + std::to_string(index + 1) + " (이름 미정)";
            m_row->Append(Display(name));
            m_column->Append(Display(name));
        }
        m_row->SetSelection(0);
        m_column->SetSelection(0);
    }
    const auto scale = StudioFrequency::ForDescriptor(descriptor);
    m_chart->SetFrequencyUnit(scale.unit);
    m_chart->SetPage(page, Display(result.at("entry").at("name")));
    ChangeMetric();
    wxListItem heading;
    heading.SetText(Display("주파수 (" + scale.unit + ")"));
    m_samples->SetColumn(0, heading);
    m_samples->DeleteAllItems();
    for (const auto& sample : page.at("samples"))
    {
        const long row = m_samples->InsertItem(m_samples->GetItemCount(),
                                               Display(StudioFrequency::Value(sample.at("frequency_hz"), scale)));
        int column = 1;
        for (const auto* key : {"real", "imag", "magnitude_db", "phase_deg", "vswr"})
        {
            m_samples->SetItem(row, column++, Display(SweepUi::SampleValue(sample, key)));
        }
        m_samples->SetItem(row, 6,
                           Display(SweepUi::Status(sample.value("status", "missing")) + " / " +
                                   SweepUi::Status(sample.value("origin", "unknown"))));
    }
    m_offset = page.value("offset", 0);
    m_nextOffset =
        page.value("next_offset", Json(nullptr)).is_number_integer() ? page.at("next_offset").get<int>() : -1;
    m_conditions->ChangeValue(Display(SweepUi::ResultConditions(result)));
    const Json evidence{{"자료 조건과 출처", descriptor},
                        {"목표 판정 원문 요약", result.value("assessments", Json::array())},
                        {"저장 당시 입력", result.value("snapshot", Json(nullptr))},
                        {"결과 기록", result.at("entry")}};
    m_source->ChangeValue(Display(evidence.dump(2, ' ', false, Json::error_handler_t::replace)));
    SetStatus("실제 표본 " + std::to_string(m_offset + 1) + "~" + std::to_string(m_offset + page.at("samples").size()) +
              " / 페이지 사이 보간·예측 없음");
}

void SweepResultDialog::ChangeMetric()
{
    if (m_result.is_null())
    {
        return;
    }
    const std::array<const char*, 6> keys{{"magnitude_db", "magnitude", "phase_deg", "real", "imag", "vswr"}};
    if (m_result.at("descriptor").at("parameter_kind") != "S" &&
        (m_metric->GetSelection() == 0 || m_metric->GetSelection() == 5))
    {
        m_metric->SetSelection(1);
    }
    m_chart->SetMetric(keys.at(std::max(0, m_metric->GetSelection())), m_metric->GetStringSelection());
}

void SweepResultDialog::UpdateActions()
{
    const bool enabled = Editable() && !m_pending;
    for (auto* choice : {m_row, m_column, m_metric})
    {
        choice->Enable(enabled && !m_result.is_null());
    }
    m_previous->Enable(enabled && m_offset > 0);
    m_next->Enable(enabled && m_nextOffset >= 0);
}

void SweepResultDialog::ShowRequestFailure(const Json& error)
{
    if (m_result.is_object())
    {
        const auto& channel = m_result.at("page").at("channel");
        m_row->SetSelection(channel.at("row").get<int>());
        m_column->SetSelection(channel.at("column").get<int>());
    }
    SetStatus("표본 조회 실패 / 마지막으로 확인한 채널과 표본을 유지합니다.\n" + DiagnosticMessage(error));
}
