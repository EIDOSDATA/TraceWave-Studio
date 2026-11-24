/** @file @brief 단위원 바깥 표본과 무한/결측 상태를 숨기지 않는 Smith 표시다. */
#include "smith_chart.h"
#include "studio_theme.h"
#include "studio_support.h"
#include <wx/dcbuffer.h>
#include <wx/graphics.h>
#include <algorithm>
#include <cmath>
#include <memory>

namespace
{
constexpr double Pi = 3.14159265358979323846;

bool Coordinates(const Json& point, double& x, double& y)
{
    if (!point.value("smith_valid", false))
    {
        return false;
    }
    const auto pair = point.value("gamma_ri", Json(nullptr));
    if (!pair.is_array() || pair.size() != 2 || !pair.at(0).is_number() || !pair.at(1).is_number())
    {
        return false;
    }
    x = pair.at(0).get<double>();
    y = pair.at(1).get<double>();
    return std::isfinite(x) && std::isfinite(y);
}
}

SmithChart::SmithChart(wxWindow* parent) : wxPanel(parent)
{
    SetName("result.smith.chart");
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    SetMinSize(FromDIP(wxSize(300, 300)));
    Bind(wxEVT_PAINT, &SmithChart::Paint, this);
    Bind(wxEVT_LEFT_DOWN, &SmithChart::Select, this);
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Refresh(false);
             event.Skip();
         });
    Bind(wxEVT_SYS_COLOUR_CHANGED,
         [this](wxSysColourChangedEvent& event)
         {
             Refresh(false);
             event.Skip();
         });
    Clear();
}

void SmithChart::SetPage(const Json& result)
{
    m_result = result;
    m_marker = -1;
    m_reason.clear();
    Refresh(false);
}

void SmithChart::SetMarker(int index)
{
    m_marker = index;
    Refresh(false);
}

void SmithChart::Clear(const std::string& reason)
{
    m_result = nullptr;
    m_marker = -1;
    m_hits.clear();
    m_reason = reason;
    Refresh(false);
}

void SmithChart::Select(wxMouseEvent& event)
{
    SetFocus();
    const auto cursor = event.GetPosition();
    const int threshold = FromDIP(14);
    int best = threshold * threshold;
    int index = -1;
    for (const auto& hit : m_hits)
    {
        const auto distance = hit.first - cursor;
        const int squared = distance.x * distance.x + distance.y * distance.y;
        if (squared < best)
        {
            index = hit.second;
            best = squared;
        }
    }
    if (index >= 0 && onMarker)
    {
        onMarker(index);
    }
}

