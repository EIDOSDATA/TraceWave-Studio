/** @file @brief 실제 격자선을 별도 설계 눈금 없이 해석 입력 경계와 함께 그린다. */
#include "solver_mesh_view.h"
#include "studio_support.h"
#include "studio_theme.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <vector>
#include <wx/dcbuffer.h>

namespace
{
using Span = std::array<double, 2>;
using Bounds = std::array<Span, 3>;
constexpr std::array<const char*, 3> Axes{"x", "y", "z"};
constexpr std::array<std::array<int, 2>, 3> Planes{{{0, 1}, {0, 2}, {1, 2}}};

/** @brief 길이가 수 픽셀인 시트도 원래 Z 위치에서 가로선으로 남긴다. */
void Rectangle(wxDC& dc, const wxPoint& a, const wxPoint& b)
{
    if (a.x == b.x || a.y == b.y)
    {
        dc.DrawLine(a, b);
        return;
    }
    dc.DrawRectangle(wxRect(wxPoint(std::min(a.x, b.x), std::min(a.y, b.y)),
                            wxPoint(std::max(a.x, b.x), std::max(a.y, b.y))));
}

/** @brief 측면 보기에서만 사용하는 입력 primitive별 축 범위다. */
Bounds PrimitiveBounds(const Json& primitive)
{
    const auto kind = primitive.at("kind").get<std::string>();
    if (kind == "box")
    {
        return primitive.at("bounds_mm").get<Bounds>();
    }
    const auto z = primitive.at("z_mm").get<Span>();
    if (kind == "circle")
    {
        const auto center = primitive.at("center_mm").get<Span>();
        const double radius = primitive.at("radius_mm");
        return {{{center[0] - radius, center[0] + radius}, {center[1] - radius, center[1] + radius}, z}};
    }
    Bounds result{{{std::numeric_limits<double>::max(), std::numeric_limits<double>::lowest()},
                   {std::numeric_limits<double>::max(), std::numeric_limits<double>::lowest()}, z}};
    for (const auto& point : primitive.at("points_mm"))
    {
        for (int axis = 0; axis < 2; ++axis)
        {
            const double value = point.at(axis).get<double>();
            result[axis][0] = std::min(result[axis][0], value);
            result[axis][1] = std::max(result[axis][1], value);
        }
    }
    return result;
}

wxColour ComponentColour(const std::string& role, bool accessible, const StudioTheme::Palette& palette)
{
    if (accessible)
    {
        return palette.text;
    }
    if (role == "conductor" || role == "via")
    {
        return wxColour(156, 72, 14);
    }
    if (role == "environment")
    {
        return wxColour(29, 112, 73);
    }
    if (role == "port" || role == "void")
    {
        return wxColour(173, 38, 59);
    }
    return wxColour(48, 95, 139);
}
}

SolverMeshView::SolverMeshView(wxWindow* parent)
    : wxPanel(parent, wxID_ANY)
{
    SetName("solver.review.mesh_view");
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    SetMinSize(FromDIP(wxSize(260, 170)));
    Bind(wxEVT_PAINT, &SolverMeshView::Paint, this);
    Bind(wxEVT_SIZE, [this](wxSizeEvent& event)
    {
        Refresh(false);
        event.Skip();
    });
}

void SolverMeshView::DisplayPlan(const Json* review)
{
    m_review = review;
    m_highlight.clear();
    Refresh(false);
}

void SolverMeshView::SetView(int plane, bool full)
{
    m_plane = plane;
    m_full = full;
    Refresh(false);
}

void SolverMeshView::Highlight(const std::string& id)
{
    m_highlight = id;
    Refresh(false);
}

