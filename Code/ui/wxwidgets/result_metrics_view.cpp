/** @file @brief 효율 곡선에 기록 주파수만 사용하고 개별 손실 정확도와 구분한다. */
#include "result_metrics_view.h"
#include "result_presentation.h"
#include "network_chart.h"
#include "frequency_display.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/dialog.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/wrapsizer.h>
#include <algorithm>
ResultMetricsView::ResultMetricsView(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    StudioTheme::BindSurface(*this);
    SetScrollRate(0, FromDIP(16));
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_heading = new wxStaticText(this, wxID_ANY, Display("전력과 손실"));
    m_heading->SetWindowStyleFlag(m_heading->GetWindowStyleFlag() | wxST_ELLIPSIZE_END);
    m_heading->SetMinSize(wxSize(1, -1));
    StudioTheme::Title(*m_heading);
    layout->Add(m_heading, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* toolbar = new wxWrapSizer(wxHORIZONTAL);
    toolbar->Add(new wxStaticText(this, wxID_ANY, Display("기록 주파수")), 0,
                 wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    m_frequency = new wxChoice(this, wxID_ANY);
    m_frequency->SetName(Display("기록 주파수"));
    toolbar->Add(m_frequency, 0, wxALL, FromDIP(4));
    auto* select = new wxButton(this, wxID_ANY, Display("원본 선택"));
    toolbar->Add(select, 0, wxALL, FromDIP(4));
    m_validationButton = new wxButton(this, wxID_ANY, Display("프로젝트 검증 기록"));
    m_validationButton->SetToolTip(
        Display("프로젝트의 별도 검증 보고서를 엽니다. 현재 결과의 검증 합격을 뜻하지 않습니다."));
    m_validationButton->Disable();
    toolbar->Add(m_validationButton, 0, wxALL, FromDIP(4));
    m_validationButton->Bind(wxEVT_BUTTON,
                             [this](wxCommandEvent&)
                             {
                                 if (onValidation)
                                 {
                                     onValidation();
                                 }
                             });
    m_details = new wxCheckBox(this, wxID_ANY, Display("전체 지표"));
    toolbar->Add(m_details, 0, wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    m_rawButton = new wxButton(this, wxID_ANY, Display("원본 수치"));
    toolbar->Add(m_rawButton, 0, wxALL, FromDIP(4));
    m_details->Disable();
    m_rawButton->Disable();
    layout->Add(toolbar, 0, wxEXPAND | wxLEFT, FromDIP(4));
    m_notice = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_notice->SetMinSize(wxSize(1, -1));
    layout->Add(m_notice, 0, wxEXPAND | wxALL, FromDIP(8));
    m_table = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 212)), wxLC_REPORT);
    m_table->SetName(Display("선택 주파수의 전력과 손실"));
    m_table->SetMinSize(FromDIP(wxSize(-1, 212)));
    StudioTheme::Table(*m_table);
    for (const auto& column : std::vector<std::pair<std::string, int>>{
             {"항목", 175}, {"기록 값", 170}, {"판독 기준", 275}})
    {
        m_table->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    layout->Add(m_table, 0, wxEXPAND | wxALL, FromDIP(8));

    m_chart = new NetworkChart(this);
    m_chart->SetMinSize(FromDIP(wxSize(320, 230)));
    layout->Add(m_chart, 1, wxEXPAND | wxALL, FromDIP(8));
    SetSizer(layout);
    Clear("방사 결과가 저장된 원본을 선택하세요.");
    m_details->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&)
    {
        Present();
    });
    m_rawButton->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        const int selection = m_frequency->GetSelection();
        if (selection < 0)
        {
            return;
        }
        const auto& selected = m_result.at("rows").at(static_cast<std::size_t>(selection));
        Json raw{{"source", m_result.at("source")}, {"pin", m_result.at("pin")}, {"sample", selected}};
        wxDialog dialog(this, wxID_ANY, Display("선택 주파수의 원본 수치"),
                        wxDefaultPosition, FromDIP(wxSize(720, 500)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
        auto* contents = new wxBoxSizer(wxVERTICAL);
        auto* data = new wxTextCtrl(&dialog, wxID_ANY, Display(raw.dump(2)), wxDefaultPosition,
                                   wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY | wxTE_DONTWRAP);
        data->SetName(Display("원본 수치와 출처"));
        contents->Add(data, 1, wxEXPAND | wxALL, FromDIP(10));
        auto* close = new wxButton(&dialog, wxID_OK, Display("닫기"));
        close->SetDefault();
        contents->Add(close, 0, wxALIGN_RIGHT | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(10));
        dialog.SetSizer(contents);
        dialog.CentreOnParent();
        dialog.ShowModal();
    });
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
             m_notice->SetLabel(m_noticeText);
             m_notice->Wrap(std::max(FromDIP(220), GetClientSize().x - FromDIP(24)));
             Layout();
             FitInside();
             event.Skip();
         });
}
void ResultMetricsView::SetValidationAvailable(bool available)
{
    m_validationButton->Enable(available);
}
void ResultMetricsView::SetDescription(const Json& description)
{
    Clear("기록한 전력과 독립 손실을 조회하고 있습니다.");
    m_description = description;
    m_heading->SetLabel(Display("전력과 손실"));
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
    const int selection = m_frequency->GetSelection();
    m_details->Enable(selection >= 0);
    m_rawButton->Enable(selection >= 0);
    const bool all = m_details->GetValue();
    std::string notice;
    if (selection < 0 || all)
    {
        for (const auto& warning : m_result.value("warnings", Json::array()))
        {
            notice += ResultUi::Text(warning) + "\n";
        }
    }
    m_table->Show(selection >= 0);
    m_chart->Show(selection >= 0);
    if (selection >= 0)
    {
        const auto& selected = m_result.at("rows").at(static_cast<std::size_t>(selection));
        const auto balance = selected.at("numerical_balance_status");
        const bool hasLosses = !selected.at("independent_losses").empty();
        if (!all)
        {
            notice = "전력 단위는 W*s^2입니다. 절대 전력 (W)은 미평가 상태입니다.\n";
            if (balance == "within_initial_numerical_budget")
            {
                notice += "전력 수지: 초기 수치 기준 충족\n";
            }
            else if (balance == "requires_review")
            {
                notice += "전력 수지: 잔차와 초기 기준을 확인하세요.\n";
            }
            if (!hasLosses)
            {
                notice += "독립 손실 미기록. 새 해석에서 방사와 독립 손실 기록을 켜세요.\n";
            }
        }
        const std::vector<std::string> overview{"accepted", "radiated", "radiation_efficiency", "total_efficiency",
                                                "dielectric_loss_w_s2", "conductor_loss_w_s2", "relative_residual"};
        for (const auto& item : m_result.at("table_rows"))
        {
            if (item.at("frequency_hz") != selected.at("frequency_hz") ||
                (!all && std::find(overview.begin(), overview.end(), item.at("key").get<std::string>()) == overview.end()))
            {
                continue;
            }
            const auto row = m_table->InsertItem(m_table->GetItemCount(), Display(ResultUi::Text(item.at("label"))));
            const auto& value = item.at("value");
            const auto denominator = item.value("denominator", Json(nullptr));
            const auto state = item.value("state", Json(nullptr));
            m_table->SetItem(row, 1, Display(value.is_number() ? ResultUi::Number(value, 6) + " " +
                ResultUi::Text(item.at("unit")) : ResultUi::State(state)));
            const auto basis = denominator == "accepted" ? "수용 전력 기준" :
                               denominator == "incident" ? "입사 전력 기준" : "기록 표본";
            m_table->SetItem(row, 2, Display(all ? basis + std::string(", ") + ResultUi::State(state) : basis));
        }
        if (all)
        {
            for (const auto& reason : selected.at("reasons"))
            {
                notice += ResultUi::Text(reason) + "\n";
            }
        }
        else if (selected.at("power_order_status") == "requires_review")
        {
            notice += "전력 순서와 효율을 검토하세요. 전체 지표에서 관련 값을 확인할 수 있습니다.\n";
        }
    }
    else
    {
        notice += "다른 원본을 선택하거나 새 해석에서 원거리 방사 패턴을 기록하세요.";
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
    m_chart->SetSeries(pages, {Display("방사 효율 (분모는 수용 전력)"), Display("총 효율 (분모는 입사 전력)")}, false);
    m_chart->SetMetric("real", Display("효율 (%) (기록된 표본)"));
    m_chart->SetFrequencyUnit(StudioFrequency::ForSamples(m_result.at("rows")).unit);
    SetNotice(notice);
}

/** @brief 안내 원문에서 매번 줄을 나누어 창을 넓히면 이전 줄바꿈도 해제한다. */
void ResultMetricsView::SetNotice(const std::string& message)
{
    m_noticeText = Display(message);
    m_noticeText.Trim();
    m_notice->SetLabel(m_noticeText);
    m_notice->Wrap(std::max(FromDIP(220), GetClientSize().x - FromDIP(24)));
    Layout();
    FitInside();
}

void ResultMetricsView::Clear(const std::string& reason)
{
    m_heading->SetLabel(Display("전력과 손실"));
    m_heading->SetToolTip(wxEmptyString);
    m_description = nullptr;
    m_result = nullptr;
    m_frequency->Clear();
    m_frequency->Disable();
    m_details->SetValue(false);
    m_details->Disable();
    m_rawButton->Disable();
    m_table->DeleteAllItems();
    m_table->Hide();
    m_chart->Clear();
    m_chart->Hide();
    SetNotice(reason);
}
