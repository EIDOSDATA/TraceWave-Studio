#include "canvas_renderer.h"
#include <algorithm>
#include <cmath>

namespace
{
using Point = CanvasGeometry::Point;
}

CanvasRenderer::CanvasRenderer(wxWindow& window, wxDC& dc, CanvasViewport viewport,
                               StudioAppearance::CanvasColours colours, wxRect damage)
    : m_window(window), m_dc(dc), m_viewport(viewport), m_colours(std::move(colours)), m_pathPadding(window.FromDIP(8)),
      m_damage(damage.IsEmpty() ? wxRect(0, 0, viewport.width, viewport.height) : damage)
{
}

void CanvasRenderer::Flush()
{
    if (m_unflushed)
    {
        m_graphics->Flush();
        m_unflushed = false;
    }
}

CanvasRenderer::~CanvasRenderer()
{
    Flush();
}

int CanvasRenderer::FromDIP(int value) const
{
    return m_window.FromDIP(value);
}

wxPoint CanvasRenderer::WorldToScreen(Point point) const
{
    const Point pixel = m_viewport.Project(point);
    return wxPoint(static_cast<int>(std::llround(std::clamp(pixel.x, -1e7, 1e7))),
                   static_cast<int>(std::llround(std::clamp(pixel.y, -1e7, 1e7))));
}

/** @brief 현재 축척에 맞는 격자 간격과 원점을 표시한다. */
void CanvasRenderer::DrawGrid(bool visible)
{
    const wxSize size = wxSize(m_viewport.width, m_viewport.height);
    const Point low = m_viewport.Unproject({0.0, static_cast<double>(size.y)});
    const Point high = m_viewport.Unproject({static_cast<double>(size.x), 0.0});
    if (visible)
    {
        const double step = m_viewport.GridStep();
        m_dc.SetPen(wxPen(m_colours.Detail(wxColour(229, 237, 249)), 1,
                         m_colours.HighContrast() ? wxPENSTYLE_DOT : wxPENSTYLE_SOLID));
        const double startX = std::ceil(low.x / step) * step;
        const double startY = std::ceil(low.y / step) * step;
        for (int i = 0; i < 400 && startX + i * step <= high.x; ++i)
        {
            const int x = WorldToScreen(Point{startX + i * step, 0.0}).x;
            m_dc.DrawLine(x, 0, x, size.y);
        }
        for (int i = 0; i < 400 && startY + i * step <= high.y; ++i)
        {
            const int y = WorldToScreen(Point{0.0, startY + i * step}).y;
            m_dc.DrawLine(0, y, size.x, y);
        }
    }
    const wxPoint origin = WorldToScreen(Point{0.0, 0.0});
    m_dc.SetPen(wxPen(m_colours.Detail(wxColour(151, 163, 176)), 1));
    if (origin.x >= 0 && origin.x <= size.x)
    {
        m_dc.DrawLine(origin.x, 0, origin.x, size.y);
    }
    if (origin.y >= 0 && origin.y <= size.y)
    {
        m_dc.DrawLine(0, origin.y, size.x, origin.y);
    }
    m_dc.SetTextForeground(m_colours.Detail(wxColour(94, 107, 121)));
    m_dc.DrawText("X / mm", std::max(2, size.x - FromDIP(60)),
                  std::clamp(origin.y + 4, 2, std::max(2, size.y - FromDIP(22))));
    m_dc.DrawText("Y / mm", std::clamp(origin.x + 4, 2, std::max(2, size.x - FromDIP(60))), FromDIP(4));
}

/** @brief 기판 외곽은 도체와 별도 배경으로 표시한다. */
void CanvasRenderer::DrawBoard(const CanvasScene::Model& scene)
{
    if (scene.hasBoard)
    {
        const wxColour outline = m_colours.Detail(wxColour(118, 151, 131));
        const wxColour fill = m_colours.HighContrast() ? m_colours.background : wxColour(198, 227, 203);
        if (!scene.boardOuter.empty())
        {
            std::vector<wxPoint> points;
            for (const auto& point : scene.boardOuter)
            {
                points.push_back(WorldToScreen(point));
            }
            m_dc.SetPen(wxPen(outline, FromDIP(1)));
            m_dc.SetBrush(wxBrush(fill));
            m_dc.DrawPolygon(static_cast<int>(points.size()), points.data());
            return;
        }
        const wxPoint leftTop = WorldToScreen(scene.circularBoard ? Point{scene.boardCenter.x - scene.boardRadius,
                                                                          scene.boardCenter.y + scene.boardRadius}
                                                                  : Point{0.0, scene.boardHeight});
        const wxPoint rightBottom = WorldToScreen(scene.circularBoard ? Point{scene.boardCenter.x + scene.boardRadius,
                                                                              scene.boardCenter.y - scene.boardRadius}
                                                                      : Point{scene.boardWidth, 0.0});
        m_dc.SetPen(wxPen(outline, FromDIP(1)));
        m_dc.SetBrush(wxBrush(fill));
        if (scene.circularBoard)
        {
            m_dc.DrawEllipse(wxRect(leftTop, rightBottom));
        }
        else
        {
            m_dc.DrawRectangle(wxRect(leftTop, rightBottom));
        }
    }
}