/** @brief 모든 입력 좌표를 사용하되 같은 픽셀에 표시되는 격자선은 한 번만 그린다. */
void SolverMeshView::Paint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(this);
    const auto palette = StudioTheme::Colours();
    dc.SetBackground(wxBrush(palette.content));
    dc.Clear();
    dc.SetTextForeground(palette.text);
    if (!m_review)
    {
        dc.DrawText(Display("조건을 검토하면 해석 격자와 포함 형상을 표시합니다."), FromDIP(12), FromDIP(12));
        return;
    }

    const auto [first, second] = Planes.at(static_cast<std::size_t>(m_plane));
    const auto& mesh = m_review->at("mesh");
    const auto& lines = mesh.at("lines_mm");
    const auto& uLines = lines.at(Axes[first]);
    const auto& vLines = lines.at(Axes[second]);
    const auto model = mesh.at("model_bounds_mm").get<Bounds>();
    const auto extent = [&](int axis, const Json& axisLines)
    {
        const double low = axisLines.front().get<double>();
        const double high = axisLines.back().get<double>();
        const double margin = std::max((model[axis][1] - model[axis][0]) * 0.08, 0.5);
        return m_full ? Span{low, high}
                      : Span{std::max(low, model[axis][0] - margin), std::min(high, model[axis][1] + margin)};
    };
    const auto u = extent(first, uLines);
    const auto v = extent(second, vLines);
    const int pad = FromDIP(22);
    const auto size = GetClientSize();
    const double availableWidth = size.x - 2 * pad;
    const double availableHeight = size.y - 2 * pad;
    if (availableWidth <= 0 || availableHeight <= 0)
    {
        return;
    }
    const double scale = std::min(availableWidth / (u[1] - u[0]), availableHeight / (v[1] - v[0]));
    const double left = (size.x - (u[1] - u[0]) * scale) / 2;
    const double bottom = (size.y + (v[1] - v[0]) * scale) / 2;
    const auto point = [&](double x, double y)
    {
        return wxPoint(static_cast<int>(std::lround(left + (x - u[0]) * scale)),
                       static_cast<int>(std::lround(bottom - (y - v[0]) * scale)));
    };
    const auto topLeft = point(u[0], v[1]);
    const auto bottomRight = point(u[1], v[0]);
    dc.SetClippingRegion(wxRect(topLeft, bottomRight));
    const bool accessible = palette.content.GetLuminance() < 0.25;
    dc.SetPen(wxPen(accessible ? palette.border : wxColour(218, 226, 233)));
    const auto drawAxis = [&](const Json& positions, bool horizontal, const Span& visible)
    {
        int previous = std::numeric_limits<int>::min();
        for (const auto& coordinate : positions)
        {
            const double value = coordinate;
            if (value < visible[0] || value > visible[1])
            {
                continue;
            }
            const int pixel = horizontal ? point(value, v[0]).x : point(u[0], value).y;
            if (pixel != previous)
            {
                if (horizontal)
                {
                    dc.DrawLine(pixel, topLeft.y, pixel, bottomRight.y + 1);
                }
                else
                {
                    dc.DrawLine(topLeft.x, pixel, bottomRight.x + 1, pixel);
                }
            }
            previous = pixel;
        }
    };
    drawAxis(uLines, true, u);
    drawAxis(vLines, false, v);
    auto markPml = [&](int axis, bool horizontal, const Span& visible)
    {
        for (const auto& coordinate : mesh.at("axes").at(Axes[axis]).at("pml_inner_mm"))
        {
            const double value = coordinate;
            if (visible[0] <= value && value <= visible[1])
            {
                if (horizontal)
                {
                    dc.DrawLine(point(value, v[0]), point(value, v[1]));
                }
                else
                {
                    dc.DrawLine(point(u[0], value), point(u[1], value));
                }
            }
        }
    };
    dc.SetPen(wxPen(accessible ? palette.accent : wxColour(100, 72, 155), FromDIP(2), wxPENSTYLE_SHORT_DASH));
    markPml(first, true, u);
    markPml(second, false, v);
    dc.SetBrush(*wxTRANSPARENT_BRUSH);
    const auto& rows = m_review->at("model").at("included");
    const auto drawComponent = [&](const Json& row, bool selected)
    {
        const auto role = row.at("role").get<std::string>();
        for (const auto& primitive : row.at("primitives"))
        {
            const auto kind = primitive.at("kind").get<std::string>();
            const auto colour = selected ? palette.accent : ComponentColour(role, accessible, palette);
            const auto style = primitive.value("opening", false) || role == "void"
                                 ? wxPENSTYLE_SHORT_DASH : wxPENSTYLE_SOLID;
            dc.SetPen(wxPen(colour, FromDIP(selected ? 3 : role == "port" ? 2 : 1), style));
            if (kind == "segment")
            {
                const auto a = primitive.at("start_mm").get<std::array<double, 3>>();
                const auto b = primitive.at("stop_mm").get<std::array<double, 3>>();
                dc.DrawLine(point(a[first], a[second]), point(b[first], b[second]));
                dc.DrawCircle(point(a[first], a[second]), FromDIP(3));
                dc.DrawCircle(point(b[first], b[second]), FromDIP(3));
            }
            else if (m_plane == 0 && kind == "polygon")
            {
                std::vector<wxPoint> polygon;
                const auto& points = primitive.at("points_mm");
                polygon.reserve(points.size() + 1);
                for (const auto& p : points)
                {
                    polygon.push_back(point(p.at(0).get<double>(), p.at(1).get<double>()));
                }
                polygon.push_back(polygon.front());
                dc.DrawLines(static_cast<int>(polygon.size()), polygon.data());
            }
            else
            {
                const auto bounds = PrimitiveBounds(primitive);
                const auto a = point(bounds[first][0], bounds[second][1]);
                const auto b = point(bounds[first][1], bounds[second][0]);
                if (m_plane == 0 && kind == "circle")
                {
                    dc.DrawEllipse(wxRect(a, b));
                }
                else
                {
                    Rectangle(dc, a, b);
                }
            }
        }
    };
    const Json* highlighted = nullptr;
    for (const auto& row : rows)
    {
        if (row.at("id") == m_highlight)
        {
            highlighted = &row;
        }
        else
        {
            drawComponent(row, false);
        }
    }
    if (highlighted)
    {
        drawComponent(*highlighted, true);
    }
    dc.DestroyClippingRegion();
    dc.SetPen(wxPen(palette.border));
    Rectangle(dc, topLeft, bottomRight);
    const int top = std::max(0, topLeft.y - dc.GetCharHeight());
    dc.DrawText(wxString::FromUTF8(Axes[second]) + " / mm", topLeft.x, top);
    dc.DrawText(wxString::FromUTF8(Axes[first]) + " / mm", bottomRight.x - FromDIP(46), bottomRight.y);
}
