/** @file @brief 실제 기록 성분과 유한 단면 요청을 화면 표시 상태로 관리한다. */
#include "field_result_view.h"
#include "field_slice_canvas.h"
#include "frequency_display.h"
#include "result_presentation.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <algorithm>
#include <array>
#include <vector>

namespace
{
wxString Display(const std::string& text)
{
    return wxString::FromUTF8(text.data(), text.size());
}

/** @brief 코드 식별자와 별개로 native 입력의 접근성 이름을 붙인다. */
wxStaticText* Label(wxWindow* parent, const std::string& text)
{
    auto* value = new wxStaticText(parent, wxID_ANY, Display(text));
    StudioTheme::Heading(*value);
    return value;
}
}

FieldResultView::FieldResultView(wxWindow* parent) : wxPanel(parent)
{
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* titleRow = new wxBoxSizer(wxHORIZONTAL);
    auto* title = Label(this, "기록 필드 / 실제 단면");
    StudioTheme::Title(*title);
    titleRow->Add(title, 1, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(12));
    m_load = new wxButton(this, wxID_ANY, Display("단면 조회"));
    StudioTheme::Button(*m_load, true);
    titleRow->Add(m_load, 0, wxALIGN_CENTER_VERTICAL);
    layout->Add(titleRow, 0, wxALL | wxEXPAND, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    StudioTheme::BindSecondary(*m_status);
    layout->Add(m_status, 0, wxLEFT | wxRIGHT | wxBOTTOM | wxEXPAND, FromDIP(12));
    auto* body = new wxBoxSizer(wxHORIZONTAL);
    auto* center = new wxBoxSizer(wxVERTICAL);
    m_canvas = new FieldSliceCanvas(this);
    center->Add(m_canvas, 1, wxEXPAND);
    auto* markerRow = new wxBoxSizer(wxHORIZONTAL);
    markerRow->Add(Label(this, "표시 표본 번호"), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(8));
    m_point = new wxSpinCtrl(this, wxID_ANY);
    m_point->SetRange(0, 0);
    m_point->SetName(Display("필드의 실제 표시 표본 번호"));
    markerRow->Add(m_point, 0);
    center->Add(markerRow, 0, wxALL, FromDIP(8));
    m_marker = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 100)), wxTE_MULTILINE | wxTE_READONLY);
    m_marker->SetName(Display("선택 필드 표본의 실제 좌표와 복소값"));
    center->Add(m_marker, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    body->Add(center, 1, wxEXPAND);
    m_controls = new wxScrolledWindow(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(270, -1)));
    m_controls->SetMinSize(FromDIP(wxSize(260, -1)));
    m_controls->SetScrollRate(0, FromDIP(16));
    StudioTheme::BindSurface(*m_controls);
    auto* fields = new wxBoxSizer(wxVERTICAL);
    const auto choice = [&](const std::string& name)
    {
        fields->Add(Label(m_controls, name), 0, wxTOP | wxBOTTOM, FromDIP(6));
        auto* control = new wxChoice(m_controls, wxID_ANY);
        control->SetName(Display(name));
        fields->Add(control, 0, wxEXPAND | wxBOTTOM, FromDIP(6));
        return control;
    };
    m_monitor = choice("기록 종류");
    m_component = choice("실제 성분");
    m_frequency = choice("기록 주파수");
    m_normal = choice("단면에 수직인 축");
    for (const auto* axis : {"x", "y", "z"})
    {
        m_normal->Append(Display(axis));
    }
    m_normal->SetSelection(2);
    fields->Add(Label(m_controls, "단면 격자 인덱스"), 0, wxTOP | wxBOTTOM, FromDIP(6));
    m_planeIndex = new wxSpinCtrl(m_controls, wxID_ANY);
    m_planeIndex->SetName(Display("필드 단면 격자 인덱스"));
    fields->Add(m_planeIndex, 0, wxEXPAND);
    m_position = new wxStaticText(m_controls, wxID_ANY, wxEmptyString);
    fields->Add(m_position, 0, wxTOP | wxBOTTOM | wxEXPAND, FromDIP(6));
    const auto range = [&](const std::string& name, wxStaticText*& label, wxSpinCtrl*& start, wxSpinCtrl*& count)
    {
        label = Label(m_controls, name);
        fields->Add(label, 0, wxTOP | wxBOTTOM, FromDIP(6));
        auto* line = new wxBoxSizer(wxHORIZONTAL);
        start = new wxSpinCtrl(m_controls, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(106, -1)));
        count = new wxSpinCtrl(m_controls, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(106, -1)));
        start->SetName(Display(name + " 시작 인덱스"));
        count->SetName(Display(name + " 원본 개수"));
        line->Add(start, 1, wxRIGHT, FromDIP(6));
        line->Add(count, 1);
        fields->Add(line, 0, wxEXPAND);
    };
    range("가로: 시작 / 개수", m_uLabel, m_uStart, m_uCount);
    range("세로: 시작 / 개수", m_vLabel, m_vStart, m_vCount);
    fields->Add(Label(m_controls, "표시 격자 간격 (stride)"), 0, wxTOP | wxBOTTOM, FromDIP(6));
    m_stride = new wxSpinCtrl(m_controls, wxID_ANY);
    m_stride->SetRange(1, 4096);
    m_stride->SetValue(1);
    m_stride->SetName(Display("필드 표시 격자 간격"));
    fields->Add(m_stride, 0, wxEXPAND);
    m_notice = new wxStaticText(m_controls, wxID_ANY, wxEmptyString);
    StudioTheme::BindSecondary(*m_notice);
    fields->Add(m_notice, 0, wxEXPAND);
    m_refineOptions = new wxPanel(m_controls);
    auto* refineLayout = new wxBoxSizer(wxVERTICAL);
    auto input = [this, refineLayout](const std::string& label, int minimum, int maximum, int initial)
    {
        auto* row = new wxBoxSizer(wxHORIZONTAL);
        row->Add(Label(m_refineOptions, label), 1, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(4));
        auto* control = new wxSpinCtrl(m_refineOptions, wxID_ANY);
        control->SetRange(minimum, maximum);
        control->SetValue(initial);
        control->SetName(Display(label));
        row->Add(control);
        refineLayout->Add(row, 0, wxTOP | wxEXPAND, FromDIP(3));
        return control;
    };
    m_changePercent = input("최소 복소 변화 (%)", 1, 200, 5);
    m_ruleLimit = input("추가 격자 규칙 수", 1, 16, 2);
    m_memoryLimit = input("예상 메모리 상한 (MiB)", 128, 16384, 2048);
    m_refine = new wxButton(m_refineOptions, wxID_ANY, Display("이 전계로 다음 격자 검토"));
    refineLayout->Add(m_refine, 0, wxTOP | wxEXPAND, FromDIP(6));
    m_refineOptions->SetSizer(refineLayout);
    fields->Add(m_refineOptions, 0, wxTOP | wxEXPAND, FromDIP(8));
    m_refine->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        if (onRefine && m_slice.is_object())
        {
            auto options = m_slice.at("selection");
            options.erase("stride");
            options["threshold_fraction"] = m_changePercent->GetValue() / 100.0;
            options["max_rules"] = m_ruleLimit->GetValue();
            options["memory_limit_mib"] = m_memoryLimit->GetValue();
            onRefine(options);
        }
    });
    auto* controlsLayout = new wxBoxSizer(wxVERTICAL);
    controlsLayout->Add(fields, 0, wxALL | wxEXPAND, FromDIP(12));
    m_controls->SetSizer(controlsLayout);
    body->Add(m_controls, 0, wxLEFT | wxEXPAND, FromDIP(8));
    layout->Add(body, 1, wxLEFT | wxRIGHT | wxBOTTOM | wxEXPAND, FromDIP(12));
    SetSizer(layout);
    m_monitor->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
    {
        RebuildMonitor();
    });
    m_component->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
    {
        RebuildComponent();
    });
    m_normal->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
    {
        RebuildPlane();
    });
    m_frequency->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
    {
        ClearSlice("주파수가 바뀌었습니다. 단면을 조회하십시오.");
    });
    for (auto* control : {m_planeIndex, m_uStart, m_uCount, m_vStart, m_vCount, m_stride})
    {
        control->Bind(wxEVT_SPINCTRL, [this](wxSpinEvent&)
        {
            if (!m_rebuilding)
            {
                ClearSlice("단면 선택이 바뀌었습니다. 조회 후 실제 표본을 확인하십시오.");
                UpdatePosition();
            }
        });
        control->Bind(wxEVT_TEXT, [this](wxCommandEvent& event)
        {
            if (!m_rebuilding)
            {
                ClearSlice("단면 선택이 바뀌었습니다. 조회 후 실제 표본을 확인하십시오.");
                UpdatePosition();
            }
            event.Skip();
        });
    }
    m_point->Bind(wxEVT_SPINCTRL, [this](wxSpinEvent&)
    {
        ShowMarker(static_cast<std::size_t>(m_point->GetValue()));
    });
    m_point->Bind(wxEVT_TEXT, [this](wxCommandEvent& event)
    {
        if (!m_markerUpdating && m_point->GetValue() >= 0)
        {
            ShowMarker(static_cast<std::size_t>(m_point->GetValue()));
        }
        event.Skip();
    });
    m_load->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        RequestSlice();
    });
    m_canvas->onMarker = [this](std::size_t index)
    {
        ShowMarker(index);
    };
    Bind(wxEVT_SIZE, [this](wxSizeEvent& event)
    {
        SetStatus(m_statusText);
        event.Skip();
    });
    Clear("기록 필드가 있는 해석 결과를 선택하십시오.");
}

