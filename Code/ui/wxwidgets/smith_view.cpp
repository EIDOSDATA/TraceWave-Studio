/** @file @brief 입력 임피던스와 원래 행렬 원소를 구분하여 서비스 투영을 표시한다. */
#include "smith_view.h"
#include "smith_chart.h"
#include "result_presentation.h"
#include "frequency_display.h"
#include "studio_theme.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/clipbrd.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/stattext.h>
#include <wx/wrapsizer.h>
#include <wx/sizer.h>
#include <algorithm>

SmithView::SmithView(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    SetScrollRate(0, FromDIP(16));
    SetName("result.smith");
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_heading = new wxStaticText(this, wxID_ANY, Display("Smith 차트"));
    m_heading->SetWindowStyleFlag(m_heading->GetWindowStyleFlag() | wxST_ELLIPSIZE_END);
    m_heading->SetMinSize(wxSize(1, -1));
    StudioTheme::Title(*m_heading);
    layout->Add(m_heading, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* controls = new wxWrapSizer(wxHORIZONTAL);
    m_port = new wxChoice(this, wxID_ANY);
    m_port->SetName("result.smith.port");
    m_chartKind = new wxChoice(this, wxID_ANY);
    m_chartKind->Append(Display("임피던스 격자"));
    m_chartKind->Append(Display("어드미턴스 격자"));
    m_chartKind->SetSelection(0);
    m_source = new wxButton(this, wxID_ANY, Display("다른 결과 선택"));
    StudioTheme::Button(*m_source);
    controls->Add(new wxStaticText(this, wxID_ANY, Display("반사 포트")), 0, wxALL | wxALIGN_CENTER_VERTICAL,
                  FromDIP(4));
    controls->Add(m_port, 0, wxALL, FromDIP(4));
    controls->Add(m_chartKind, 0, wxALL, FromDIP(4));
    controls->Add(m_source, 0, wxALL, FromDIP(4));
    layout->Add(controls, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_notice = new wxStaticText(
        this, wxID_ANY, Display("실제 원본 결과를 선택하세요. 이 화면은 새 계산이나 Z0 변환을 수행하지 않습니다."));
    StudioTheme::BindSecondary(*m_notice);
    layout->Add(m_notice, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* content = new wxBoxSizer(wxHORIZONTAL);
    m_chart = new SmithChart(this);
    content->Add(m_chart, 3, wxEXPAND | wxRIGHT, FromDIP(12));
    auto* values = new wxBoxSizer(wxVERTICAL);
    m_markerValues =
        new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(360, 310)), wxLC_REPORT | wxLC_HRULES);
    m_markerValues->SetMinSize(FromDIP(wxSize(360, 310)));
    m_markerValues->SetName("result.smith.marker-values");
    StudioTheme::Table(*m_markerValues);
    m_markerValues->AppendColumn(Display("항목"), wxLIST_FORMAT_LEFT, FromDIP(130));
    m_markerValues->AppendColumn(Display("M1 값"), wxLIST_FORMAT_LEFT, FromDIP(210));
    m_markerValues->Bind(wxEVT_SIZE, [this](wxSizeEvent& event)
    {
        const int available = m_markerValues->GetClientSize().x - m_markerValues->GetColumnWidth(0) - FromDIP(4);
        m_markerValues->SetColumnWidth(1, std::max(FromDIP(170), available));
        event.Skip();
    });
    values->Add(m_markerValues, 1, wxEXPAND);
    auto* markers = new wxWrapSizer(wxHORIZONTAL);
    m_markerPrevious = new wxButton(this, wxID_ANY, Display("이전 표본"));
    m_markerNext = new wxButton(this, wxID_ANY, Display("다음 표본"));
    markers->Add(m_markerPrevious, 0, wxALL, FromDIP(4));
    markers->Add(m_markerNext, 0, wxALL, FromDIP(4));
    auto* copyMarker = new wxButton(this, wxID_ANY, Display("표본 원문 복사"));
    copyMarker->SetToolTip(Display("선택한 표본의 주파수(Hz)와 복소값을 원래 자릿수로 복사합니다."));
    markers->Add(copyMarker, 0, wxALL, FromDIP(4));
    copyMarker->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        if (m_response.is_object())
        {
            for (const auto& point : m_response.at("points"))
            {
                if (point.at("index") == m_markerIndex && wxTheClipboard->Open())
                {
                    wxTheClipboard->SetData(new wxTextDataObject(Display(point.dump(2))));
                    wxTheClipboard->Close();
                    break;
                }
            }
        }
    });
    values->Add(markers, 0, wxEXPAND);
    auto* notice = new wxStaticText(this, wxID_ANY,
                                    Display("Z0 변경은 명시적 파생 변환입니다. 원본 자료와 과거 조건은 유지합니다."));
    notice->Wrap(FromDIP(290));
    StudioTheme::BindSecondary(*notice);
    values->Add(notice, 0, wxEXPAND | wxALL, FromDIP(8));
    content->Add(values, 2, wxEXPAND);
    layout->Add(content, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* paging = new wxWrapSizer(wxHORIZONTAL);
    m_previous = new wxButton(this, wxID_ANY, Display("이전 201개"));
    m_next = new wxButton(this, wxID_ANY, Display("다음 201개"));
    paging->Add(m_previous, 0, wxALL, FromDIP(4));
    paging->Add(m_next, 0, wxALL, FromDIP(4));
    layout->Add(paging, 0, wxEXPAND | wxALL, FromDIP(8));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    SetSizer(layout);
    m_chart->onMarker = [this](int index)
    {
        SelectMarker(index);
    };
    for (auto* choice : {m_port, m_chartKind})
    {
        choice->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         Request(0);
                     });
    }
    m_source->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       if (onSelectSource)
                       {
                           onSelectSource();
                       }
                   });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         Request(std::max(0, m_response.value("offset", 0) - 201));
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (m_response.value("next_offset", Json(nullptr)).is_number_integer())
                     {
                         Request(m_response.at("next_offset").get<int>());
                     }
                 });
    m_markerPrevious->Bind(wxEVT_BUTTON,
                           [this](wxCommandEvent&)
                           {
                               SelectMarker(m_markerIndex - 1);
                           });
    m_markerNext->Bind(wxEVT_BUTTON,
                       [this](wxCommandEvent&)
                       {
                           SelectMarker(m_markerIndex + 1);
                       });
    Bind(wxEVT_SIZE,
         [this, content](wxSizeEvent& event)
         {
             const int width = std::max(220, GetClientSize().x - FromDIP(28));
             m_notice->Wrap(width);
             m_status->Wrap(width);
             content->SetOrientation(GetClientSize().x < FromDIP(750) ? wxVERTICAL : wxHORIZONTAL);
             Layout();
             FitInside();
             event.Skip();
         });
    Clear("왼쪽에서 실제 결과를 선택하세요.");
}

