/** @file @brief 비동기 방사 페이지 조회와 theta 절단면 표시를 구현한다. */
#include "radiation_dialog.h"
#include "studio_support.h"
#include <wx/wx.h>
#include <wx/dcbuffer.h>
#include <wx/weakref.h>
#include <algorithm>

RadiationDialog::RadiationDialog(wxWindow* parent, const Json& result, bool stale, RadiationGateway gateway)
    : wxDialog(parent, wxID_ANY, Display("방사 패턴 / 계산 결과 / 물리 검증 전"), wxDefaultPosition,
               wxSize(980, 740), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
      m_gateway(std::move(gateway)), m_artifact(result.at("artifact_id").get<std::string>()), m_timeout(this)
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* tools = new wxBoxSizer(wxHORIZONTAL);
    m_frequency = new wxChoice(this, wxID_ANY);
    const auto& summary = result.at("metadata").at("radiation_summary");
    for (const auto& frequency : summary.at("frequency_hz"))
    {
        m_frequency->Append(wxString::Format("%.6g GHz", frequency.get<double>() / 1e9));
    }
    m_frequency->SetSelection(0);
    m_phi = new wxChoice(this, wxID_ANY);
    m_metric = new wxChoice(this, wxID_ANY);
    for (const auto* label : {"정규화 전력 (dB)", "지향성 (dBi)", "이득 (dBi)", "실현 이득 (dBi)"})
    {
        m_metric->Append(Display(label));
    }
    m_metric->SetSelection(0);
    tools->Add(m_frequency, 0, wxALL, 6);
    tools->Add(new wxStaticText(this, wxID_ANY, "phi"), 0, wxALL | wxALIGN_CENTER_VERTICAL, 6);
    tools->Add(m_phi, 0, wxALL, 6);
    tools->Add(m_metric, 0, wxALL, 6);
    layout->Add(tools, 0, wxEXPAND);
    layout->Add(new wxStaticText(this, wxID_ANY, Display(stale ? "이전 설계 스냅샷의 결과입니다." : "조회 시점의 적용 설계 스냅샷 결과입니다.")), 0, wxALL, 6);
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, 6);
    m_chart = new wxPanel(this);
    m_chart->SetBackgroundStyle(wxBG_STYLE_PAINT);
    m_chart->SetMinSize(FromDIP(wxSize(500, 240)));
    layout->Add(m_chart, 1, wxEXPAND | wxALL, 6);
    m_details = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 155)), wxTE_MULTILINE | wxTE_READONLY);
    layout->Add(m_details, 0, wxEXPAND | wxALL, 6);
    auto* close = new wxButton(this, wxID_CLOSE, Display("닫기"));
    layout->Add(close, 0, wxALIGN_RIGHT | wxALL, 8);
    SetSizer(layout);
    close->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        Destroy();
    });
    Bind(wxEVT_CLOSE_WINDOW, [this](wxCloseEvent&)
    {
        Destroy();
    });
    Bind(wxEVT_TIMER, [this](wxTimerEvent&)
    {
        ++m_generation;
        Failed("조회 시간이 초과되었습니다. 서비스 연결을 확인한 후 화면을 다시 여십시오.");
    });
    m_frequency->Bind(wxEVT_CHOICE, [this](wxCommandEvent& event)
    {
        Load(event.GetSelection());
    });
    for (auto* choice : {m_phi, m_metric})
    {
        choice->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
        {
            m_chart->Refresh(false);
        });
    }
    m_chart->Bind(wxEVT_PAINT, &RadiationDialog::Paint, this);
    m_chart->Bind(wxEVT_SIZE, [this](wxSizeEvent& event)
    {
        m_chart->Refresh(false);
        event.Skip();
    });
    Load(0);
}

void RadiationDialog::Load(int frequency)
{
    ++m_generation;
    m_pattern.Reset();
    m_frequency->Disable();
    m_phi->Disable();
    m_metric->Disable();
    m_status->SetLabel(Display("봉인된 방사 패턴을 읽고 있습니다. 해석은 실행하지 않습니다."));
    m_details->Clear();
    m_chart->Refresh(false);
    m_timeout.StartOnce(10000);
    Fetch(frequency, 0, m_generation);
}

void RadiationDialog::Fetch(int frequency, int offset, std::size_t generation)
{
    wxWeakRef<RadiationDialog> weak(this);
    m_gateway(Json{{"artifact_id", m_artifact}, {"frequency_index", frequency}, {"theta_offset", offset}},
        [weak, frequency, generation](const Json& page)
        {
            if (!weak || weak->m_generation != generation)
            {
                return;
            }
            try
            {
                weak->m_pattern.Append(page, weak->m_artifact, frequency);
                if (weak->m_pattern.Complete())
                {
                    weak->ShowPattern();
                }
                else
                {
                    weak->Fetch(frequency, page.at("next_offset").get<int>(), generation);
                }
            }
            catch (const std::exception& error)
            {
                weak->Failed(error.what());
            }
        },
        [weak, generation](const Json& error)
        {
            if (weak && weak->m_generation == generation)
            {
                weak->Failed(DiagnosticMessage(error));
            }
        });
}