const Json* FieldResultView::Monitor() const
{
    const int index = m_monitor->GetSelection();
    if (!m_description.is_object() || !m_description.contains("monitors") || !m_description.at("monitors").is_array()
        || index < 0 || static_cast<std::size_t>(index) >= m_description.at("monitors").size())
    {
        return nullptr;
    }
    return &m_description.at("monitors")[index];
}

const Json* FieldResultView::Component() const
{
    const Json* monitor = Monitor();
    const int index = m_component->GetSelection();
    if (monitor == nullptr || !monitor->contains("components") || !monitor->at("components").is_array()
        || index < 0 || static_cast<std::size_t>(index) >= monitor->at("components").size())
    {
        return nullptr;
    }
    return &monitor->at("components")[index];
}

void FieldResultView::SetDescription(const Json& description)
{
    Clear("필드 기록을 확인하고 있습니다.");
    try
    {
        if (!description.is_object() || !description.contains("monitors") || !description.at("monitors").is_array())
        {
            Clear("필드 기록 설명을 읽을 수 없습니다.");
            return;
        }
        m_description = description;
        std::string notice = "색 범위는 현재 반환된 단면 표본의 크기입니다. 다른 단면과 색만으로 크기를 비교하지 마십시오.";
        if (description.contains("warnings") && description.at("warnings").is_array())
        {
            for (const auto& warning : description.at("warnings"))
            {
                if (warning.is_string())
                {
                    notice += "\n\n" + warning.get<std::string>();
                }
            }
        }
        m_notice->SetLabel(Display(notice));
        m_notice->Wrap(FromDIP(234));
        m_controls->FitInside();
        for (const auto& monitor : description.at("monitors"))
        {
            m_monitor->Append(Display(monitor.value("label", monitor.value("monitor_id", "기록"))));
        }
        if (m_monitor->GetCount() == 0)
        {
            ClearSlice("선택한 결과에는 표시할 내부 필드가 기록되지 않았습니다.");
            SetBusy(false);
            return;
        }
        m_monitor->SetSelection(0);
        RebuildMonitor();
        SetBusy(false);
    }
    catch (const Json::exception&)
    {
        Clear("필드 기록 설명의 필수 항목이 유효하지 않습니다.");
    }
}

