/** @file @brief 실제 필드 표본 사이를 합성하지 않는 좌표 단면과 키보드 마커다. */
#include "field_slice_canvas.h"
#include "studio_theme.h"
#include <wx/dcbuffer.h>
#include <wx/graphics.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <memory>

namespace
{
wxString Display(const std::string& text)
{
    return wxString::FromUTF8(text.data(), text.size());
}

/** @brief 서비스가 결정한 색 범위의 위치만 표시 팔레트로 바꾼다. */
wxColour Colour(double position)
{
    const std::array<std::array<int, 3>, 4> colours{{{{38, 75, 145}}, {{71, 164, 191}}, {{245, 220, 122}}, {{198, 54, 44}}}};
    const double scaled = std::clamp(position, 0.0, 1.0) * 3.0;
    const int start = std::min(2, static_cast<int>(scaled));
    const double fraction = scaled - start;
    const auto channel = [&](int index)
    {
        return static_cast<unsigned char>(colours[start][index] * (1.0 - fraction) + colours[start + 1][index] * fraction);
    };
    return wxColour(channel(0), channel(1), channel(2));
}

bool Coordinates(const Json& value, std::vector<double>& output)
{
    if (!value.is_array() || value.empty() || value.size() > 4096)
    {
        return false;
    }
    for (const auto& coordinate : value)
    {
        if (!coordinate.is_number())
        {
            return false;
        }
        const double number = coordinate.get<double>();
        if (!std::isfinite(number) || (!output.empty() && number <= output.back()))
        {
            return false;
        }
        output.push_back(number);
    }
    return true;
}
}

FieldSliceCanvas::FieldSliceCanvas(wxWindow* parent) : wxPanel(parent)
{
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    SetMinSize(FromDIP(wxSize(320, 260)));
    SetName(Display("기록 필드 단면. 방향키로 실제 표본 이동"));
    Bind(wxEVT_PAINT, &FieldSliceCanvas::Paint, this);
    Bind(wxEVT_LEFT_DOWN, &FieldSliceCanvas::Select, this);
    Bind(wxEVT_CHAR, &FieldSliceCanvas::Key, this);
    Bind(wxEVT_SIZE, [this](wxSizeEvent& event)
    {
        Refresh();
        event.Skip();
    });
    Bind(wxEVT_SYS_COLOUR_CHANGED, [this](wxSysColourChangedEvent& event)
    {
        Refresh();
        event.Skip();
    });
}

bool FieldSliceCanvas::SetSlice(const Json& slice)
{
    m_u.clear();
    m_v.clear();
    m_marker = 0;
    try
    {
        if (!Coordinates(slice.at("u_coordinates_mm"), m_u) || !Coordinates(slice.at("v_coordinates_mm"), m_v)
            || m_u.size() * m_v.size() > 4096 || !slice.at("color").is_array() || slice.at("color").size() != m_v.size())
        {
            Clear("기록 필드의 좌표 또는 표시 크기가 유효하지 않습니다.");
            return false;
        }
        const auto& range = slice.at("color_range");
        if (!range.is_array() || range.size() != 2 || !range[0].is_number() || !range[1].is_number()
            || !std::isfinite(range[0].get<double>()) || !std::isfinite(range[1].get<double>())
            || range[1].get<double>() < range[0].get<double>())
        {
            Clear("필드 색 범위가 유효하지 않습니다.");
            return false;
        }
        m_minimum = range[0].get<double>();
        m_maximum = range[1].get<double>();
        m_uLabel = slice.value("u_axis", "u") + " (mm)";
        m_vLabel = slice.value("v_axis", "v") + " (mm)";
        m_unit = slice.value("unit", "");
        m_colors.clear();
        m_colors.reserve(m_u.size() * m_v.size());
        for (const auto& row : slice.at("color"))
        {
            if (!row.is_array() || row.size() != m_u.size())
            {
                Clear("기록 필드의 행 크기가 좌표와 다릅니다.");
                return false;
            }
            for (const auto& cell : row)
            {
                const double value = cell.is_number() ? cell.get<double>() : std::numeric_limits<double>::quiet_NaN();
                if (!std::isfinite(value))
                {
                    m_colors.emplace_back();
                    continue;
                }
                const double position = m_maximum > m_minimum ? (value - m_minimum) / (m_maximum - m_minimum) : 0.5;
                m_colors.push_back(Colour(position));
            }
        }
        m_message.clear();
        Refresh();
        return true;
    }
    catch (const Json::exception&)
    {
        Clear("필드 표시 응답의 필수 항목을 확인할 수 없습니다.");
        return false;
    }
}