int SmithView::Port() const
{
    return std::max(0, m_port->GetSelection());
}

std::string SmithView::Chart() const
{
    return m_chartKind->GetSelection() == 1 ? "admittance" : "impedance";
}

void SmithView::SetDescription(const Json& description)
{
    m_description = description;
    m_heading->SetLabel(Display("Smith 차트"));
    m_heading->SetToolTip(Display(ResultUi::Text(description.value("label", Json(nullptr)))));
    m_response = nullptr;
    m_port->Clear();
    const auto descriptor = description.value("descriptor", Json::object());
    for (std::size_t index = 0; index < descriptor.value("port_ids", Json::array()).size(); ++index)
    {
        m_port->Append(Display(ResultUi::PortName(descriptor, index)));
    }
    if (m_port->GetCount())
    {
        m_port->SetSelection(0);
    }
    m_notice->SetLabel(
        Display("2포트의 입력 임피던스는 다른 포트의 기록 Z0 정합 종단 조건입니다. Z 행렬의 Zii가 아닙니다."));
    m_chart->Clear("선택한 원본의 실제 반사 표본을 읽어야 합니다.");
    m_markerValues->DeleteAllItems();
    UpdateActions();
    Layout();
}

void SmithView::Request(int offset)
{
    if (m_busy || m_description.is_null() || !onRequest)
    {
        return;
    }
    m_response = nullptr;
    m_markerValues->DeleteAllItems();
    m_chart->Clear("선택한 포트와 격자의 실제 표본을 읽고 있습니다.");
    onRequest(Port(), Chart(), offset);
}