void FieldResultView::RebuildMonitor()
{
    ClearSlice("기록 성분과 단면을 고른 뒤 조회하십시오.");
    m_component->Clear();
    m_frequency->Clear();
    const Json* monitor = Monitor();
    if (monitor == nullptr)
    {
        return;
    }
    try
    {
        for (const auto& component : monitor->at("components"))
        {
            m_component->Append(Display(component.value("label", component.at("component").get<std::string>())));
        }
        const auto& frequencies = monitor->at("frequency_hz");
        const auto scale = frequencies.empty() ? StudioFrequency::Scale{"Hz", 1.0}
            : StudioFrequency::ForRange(frequencies.front().get<double>(), frequencies.back().get<double>());
        for (const auto& frequency : frequencies)
        {
            m_frequency->Append(Display(StudioFrequency::Value(frequency, scale, 10) + " " + scale.unit));
        }
        if (m_component->GetCount() > 0 && m_frequency->GetCount() > 0)
        {
            m_component->SetSelection(0);
            m_frequency->SetSelection(0);
            RebuildComponent();
        }
    }
    catch (const Json::exception&)
    {
        ClearSlice("필드 성분 또는 주파수 기록을 읽을 수 없습니다.");
    }
    SetBusy(m_busy);
}

void FieldResultView::RebuildComponent()
{
    ClearSlice("기록 성분이 바뀌었습니다. 단면을 조회하십시오.");
    RebuildPlane();
}

