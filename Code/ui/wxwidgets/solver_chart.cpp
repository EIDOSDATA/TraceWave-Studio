/** @file @brief 자릿수에 맞는 눈금과 색상·선 종류를 함께 쓰는 해석 그래프다. */
#include "solver_chart.h"
#include "frequency_display.h"
#include "studio_theme.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <memory>
#include <vector>
#include <wx/dcbuffer.h>
#include <wx/graphics.h>
#include <wx/settings.h>

namespace
{
struct Axis
{
    double low;
    double high;
    double step;
};

struct Channel
{
    const char* key;
    const char* label;
    wxColour colour;
    wxPenStyle style;
};

wxString Text(const char* text)
{
    return wxString::FromUTF8(text);
}

/** @brief 1, 2, 2.5, 5의 십진 눈금으로 실제 데이터 범위를 표시한다. */
Axis DisplayAxis(double low, double high, int intervals, bool roundedBounds)
{
    if (low == high)
    {
        const double margin = std::max(0.001, std::abs(low) * 0.01);
        low -= margin;
        high += margin;
    }
    const double rough = (high - low) / intervals;
    const double unit = std::pow(10.0, std::floor(std::log10(rough)));
    if (!std::isfinite(unit) || unit <= 0.0 || !std::isfinite(high - low))
    {
        return {low, high, high - low};
    }
    for (const double multiple : {1.0, 2.0, 2.5, 5.0, 10.0})
    {
        const double step = multiple * unit;
        if (step >= rough)
        {
            return roundedBounds ? Axis{std::floor(low / step) * step, std::ceil(high / step) * step, step}
                                 : Axis{low, high, step};
        }
    }
    return {low, high, rough};
}

std::vector<double> TickValues(const Axis& axis)
{
    std::vector<double> values;
    if (!std::isfinite(axis.step) || axis.step <= 0.0)
    {
        return values;
    }
    const double first = std::ceil(axis.low / axis.step - 1e-9);
    for (int index = 0; index < 12; ++index)
    {
        const double value = (first + index) * axis.step;
        if (value > axis.high + axis.step * 1e-9)
        {
            break;
        }
        values.push_back(value);
    }
    return values;
}

wxString TickText(double value, double step)
{
    const double magnitude = std::abs(value);
    if ((magnitude > 0.0 && magnitude < 1e-6) || magnitude >= 1e9 || step < 1e-8)
    {
        return wxString::Format("%.7g", value);
    }
    int decimals = 0;
    while (decimals < 8 && std::abs(step - std::round(step)) > 1e-8)
    {
        step *= 10.0;
        ++decimals;
    }
    return wxString::Format("%.*f", decimals, value == 0.0 ? 0.0 : value);
}

/** @brief 누락값에서 경로를 끊고 독립 표본도 점으로 보여준다. */
void DrawChannel(wxDC& dc, wxGraphicsContext* graphics, const wxPen& pen,
                 const std::vector<std::vector<wxPoint2DDouble>>& groups)
{
    dc.SetPen(pen);
    if (graphics)
    {
        graphics->SetPen(pen);
        graphics->SetBrush(wxBrush(pen.GetColour()));
    }
    for (const auto& group : groups)
    {
        const auto first = group.front();
        if (group.size() == 1)
        {
            if (graphics)
            {
                const auto radius = static_cast<double>(pen.GetWidth());
                graphics->DrawEllipse(first.m_x - radius, first.m_y - radius, radius * 2, radius * 2);
            }
            else
            {
                dc.DrawPoint(wxPoint(static_cast<int>(first.m_x), static_cast<int>(first.m_y)));
            }
            continue;
        }
        if (graphics)
        {
            auto path = graphics->CreatePath();
            path.MoveToPoint(first.m_x, first.m_y);
            for (std::size_t i = 1; i < group.size(); ++i)
            {
                path.AddLineToPoint(group[i].m_x, group[i].m_y);
            }
            graphics->StrokePath(path);
        }
        else
        {
            std::vector<wxPoint> points;
            for (const auto& point : group)
            {
                points.emplace_back(static_cast<int>(std::lround(point.m_x)), static_cast<int>(std::lround(point.m_y)));
            }
            dc.DrawLines(static_cast<int>(points.size()), points.data());
        }
    }
}
}

SolverChart::SolverChart(wxWindow* parent) : wxPanel(parent)
{
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    Bind(wxEVT_PAINT, &SolverChart::Paint, this);
    Bind(wxEVT_SIZE, [this](wxSizeEvent& event)
    {
        Refresh(false);
        event.Skip();
    });
    Bind(wxEVT_SYS_COLOUR_CHANGED, [this](wxSysColourChangedEvent& event)
    {
        Refresh(false);
        event.Skip();
    });
}