void SmithView::SetPage(const Json& response)
{
    if (!ResultUi::Matches(response, m_description))
    {
        throw std::runtime_error("Smith 응답의 원본 또는 pin이 선택과 다릅니다.");
    }
    m_response = response;
    m_busy = false;
    m_chart->SetPage(response);
    const auto points = response.value("points", Json::array());
    m_status->SetLabel(Display("실제 표본 " + std::to_string(response.value("offset", 0) + (points.empty() ? 0 : 1)) +
                               "~" + std::to_string(response.value("offset", 0) + points.size()) + ", " +
                               std::to_string(response.value("total", 0)) + " (보간 및 자동 재정규화 없음)"));
    SelectMarker(points.empty() ? -1 : points.front().value("index", -1));
    UpdateActions();
    Layout();
}

void SmithView::SelectMarker(int index)
{
    const auto points = m_response.is_object() ? m_response.value("points", Json::array()) : Json::array();
    const auto point = std::find_if(points.begin(), points.end(),
                                    [index](const Json& item)
                                    {
                                        return item.value("index", -1) == index;
                                    });
    if (point == points.end())
    {
        return;
    }
    m_markerIndex = index;
    m_chart->SetMarker(index);
    m_markerValues->DeleteAllItems();
    const auto row = [this](const std::string& name, const std::string& value)
    {
        const long index = m_markerValues->InsertItem(m_markerValues->GetItemCount(), Display(name));
        m_markerValues->SetItem(index, 1, Display(value));
    };
    const auto scale = StudioFrequency::ForDescriptor(m_description.at("descriptor"));
    row("마커와 표본", "마커 M1: " + std::to_string(index + 1));
    row("주파수", StudioFrequency::Value(point->value("frequency_hz", Json(nullptr)), scale, 8) + " " + scale.unit);
    row("Gamma", ResultUi::Complex(point->value("gamma_ri", Json(nullptr))));
    row("기준 Z0", ResultUi::Complex(point->value("z0_ohm", Json(nullptr))) + " ohm");
    row("입력 임피던스", ResultUi::Complex(point->value("input_impedance_ohm_ri", Json(nullptr)),
                                           point->value("impedance_state", "missing")) +
                             " ohm");
    row("정규화 z", ResultUi::Complex(point->value("normalized_impedance_ri", Json(nullptr)),
                                      point->value("normalized_impedance_state", "missing")));
    row("정규화 y", ResultUi::Complex(point->value("normalized_admittance_ri", Json(nullptr)),
                                      point->value("normalized_admittance_state", "missing")));
    row("입력 어드미턴스", ResultUi::Complex(point->value("input_admittance_siemens_ri", Json(nullptr)),
                                             point->value("admittance_state", "missing")) +
                               " S");
    row("표본 상태", ResultUi::State(point->value("status", Json(nullptr))));
    row("위치", ResultUi::State(point->value("passivity_region", Json(nullptr))));
    row("출처", ResultUi::State(point->value("origin", Json(nullptr))));
    if (point->contains("reason") && !point->at("reason").is_null())
    {
        row("이유", ResultUi::Text(point->at("reason")));
    }
    for (const auto& reason : point->value("reasons", Json::array()))
    {
        row("표시 조건", ResultUi::Text(reason));
    }
    UpdateActions();
}

void SmithView::SetBusy(bool busy)
{
    m_busy = busy;
    UpdateActions();
}

void SmithView::Clear(const std::string& reason)
{
    m_heading->SetLabel(Display("Smith 차트"));
    m_heading->SetToolTip(wxEmptyString);
    m_busy = false;
    m_description = nullptr;
    m_response = nullptr;
    m_markerIndex = -1;
    m_port->Clear();
    m_chart->Clear(reason);
    m_markerValues->DeleteAllItems();
    m_status->SetLabel(Display(reason));
    UpdateActions();
}

void SmithView::UpdateActions()
{
    const bool selected = !m_description.is_null() && !m_busy;
    m_port->Enable(selected);
    m_chartKind->Enable(selected);
    m_source->Enable(!m_busy);
    m_previous->Enable(selected && m_response.is_object() && m_response.value("offset", 0) > 0);
    m_next->Enable(selected && m_response.is_object() &&
                   m_response.value("next_offset", Json(nullptr)).is_number_integer());
    const auto points = m_response.is_object() ? m_response.value("points", Json::array()) : Json::array();
    m_markerPrevious->Enable(selected && !points.empty() && m_markerIndex > points.front().value("index", -1));
    m_markerNext->Enable(selected && !points.empty() && m_markerIndex < points.back().value("index", -1));
}