void FieldResultView::RebuildPlane()
{
    ClearSlice("실제 단면과 ROI를 선택한 뒤 조회하십시오.");
    const Json* component = Component();
    if (component == nullptr || m_normal->GetSelection() < 0)
    {
        return;
    }
    m_rebuilding = true;
    try
    {
        const std::array<std::string, 3> axes{"x", "y", "z"};
        const int normal = m_normal->GetSelection();
        std::vector<std::string> plane;
        for (int axis = 0; axis < 3; ++axis)
        {
            if (axis != normal)
            {
                plane.push_back(axes[axis]);
            }
        }
        m_uAxis = plane[0];
        m_vAxis = plane[1];
        const auto& coordinates = component->at("coordinates_mm");
        const int size = static_cast<int>(coordinates.at(axes[normal]).size());
        const int uSize = static_cast<int>(coordinates.at(m_uAxis).size());
        const int vSize = static_cast<int>(coordinates.at(m_vAxis).size());
        if (size <= 0 || uSize <= 0 || vSize <= 0 || size > 100000 || uSize > 100000 || vSize > 100000)
        {
            throw Json::out_of_range::create(401, "field coordinate count", &coordinates);
        }
        m_planeIndex->SetRange(0, size - 1);
        m_planeIndex->SetValue(size / 2);
        m_uStart->SetRange(0, uSize - 1);
        m_uStart->SetValue(0);
        m_vStart->SetRange(0, vSize - 1);
        m_vStart->SetValue(0);
        m_uCount->SetRange(1, uSize);
        m_uCount->SetValue(std::min(32, uSize));
        m_vCount->SetRange(1, vSize);
        m_vCount->SetValue(std::min(32, vSize));
        m_stride->SetValue(1);
        m_uLabel->SetLabel(Display(m_uAxis + ": 시작 / 원본 개수"));
        m_vLabel->SetLabel(Display(m_vAxis + ": 시작 / 원본 개수"));
        UpdatePosition();
    }
    catch (const Json::exception&)
    {
        ClearSlice("필드 성분의 실제 격자 좌표를 읽을 수 없습니다.");
    }
    m_rebuilding = false;
    m_controls->FitInside();
    SetBusy(m_busy);
}