/** @brief 서비스에서 허용한 유한 표시 표본을 확인하고 원본 DTO를 유지한다. */
void SolverChart::SetResult(const Json& value)
{
    if (value.value("profile", "") != "rfad.solver-chart/0.1" || !value.at("samples").is_array() ||
        value.at("samples").empty() || value.at("samples").size() > 201)
    {
        throw std::runtime_error("지원하지 않는 해석 표시 데이터입니다.");
    }
    double previous = 0.0;
    for (const auto& row : value.at("samples"))
    {
        const double frequency = row.at("frequency_hz").get<double>();
        if (!std::isfinite(frequency) || frequency <= previous)
        {
            throw std::runtime_error("해석 결과 주파수 축이 유효하지 않습니다.");
        }
        previous = frequency;
        for (const auto* key : {"s11_db", "vswr", "impedance_real_ohm", "impedance_imag_ohm"})
        {
            const auto& item = row.at(key);
            if (!item.is_null() && (!item.is_number() || !std::isfinite(item.get<double>()) || std::abs(item.get<double>()) > 1e100))
            {
                throw std::runtime_error("해석 그래프 값은 유한수 또는 미표시 값이어야 합니다.");
            }
        }
    }
    m_result = value;
    Refresh(false);
}

void SolverChart::Clear()
{
    m_result = Json::object();
    Refresh(false);
}

void SolverChart::SetMetric(int metric)
{
    m_metric = std::clamp(metric, 0, 2);
    Refresh(false);
}

std::size_t SolverChart::SampleCount() const
{
    return m_result.empty() ? 0 : m_result.at("samples").size();
}

std::size_t SolverChart::RenderedFrames() const
{
    return m_frames;
}

