/** @file @brief 실제 표본의 페이지 범위와 결측을 숨기지 않는 공통 결과 곡선이다. */
#include "network_chart.h"
#include "studio_theme.h"
#include "frequency_display.h"
#include <wx/dcbuffer.h>
#include <wx/graphics.h>
#include <wx/control.h>
#include <algorithm>
#include <cmath>
#include <limits>
#include <memory>

namespace
{
wxString Display(const std::string& text)
{
    return wxString::FromUTF8(text.data(), text.size());
}

/** @brief null/비수치/비유한 표시값은 0으로 대체하지 않는다. */
bool Number(const Json& item, const std::string& key, double& value)
{
    if (!item.contains(key) || !item.at(key).is_number())
    {
        return false;
    }
    value = item.at(key).get<double>();
    return std::isfinite(value);
}

wxString Label(double value)
{
    return wxString::Format("%.4g", value);
}
}

NetworkChart::NetworkChart(wxWindow* parent) : wxPanel(parent)
{
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    SetMinSize(FromDIP(wxSize(320, 240)));
    SetName(Display("네트워크 실제 표본 곡선"));
    Bind(wxEVT_PAINT, &NetworkChart::Paint, this);
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Refresh();
             event.Skip();
         });
    Bind(wxEVT_SYS_COLOUR_CHANGED,
         [this](wxSysColourChangedEvent& event)
         {
             Refresh();
             event.Skip();
         });
}

void NetworkChart::ChooseDefaultMetric(const Json& page)
{
    if (m_explicitMetric)
    {
        return;
    }
    const bool scattering = page.value("parameter_kind", "S") == "S";
    m_metric = scattering ? "magnitude_db" : "magnitude";
    m_axisLabel = scattering ? Display("크기 / dB") : Display("크기 / " + page.value("unit", ""));
}

void NetworkChart::SetPage(const Json& page, const wxString& label)
{
    m_series.clear();
    m_marker = -1;
    if (page.is_object() && page.contains("samples") && page.at("samples").is_array())
    {
        m_series.push_back({page, label.empty() ? Display("선택 결과") : label});
        ChooseDefaultMetric(page);
    }
    Refresh();
}

void NetworkChart::SetComparison(const Json& originalPage, const Json& derivedPage, const wxString& originalLabel,
                                 const wxString& derivedLabel)
{
    m_series.clear();
    m_marker = -1;
    for (const auto& entry : std::vector<Series>{{originalPage, originalLabel}, {derivedPage, derivedLabel}})
    {
        if (entry.page.is_object() && entry.page.contains("samples") && entry.page.at("samples").is_array())
        {
            m_series.push_back(entry);
        }
    }
    if (!m_series.empty())
    {
        ChooseDefaultMetric(m_series.back().page);
    }
    Refresh();
}

void NetworkChart::SetMetric(const std::string& key, const wxString& axisLabel)
{
    m_metric = key;
    m_axisLabel = axisLabel;
    m_explicitMetric = true;
    Refresh();
}

void NetworkChart::Clear()
{
    m_series.clear();
    m_marker = -1;
    Refresh();
}

void NetworkChart::SetFrequencyUnit(const std::string& unit)
{
    StudioFrequency::ForRange(0.0, 0.0, unit);
    m_frequencyUnit = unit;
    Refresh();
}

void NetworkChart::SetMarker(int sampleIndex)
{
    m_marker = sampleIndex;
    Refresh();
}