void FieldResultView::UpdatePosition()
{
    const Json* component = Component();
    if (component == nullptr || m_normal->GetSelection() < 0)
    {
        m_position->SetLabel(wxEmptyString);
        return;
    }
    const std::string axis = m_normal->GetStringSelection().ToStdString();
    try
    {
        const auto& coordinates = component->at("coordinates_mm").at(axis);
        const int index = m_planeIndex->GetValue();
        m_position->SetLabel(Display(axis + " = " + ResultUi::Number(coordinates.at(index), 10) + " mm"));
    }
    catch (const Json::exception&)
    {
        m_position->SetLabel(Display("좌표 미정"));
    }
}

void FieldResultView::RequestSlice()
{
    const Json* monitor = Monitor();
    const Json* component = Component();
    if (m_busy || monitor == nullptr || component == nullptr || !onSlice || m_frequency->GetSelection() < 0)
    {
        return;
    }
    const int stride = m_stride->GetValue();
    if (stride < 1 || m_uCount->GetValue() < 1 || m_vCount->GetValue() < 1)
    {
        SetStatus("ROI 개수와 표시 간격은 양수여야 합니다.");
        return;
    }
    const long long uPoints = (static_cast<long long>(m_uCount->GetValue()) + stride - 1) / stride;
    const long long vPoints = (static_cast<long long>(m_vCount->GetValue()) + stride - 1) / stride;
    if (uPoints * vPoints > 4096)
    {
        SetStatus("한 단면 조회는 최대 4096개 표본입니다. ROI 개수나 표시 간격을 조정하십시오.");
        return;
    }
    ClearSlice("선택한 실제 단면을 조회하고 있습니다.");
    m_request = {{"monitor_id", monitor->at("monitor_id")}, {"frequency_index", m_frequency->GetSelection()},
                 {"component", component->at("component")},
                 {"plane", {{"normal_axis", m_normal->GetStringSelection().ToStdString()}, {"index", m_planeIndex->GetValue()}}},
                 {"roi", {{"u_start", m_uStart->GetValue()}, {"u_count", m_uCount->GetValue()},
                          {"v_start", m_vStart->GetValue()}, {"v_count", m_vCount->GetValue()}}}, {"stride", stride}};
    onSlice(m_request);
}

void FieldResultView::SetSlice(const Json& slice)
{
    if (m_request.is_null() || !slice.is_object() || slice.value("selection", Json(nullptr)) != m_request)
    {
        return;
    }
    try
    {
        const std::size_t columns = slice.at("u_coordinates_mm").size();
        const std::size_t rows = slice.at("v_coordinates_mm").size();
        for (const auto* name : {"values_ri", "magnitude", "phase_deg", "state"})
        {
            if (!slice.at(name).is_array() || slice.at(name).size() != rows)
            {
                throw Json::out_of_range::create(401, "field rows", &slice);
            }
            for (const auto& row : slice.at(name))
            {
                if (!row.is_array() || row.size() != columns)
                {
                    throw Json::out_of_range::create(401, "field columns", &slice);
                }
            }
        }
        if (!m_canvas->SetSlice(slice))
        {
            ClearSlice("필드 단면의 좌표와 표시 배열이 유효하지 않습니다.");
            return;
        }
        m_slice = slice;
        m_point->SetRange(0, static_cast<int>(rows * columns) - 1);
        m_point->Enable(true);
        ShowMarker(0);
        SetStatus("기록한 " + std::to_string(rows * columns) + "개 성분 표본. 색 범위는 현재 반환 단면의 크기이며 공간/주파수 보간은 없습니다.");
    }
    catch (const Json::exception&)
    {
        ClearSlice("필드 단면의 필수 표본 배열을 확인할 수 없습니다.");
    }
}

