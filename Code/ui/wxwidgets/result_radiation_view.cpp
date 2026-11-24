/** @file @brief 복소 성분과 서비스 투영을 실제 표본으로 표시하며 RF 값을 생성하지 않는다. */
#include "result_radiation_view.h"
#include "result_radiation_canvas.h"
#include "result_presentation.h"
#include "frequency_display.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <wx/wrapsizer.h>
#include <wx/dcbuffer.h>
#include <array>
#include <algorithm>
#include <cmath>
#include <wx/textdlg.h>
namespace
{
const std::array<std::string, 8> Observables{"total", "e_theta",     "e_phi", "rhcp",
                                             "lhcp",  "directivity", "gain",  "realized_gain"};
const std::array<std::string, 8> ObservableLabels{"총 전계", "Etheta", "Ephi", "RHCP",
                                                  "LHCP",    "지향성", "이득", "실현 이득"};
const std::array<std::string, 3> Bases{"theta_phi", "theta_co", "phi_co"};
}
RadiationResultView::RadiationResultView(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    SetScrollRate(0, FromDIP(16));
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_heading = new wxStaticText(this, wxID_ANY, Display("방사와 편파"));
    m_heading->SetWindowStyleFlag(m_heading->GetWindowStyleFlag() | wxST_ELLIPSIZE_END);
    m_heading->SetMinSize(wxSize(1, -1));
    StudioTheme::Title(*m_heading);
    layout->Add(m_heading, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* tools = new wxWrapSizer(wxHORIZONTAL);
    m_frequency = new wxChoice(this, wxID_ANY);
    m_observable = new wxChoice(this, wxID_ANY);
    m_scale = new wxChoice(this, wxID_ANY);
    m_basis = new wxChoice(this, wxID_ANY);
    m_target = new wxChoice(this, wxID_ANY);
    m_target->SetName("radiation.snapshot_target");
    m_target->SetToolTip(Display("계산에 사용한 원본 개정의 방사 관측 목표"));
    for (const auto& label : ObservableLabels)
    {
        m_observable->Append(Display(label));
    }
    m_scale->Append(Display("선형 표시"));
    m_scale->Append(Display("dB 표시"));
    for (const auto& label : {"극각과 방위각 (co 미지정)", "theta를 co로 지정", "phi를 co로 지정"})
    {
        m_basis->Append(Display(label));
    }
    m_observable->SetSelection(0);
    m_scale->SetSelection(0);
    m_basis->SetSelection(0);
    for (wxChoice* choice : {m_frequency, m_observable, m_scale, m_basis, m_target})
    {
        tools->Add(choice, 0, wxALL, FromDIP(4));
        choice->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         Request();
                     });
    }
    tools->Add(new wxStaticText(this, wxID_ANY, Display("표시 하한 dB")), 0, wxALIGN_CENTER_VERTICAL | wxALL,
               FromDIP(4));
    m_floor = new wxSpinCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(80, -1)), wxSP_ARROW_KEYS,
                             -120, -10, -40);
    tools->Add(m_floor, 0, wxALL, FromDIP(4));
    m_floor->Bind(wxEVT_SPINCTRL,
                  [this](wxSpinEvent&)
                  {
                      Request();
                  });
    m_floor->Bind(wxEVT_TEXT,
                  [this](wxCommandEvent&)
                  {
                      if (!m_loading && m_description.is_object())
                      {
                          SetError("표시 하한 초안입니다. 표시 조건 적용을 눌러 새 조건의 표본을 읽으세요.");
                          if (onInvalidate)
                          {
                              onInvalidate();
                          }
                      }
                  });
    auto* refresh = new wxButton(this, wxID_ANY, Display("표시 조건 적용"));
    tools->Add(refresh, 0, wxALL, FromDIP(4));
    refresh->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Request();
                  });
    auto* source = new wxButton(this, wxID_ANY, Display("원본 선택"));
    tools->Add(source, 0, wxALL, FromDIP(4));
    source->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (onSelectSource)
                     {
                         onSelectSource();
                     }
                 });
    layout->Add(tools, 0, wxEXPAND);
    m_status = new wxStaticText(this, wxID_ANY, Display("봉인된 NF2FF 방사 기록을 선택하세요."));
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(8));
    m_observation = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_observation->SetMinSize(wxSize(1, -1));
    m_observation->Hide();
    layout->Add(m_observation, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_tabs = new StudioNotebook(this);
    auto* cut = new wxPanel(m_tabs);
    auto* cutLayout = new wxBoxSizer(wxVERTICAL);
    auto* cutTools = new wxBoxSizer(wxHORIZONTAL);
    cutTools->Add(new wxStaticText(cut, wxID_ANY, Display("기록 phi 절단면")), 0, wxALIGN_CENTER_VERTICAL | wxALL,
                  FromDIP(4));
    m_phi = new wxChoice(cut, wxID_ANY);
    cutTools->Add(m_phi, 0, wxALL, FromDIP(4));
    cutLayout->Add(cutTools, 0, wxEXPAND);
    m_slice = new RadiationResultSlice(cut);
    cutLayout->Add(m_slice, 1, wxEXPAND | wxALL, FromDIP(8));
    cut->SetSizer(cutLayout);
    m_tabs->AddPage(cut, Display("2D 절단면"));
    m_phi->Bind(wxEVT_CHOICE,
                [this](wxCommandEvent&)
                {
                    if (m_data.is_object())
                    {
                        m_slice->SetPattern(m_data, m_phi->GetSelection());
                    }
                });
    auto* spatial = new wxPanel(m_tabs);
    auto* spatialLayout = new wxBoxSizer(wxHORIZONTAL);
    m_canvas = new RadiationResultCanvas(spatial);
    spatialLayout->Add(m_canvas, 1, wxEXPAND | wxALL, FromDIP(8));
    auto* side = new wxPanel(spatial);
    side->SetMinSize(FromDIP(wxSize(225, -1)));
    auto* sideLayout = new wxBoxSizer(wxVERTICAL);
    auto* fit = new wxButton(side, wxID_ANY, Display("등각 보기 (F)"));
    sideLayout->Add(fit, 0, wxEXPAND | wxALL, FromDIP(4));
    fit->Bind(wxEVT_BUTTON,
              [this](wxCommandEvent&)
              {
                  m_canvas->Fit();
              });
    auto* axes = new wxStaticText(side, wxID_ANY,
                                  Display("마우스를 끌어 회전합니다.\n휠로 확대·축소합니다.\n빨강 x축, 초록 y축, 파랑 z축\n좌표: "
                                          "무차원 표시\n면 연결과 색 혼합: 표시 전용"));
    sideLayout->Add(axes, 0, wxEXPAND | wxALL, FromDIP(8));
    m_colour = new wxPanel(side, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(205, 65)));
    m_colour->SetMinSize(FromDIP(wxSize(205, 65)));
    m_colour->SetBackgroundStyle(wxBG_STYLE_PAINT);
    sideLayout->Add(m_colour, 0, wxEXPAND | wxALL, FromDIP(8));
    m_colour->Bind(wxEVT_PAINT,
                   [this](wxPaintEvent&)
                   {
                       wxAutoBufferedPaintDC dc(m_colour);
                       dc.SetBackground(wxBrush(StudioTheme::Colours().panel));
                       dc.Clear();
                       if (!m_data.is_object())
                       {
                           return;
                       }
                       const auto size = m_colour->GetClientSize();
                       const int width = std::max(1, size.x - 12);
                       for (int x = 0; x < width; ++x)
                       {
                           const double t = static_cast<double>(x) / std::max(1, width - 1);
                           const auto channel = [t](double center)
                           {
                               return static_cast<unsigned char>(255 *
                                                                 std::clamp(1.5 - std::abs(4 * t - center), 0.0, 1.0));
                           };
                           dc.SetPen(wxPen(wxColour(channel(3), channel(2), channel(1))));
                           dc.DrawLine(6 + x, 6, 6 + x, 24);
                       }
                       dc.SetTextForeground(StudioTheme::Colours().text);
                       const auto range = m_data.at("color_range");
                       dc.DrawText(Display(ResultUi::Number(range[0]) + " ~ " + ResultUi::Number(range[1]) + " " +
                                           ResultUi::Text(m_data.value("color_unit", Json(nullptr)))),
                                   6, 30);
                   });
    m_metrics = new wxStaticText(side, wxID_ANY, wxEmptyString);
    sideLayout->Add(m_metrics, 0, wxEXPAND | wxALL, FromDIP(8));
    side->SetSizer(sideLayout);
    spatialLayout->Add(side, 0, wxEXPAND);
    spatial->SetSizer(spatialLayout);
    m_tabs->AddPage(spatial, Display("3D 방사"));
    auto* numbers = new wxPanel(m_tabs);
    auto* numbersLayout = new wxBoxSizer(wxVERTICAL);
    m_convention = new wxStaticText(numbers, wxID_ANY, Display("원문 복소 성분과 명시된 편파 규약을 표시합니다."));
    numbersLayout->Add(m_convention, 0, wxEXPAND | wxALL, FromDIP(8));
    m_samples = new wxListCtrl(numbers, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 210)),
                               wxLC_REPORT | wxLC_SINGLE_SEL);
    m_samples->SetMinSize(FromDIP(wxSize(-1, 210)));
    StudioTheme::Table(*m_samples);
    const std::array<std::string, 10> columns{"극각 (deg)", "방위각 (deg)", "축비 (dB)", "관측량 값", "상태",
                                             "상대 위상 (deg)", "Etheta (V*s/m)", "Ephi (V*s/m)",
                                             "RHCP (V*s/m)", "LHCP (V*s/m)"};
    const std::array<int, 10> columnWidths{105, 110, 90, 112, 120, 145, 156, 156, 156, 156};
    for (std::size_t index = 0; index < columns.size(); ++index)
    {
        m_samples->AppendColumn(Display(columns[index]), index != 0 && index != 4 ? wxLIST_FORMAT_RIGHT : wxLIST_FORMAT_LEFT,
                                FromDIP(columnWidths[index]));
    }
    numbersLayout->Add(m_samples, 1, wxEXPAND | wxALL, FromDIP(8));
    m_samples->SetToolTip(Display("행을 두 번 클릭하거나 Enter를 눌러 원래 자릿수의 복소 표본을 열 수 있습니다."));
    m_samples->Bind(wxEVT_LIST_ITEM_ACTIVATED, [this](wxListEvent& event)
    {
        if (!m_data.is_object() || m_data.at("phi_deg").empty() || event.GetIndex() < 0 ||
            event.GetIndex() >= m_samples->GetItemCount())
        {
            return;
        }
        const auto columns = m_data.at("phi_deg").size();
        const auto index = static_cast<std::size_t>(m_sampleOffset + event.GetIndex());
        const auto theta = index / columns;
        const auto phi = index % columns;
        const Json sample{{"theta_deg", m_data.at("theta_deg").at(theta)}, {"phi_deg", m_data.at("phi_deg").at(phi)},
                          {"e_theta_v_s_per_m", m_data.at("e_theta").at(theta).at(phi)},
                          {"e_phi_v_s_per_m", m_data.at("e_phi").at(theta).at(phi)},
                          {"polarization", m_data.at("polarization").at(theta).at(phi)},
                          {"projection", m_data.at("projection").at(theta).at(phi)}};
        wxTextEntryDialog detail(this, Display("표의 요약값에 대응하는 원본 표시 표본입니다. Ctrl+C로 복사할 수 있습니다."),
                                 Display("편파와 방사 표본 상세"), Display(sample.dump(2)), wxOK | wxTE_MULTILINE | wxTE_READONLY);
        detail.SetSize(FromDIP(wxSize(700, 560)));
        detail.ShowModal();
    });
    auto* paging = new wxBoxSizer(wxHORIZONTAL);
    m_previous = new wxButton(numbers, wxID_ANY, Display("이전 201표본"));
    m_next = new wxButton(numbers, wxID_ANY, Display("다음 201표본"));
    paging->Add(m_previous, 0, wxALL, FromDIP(4));
    paging->Add(m_next, 0, wxALL, FromDIP(4));
    numbersLayout->Add(paging, 0, wxALL, FromDIP(4));
    numbers->SetSizer(numbersLayout);
    m_tabs->AddPage(numbers, Display("편파와 방사 수치"));
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         m_sampleOffset = std::max(0, m_sampleOffset - 201);
                         PresentSamples();
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     m_sampleOffset += 201;
                     PresentSamples();
                 });
    m_tabs->SetMinSize(FromDIP(wxSize(600, 420)));
    layout->Add(m_tabs, 1, wxEXPAND | wxALL, FromDIP(4));
    SetSizer(layout);
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             m_status->Wrap(std::max(FromDIP(220), GetClientSize().x - FromDIP(24)));
             m_convention->Wrap(std::max(FromDIP(220), GetClientSize().x - FromDIP(32)));
             Layout();
             FitInside();
             event.Skip();
         });
    Clear("왼쪽에서 방사를 기록한 원본을 선택하세요. 새 계산의 방사 기록은 해석 설정에서 지정합니다.");
}
Json RadiationResultView::Options() const
{
    Json options{{"frequency_index", std::max(0, m_frequency->GetSelection())},
            {"observable", Observables.at(static_cast<std::size_t>(m_observable->GetSelection()))},
            {"display_scale", m_scale->GetSelection() == 1 ? "db_amplitude" : "linear_amplitude"},
            {"floor_db", m_floor->GetValue()},
            {"polarization_basis", Bases.at(static_cast<std::size_t>(m_basis->GetSelection()))}};
    const int selected = m_target->GetSelection();
    if (selected > 0 && m_description.is_object())
    {
        options["target_id"] = m_description.at("radiation_targets").at(selected - 1).at("id");
    }
    return options;
}
void RadiationResultView::SetDescription(const Json& description)
{
    Clear("봉인된 방사 표본을 조회하고 있습니다.");
    m_description = description;
    m_heading->SetLabel(Display("방사와 편파"));
    m_heading->SetToolTip(Display(ResultUi::Text(description.at("label"))));
    m_observable->SetSelection(0);
    m_scale->SetSelection(0);
    m_basis->SetSelection(0);
    m_target->Append(Display("방사 관측 목표 선택"));
    for (const auto& target : description.value("radiation_targets", Json::array()))
    {
        m_target->Append(Display(target.at("name").get<std::string>()));
    }
    m_target->SetSelection(0);
    m_target->Enable(m_target->GetCount() > 1);
    m_floor->SetValue(-40);
}
void RadiationResultView::SetPattern(const Json& data)
{
    if (!ResultUi::Matches(data, m_description))
    {
        return;
    }
    m_loading = true;
    m_data = data;
    m_sampleOffset = 0;
    m_frequency->Clear();
    for (const auto& frequency : data.at("frequency_hz"))
    {
        m_frequency->Append(Display(StudioFrequency::WithUnit(frequency)));
    }
    m_frequency->SetSelection(data.at("frequency_index").get<int>());
    m_phi->Clear();
    for (const auto& phi : data.at("phi_deg"))
    {
        m_phi->Append(Display(ResultUi::Number(phi) + " deg"));
    }
    m_phi->SetSelection(0);
    m_canvas->SetPattern(data);
    m_slice->SetPattern(data, 0);
    m_colour->Refresh();
    const auto metrics = data.at("metrics");
    m_metrics->SetLabel(
        Display("형상: 총장 peak 정규화\n관측량: " +
                ObservableLabels.at(static_cast<std::size_t>(m_observable->GetSelection())) +
                "\n\n최대 지향성: " + ResultUi::Number(metrics.value("directivity_dbi", Json(nullptr))) +
                " dBi\n최대 이득: " + ResultUi::Number(metrics.value("gain_dbi", Json(nullptr))) + " dBi\n실현 이득: " +
                ResultUi::Number(metrics.value("realized_gain_dbi", Json(nullptr))) + " dBi\n\n물리 검증: 미확립"));
    m_metrics->Wrap(FromDIP(205));
    const auto convention = data.value("polarization_convention", Json::object());
    const std::string co = data.value("co_component", Json(nullptr)) == "e_theta" ? "Etheta"
                           : data.value("co_component", Json(nullptr)) == "e_phi" ? "Ephi"
                                                                                  : "미지정";
    std::string details = "openEMS 0.37.0 원형 편파 규약. 바깥쪽 e_r로 전파하며 우수 구면 기저를 사용합니다.\n시간 규약: " +
                          ResultUi::Text(convention.value("phasor", Json(nullptr))) + ", co 성분: " + co +
                          "\nRHCP = " + ResultUi::Text(convention.value("rh_formula", Json(nullptr))) +
                          "\nLHCP = " + ResultUi::Text(convention.value("lh_formula", Json(nullptr)));
    m_convention->SetLabel(Display(details));
    m_convention->Wrap(std::max(FromDIP(220), GetClientSize().x - FromDIP(32)));
    PresentObservation(data.value("target_observation", Json(nullptr)));
    SetBusy(false, "실제 기록 표본을 총장의 최댓값으로 정규화했습니다. 표면 연결은 표시 전용입니다.");
    if (!m_canvas->Ready())
    {
        m_status->SetLabel(Display("OpenGL 표시 환경을 사용할 수 없습니다. 2D 절단면과 실제 수치표를 확인하세요."));
    }
    PresentSamples();
    m_loading = false;
    Layout();
    FitInside();
}