void RadiationDialog::Failed(const std::string& message)
{
    m_timeout.Stop();
    m_pattern.Reset();
    m_status->SetLabel(Display("방사 패턴 조회 실패: " + message));
    m_status->Wrap(GetClientSize().x - FromDIP(20));
    m_frequency->Enable();
    m_chart->Refresh(false);
    Layout();
}

void RadiationDialog::ShowPattern()
{
    m_timeout.Stop();
    const auto& data = m_pattern.Data();
    const auto& metrics = data.at("metrics");
    m_phi->Clear();
    for (const auto& angle : data.at("phi_deg"))
    {
        m_phi->Append(wxString::Format("%g deg", angle.get<double>()));
    }
    m_phi->SetSelection(0);
    m_frequency->Enable();
    m_phi->Enable();
    m_metric->Enable();
    m_status->SetLabel(Display(metrics.at("power_balance_status") == "requires_review"
        ? "전력 균형 검토 필요 / 효율을 100%로 보정하지 않음 / 제작 및 측정 검증 전"
        : "theta 절단면 / 편광 합산 전력 / 1 m / 절대 출력 전력 미정 / 제작 및 측정 검증 전"));
    m_details->SetValue(Display("스냅샷 개정: " + data.at("snapshot").at("revision_id").get<std::string>() +
        "\n방사 효율: " + std::to_string(metrics.at("radiation_efficiency").get<double>() * 100) +
        "% / 전력 균형: " + metrics.at("power_balance_status").get<std::string>() +
        "\nDmax: " + std::to_string(metrics.at("directivity_dbi").get<double>()) +
        " dBi / 최대 이득: " + std::to_string(metrics.at("gain_dbi").get<double>()) +
        " dBi / 최대 실현 이득: " + std::to_string(metrics.at("realized_gain_dbi").get<double>()) +
        " dBi\n원시 복소 필드: V*s/m / 전력 스펙트럼: W*s^2 / 절대 W로 환산하지 않음"
        "\n각도 표본 사이 선은 시각적 연결입니다. 표시 하한은 -40 dB이며 원시 값은 보존합니다."));
    m_chart->Refresh(false);
    Layout();
}

void RadiationDialog::Paint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(m_chart);
    dc.SetBackground(wxBrush(wxColour(250, 251, 253)));
    dc.Clear();
    if (!m_pattern.Complete() || m_phi->GetSelection() < 0)
    {
        return;
    }
    const auto& data = m_pattern.Data();
    const auto& metrics = data.at("metrics");
    const int metric = m_metric->GetSelection();
    const char* peakKey = metric == 1 ? "directivity_dbi" : (metric == 2 ? "gain_dbi" : "realized_gain_dbi");
    const double high = metric == 0 ? 0.0 : std::max(0.0, std::ceil(metrics.at(peakKey).get<double>() / 5) * 5);
    const double low = -40.0;
    const auto size = m_chart->GetClientSize();
    const int left = FromDIP(55), top = FromDIP(22), width = size.x - left - FromDIP(30), height = size.y - top - FromDIP(50);
    if (width < 60 || height < 40)
    {
        return;
    }
    for (int index = 0; index <= 4; ++index)
    {
        const int x = left + width * index / 4, y = top + height * index / 4;
        dc.SetPen(wxPen(wxColour(220, 225, 232)));
        dc.DrawLine(left, y, left + width, y);
        dc.DrawLine(x, top, x, top + height);
        dc.DrawText(wxString::Format("%g", high - (high - low) * index / 4), FromDIP(6), y - FromDIP(7));
        dc.DrawText(wxString::Format("%d", 180 * index / 4), x - FromDIP(10), top + height + FromDIP(5));
    }
    dc.DrawText("theta (deg)", left + width / 2 - FromDIP(30), top + height + FromDIP(24));
    dc.DrawText(metric == 0 ? "dB" : "dBi", left, 0);
    dc.SetClippingRegion(left, top, width + 1, height + 1);
    dc.SetPen(wxPen(wxColour(31, 115, 195), FromDIP(2)));
    wxPoint previous;
    const auto column = static_cast<std::size_t>(m_phi->GetSelection());
    for (std::size_t index = 0; index < data.at("theta_deg").size(); ++index)
    {
        const double normalized = data.at("normalized_power").at(index).at(column);
        const double db = (normalized > 0 ? 10 * std::log10(normalized) : -400.0) + (metric == 0 ? 0.0 : metrics.at(peakKey).get<double>());
        const double theta = data.at("theta_deg").at(index);
        const wxPoint point(left + static_cast<int>(theta / 180 * width),
                            top + static_cast<int>((high - std::clamp(db, low, high)) / (high - low) * height));
        if (index > 0)
        {
            dc.DrawLine(previous, point);
        }
        previous = point;
        dc.DrawCircle(point, FromDIP(2));
    }
    dc.DestroyClippingRegion();
    ++m_renderedFrames;
}