/** @brief 한 frame에서 native context를 재사용하고 선/원호/영역의 표시 순서를 유지한다. */
bool CanvasRenderer::DrawShape(const CanvasScene::Shape& shape, Point offset, const wxColour& suppliedColour,
                               bool highlight)
{
    if (!m_viewport.Renderable(shape, offset))
    {
        return false;
    }
    const bool removal = shape.selectionKind == "cutout" || shape.selectionKind == "hole";
    const bool outline = shape.selectionKind == "keepout" || shape.selectionKind == "footprint";
    const bool line = shape.kind == "line_path";
    const bool arc = shape.kind == "arc_path";
    Point start{}, end{}, arcCenter{};
    const double width = std::max(shape.width * m_viewport.pixelsPerMm, 1.0);
    const double padding = width / 2.0 + m_pathPadding;
    // @brief native 범위 진단은 유지하고 창에 닿지 않는 경로에는 native path를 만들지 않는다.
    if (line)
    {
        start = m_viewport.Project(shape.start, offset);
        end = m_viewport.Project(shape.end, offset);
        if (m_damage.width != m_viewport.width || m_damage.height != m_viewport.height)
        {
            Point first = start;
            Point last = end;
            if (!CanvasGeometry::ClipSegment(first, last, m_damage.x - padding, m_damage.y - padding,
                                             m_damage.x + m_damage.width + padding, m_damage.y + m_damage.height + padding))
            {
                return true;
            }
        }
        if (!outline && !CanvasGeometry::ClipSegment(start, end, -padding, -padding, m_viewport.width + padding,
                                                     m_viewport.height + padding))
        {
            return true;
        }
    }
    else if (arc)
    {
        arcCenter = m_viewport.Project(shape.center, offset);
        const double extent = shape.radius * m_viewport.pixelsPerMm + padding;
        if (arcCenter.x + extent < m_damage.x || arcCenter.x - extent > m_damage.x + m_damage.width ||
            arcCenter.y + extent < m_damage.y || arcCenter.y - extent > m_damage.y + m_damage.height)
        {
            return true;
        }
    }
    const wxColour colour = removal ? m_colours.background
                            : m_colours.Detail(outline ? wxColour(178, 66, 112)
                                               : shape.selectionKind == "aperture" ? wxColour(95, 158, 183)
                                                                                  : suppliedColour);
    if (!m_graphics)
    {
        m_graphics.reset(wxGraphicsContext::CreateFromUnknownDC(m_dc));
        if (m_graphics)
        {
            m_graphics->Clip(m_damage.x, m_damage.y, m_damage.width, m_damage.height);
        }
    }
    auto* graphics = m_graphics.get();
    if (!graphics)
    {
        return false;
    }
    // @brief 일반 선분은 끝점을 직접 전달해 같은 native 펜과 겹침 순서를 유지한다.
    const bool simpleLine = line && !outline && !removal && !highlight &&
        (static_cast<float>(start.x) != static_cast<float>(end.x) ||
         static_cast<float>(start.y) != static_cast<float>(end.y));
    wxGraphicsPath path;
    if (!simpleLine)
    {
        path = graphics->CreatePath();
    }
    if (line && outline)
    {
        const double angle = std::atan2(end.y - start.y, end.x - start.x);
        const double radius = shape.width * m_viewport.pixelsPerMm / 2;
        for (int side = 0; side < 2; ++side)
        {
            const auto center = side == 0 ? end : start;
            for (int step = 0; step <= 24; ++step)
            {
                const double theta =
                    angle - CanvasGeometry::Pi / 2 + side * CanvasGeometry::Pi + step * CanvasGeometry::Pi / 24;
                const double x = center.x + radius * std::cos(theta);
                const double y = center.y + radius * std::sin(theta);
                if (side == 0 && step == 0)
                {
                    path.MoveToPoint(x, y);
                }
                else
                {
                    path.AddLineToPoint(x, y);
                }
            }
        }
        path.CloseSubpath();
    }
    else if (line)
    {
        if (!simpleLine)
        {
            path.MoveToPoint(start.x, start.y);
            path.AddLineToPoint(end.x, end.y);
        }
    }
    else if (arc)
    {
        path.AddArc(arcCenter.x, arcCenter.y, shape.radius * m_viewport.pixelsPerMm,
                    -shape.startAngle * CanvasGeometry::Pi / 180.0,
                    -(shape.startAngle + shape.sweepAngle) * CanvasGeometry::Pi / 180.0, shape.sweepAngle < 0.0);
    }
    else if (!shape.rings.empty())
    {
        for (const auto& ring : shape.rings)
        {
            const Point first = m_viewport.Project(ring.front(), offset);
            path.MoveToPoint(first.x, first.y);
            for (std::size_t index = 1; index < ring.size(); ++index)
            {
                const Point point = m_viewport.Project(ring[index], offset);
                path.AddLineToPoint(point.x, point.y);
            }
            path.CloseSubpath();
        }
    }
    else
    {
        Flush();
        const Point center = m_viewport.Project(shape.center, offset);
        const double radius = shape.radius * m_viewport.pixelsPerMm;
        if (radius > 0.0)
        {
            path.AddCircle(center.x, center.y, radius);
            if (shape.kind == "via" && shape.holeRadius > 0 && shape.holeRadius < shape.radius)
            {
                path.AddCircle(center.x, center.y, shape.holeRadius * m_viewport.pixelsPerMm);
            }
        }
        if (shape.kind == "via" && shape.incomplete)
        {
            wxGraphicsPath marker = graphics->CreatePath();
            const double half = FromDIP(5);
            marker.MoveToPoint(center.x - half, center.y);
            marker.AddLineToPoint(center.x + half, center.y);
            marker.MoveToPoint(center.x, center.y - half);
            marker.AddLineToPoint(center.x, center.y + half);
            graphics->SetPen(
                wxPen(highlight ? m_colours.Focus(wxColour(36, 141, 225)) : m_colours.Detail(wxColour(105, 113, 121)),
                      FromDIP(2), wxPENSTYLE_SHORT_DASH));
            graphics->StrokePath(marker);
        }
    }
    if (outline || (!line && !arc))
    {
        Flush();
        if (highlight)
        {
            graphics->SetPen(wxPen(m_colours.Focus(wxColour(36, 141, 225)), FromDIP(5)));
            graphics->StrokePath(path);
        }
        graphics->SetPen(wxPen(removal ? m_colours.Detail(wxColour(92, 107, 122)) : colour, FromDIP(1),
                               outline || shape.incomplete ? wxPENSTYLE_SHORT_DASH : wxPENSTYLE_SOLID));
        graphics->SetBrush(outline ? *wxTRANSPARENT_BRUSH : wxBrush(colour));
        if (outline || (shape.kind == "via" && (shape.incomplete || shape.holeRadius >= shape.radius)))
        {
            graphics->StrokePath(path);
        }
        else
        {
            graphics->DrawPath(path, wxODDEVEN_RULE);
        }
        if (shape.kind == "via" && shape.holeRadius > 0.0)
        {
            const Point center = m_viewport.Project(shape.center, offset);
            const double radius = shape.holeRadius * m_viewport.pixelsPerMm;
            graphics->SetPen(*wxTRANSPARENT_PEN);
            graphics->SetBrush(wxBrush(m_colours.HighContrast() ? m_colours.background : wxColour(250, 251, 253)));
            graphics->DrawEllipse(center.x - radius, center.y - radius, radius * 2.0, radius * 2.0);
        }
        m_unflushed = true;
        return true;
    }
    if (removal)
    {
        wxGraphicsPenInfo boundary(m_colours.Detail(wxColour(92, 107, 122)), width + FromDIP(highlight ? 5 : 2));
        boundary.Cap(wxCAP_ROUND);
        if (highlight)
        {
            boundary.Colour(m_colours.Focus(wxColour(36, 141, 225)));
        }
        graphics->SetPen(graphics->CreatePen(boundary));
        graphics->StrokePath(path);
    }
    if (highlight)
    {
        Flush();
        wxGraphicsPenInfo halo(m_colours.Focus(wxColour(36, 141, 225)), width + FromDIP(5));
        halo.Cap(wxCAP_ROUND);
        graphics->SetPen(graphics->CreatePen(halo));
        graphics->StrokePath(path);
    }
    // @brief 같은 paint 안의 연속된 선폭/색상은 native pen을 재생성하지 않는다.
    if (m_linePen.IsNull() || m_lineColour != colour || m_lineWidth != width)
    {
        wxGraphicsPenInfo pen(colour, width);
        pen.Cap(wxCAP_ROUND);
        m_linePen = graphics->CreatePen(pen);
        m_lineColour = colour;
        m_lineWidth = width;
    }
    graphics->SetPen(m_linePen);
    if (simpleLine)
    {
        const wxPoint2DDouble points[] = {{start.x, start.y}, {end.x, end.y}};
        graphics->StrokeLines(2, points);
    }
    else
    {
        graphics->StrokePath(path);
    }
    m_unflushed = true;
    return true;
}
