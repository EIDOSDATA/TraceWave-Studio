/** @file @brief 네트워크 표시 단위를 원본 SI 및 조회 조건과 분리한다. */
#include "result_network_view.h"
#include "result_presentation.h"
#include "network_chart.h"
#include "frequency_display.h"
#include "studio_theme.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/wrapsizer.h>
#include <array>
namespace
{
const std::array<std::string, 5> Units{"auto", "Hz", "kHz", "MHz", "GHz"};
const std::array<std::string, 9> Metrics{"magnitude_db", "phase_deg", "vswr", "real", "imag", "magnitude",
                                         "group_delay_ns", "sigma_max", "reciprocity_residual"};
const std::array<std::string, 9> Labels{"크기 (dB)", "위상 (deg)", "VSWR", "실수부", "허수부", "크기",
                                        "군지연 (ns)", "최대 특이값", "상호성 잔차"};
}
ResultNetworkView::ResultNetworkView(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    SetScrollRate(0, FromDIP(16));
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_heading = new wxStaticText(this, wxID_ANY, Display("네트워크 결과"));
    m_heading->SetWindowStyleFlag(m_heading->GetWindowStyleFlag() | wxST_ELLIPSIZE_END);
    m_heading->SetMinSize(wxSize(1, -1));
    StudioTheme::Title(*m_heading);
    layout->Add(m_heading, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* tools = new wxWrapSizer(wxHORIZONTAL);
    m_row = new wxChoice(this, wxID_ANY);
    m_column = new wxChoice(this, wxID_ANY);
    m_row->SetName(Display("응답 포트"));
    m_column->SetName(Display("입력 포트"));
    m_row->SetToolTip(Display("S 행렬에서 응답을 읽는 포트입니다."));
    m_column->SetToolTip(Display("S 행렬에서 신호를 넣는 포트입니다."));
    m_metric = new wxChoice(this, wxID_ANY);
    m_metric->SetName(Display("표시 지표"));
    m_metric->SetToolTip(Display("군지연은 원본의 시간 위상 규약과 인접 S 표본을 사용합니다. 표본 사이 위상 변화가 180도를 넘으면 복원할 수 없습니다."));
    m_frequencyUnit = new wxChoice(this, wxID_ANY);
    m_frequencyUnit->SetName(Display("주파수 표시 단위"));
    for (const auto& label : Labels)
    {
        m_metric->Append(Display(label));
    }
    for (const auto& unit : Units)
    {
        m_frequencyUnit->Append(Display(unit == "auto" ? "주파수 자동" : unit));
    }
    m_metric->SetSelection(0);
    m_frequencyUnit->SetSelection(0);
    auto* source = new wxButton(this, wxID_ANY, Display("원본 선택"));
    auto* library = new wxButton(this, wxID_ANY, Display("자료 및 정합 도구"));
    auto* exportResult = new wxButton(this, wxID_ANY, Display("원본 결과 내보내기"));
    for (auto* port : {m_row, m_column})
    {
        auto* field = new wxBoxSizer(wxHORIZONTAL);
        field->Add(new wxStaticText(this, wxID_ANY, port->GetName()), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(4));
        field->Add(port, 0, wxALIGN_CENTER_VERTICAL);
        tools->Add(field, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    }
    for (auto* control : std::array<wxWindow*, 5>{m_metric, m_frequencyUnit, source, library, exportResult})
    {
        tools->Add(control, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    }
    layout->Add(tools, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(4));
    m_notice =
        new wxStaticText(this, wxID_ANY, Display("왼쪽에서 보존된 원본을 선택하세요. 현재 설계는 변경하지 않습니다."));
    layout->Add(m_notice, 0, wxEXPAND | wxALL, FromDIP(8));
    m_chart = new NetworkChart(this);
    m_chart->SetMinSize(FromDIP(wxSize(360, 250)));
    layout->Add(m_chart, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_marker = new wxStaticText(this, wxID_ANY, Display("M1: 실제 곡선 점 또는 표본 행을 선택하세요."));
    layout->Add(m_marker, 0, wxEXPAND | wxALL, FromDIP(8));
    m_samples =
        new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 128)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_samples->SetMinSize(FromDIP(wxSize(-1, 155)));
    StudioTheme::Table(*m_samples);
    m_samples->SetName(Display("선택 채널의 주파수 표본"));
    m_samples->SetToolTip(Display("행을 선택하면 그래프에 해당 표본을 표시합니다. 우클릭으로 표의 전체 행을 읽을 수 있습니다."));
    layout->Add(m_samples, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    auto* paging = new wxBoxSizer(wxHORIZONTAL);
    m_previous = new wxButton(this, wxID_ANY, Display("이전 201표본"));
    m_next = new wxButton(this, wxID_ANY, Display("다음 201표본"));
    paging->Add(m_previous, 0, wxALL, FromDIP(4));
    paging->Add(m_next, 0, wxALL, FromDIP(4));
    layout->Add(paging, 0, wxALL, FromDIP(4));
    SetSizer(layout);
    m_row->Bind(wxEVT_CHOICE,
                [this](wxCommandEvent&)
                {
                    Request(0);
                });
    m_column->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       Request(0);
                   });
    m_metric->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       Present();
                   });
    m_frequencyUnit->Bind(wxEVT_CHOICE,
                          [this](wxCommandEvent&)
                          {
                              Present();
                          });
    source->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (onSelectSource)
                     {
                         onSelectSource();
                     }
                 });
    library->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      if (onOpenTools)
                      {
                          onOpenTools();
                      }
                  });
    exportResult->Bind(wxEVT_BUTTON,
                       [this](wxCommandEvent&)
                       {
                           if (onExport)
                           {
                               onExport();
                           }
                       });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         Request(std::max(0, m_response.at("page").value("offset", 0) - 201));
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     Request(m_response.at("page").at("next_offset").get<int>());
                 });
    m_samples->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [this](wxListEvent& event)
                    {
                        if (!m_loading && m_response.is_object())
                        {
                            Marker(m_response.at("page")
                                       .at("samples")
                                       .at(static_cast<std::size_t>(event.GetIndex()))
                                       .value("index", -1));
                        }
                    });
    m_chart->onMarker = [this](std::size_t, int index, double)
    {
        Marker(index);
    };
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Layout();
             FitInside();
             event.Skip();
         });
    Clear("왼쪽에서 원본을 선택하세요.");
}
void ResultNetworkView::SetDescription(const Json& description)
{
    m_description = description;
    m_response = nullptr;
    m_markerIndex = -1;
    m_heading->SetLabel(Display("네트워크"));
    m_heading->SetToolTip(Display(ResultUi::Text(description.value("label", Json(nullptr)))));
    m_row->Clear();
    m_column->Clear();
    const auto& descriptor = description.at("descriptor");
    const int ports = static_cast<int>(descriptor.value("port_ids", Json::array()).size());
    for (int index = 0; index < ports; ++index)
    {
        const auto name = Display(ResultUi::PortName(descriptor, static_cast<std::size_t>(index)));
        m_row->Append(name);
        m_column->Append(name);
    }
    if (ports > 0)
    {
        m_row->SetSelection(0);
        m_column->SetSelection(0);
    }
    m_notice->SetLabel(Display(description.value("is_current_design", false)
                                   ? "현재 설계 개정의 보존 자료입니다."
                                   : "과거 원본의 결과입니다. 현재 설계를 덮어쓰지 않습니다."));
    m_samples->DeleteAllItems();
    m_chart->Clear();
    m_marker->SetLabel(Display("M1: 실제 곡선 점 또는 표본 행을 선택하세요."));
    SetBusy(false);
}
void ResultNetworkView::SetPage(const Json& response)
{
    if (!ResultUi::Matches(response, m_description))
    {
        return;
    }
    m_response = response;
    m_markerIndex = -1;
    Present();
    SetBusy(false);
}
void ResultNetworkView::Present()
{
    if (!m_response.is_object())
    {
        return;
    }
    m_loading = true;
    const auto& page = m_response.at("page");
    const auto scale = StudioFrequency::ForDescriptor(
        m_description.at("descriptor"), Units.at(static_cast<std::size_t>(m_frequencyUnit->GetSelection())));
    if (page.value("parameter_kind", "S") != "S" && (m_metric->GetSelection() == 0 || m_metric->GetSelection() == 2))
    {
        m_metric->SetSelection(5);
    }
    const auto metric = static_cast<std::size_t>(m_metric->GetSelection());
    const auto title = Display(ResultUi::Text(m_description.at("label")));
    m_chart->SetToolTip(title);
    m_chart->SetPage(page, title.length() > 38 ? title.Left(38) + "..." : title);
    const auto unit = page.value("unit", std::string());
    m_chart->SetMetric(Metrics.at(metric),
                       Display(Labels.at(metric) + (metric >= 3 && metric <= 5 && !unit.empty() ? " (" + unit + ")" : "")));
    m_chart->SetFrequencyUnit(scale.unit);
    m_samples->ClearAll();
    const bool diagnostic = metric >= 6;
    const std::array<std::string, 8> labels{
        "표본", "주파수 (" + scale.unit + ")", "실수부", "허수부", "크기 (dB)", "위상 (deg)",
        diagnostic ? Labels.at(metric) : "VSWR", "상태와 출처"};
    for (std::size_t index = 0; index < labels.size(); ++index)
    {
        static constexpr std::array<int, 8> widths{48, 116, 90, 90, 95, 96, 90, 140};
        m_samples->InsertColumn(static_cast<long>(index), Display(labels[index]),
                                index > 0 && index < 7 ? wxLIST_FORMAT_RIGHT : wxLIST_FORMAT_LEFT,
                                FromDIP(widths[index]));
    }
    for (const auto& sample : page.at("samples"))
    {
        const long row =
            m_samples->InsertItem(m_samples->GetItemCount(), Display(std::to_string(sample.value("index", 0) + 1)));
        m_samples->SetItem(row, 1, Display(StudioFrequency::Value(sample.value("frequency_hz", Json(nullptr)), scale, 7)));
        for (std::size_t index = 0; index < 5; ++index)
        {
            m_samples->SetItem(
                row, static_cast<int>(index + 2),
                Display(ResultUi::SampleValue(
                    sample, std::array<std::string, 5>{"real", "imag", "magnitude_db", "phase_deg",
                                                      diagnostic ? Metrics.at(metric) : "vswr"}[index])));
        }
        m_samples->SetItem(row, 7,
                           Display(ResultUi::State(sample.value("status", Json(nullptr))) + ", " +
                                   ResultUi::State(sample.value("origin", Json(nullptr)))));
    }
    m_loading = false;
    if (m_markerIndex >= 0)
    {
        Marker(m_markerIndex);
    }
    else
    {
        m_marker->SetLabel(Display("M1: 실제 곡선 점 또는 표본 행을 선택하세요."));
    }
    Layout();
    FitInside();
}
void ResultNetworkView::Marker(int index)
{
    if (!m_response.is_object())
    {
        return;
    }
    const auto scale = StudioFrequency::ForDescriptor(
        m_description.at("descriptor"), Units.at(static_cast<std::size_t>(m_frequencyUnit->GetSelection())));
    for (const auto& sample : m_response.at("page").at("samples"))
    {
        if (sample.value("index", -1) != index)
        {
            continue;
        }
        m_markerIndex = index;
        m_chart->SetMarker(index);
        m_marker->SetLabel(Display(
            "마커 M1: " + StudioFrequency::Value(sample.value("frequency_hz", Json(nullptr)), scale) + " " + scale.unit +
            ", " + ResultUi::SampleValue(sample, Metrics.at(static_cast<std::size_t>(m_metric->GetSelection()))) +
            ", " + ResultUi::State(sample.value("status", Json(nullptr)))));
        return;
    }
}
void ResultNetworkView::Request(int offset)
{
    if (m_busy || !m_description.is_object() || m_row->GetSelection() < 0 || m_column->GetSelection() < 0)
    {
        return;
    }
    m_response = nullptr;
    m_markerIndex = -1;
    m_samples->DeleteAllItems();
    m_chart->Clear();
    m_marker->SetLabel(Display("선택한 채널의 실제 표본 조회 중"));
    SetBusy(true);
    if (onRequest)
    {
        onRequest(m_row->GetSelection(), m_column->GetSelection(), offset);
    }
}
void ResultNetworkView::SetBusy(bool busy)
{
    m_busy = busy;
    const bool available = m_description.is_object() && !busy;
    m_row->Enable(available);
    m_column->Enable(available);
    const bool hasPage = available && m_response.is_object();
    const bool previous = hasPage && m_response.at("page").value("offset", 0) > 0;
    const bool next = hasPage && !m_response.at("page").value("next_offset", Json(nullptr)).is_null();
    m_previous->Enable(previous);
    m_next->Enable(next);
    m_previous->Show(previous || next);
    m_next->Show(previous || next);
    m_chart->Show(hasPage);
    m_samples->Show(hasPage);
    m_marker->Show(hasPage || busy);
    Layout();
    FitInside();
}
void ResultNetworkView::Clear(const std::string& message)
{
    m_heading->SetLabel(Display("네트워크"));
    m_heading->SetToolTip(wxEmptyString);
    m_description = nullptr;
    m_response = nullptr;
    m_markerIndex = -1;
    m_chart->Clear();
    m_samples->DeleteAllItems();
    m_notice->SetLabel(Display(message));
    m_marker->SetLabel(Display("M1: 원본 선택 후 실제 표본을 표시합니다."));
    SetBusy(false);
}
