/** @file @brief 효율 곡선에 기록 주파수만 사용하고 개별 손실 정확도와 구분한다. */
#include "result_metrics_view.h"
#include "result_presentation.h"
#include "network_chart.h"
#include "frequency_display.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
ResultMetricsView::ResultMetricsView(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    StudioTheme::BindSurface(*this);
    SetScrollRate(0, FromDIP(16));
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_heading = new wxStaticText(this, wxID_ANY, Display("전력 / 손실"));
    m_heading->SetWindowStyleFlag(m_heading->GetWindowStyleFlag() | wxST_ELLIPSIZE_END);
    m_heading->SetMinSize(wxSize(1, -1));
    StudioTheme::Title(*m_heading);
    layout->Add(m_heading, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* toolbar = new wxBoxSizer(wxHORIZONTAL);
    m_frequency = new wxChoice(this, wxID_ANY);
    toolbar->Add(m_frequency, 0, wxALL, FromDIP(4));
    auto* select = new wxButton(this, wxID_ANY, Display("원본 선택"));
    toolbar->Add(select, 0, wxALL, FromDIP(4));
    layout->Add(toolbar, 0, wxEXPAND | wxLEFT, FromDIP(4));
    m_table = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 300)), wxLC_REPORT);
    m_table->SetMinSize(FromDIP(wxSize(-1, 300)));
    StudioTheme::Table(*m_table);
    for (const auto& column : std::vector<std::pair<std::string, int>>{
             {"항목", 185}, {"기록 값", 215}, {"분모 / 기록 범위", 220}, {"검증 상태", 230}})
    {
        m_table->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    layout->Add(m_table, 0, wxEXPAND | wxALL, FromDIP(8));
    m_notice = new wxStaticText(this, wxID_ANY, Display("NF2FF 전력 기록이 있는 원본을 선택하세요."));
    layout->Add(m_notice, 0, wxEXPAND | wxALL, FromDIP(8));
    m_chart = new NetworkChart(this);
    m_chart->SetMinSize(FromDIP(wxSize(320, 230)));
    layout->Add(m_chart, 1, wxEXPAND | wxALL, FromDIP(8));
    SetSizer(layout);
    m_frequency->Bind(wxEVT_CHOICE,
                      [this](wxCommandEvent&)
                      {
                          Present();
                      });
    select->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (onSelectSource)
                     {
                         onSelectSource();
                     }
                 });
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             m_notice->Wrap(std::max(FromDIP(220), GetClientSize().x - FromDIP(24)));
             Layout();
             FitInside();
             event.Skip();
         });
}
void ResultMetricsView::SetDescription(const Json& description)
{
    Clear("기록한 전력과 독립 손실을 조회하고 있습니다.");
    m_description = description;
    m_heading->SetLabel(Display("전력 / 손실"));
    m_heading->SetToolTip(Display(ResultUi::Text(description.at("label"))));
}
void ResultMetricsView::SetMetrics(const Json& result)
{
    if (!ResultUi::Matches(result, m_description))
    {
        return;
    }
    m_result = result;
    m_frequency->Clear();
    for (const auto& row : result.at("rows"))
    {
        m_frequency->Append(Display(StudioFrequency::WithUnit(row.at("frequency_hz"))));
    }
    m_frequency->Enable(m_frequency->GetCount() > 0);
    if (m_frequency->GetCount() > 0)
    {
        m_frequency->SetSelection(0);
    }
    Present();
}
void ResultMetricsView::Present()
{
    if (!m_result.is_object())
    {
        return;
    }
    m_table->DeleteAllItems();
    std::string notice;
    for (const auto& warning : m_result.value("warnings", Json::array()))
    {
        notice += ResultUi::Text(warning) + "\n";
    }
    const int selection = m_frequency->GetSelection();
    if (selection >= 0)
    {
        const auto& selected = m_result.at("rows").at(static_cast<std::size_t>(selection));
        for (const auto& item : m_result.at("table_rows"))
        {
            if (item.at("frequency_hz") != selected.at("frequency_hz"))
            {
                continue;
            }
            const auto row = m_table->InsertItem(m_table->GetItemCount(), Display(ResultUi::Text(item.at("label"))));
            m_table->SetItem(row, 1,
                             Display(ResultUi::Number(item.at("value")) + " " + ResultUi::Text(item.at("unit"))));
            const auto denominator = item.value("denominator", Json(nullptr));
            m_table->SetItem(row, 2,
                             Display(denominator == "accepted"   ? "수용 전력"
                                     : denominator == "incident" ? "입사 전력"
                                                                 : "실제 기록 주파수"));
            m_table->SetItem(row, 3, Display(ResultUi::State(item.value("state", Json(nullptr)))));
        }
        for (const auto& reason : selected.value("reasons", Json::array()))
        {
            notice += ResultUi::Text(reason) + "\n";
        }
    }
    std::vector<Json> pages;
    for (const std::string key : {"radiation_efficiency", "total_efficiency"})
    {
        Json samples = Json::array();
        for (const auto& item : m_result.at("table_rows"))
        {
            if (item.at("key") == key)
            {
                samples.push_back({{"index", samples.size()},
                                   {"frequency_hz", item.at("frequency_hz")},
                                   {"real", item.at("value")},
                                   {"status", item.at("state")},
                                   {"valid", item.at("value").is_number()},
                                   {"origin", "computed"}});
            }
        }
        pages.push_back({{"samples", samples},
                         {"offset", 0},
                         {"total", samples.size()},
                         {"next_offset", nullptr},
                         {"parameter_kind", "scalar"},
                         {"unit", "%"}});
    }
    m_chart->SetSeries(pages, {Display("방사 효율 / 수용 전력 분모"), Display("총 효율 / 입사 전력 분모")}, false);
    m_chart->SetMetric("real", Display("효율 (%) / 기록 표본만"));
    m_chart->SetFrequencyUnit(StudioFrequency::ForSamples(m_result.at("rows")).unit);
    m_notice->SetLabel(Display(notice));
    m_notice->Wrap(std::max(FromDIP(220), GetClientSize().x - FromDIP(24)));
    Layout();
    FitInside();
}
void ResultMetricsView::Clear(const std::string& reason)
{
    m_heading->SetLabel(Display("전력 / 손실"));
    m_heading->SetToolTip(wxEmptyString);
    m_description = nullptr;
    m_result = nullptr;
    m_frequency->Clear();
    m_frequency->Disable();
    m_table->DeleteAllItems();
    m_chart->Clear();
    m_notice->SetLabel(Display(reason));
}