void FieldResultView::ShowMarker(std::size_t index)
{
    if (!m_slice.is_object())
    {
        return;
    }
    try
    {
        const std::size_t columns = m_slice.at("u_coordinates_mm").size();
        const std::size_t row = index / columns;
        const std::size_t column = index % columns;
        if (row >= m_slice.at("v_coordinates_mm").size())
        {
            return;
        }
        m_markerUpdating = true;
        m_point->SetValue(static_cast<int>(index));
        m_markerUpdating = false;
        m_canvas->SetMarker(index);
        const std::string unit = m_slice.value("unit", "");
        const auto& value = m_slice.at("values_ri")[row][column];
        std::string text = m_uAxis + " = " + ResultUi::Number(m_slice.at("u_coordinates_mm")[column], 10) + " mm, "
            + m_vAxis + " = " + ResultUi::Number(m_slice.at("v_coordinates_mm")[row], 10) + " mm\n";
        text += "원본 격자 " + ResultUi::Number(m_slice.at("u_indices")[column]) + ", " + ResultUi::Number(m_slice.at("v_indices")[row]);
        text += " | 복소값 " + ResultUi::Complex(value) + " " + unit + "\n";
        text += "크기 " + ResultUi::Number(m_slice.at("magnitude")[row][column]) + " " + unit;
        text += " | 위상 " + ResultUi::Number(m_slice.at("phase_deg")[row][column]) + " deg";
        text += " | " + ResultUi::State(m_slice.at("state")[row][column]);
        text += "\n펄스 Fourier 원문. 원문 시간 위치 유지 / 시간·위상 보정 미적용.";
        m_marker->ChangeValue(Display(text));
    }
    catch (const Json::exception&)
    {
        m_markerUpdating = false;
        m_marker->ChangeValue(Display("선택 표본의 원본 좌표 또는 값을 읽을 수 없습니다."));
    }
}

void FieldResultView::ClearSlice(const std::string& message)
{
    m_slice = nullptr;
    m_request = nullptr;
    m_canvas->Clear(message);
    m_marker->Clear();
    m_point->Enable(false);
    m_refine->Disable();
    SetStatus(message);
}

void FieldResultView::Clear(const std::string& message)
{
    m_description = nullptr;
    m_monitor->Clear();
    m_component->Clear();
    m_frequency->Clear();
    m_position->SetLabel(wxEmptyString);
    m_notice->SetLabel(Display("기록 위치의 색 타일입니다. 성분별 Yee 위치를 유지하며 공간 보간은 없습니다."));
    m_notice->Wrap(FromDIP(234));
    ClearSlice(message);
    SetBusy(false);
}

void FieldResultView::SetError(const std::string& message)
{
    ClearSlice(message);
    SetBusy(false);
}

void FieldResultView::SetStatus(const std::string& message)
{
    m_statusText = message;
    m_status->SetLabel(Display(message));
    m_status->Wrap(std::max(FromDIP(200), GetClientSize().x - FromDIP(30)));
    Layout();
}

void FieldResultView::SetBusy(bool busy)
{
    m_busy = busy;
    const bool available = Monitor() != nullptr;
    const bool component = Component() != nullptr;
    for (auto* choice : {m_monitor, m_component, m_frequency, m_normal})
    {
        choice->Enable(available && !busy);
    }
    for (auto* control : {m_planeIndex, m_uStart, m_uCount, m_vStart, m_vCount, m_stride})
    {
        control->Enable(component && !busy);
    }
    m_load->Enable(component && !busy && m_frequency->GetSelection() >= 0);
    const auto* monitor = Monitor();
    const bool electric = monitor && (monitor->at("monitor_id") == "electric" || monitor->at("monitor_id") == "probe_electric");
    const bool show = static_cast<bool>(onRefine) && electric;
    if (m_refineOptions->IsShown() != show)
    {
        m_refineOptions->Show(show);
        m_controls->Layout();
        m_controls->FitInside();
    }
    m_refine->Enable(show && m_slice.is_object() && !busy);
}