void FieldSliceCanvas::Clear(const std::string& message)
{
    m_colors.clear();
    m_u.clear();
    m_v.clear();
    m_message = message;
    Refresh();
}

void FieldSliceCanvas::SetMarker(std::size_t index)
{
    if (!m_u.empty() && index < m_u.size() * m_v.size())
    {
        m_marker = index;
        Refresh();
    }
}

double FieldSliceCanvas::PixelU(std::size_t index) const
{
    return m_plot.x + (m_u.size() == 1 ? 0.5 : (m_u[index] - m_u.front()) / (m_u.back() - m_u.front())) * m_plot.width;
}

double FieldSliceCanvas::PixelV(std::size_t index) const
{
    return m_plot.GetBottom() - (m_v.size() == 1 ? 0.5 : (m_v[index] - m_v.front()) / (m_v.back() - m_v.front())) * m_plot.height;
}

void FieldSliceCanvas::Paint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(this);
    const auto colours = StudioTheme::Colours();
    dc.SetBackground(wxBrush(colours.content));
    dc.Clear();
    std::unique_ptr<wxGraphicsContext> context(wxGraphicsContext::Create(dc));
    if (!context)
    {
        return;
    }
    context->SetFont(GetFont(), colours.text);
    if (m_colors.empty())
    {
        context->DrawText(Display(m_message.empty() ? "기록된 필드 단면을 선택하십시오." : m_message), FromDIP(16), FromDIP(22));
        return;
    }
    const auto size = GetClientSize();
    m_plot = wxRect(FromDIP(64), FromDIP(30), std::max(1, size.x - FromDIP(176)), std::max(1, size.y - FromDIP(96)));
    if (m_u.size() > 1 && m_v.size() > 1)
    {
        const double rangeU = m_u.back() - m_u.front();
        const double rangeV = m_v.back() - m_v.front();
        const double scale = std::min(m_plot.width / rangeU, m_plot.height / rangeV);
        const int width = std::max(1, static_cast<int>(rangeU * scale));
        const int height = std::max(1, static_cast<int>(rangeV * scale));
        m_plot.x += (m_plot.width - width) / 2;
        m_plot.y += (m_plot.height - height) / 2;
        m_plot.width = width;
        m_plot.height = height;
    }
    context->SetPen(*wxTRANSPARENT_PEN);
    context->Clip(m_plot.x, m_plot.y, m_plot.width, m_plot.height);
    for (std::size_t row = 0; row < m_v.size(); ++row)
    {
        for (std::size_t column = 0; column < m_u.size(); ++column)
        {
            const auto& color = m_colors[row * m_u.size() + column];
            if (!color.IsOk())
            {
                continue;
            }
            const double left = m_u.size() == 1 ? PixelU(column) - FromDIP(6)
                : (column == 0 ? PixelU(column) : (PixelU(column - 1) + PixelU(column)) * 0.5);
            const double right = m_u.size() == 1 ? PixelU(column) + FromDIP(6)
                : (column + 1 == m_u.size() ? PixelU(column) : (PixelU(column + 1) + PixelU(column)) * 0.5);
            const double top = m_v.size() == 1 ? PixelV(row) - FromDIP(6)
                : (row + 1 == m_v.size() ? PixelV(row) : (PixelV(row + 1) + PixelV(row)) * 0.5);
            const double bottom = m_v.size() == 1 ? PixelV(row) + FromDIP(6)
                : (row == 0 ? PixelV(row) : (PixelV(row - 1) + PixelV(row)) * 0.5);
            context->SetBrush(wxBrush(color));
            context->DrawRectangle(left, top, std::max(1.0, right - left), std::max(1.0, bottom - top));
        }
    }
    context->ResetClip();
    context->SetPen(wxPen(colours.border));
    context->SetBrush(*wxTRANSPARENT_BRUSH);
    context->DrawRectangle(m_plot.x, m_plot.y, m_plot.width, m_plot.height);
    context->DrawText(Display(m_vLabel), m_plot.x, m_plot.y - FromDIP(24));
    context->DrawText(Display(m_uLabel), m_plot.x + m_plot.width * 0.5, m_plot.GetBottom() + FromDIP(30));
    context->DrawText(wxString::Format("%.6g", m_u.front()), m_plot.x, m_plot.GetBottom() + FromDIP(7));
    context->DrawText(wxString::Format("%.6g", m_u.back()), m_plot.GetRight() - FromDIP(40), m_plot.GetBottom() + FromDIP(7));
    const auto ordinate = [&](double value, int y)
    {
        const auto label = wxString::Format("%.6g", value);
        double width = 0, height = 0;
        context->GetTextExtent(label, &width, &height);
        context->DrawText(label, std::max(0.0, m_plot.x - width - FromDIP(6)), y);
    };
    ordinate(m_v.front(), m_plot.GetBottom() - FromDIP(15));
    if (m_v.size() > 1)
    {
        ordinate(m_v.back(), m_plot.y);
    }
    const double legendX = m_plot.GetRight() + FromDIP(18);
    const double legendWidth = FromDIP(15);
    context->SetPen(*wxTRANSPARENT_PEN);
    for (int i = 0; i < 64; ++i)
    {
        context->SetBrush(wxBrush(Colour(1.0 - static_cast<double>(i) / 63.0)));
        context->DrawRectangle(legendX, m_plot.y + m_plot.height * i / 64.0, legendWidth, m_plot.height / 64.0 + 1);
    }
    context->DrawText(wxString::Format("%.4g", m_maximum), legendX + legendWidth + FromDIP(5), m_plot.y);
    context->DrawText(wxString::Format("%.4g", m_minimum), legendX + legendWidth + FromDIP(5), m_plot.GetBottom() - FromDIP(16));
    context->DrawText(Display(m_unit), legendX, m_plot.GetBottom() + FromDIP(22));
    const double markerX = PixelU(m_marker % m_u.size());
    const double markerY = PixelV(m_marker / m_u.size());
    context->SetPen(wxPen(*wxWHITE, FromDIP(3)));
    context->SetBrush(*wxTRANSPARENT_BRUSH);
    context->DrawEllipse(markerX - FromDIP(6), markerY - FromDIP(6), FromDIP(12), FromDIP(12));
    context->SetPen(wxPen(colours.text, FromDIP(1)));
    context->DrawEllipse(markerX - FromDIP(7), markerY - FromDIP(7), FromDIP(14), FromDIP(14));
}