void SmithChart::Paint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(this);
    const auto colours = StudioTheme::Colours();
    dc.SetBackground(wxBrush(colours.content));
    dc.Clear();
    dc.SetFont(GetFont());
    dc.SetTextForeground(colours.secondary);
    m_hits.clear();
    const auto size = GetClientSize();
    const int margin = FromDIP(24);
    const int available = std::min(size.x - margin * 2, size.y - FromDIP(100));
    if (available < FromDIP(80))
    {
        return;
    }
    const auto points = m_result.is_object() ? m_result.value("points", Json::array()) : Json::array();
    double extent = 1.0;
    std::size_t outside = 0;
    std::size_t omitted = 0;
    for (const auto& point : points)
    {
        double x = 0.0, y = 0.0;
        if (!Coordinates(point, x, y))
        {
            ++omitted;
            continue;
        }
        const double distance = std::hypot(x, y);
        if (!std::isfinite(distance) || distance > 1e6)
        {
            ++omitted;
            continue;
        }
        extent = std::max(extent, distance);
        outside += distance > 1.0 ? 1 : 0;
    }
    /** @brief 확대 범위는 표시 좌표에만 적용하며 반사계수를 단위원 안으로 자르지 않는다. */
    const double radius = available / (2.0 * extent * 1.05);
    const double centerX = size.x / 2.0;
    const double centerY = FromDIP(38) + available / 2.0;
    const auto position = [centerX, centerY, radius](double x, double y)
    {
        return wxPoint2DDouble(centerX + x * radius, centerY - y * radius);
    };
    std::unique_ptr<wxGraphicsContext> gc(wxGraphicsContext::Create(dc));
    if (!gc)
    {
        dc.DrawText(Display("Smith 표시 컨텍스트를 만들 수 없습니다. 실제 표본 표를 사용하세요."), margin, margin);
        return;
    }
    const bool admittance = m_result.is_object() && m_result.value("chart", "impedance") == "admittance";
    const double orientation = admittance ? -1.0 : 1.0;
    dc.DrawText(Display(admittance ? "실제 Gamma와 정규화 어드미턴스 격자" : "실제 Gamma와 정규화 임피던스 격자"),
                margin, FromDIP(10));
    const wxColour gridColour((colours.border.Red() + colours.secondary.Red()) / 2,
                              (colours.border.Green() + colours.secondary.Green()) / 2,
                              (colours.border.Blue() + colours.secondary.Blue()) / 2);
    gc->SetPen(wxPen(colours.secondary, FromDIP(1)));
    gc->SetBrush(*wxTRANSPARENT_BRUSH);
    gc->DrawEllipse(centerX - radius, centerY - radius, 2 * radius, 2 * radius);
    gc->StrokeLine(centerX - radius, centerY, centerX + radius, centerY);
    gc->SetPen(wxPen(gridColour, FromDIP(1)));
    for (double resistance : {0.2, 0.5, 1.0, 2.0, 5.0})
    {
        const double localRadius = radius / (1.0 + resistance);
        const auto center = position(orientation * resistance / (1.0 + resistance), 0.0);
        gc->DrawEllipse(center.m_x - localRadius, center.m_y - localRadius, 2 * localRadius, 2 * localRadius);
    }
    for (double reactance : {-5.0, -2.0, -1.0, -0.5, -0.2, 0.2, 0.5, 1.0, 2.0, 5.0})
    {
        auto path = gc->CreatePath();
        bool connected = false;
        for (int step = 0; step <= 720; ++step)
        {
            const double angle = step * Pi / 360.0;
            const double x = orientation * (1.0 + std::cos(angle) / std::abs(reactance));
            const double y = orientation * (1.0 / reactance + std::sin(angle) / std::abs(reactance));
            if (x * x + y * y > 1.0 + 1e-9)
            {
                connected = false;
                continue;
            }
            const auto p = position(x, y);
            if (connected)
            {
                path.AddLineToPoint(p);
            }
            else
            {
                path.MoveToPoint(p);
            }
            connected = true;
        }
        gc->StrokePath(path);
    }
    /** @brief 눈금은 정규화 격자의 기하이며 원본 반사 표본을 변환하거나 보간하지 않는다. */
    if (radius >= FromDIP(90))
    {
        const auto label = [&dc, &colours, &size, this](const wxString& text, double x, double y)
        {
            const auto extent = dc.GetTextExtent(text);
            const int left = std::clamp(static_cast<int>(x - extent.x / 2.0), FromDIP(4),
                                        std::max(FromDIP(4), size.x - extent.x - FromDIP(4)));
            const int top = std::clamp(static_cast<int>(y - extent.y / 2.0), FromDIP(30),
                                       std::max(FromDIP(30), size.y - extent.y - FromDIP(54)));
            dc.SetPen(*wxTRANSPARENT_PEN);
            dc.SetBrush(wxBrush(colours.content));
            dc.DrawRectangle(left - FromDIP(2), top, extent.x + FromDIP(4), extent.y);
            dc.SetTextForeground(colours.secondary);
            dc.DrawText(text, left, top);
        };
        for (double resistance : {0.2, 0.5, 1.0, 2.0, 5.0})
        {
            const auto p = position(orientation * (resistance - 1.0) / (resistance + 1.0), 0.0);
            label(wxString::Format("%.1g", resistance), p.m_x, p.m_y + FromDIP(12));
        }
        label(admittance ? "g" : "r", centerX + orientation * radius * 0.88, centerY + FromDIP(12));
        for (double reactance : {-5.0, -2.0, -1.0, -0.5, 0.5, 1.0, 2.0, 5.0})
        {
            const double denominator = 1.0 + reactance * reactance;
            const auto p = position(orientation * (reactance * reactance - 1.0) / denominator * 0.87,
                                    orientation * 2.0 * reactance / denominator * 0.87);
            label((admittance ? "b=" : "x=") + wxString::Format("%.1g", reactance), p.m_x, p.m_y);
        }
    }
    gc->SetPen(wxPen(colours.accent, FromDIP(2)));
    gc->SetBrush(wxBrush(colours.accent));
    bool connected = false;
    int previousIndex = -1;
    wxPoint2DDouble previous;
    for (const auto& point : points)
    {
        double x = 0.0, y = 0.0;
        if (!Coordinates(point, x, y) || !std::isfinite(std::hypot(x, y)) || std::hypot(x, y) > 1e6)
        {
            connected = false;
            continue;
        }
        const auto p = position(x, y);
        const int index = point.value("index", -1);
        if (connected && index == previousIndex + 1)
        {
            gc->StrokeLine(previous.m_x, previous.m_y, p.m_x, p.m_y);
        }
        const int dot = FromDIP(index == m_marker ? 5 : 2);
        gc->DrawEllipse(p.m_x - dot, p.m_y - dot, 2 * dot, 2 * dot);
        if (index == m_marker)
        {
            dc.SetTextForeground(colours.accent);
            dc.DrawText("M1", static_cast<int>(p.m_x) + FromDIP(8), static_cast<int>(p.m_y) - FromDIP(16));
        }
        m_hits.push_back({wxPoint(static_cast<int>(p.m_x), static_cast<int>(p.m_y)), index});
        previous = p;
        previousIndex = index;
        connected = true;
    }
    dc.SetTextForeground(colours.secondary);
    const std::string notice = points.empty()
                                   ? (m_reason.empty() ? "표시할 실제 반사 표본이 없습니다." : m_reason)
                                   : "실제 " + std::to_string(points.size()) + "표본, 단위원 밖 " +
                                         std::to_string(outside) + ", 결측 또는 표시 범위 밖 " + std::to_string(omitted);
    dc.DrawText(Display(notice), margin, size.y - FromDIP(45));
    dc.DrawText(Display("선은 인접 표본의 시각적 연결이며 중간 RF 값을 만들지 않습니다."), margin,
                size.y - FromDIP(25));
}
