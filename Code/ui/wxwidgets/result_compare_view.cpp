/** @file @brief 수학적 차이와 물리 조건 차이를 섞지 않는 비교 View다. */
#include "result_compare_view.h"
#include "result_presentation.h"
#include "measurement_model.h"
#include "network_chart.h"
#include "frequency_display.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/choicdlg.h>
#include <wx/listctrl.h>
#include <wx/msgdlg.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/wrapsizer.h>
#include <array>
#include <set>
namespace
{
const std::array<std::string, 6> Metrics{"magnitude_db", "phase_deg", "vswr", "real", "imag", "magnitude"};
const std::array<std::string, 6> Labels{"크기 (dB)", "위상 (deg)", "VSWR", "실수부", "허수부", "크기"};
}
ResultCompareView::ResultCompareView(wxWindow* parent, bool measurementMode)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL),
      m_measurementMode(measurementMode)
{
    SetScrollRate(0, FromDIP(16));
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY, Display(measurementMode ? "측정 비교" : "결과 / 후보 비교"));
    StudioTheme::Title(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(8));
    auto* tools = new wxWrapSizer(wxHORIZONTAL);
    m_add = new wxButton(this, wxID_ANY, Display(measurementMode ? "선택 원본을 기준에 추가" : "선택 원본 추가"));
    m_remove = new wxButton(this, wxID_ANY, Display("목록에서 제외"));
    m_map = new wxButton(this, wxID_ANY, Display("포트 대응 지정"));
    m_compare =
        new wxButton(this, wxID_ANY, Display(measurementMode ? "측정 조건 / 차이 확인" : "조건 / 수학 차이 확인"));
    for (wxButton* button : {m_add, m_remove, m_map, m_compare})
    {
        StudioTheme::Button(*button);
        tools->Add(button, 0, wxALL, FromDIP(4));
    }
    layout->Add(tools, 0, wxEXPAND);
    m_sources =
        new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 150)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_sources->SetMinSize(FromDIP(wxSize(-1, 150)));
    StudioTheme::Table(*m_sources);
    m_sources->Bind(wxEVT_SYS_COLOUR_CHANGED, [this](wxSysColourChangedEvent& event)
    {
        for (long row = 0; row < m_sources->GetItemCount(); ++row)
        {
            m_sources->SetItemTextColour(row, NetworkChart::SeriesColour(static_cast<std::size_t>(row)));
        }
        event.Skip();
    });
    for (const auto& entry :
         std::vector<std::pair<std::string, int>>{{"곡선 / 원본", 260},
                                                  {measurementMode ? "시료 / 기록" : "당시 개정", 180},
                                                  {"표본 페이지", 120},
                                                  {"포트 대응 / 비교", 270}})
    {
        m_sources->AppendColumn(Display(entry.first), wxLIST_FORMAT_LEFT, FromDIP(entry.second));
    }
    layout->Add(m_sources, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* choices = new wxWrapSizer(wxHORIZONTAL);
    m_row = new wxChoice(this, wxID_ANY);
    m_column = new wxChoice(this, wxID_ANY);
    m_metric = new wxChoice(this, wxID_ANY);
    for (const auto& label : Labels)
    {
        m_metric->Append(Display(label));
    }
    m_metric->SetSelection(0);
    for (wxChoice* choice : {m_row, m_column, m_metric})
    {
        choices->Add(choice, 0, wxALL, FromDIP(4));
    }
    m_previous = new wxButton(this, wxID_ANY, Display("선택 곡선 이전 표본"));
    m_next = new wxButton(this, wxID_ANY, Display("선택 곡선 다음 표본"));
    choices->Add(m_previous, 0, wxALL, FromDIP(4));
    choices->Add(m_next, 0, wxALL, FromDIP(4));
    layout->Add(choices, 0, wxEXPAND);
    m_status = new wxStaticText(
        this, wxID_ANY, Display("첫 원본이 비교 기준입니다. 최대 8개, 각 원본의 실제 주파수와 페이지를 유지합니다."));
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(8));
    m_chart = new NetworkChart(this);
    m_chart->SetMinSize(FromDIP(wxSize(360, 240)));
    layout->Add(m_chart, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_markers = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 112)), wxLC_REPORT);
    m_markers->SetMinSize(FromDIP(wxSize(-1, 112)));
    for (const auto& entry : std::vector<std::pair<std::string, int>>{
             {"M1 원본", 230}, {"주파수", 150}, {"실제 복소값", 220}, {"상태 / 출처", 240}})
    {
        m_markers->AppendColumn(Display(entry.first), wxLIST_FORMAT_LEFT, FromDIP(entry.second));
    }
    layout->Add(m_markers, 0, wxEXPAND | wxALL, FromDIP(8));
    m_differences = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 112)), wxLC_REPORT);
    m_differences->SetMinSize(FromDIP(wxSize(-1, 112)));
    for (const auto& entry :
         std::vector<std::pair<std::string, int>>{{"주파수", 150}, {"차이 (비교 - 기준)", 250}, {"상태 / 사유", 430}})
    {
        m_differences->AppendColumn(Display(entry.first), wxLIST_FORMAT_LEFT, FromDIP(entry.second));
    }
    layout->Add(m_differences, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    auto* differencePaging = new wxBoxSizer(wxHORIZONTAL);
    m_differencePrevious = new wxButton(this, wxID_ANY, Display("수학 차이 이전 201표본"));
    m_differenceNext = new wxButton(this, wxID_ANY, Display("수학 차이 다음 201표본"));
    differencePaging->Add(m_differencePrevious, 0, wxALL, FromDIP(4));
    differencePaging->Add(m_differenceNext, 0, wxALL, FromDIP(4));
    layout->Add(differencePaging, 0, wxALL, FromDIP(4));
    m_differencePrevious->Bind(wxEVT_BUTTON,
                               [this](wxCommandEvent&)
                               {
                                   const auto index = static_cast<std::size_t>(Selected());
                                   if (onComparePage)
                                   {
                                       onComparePage(index, std::max(0, m_comparisons[index].value("offset", 0) - 201));
                                   }
                               });
    m_differenceNext->Bind(wxEVT_BUTTON,
                           [this](wxCommandEvent&)
                           {
                               const auto index = static_cast<std::size_t>(Selected());
                               if (onComparePage)
                               {
                                   onComparePage(index, m_comparisons[index].at("next_offset").get<int>());
                               }
                           });
    SetSizer(layout);
    m_add->Bind(wxEVT_BUTTON,
                [this](wxCommandEvent&)
                {
                    if (onAddSelected)
                    {
                        onAddSelected();
                    }
                });
    m_remove->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Remove();
                   });
    m_map->Bind(wxEVT_BUTTON,
                [this](wxCommandEvent&)
                {
                    MapPorts();
                });
    m_compare->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (Selected() > 0 && onCompare)
                        {
                            onCompare(static_cast<std::size_t>(Selected()));
                        }
                    });
    m_sources->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [this](wxListEvent&)
                    {
                        if (!m_loading)
                        {
                            Actions();
                            const int selected = Selected();
                            if (selected >= 0 && m_comparisons[static_cast<std::size_t>(selected)].is_object())
                            {
                                SetComparison(static_cast<std::size_t>(selected),
                                              m_comparisons[static_cast<std::size_t>(selected)]);
                            }
                            else
                            {
                                m_differences->DeleteAllItems();
                                if (onInspect)
                                {
                                    onInspect(selected >= 0 &&
                                                      static_cast<std::size_t>(selected) < m_descriptions.size()
                                                  ? m_descriptions[static_cast<std::size_t>(selected)]
                                                  : Json(nullptr));
                                }
                            }
                        }
                    });
    m_row->Bind(wxEVT_CHOICE,
                [this](wxCommandEvent&)
                {
                    ChannelChanged();
                });
    m_column->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       ChannelChanged();
                   });
    m_metric->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       Present();
                   });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         const auto index = static_cast<std::size_t>(Selected());
                         if (onPage)
                         {
                             onPage(index, std::max(0, m_pages[index].value("offset", 0) - 201));
                         }
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     const auto index = static_cast<std::size_t>(Selected());
                     if (onPage)
                     {
                         onPage(index, m_pages[index].at("next_offset").get<int>());
                     }
                 });
    m_chart->onMarker = [this](std::size_t, int, double frequency)
    {
        m_markers->DeleteAllItems();
        for (const auto& description : m_descriptions)
        {
            const auto row =
                m_markers->InsertItem(m_markers->GetItemCount(), Display(ResultUi::Text(description.at("label"))));
            m_markers->SetItem(row, 3, Display("같은 실제 주파수 조회 중"));
        }
        if (onMarkers)
        {
            onMarkers(frequency);
        }
    };
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Layout();
             FitInside();
             event.Skip();
         });
    SetAvailable(false);
}
bool ResultCompareView::Add(const Json& description)
{
    if (!m_descriptions.empty() &&
        (description.at("descriptor").at("parameter_kind") !=
             m_descriptions.front().at("descriptor").at("parameter_kind") ||
         description.at("descriptor").at("unit") != m_descriptions.front().at("descriptor").at("unit")))
    {
        m_status->SetLabel(Display("파라미터 종류와 단위가 다른 자료는 같은 곡선 축에 겹칠 수 없습니다. 자료 / 정합 "
                                   "도구에서 변환 조건을 명시하거나 개별 결과를 확인하세요."));
        return false;
    }
    if (m_descriptions.size() >= 8)
    {
        m_status->SetLabel(Display("최대 8개입니다. 비교 목록에서 원본 하나를 제외한 뒤 추가하세요."));
        return false;
    }
    for (const auto& existing : m_descriptions)
    {
        if (ResultUi::Matches(description, existing) &&
            description.value("measurement_ref", Json(nullptr)) == existing.value("measurement_ref", Json(nullptr)))
        {
            m_status->SetLabel(Display("이미 같은 원본과 개정이 목록에 있습니다."));
            return false;
        }
    }
    m_descriptions.push_back(description);
    m_pages.emplace_back(nullptr);
    m_orders.emplace_back(nullptr);
    m_comparisons.emplace_back(nullptr);
    m_markerIndices.push_back(-1);
    if (m_descriptions.size() == 1)
    {
        m_row->Clear();
        m_column->Clear();
        const auto& descriptor = description.at("descriptor");
        for (std::size_t index = 0; index < descriptor.value("port_ids", Json::array()).size(); ++index)
        {
            const auto name = Display(ResultUi::PortName(descriptor, index));
            m_row->Append(name);
            m_column->Append(name);
        }
        if (m_row->GetCount() > 0)
        {
            m_row->SetSelection(0);
            m_column->SetSelection(0);
        }
    }
    RefreshRows();
    m_sources->SetItemState(static_cast<long>(m_descriptions.size() - 1), wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                            wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
    if (onChanged)
    {
        onChanged();
    }
    if (onPage)
    {
        onPage(m_descriptions.size() - 1, 0);
    }
    return true;
}
Json ResultCompareView::PortOrder(std::size_t index) const
{
    return index < m_orders.size() ? m_orders[index] : Json(nullptr);
}
int ResultCompareView::Row() const
{
    return std::max(0, m_row->GetSelection());
}
int ResultCompareView::Column() const
{
    return std::max(0, m_column->GetSelection());
}
int ResultCompareView::Selected() const
{
    return static_cast<int>(m_sources->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED));
}
void ResultCompareView::SetNotice(const std::string& message)
{
    m_status->SetLabel(Display(message));
    m_status->Wrap(std::max(FromDIP(240), GetClientSize().x - FromDIP(24)));
    Layout();
    FitInside();
}
void ResultCompareView::RefreshRows()
{
    const int selected = Selected();
    m_loading = true;
    m_sources->DeleteAllItems();
    for (std::size_t index = 0; index < m_descriptions.size(); ++index)
    {
        const auto& description = m_descriptions[index];
        const auto row = m_sources->InsertItem(static_cast<long>(index), Display(
            std::to_string(index + 1) + (index == 0 ? " 기준 / " : " / ") +
            ResultUi::Text(description.at("label")) + " / " + NetworkChart::SeriesStyleText(index)));
        m_sources->SetItemTextColour(row, NetworkChart::SeriesColour(index));
        m_sources->SetItem(
            row, 1,
            Display(ResultUi::Text(
                m_measurementMode && description.value("measurement_label", Json(nullptr)).is_string()
                    ? description.at("measurement_label")
                    : description.value("source_revision", Json::object()).value("label", Json(nullptr)))));
        m_sources->SetItem(row, 2,
                           Display(m_pages[index].is_object()
                                       ? std::to_string(m_pages[index].value("offset", 0) + 1) + "부터 " +
                                             std::to_string(m_pages[index].at("samples").size()) + "개"
                                       : "조회 전"));
        m_sources->SetItem(row, 3,
                           Display(index == 0                  ? "기준 원본"
                                   : m_orders[index].is_null() ? "자체 첫 채널 / 포트 대응 미지정"
                                   : m_comparisons[index].is_object()
                                       ? ResultUi::State(m_comparisons[index]
                                                             .value("math_comparability", Json::object())
                                                             .value("status", Json(nullptr)))
                                       : "명시 포트 대응 / 차이 조회 전"));
    }
    if (selected >= 0 && static_cast<std::size_t>(selected) < m_descriptions.size())
    {
        m_sources->SetItemState(selected, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
    }
    m_loading = false;
    Actions();
}
void ResultCompareView::Present()
{
    std::vector<Json> pages;
    std::vector<wxString> labels;
    double minimum = 0.0, maximum = 0.0;
    for (std::size_t index = 0; index < m_descriptions.size(); ++index)
    {
        pages.push_back(m_pages[index].is_object() ? m_pages[index]
                                                   : Json{{"samples", Json::array()}, {"parameter_type", "S"}});
        labels.push_back(
            Display(std::to_string(index + 1) + " / " + ResultUi::Text(m_descriptions[index].at("label"))));
        const auto& descriptor = m_descriptions[index].at("descriptor");
        if (descriptor.value("frequency_max_hz", Json(nullptr)).is_number())
        {
            maximum = std::max(maximum, descriptor.at("frequency_max_hz").get<double>());
        }
        if (descriptor.value("frequency_min_hz", Json(nullptr)).is_number())
        {
            minimum = std::min(minimum, descriptor.at("frequency_min_hz").get<double>());
        }
    }
    if (pages.empty())
    {
        m_chart->Clear();
        return;
    }
    m_chart->SetSeries(pages, labels);
    if (m_descriptions.front().at("descriptor").value("parameter_kind", "S") != "S" &&
        (m_metric->GetSelection() == 0 || m_metric->GetSelection() == 2))
    {
        m_metric->SetSelection(5);
    }
    const auto metric = static_cast<std::size_t>(m_metric->GetSelection());
    const auto unit = m_descriptions.front().at("descriptor").value("unit", std::string());
    m_chart->SetMetric(Metrics[metric], Display(Labels[metric] + (metric >= 3 && !unit.empty() ? " / " + unit : "")));
    m_chart->SetFrequencyUnit(StudioFrequency::ForRange(minimum, maximum).unit);
    m_chart->SetMarkers(m_markerIndices);
    Layout();
    FitInside();
}
void ResultCompareView::SetPage(std::size_t index, const Json& response)
{
    if (index >= m_descriptions.size() || !ResultUi::Matches(response, m_descriptions[index]))
    {
        return;
    }
    m_pages[index] = response.at("page");
    m_markerIndices[index] = -1;
    RefreshRows();
    Present();
}
void ResultCompareView::MapPorts()
{
    const int selected = Selected();
    if (selected <= 0)
    {
        return;
    }
    const auto index = static_cast<std::size_t>(selected);
    const auto leftSource = m_descriptions.front(), rightSource = m_descriptions[index];
    const auto left = leftSource.at("descriptor"), right = rightSource.at("descriptor");
    const int ports = static_cast<int>(left.value("port_ids", Json::array()).size());
    if (ports != static_cast<int>(right.value("port_ids", Json::array()).size()))
    {
        m_status->SetLabel(Display("포트 수가 달라 수학 차이를 계산할 수 없습니다. 개별 곡선은 유지합니다."));
        return;
    }
    wxArrayString names;
    for (int port = 0; port < ports; ++port)
    {
        names.Add(Display(ResultUi::PortName(right, static_cast<std::size_t>(port))));
    }
    Json order = Json::array();
    std::set<int> used;
    for (int port = 0; port < ports; ++port)
    {
        wxSingleChoiceDialog dialog(this,
                                    Display("기준 " + ResultUi::PortName(left, static_cast<std::size_t>(port)) +
                                            "에 대응하는 비교 원본 포트를 선택하세요."),
                                    Display("명시 포트 대응"), names);
        if (dialog.ShowModal() != wxID_OK)
        {
            return;
        }
        if (!m_available || index >= m_descriptions.size() || !MeasurementUi::SameRecord(leftSource, m_descriptions.front()) ||
            !MeasurementUi::SameRecord(rightSource, m_descriptions[index]))
        {
            return;
        }
        const int chosen = dialog.GetSelection();
        if (!used.insert(chosen).second)
        {
            wxMessageBox(Display("같은 포트를 중복 대응할 수 없습니다. 기존 대응은 유지합니다."), Display("포트 대응"),
                         wxOK | wxICON_INFORMATION, this);
            return;
        }
        order.push_back(chosen);
    }
    m_orders[index] = order;
    m_comparisons[index] = nullptr;
    m_pages[index] = nullptr;
    m_markerIndices[index] = -1;
    m_differences->DeleteAllItems();
    if (onChanged)
    {
        onChanged();
    }
    RefreshRows();
    Present();
    if (onPage)
    {
        onPage(index, 0);
    }
    if (onCompare)
    {
        onCompare(index);
    }
}
void ResultCompareView::SetComparison(std::size_t index, const Json& response)
{
    if (index == 0 || index >= m_descriptions.size())
    {
        return;
    }
    m_comparisons[index] = response;
    RefreshRows();
    if (Selected() != static_cast<int>(index))
    {
        return;
    }
    m_status->SetLabel(Display(
        "수학: " +
        ResultUi::State(response.value("math_comparability", Json::object()).value("status", Json(nullptr))) +
        " / 물리: " +
        ResultUi::State(response.value("physical_comparability", Json::object()).value("status", Json(nullptr))) +
        " / 차이가 설계 개선이나 합격을 뜻하지 않습니다.\n차이 표본 " +
        std::to_string(response.value("offset", 0) + (response.value("points", Json::array()).empty() ? 0 : 1)) + "~" +
        std::to_string(response.value("offset", 0) + response.value("points", Json::array()).size()) + " / " +
        std::to_string(response.value("total", 0))));
    m_differences->DeleteAllItems();
    const auto points = response.value("points", Json::array());
    const auto scale = StudioFrequency::ForDescriptor(m_descriptions.front().at("descriptor"));
    m_differences->SetColumnWidth(0, FromDIP(150));
    for (const auto& point : points)
    {
        const auto row = m_differences->InsertItem(
            m_differences->GetItemCount(),
            Display(StudioFrequency::Value(point.value("frequency_hz", Json(nullptr)), scale) + " " + scale.unit));
        m_differences->SetItem(row, 1, Display(ResultUi::Complex(point.value("difference_ri", Json(nullptr)))));
        m_differences->SetItem(row, 2,
                               Display(ResultUi::State(point.value("status", Json(nullptr))) + " / " +
                                       ResultUi::Text(point.value("reason", Json(nullptr)))));
    }
    if (onConditions)
    {
        onConditions(response);
    }
}
void ResultCompareView::SetMarker(std::size_t index, const Json& response)
{
    if (index >= m_descriptions.size() || !ResultUi::Matches(response, m_descriptions[index]))
    {
        return;
    }
    if (m_markers->GetItemCount() != static_cast<long>(m_descriptions.size()))
    {
        return;
    }
    const auto point = response.value("point", Json(nullptr));
    const auto row = static_cast<long>(index);
    if (!response.value("found", false) || !point.is_object())
    {
        m_markerIndices[index] = -1;
        m_markers->SetItem(row, 3, Display(ResultUi::State(response.value("reason", Json("frequency_missing")))));
    }
    else
    {
        m_markerIndices[index] = point.value("index", -1);
        m_markers->SetItem(row, 1, Display(StudioFrequency::WithUnit(point.value("frequency_hz", Json(nullptr)))));
        m_markers->SetItem(row, 2,
                           Display(ResultUi::Complex(
                               Json::array({point.value("real", Json(nullptr)), point.value("imag", Json(nullptr))}))));
        m_markers->SetItem(row, 3,
                           Display(ResultUi::State(point.value("status", Json(nullptr))) + " / " +
                                   ResultUi::State(point.value("origin", Json(nullptr)))));
    }
    m_chart->SetMarkers(m_markerIndices);
}
void ResultCompareView::ChannelChanged()
{
    for (std::size_t index = 0; index < m_pages.size(); ++index)
    {
        m_pages[index] = nullptr;
        m_comparisons[index] = nullptr;
        m_markerIndices[index] = -1;
    }
    m_markers->DeleteAllItems();
    m_differences->DeleteAllItems();
    if (onChanged)
    {
        onChanged();
    }
    RefreshRows();
    Present();
    for (std::size_t index = 0; index < m_descriptions.size(); ++index)
    {
        if (onPage)
        {
            onPage(index, 0);
        }
    }
}
void ResultCompareView::Remove()
{
    const int selected = Selected();
    if (selected < 0)
    {
        return;
    }
    const auto index = static_cast<std::size_t>(selected);
    m_descriptions.erase(m_descriptions.begin() + selected);
    m_pages.erase(m_pages.begin() + selected);
    m_orders.erase(m_orders.begin() + selected);
    m_comparisons.erase(m_comparisons.begin() + selected);
    m_markerIndices.erase(m_markerIndices.begin() + selected);
    if (index == 0)
    {
        const auto remaining = m_descriptions;
        Clear();
        for (const auto& description : remaining)
        {
            Add(description);
        }
        return;
    }
    if (onChanged)
    {
        onChanged();
    }
    m_markers->DeleteAllItems();
    m_differences->DeleteAllItems();
    RefreshRows();
    Present();
}
void ResultCompareView::Actions()
{
    const int selected = Selected();
    const bool valid = selected >= 0 && static_cast<std::size_t>(selected) < m_pages.size();
    m_add->Enable(m_available && m_descriptions.size() < 8);
    m_remove->Enable(m_available && valid);
    m_map->Enable(m_available && selected > 0);
    m_compare->Enable(m_available && selected > 0 && m_orders[static_cast<std::size_t>(selected)].is_array());
    m_previous->Enable(m_available && valid && m_pages[static_cast<std::size_t>(selected)].is_object() &&
                       m_pages[static_cast<std::size_t>(selected)].value("offset", 0) > 0);
    m_next->Enable(m_available && valid && m_pages[static_cast<std::size_t>(selected)].is_object() &&
                   !m_pages[static_cast<std::size_t>(selected)].value("next_offset", Json(nullptr)).is_null());
    m_row->Enable(m_available && !m_descriptions.empty());
    m_column->Enable(m_available && !m_descriptions.empty());
    const bool compared = valid && m_comparisons[static_cast<std::size_t>(selected)].is_object();
    m_differencePrevious->Enable(m_available && compared &&
                                 m_comparisons[static_cast<std::size_t>(selected)].value("offset", 0) > 0);
    m_differenceNext->Enable(
        m_available && compared &&
        !m_comparisons[static_cast<std::size_t>(selected)].value("next_offset", Json(nullptr)).is_null());
    if (onActionsChanged)
    {
        onActionsChanged();
    }
}
void ResultCompareView::SetAvailable(bool available)
{
    m_available = available;
    Actions();
}
void ResultCompareView::InspectSelection()
{
    const int selected = Selected();
    if (selected >= 0 && static_cast<std::size_t>(selected) < m_descriptions.size())
    {
        const auto index = static_cast<std::size_t>(selected);
        if (m_comparisons[index].is_object())
        {
            SetComparison(index, m_comparisons[index]);
        }
        else if (onInspect)
        {
            onInspect(m_descriptions[index]);
        }
    }
    else if (onInspect)
    {
        onInspect(nullptr);
    }
}
void ResultCompareView::Clear()
{
    m_descriptions.clear();
    m_pages.clear();
    m_orders.clear();
    m_comparisons.clear();
    m_markerIndices.clear();
    m_row->Clear();
    m_column->Clear();
    m_sources->DeleteAllItems();
    m_markers->DeleteAllItems();
    m_differences->DeleteAllItems();
    m_chart->Clear();
    m_status->SetLabel(Display("왼쪽에서 원본을 선택한 뒤 비교 목록에 추가하세요. 현재 설계는 변경하지 않습니다."));
    if (onChanged)
    {
        onChanged();
    }
    Actions();
}