void FieldSliceCanvas::Select(wxMouseEvent& event)
{
    SetFocus();
    if (m_u.empty() || m_v.empty() || !m_plot.Contains(event.GetPosition()))
    {
        return;
    }
    std::size_t column = 0;
    std::size_t row = 0;
    double closest = std::numeric_limits<double>::max();
    for (std::size_t i = 0; i < m_u.size(); ++i)
    {
        if (std::abs(PixelU(i) - event.GetX()) < closest)
        {
            closest = std::abs(PixelU(i) - event.GetX());
            column = i;
        }
    }
    closest = std::numeric_limits<double>::max();
    for (std::size_t i = 0; i < m_v.size(); ++i)
    {
        if (std::abs(PixelV(i) - event.GetY()) < closest)
        {
            closest = std::abs(PixelV(i) - event.GetY());
            row = i;
        }
    }
    SetMarker(row * m_u.size() + column);
    if (onMarker)
    {
        onMarker(m_marker);
    }
}

void FieldSliceCanvas::Key(wxKeyEvent& event)
{
    if (m_u.empty() || m_v.empty())
    {
        event.Skip();
        return;
    }
    const long long columns = static_cast<long long>(m_u.size());
    const long long count = columns * static_cast<long long>(m_v.size());
    long long index = static_cast<long long>(m_marker);
    switch (event.GetKeyCode())
    {
        case WXK_LEFT:
            --index;
            break;
        case WXK_RIGHT:
            ++index;
            break;
        case WXK_UP:
            index += columns;
            break;
        case WXK_DOWN:
            index -= columns;
            break;
        default:
            event.Skip();
            return;
    }
    SetMarker(static_cast<std::size_t>(std::clamp(index, 0LL, count - 1)));
    if (onMarker)
    {
        onMarker(m_marker);
    }
}