void SolverChart::Paint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(this);
    const auto palette = StudioTheme::Colours();
    dc.SetFont(GetFont());
    dc.SetBackground(wxBrush(palette.content));
    dc.Clear();
    dc.SetTextForeground(palette.text);
    const auto notice = [&](const char* text)
    {
        dc.DrawText(Text(text), FromDIP(12), FromDIP(12));
    };
    if (m_result.empty())
    {
        notice("해석 결과가 준비되면 그래프가 표시됩니다.");
        return;
    }
    const bool impedance = m_metric == 2;
    const bool contrast = wxSystemSettings::GetAppearance().IsUsingDarkBackground() ||
                          palette.text == palette.secondary;
    const wxColour blue = contrast ? palette.text : wxColour(19, 98, 180);
    const wxColour orange = contrast ? palette.text : wxColour(171, 76, 13);
    const std::array<Channel, 2> channels{{
        {impedance ? "impedance_real_ohm" : (m_metric == 1 ? "vswr" : "s11_db"), "실수부 (Re)", blue, wxPENSTYLE_SOLID},
        {"impedance_imag_ohm", "허수부 (Im)", orange, wxPENSTYLE_SHORT_DASH},
    }};
    const std::size_t count = impedance ? 2 : 1;
    const auto& rows = m_result.at("samples");
    const double first = rows.front().at("frequency_hz"), last = rows.back().at("frequency_hz");
    const auto scale = StudioFrequency::ForRange(first, last);
    double low = std::numeric_limits<double>::infinity(), high = -low;
    std::size_t missing = 0;
    for (const auto& row : rows)
    {
        for (std::size_t i = 0; i < count; ++i)
        {
            const auto& item = row.at(channels[i].key);
            if (item.is_null())
            {
                ++missing;
            }
            else
            {
                const auto value = item.get<double>();
                low = std::min(low, value);
                high = std::max(high, value);
            }
        }
    }
    if (!std::isfinite(low) || !std::isfinite(high))
    {
        notice("이 항목에는 표시할 수 있는 유한 표본이 없습니다.");
        return;
    }

    const auto size = GetClientSize();
    const int margin = FromDIP(12);
    const int line = dc.GetCharHeight();
    const double padding = (high - low) * 0.04;
    const Axis vertical = DisplayAxis(low - padding, high + padding, std::clamp(size.y / FromDIP(72), 3, 6), true);
    const auto axisLabel = Text(impedance ? "임피던스 (Ω)" : (m_metric == 1 ? "VSWR" : "S11 (dB)"));
    const auto legendWidth = impedance ? dc.GetTextExtent(Text(channels[0].label)).x +
                                            dc.GetTextExtent(Text(channels[1].label)).x + FromDIP(88) : 0;
    const bool wrapLegend = impedance && dc.GetTextExtent(axisLabel).x + legendWidth + margin * 3 > size.x;
    const int top = margin + line * (wrapLegend ? 2 : 1) + FromDIP(8);
    int left = margin;
    const auto yTicks = TickValues(vertical);
    for (const double tick : yTicks)
    {
        left = std::max(left, margin + dc.GetTextExtent(TickText(tick, vertical.step)).x + FromDIP(8));
    }
    const int right = size.x - FromDIP(24);
    const int bottom = size.y - margin - line * 2 - FromDIP(6);
    const int width = right - left, height = bottom - top;
    if (width < FromDIP(120) || height < FromDIP(46))
    {
        notice("그래프를 보려면 창을 넓혀 주세요.");
        return;
    }
    const Axis horizontal = DisplayAxis(first / scale.divisor, last / scale.divisor,
                                        std::clamp(width / FromDIP(96), 2, 6), false);
    const auto x = [&](double value) { return left + (value - horizontal.low) / (horizontal.high - horizontal.low) * width; };
    const auto y = [&](double value) { return bottom - (value - vertical.low) / (vertical.high - vertical.low) * height; };
    dc.DrawText(axisLabel, left, margin);
    if (impedance)
    {
        int position = wrapLegend ? left : right - legendWidth;
        const int legendY = margin + (wrapLegend ? line : 0);
        for (const auto& channel : channels)
        {
            const auto label = Text(channel.label);
            dc.SetPen(wxPen(channel.colour, FromDIP(2), channel.style));
            dc.DrawLine(position, legendY + line / 2, position + FromDIP(28), legendY + line / 2);
            position += FromDIP(34);
            dc.DrawText(label, position, legendY);
            position += dc.GetTextExtent(label).x + FromDIP(10);
        }
    }
    for (const double tick : yTicks)
    {
        const auto label = TickText(tick, vertical.step);
        const int row = static_cast<int>(std::lround(y(tick)));
        dc.SetPen(wxPen(tick == 0.0 ? palette.secondary : palette.border));
        dc.DrawLine(left, row, right, row);
        dc.DrawText(label, left - dc.GetTextExtent(label).x - FromDIP(8), row - line / 2);
    }
    int previousLabelEnd = 0;
    for (const double tick : TickValues(horizontal))
    {
        const int column = static_cast<int>(std::lround(x(tick)));
        const auto label = TickText(tick, horizontal.step);
        const int labelWidth = dc.GetTextExtent(label).x;
        const int start = std::clamp(column - labelWidth / 2, margin, std::max(margin, size.x - margin - labelWidth));
        dc.SetPen(wxPen(palette.border));
        dc.DrawLine(column, top, column, bottom);
        if (start >= previousLabelEnd + FromDIP(4))
        {
            dc.DrawText(label, start, bottom + FromDIP(4));
            previousLabelEnd = start + labelWidth;
        }
    }
    dc.SetPen(wxPen(palette.secondary));
    dc.DrawLine(left, top, left, bottom);
    dc.DrawLine(left, bottom, right + 1, bottom);
    const auto frequencyLabel = Text("주파수 (") + wxString::FromUTF8(scale.unit.c_str()) + ")";
    dc.DrawText(frequencyLabel, right - dc.GetTextExtent(frequencyLabel).x, bottom + line + FromDIP(6));
    if (missing)
    {
        dc.DrawText(Text("미표시 표본 ") + wxString::Format("%zu", missing), left, bottom + line + FromDIP(6));
    }

    dc.SetClippingRegion(left, top, width + 1, height + 1);
    auto graphics = std::unique_ptr<wxGraphicsContext>(wxGraphicsContext::CreateFromUnknownDC(dc));
    if (graphics)
    {
        graphics->Clip(left, top, width + 1, height + 1);
    }
    for (std::size_t i = 0; i < count; ++i)
    {
        const auto& channel = channels[i];
        std::vector<std::vector<wxPoint2DDouble>> groups;
        bool begin = true;
        for (const auto& row : rows)
        {
            const auto& item = row.at(channel.key);
            if (item.is_null())
            {
                begin = true;
                continue;
            }
            if (begin)
            {
                groups.emplace_back();
                begin = false;
            }
            groups.back().emplace_back(x(row.at("frequency_hz").get<double>() / scale.divisor), y(item.get<double>()));
        }
        DrawChannel(dc, graphics.get(), wxPen(channel.colour, FromDIP(2), channel.style), groups);
    }
    graphics.reset();
    dc.DestroyClippingRegion();
    ++m_frames;
}