/** @brief 원본 개정의 목표와 정확한 기록 표본의 관측 결과를 표시한다. */
void RadiationResultView::PresentObservation(const Json& observation)
{
    m_observation->Show(observation.is_object());
    if (!observation.is_object())
    {
        return;
    }
    const Json& point = observation.at("observation");
    const auto frequency = point.at("frequency");
    const std::string status = observation.at("status").get<std::string>();
    const std::string decision = status == "conditional" ? "표본 통과" : status == "fail" ? "표본 미달" :
        status == "recorded" ? "한계 미정" : "미평가";
    const std::string gain = observation.at("value_state") == "negative_infinity" ? "-Inf dBi" :
        observation.at("gain_dbi").is_null() ? "미기록" : ResultUi::Number(observation.at("gain_dbi")) + " dBi";
    m_observation->SetLabel(Display(observation.at("name").get<std::string>() + ", " +
        (frequency.is_null() ? "주파수 미정" : StudioFrequency::WithUnit(frequency.at("value_si"))) +
        ", 극각 " + ResultUi::Number(point.at("theta_deg")) + " deg, 방위각 " +
        ResultUi::Number(point.at("phi_deg")) + " deg, " + ResultUi::Text(point.at("polarization")) +
        "\n실현 이득 " + gain + ", " + decision + ", " + observation.at("reason").get<std::string>()));
    m_observation->Wrap(std::max(FromDIP(220), GetClientSize().x - FromDIP(32)));
}
void RadiationResultView::PresentSamples()
{
    m_samples->DeleteAllItems();
    if (!m_data.is_object())
    {
        m_previous->Disable();
        m_next->Disable();
        return;
    }
    const int columns = static_cast<int>(m_data.at("phi_deg").size()),
              total = static_cast<int>(m_data.at("theta_deg").size()) * columns;
    for (int index = m_sampleOffset; index < std::min(total, m_sampleOffset + 201); ++index)
    {
        const auto t = static_cast<std::size_t>(index / columns), p = static_cast<std::size_t>(index % columns);
        const auto& polarization = m_data.at("polarization")[t][p];
        const auto& projection = m_data.at("projection")[t][p];
        const long row =
            m_samples->InsertItem(m_samples->GetItemCount(), Display(ResultUi::Number(m_data.at("theta_deg")[t])));
        m_samples->SetItem(row, 1, Display(ResultUi::Number(m_data.at("phi_deg")[p])));
        m_samples->SetItem(row, 6, Display(ResultUi::Complex(m_data.at("e_theta")[t][p])));
        m_samples->SetItem(row, 7, Display(ResultUi::Complex(m_data.at("e_phi")[t][p])));
        m_samples->SetItem(row, 8, Display(ResultUi::Complex(polarization.at("rhcp_ri"))));
        m_samples->SetItem(row, 9, Display(ResultUi::Complex(polarization.at("lhcp_ri"))));
        m_samples->SetItem(row, 5,
                           Display(polarization.at("relative_phase_deg").is_null()
                                       ? ResultUi::State(polarization.value("relative_phase_state", Json("missing")))
                                       : ResultUi::Number(polarization.at("relative_phase_deg"))));
        m_samples->SetItem(row, 2,
                           Display(polarization.at("axial_ratio_db").is_null()
                                       ? ResultUi::State(polarization.value("axial_ratio_state", Json("missing")))
                                       : ResultUi::Number(polarization.at("axial_ratio_db"))));
        const auto quantity = projection.value("quantity_db", projection.value("db", Json(nullptr)));
        const auto quantityState = projection.value("quantity_db_state", projection.value("db_state", Json("missing")));
        m_samples->SetItem(
            row, 3,
            Display(quantityState == "negative_infinity"
                        ? "-inf (크기 0)"
                        : ResultUi::Number(quantity) + " " + (projection.contains("quantity_db") ? "dBi" : "dB")));
        m_samples->SetItem(row, 4,
                           Display(ResultUi::State(polarization.value("axial_ratio_state", Json(nullptr))) +
                                   (projection.value("clipped", false) ? " (표시 하한 적용)" : "")));
    }
    m_previous->Enable(m_sampleOffset > 0);
    m_next->Enable(m_sampleOffset + 201 < total);
}
void RadiationResultView::Request()
{
    if (m_loading || !m_description.is_object())
    {
        return;
    }
    m_data = nullptr;
    m_canvas->Clear();
    m_slice->Clear();
    m_samples->DeleteAllItems();
    m_colour->Refresh();
    m_metrics->SetLabel(wxEmptyString);
    m_observation->Hide();
    SetBusy(true, "선택한 주파수와 표시 조건의 원본 표본 조회 중");
    if (onRequest)
    {
        onRequest(Options());
    }
}
void RadiationResultView::SetBusy(bool busy, const std::string& message)
{
    if (!message.empty())
    {
        m_status->SetLabel(Display(message));
    }
    const bool hasPattern = m_data.is_object();
    if (m_tabs->Show(hasPattern))
    {
        Layout();
        FitInside();
    }
    m_previous->Enable(!busy && hasPattern && m_sampleOffset > 0);
    m_next->Enable(!busy && hasPattern &&
                   m_sampleOffset + 201 <
                       static_cast<int>(m_data.at("theta_deg").size() * m_data.at("phi_deg").size()));
}
void RadiationResultView::SetError(const std::string& message)
{
    m_data = nullptr;
    m_samples->DeleteAllItems();
    m_canvas->Clear();
    m_slice->Clear();
    m_metrics->SetLabel(wxEmptyString);
    m_observation->Hide();
    m_colour->Refresh();
    SetBusy(false, message);
}
void RadiationResultView::Clear(const std::string& reason)
{
    m_heading->SetLabel(Display("방사와 편파"));
    m_heading->SetToolTip(wxEmptyString);
    m_description = nullptr;
    m_data = nullptr;
    m_frequency->Clear();
    m_target->Clear();
    m_target->Disable();
    m_phi->Clear();
    m_samples->DeleteAllItems();
    m_canvas->Clear();
    m_slice->Clear();
    m_metrics->SetLabel(wxEmptyString);
    m_observation->Hide();
    m_convention->SetLabel(Display("편파 규약은 원본을 선택한 뒤 표시합니다."));
    m_colour->Refresh();
    SetBusy(false, reason);
}