void NetworkChart::Paint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(this);
    const auto colours = StudioTheme::Colours();
    dc.SetBackground(wxBrush(colours.content));
    dc.Clear();
    dc.SetFont(GetFont());
    dc.SetTextForeground(colours.text);
    const wxSize size = GetClientSize();
    const int margin = FromDIP(16);
    if (size.x < FromDIP(180) || size.y < FromDIP(150))
    {
        return;
    }
    if (m_series.empty())
    {
        dc.DrawText(Display("표시할 실제 표본이 없습니다."), margin, margin);
        return;
    }
    const int lineHeight = GetCharHeight() + FromDIP(4);
    const int footerHeight = lineHeight * static_cast<int>(m_series.size() + 1);
    const wxRect plot(FromDIP(88), FromDIP(34), std::max(1, size.x - FromDIP(110)),
                      std::max(1, size.y - FromDIP(80) - footerHeight));
    double minX = std::numeric_limits<double>::infinity();
    double maxX = -minX;
    double minY = minX;
    double maxY = -minX;
    for (const auto& series : m_series)
    {
        for (const auto& sample : series.page.at("samples"))
        {
            double x = 0.0;
            double y = 0.0;
            if (Number(sample, "frequency_hz", x))
            {
                minX = std::min(minX, x);
                maxX = std::max(maxX, x);
                if (sample.value("valid", false) && Number(sample, m_metric, y))
                {
                    minY = std::min(minY, y);
                    maxY = std::max(maxY, y);
                }
            }
        }
    }
    const auto frequencyScale = StudioFrequency::ForRange(minX, maxX, m_frequencyUnit);
    dc.DrawText(m_axisLabel, plot.x, FromDIP(6));
    bool valuesAvailable = std::isfinite(minX) && std::isfinite(maxX) && std::isfinite(minY) && std::isfinite(maxY) &&
                           std::isfinite(maxX - minX) && std::isfinite(maxY - minY);
    if (valuesAvailable)
    {
        if (minX == maxX)
        {
            const double extra = std::max(std::abs(minX) * 0.01, 1.0);
            minX -= extra;
            maxX += extra;
        }
        const double yExtra =
            std::max((maxY - minY) * 0.08, minY == maxY ? std::max(std::abs(minY) * 0.1, 1.0) : 1.0e-12);
        if (std::isfinite(minY - yExtra) && std::isfinite(maxY + yExtra))
        {
            minY -= yExtra;
            maxY += yExtra;
        }
        valuesAvailable = maxY > minY && maxX > minX && std::isfinite(maxX - minX) && std::isfinite(maxY - minY);
    }
    if (valuesAvailable)
    {
        dc.SetPen(wxPen(colours.border));
        dc.SetTextForeground(colours.secondary);
        for (int index = 0; index <= 4; ++index)
        {
            const int x = plot.x + plot.width * index / 4;
            const int y = plot.y + plot.height * index / 4;
            dc.DrawLine(x, plot.y, x, plot.GetBottom());
            dc.DrawLine(plot.x, y, plot.GetRight(), y);
            const wxString xLabel =
                Display(StudioFrequency::Value(minX + (maxX - minX) * index / 4, frequencyScale, 6));
            const int labelWidth = dc.GetTextExtent(xLabel).x;
            const int labelX = std::clamp(x - labelWidth / 2, margin, std::max(margin, size.x - margin - labelWidth));
            dc.DrawText(xLabel, labelX, plot.GetBottom() + FromDIP(4));
            const wxString yLabel = Label(maxY - (maxY - minY) * index / 4);
            dc.DrawText(yLabel, plot.x - dc.GetTextExtent(yLabel).x - FromDIP(8), y - GetCharHeight() / 2);
        }
        std::unique_ptr<wxGraphicsContext> graphics(wxGraphicsContext::Create(dc));
        if (graphics)
        {
            graphics->Clip(plot.x, plot.y, plot.width, plot.height);
            for (std::size_t seriesIndex = 0; seriesIndex < m_series.size(); ++seriesIndex)
            {
                const bool original = m_series.size() > 1 && seriesIndex == 0;
                const wxColour colour = original ? colours.secondary : colours.accent;
                graphics->SetPen(wxPen(colour, FromDIP(2), original ? wxPENSTYLE_SHORT_DASH : wxPENSTYLE_SOLID));
                graphics->SetBrush(wxBrush(colour));
                bool previousValid = false;
                int previousIndex = -1;
                wxPoint2DDouble previous;
                for (const auto& sample : m_series[seriesIndex].page.at("samples"))
                {
                    double x = 0.0;
                    double y = 0.0;
                    const int index = sample.value("index", -1);
                    if (!sample.value("valid", false) || !Number(sample, "frequency_hz", x) ||
                        !Number(sample, m_metric, y))
                    {
                        previousValid = false;
                        continue;
                    }
                    const wxPoint2DDouble point(plot.x + (x - minX) / (maxX - minX) * plot.width,
                                                plot.GetBottom() - (y - minY) / (maxY - minY) * plot.height);
                    if (previousValid && index == previousIndex + 1)
                    {
                        graphics->StrokeLine(previous.m_x, previous.m_y, point.m_x, point.m_y);
                    }
                    const int radius = FromDIP(2);
                    graphics->DrawEllipse(point.m_x - radius, point.m_y - radius, radius * 2, radius * 2);
                    if (index == m_marker)
                    {
                        graphics->DrawEllipse(point.m_x - radius * 2, point.m_y - radius * 2, radius * 4, radius * 4);
                    }
                    previous = point;
                    previousIndex = index;
                    previousValid = true;
                }
            }
        }
    }
    else
    {
        dc.DrawText(Display("유한한 곡선값이 없습니다. 무한대/미정은 표에서 확인하세요."), margin,
                    plot.y + FromDIP(24));
    }
    dc.SetTextForeground(colours.secondary);
    const wxString frequencyLabel = Display("주파수 / " + frequencyScale.unit);
    dc.DrawText(frequencyLabel, plot.GetRight() - dc.GetTextExtent(frequencyLabel).x,
                plot.GetBottom() + lineHeight + FromDIP(4));
    int footerY = size.y - footerHeight;
    for (std::size_t index = 0; index < m_series.size(); ++index)
    {
        const auto& series = m_series[index];
        const int offset = series.page.value("offset", 0);
        const int count = static_cast<int>(series.page.at("samples").size());
        const wxString text = series.label + Display(" / 표본 ") +
                              wxString::Format("%d-%d / %d", count == 0 ? 0 : offset + 1, offset + count,
                                               series.page.value("total", count));
        const bool original = m_series.size() > 1 && index == 0;
        dc.SetPen(wxPen(original ? colours.secondary : colours.accent, FromDIP(2),
                        original ? wxPENSTYLE_SHORT_DASH : wxPENSTYLE_SOLID));
        dc.DrawLine(margin, footerY + GetCharHeight() / 2, margin + FromDIP(24), footerY + GetCharHeight() / 2);
        dc.DrawText(wxControl::Ellipsize(text, dc, wxELLIPSIZE_END, std::max(1, size.x - FromDIP(64))),
                    margin + FromDIP(32), footerY);
        footerY += lineHeight;
    }
    dc.DrawText(Display("결측/무한대는 표에서 확인하세요."), margin, footerY);
}
