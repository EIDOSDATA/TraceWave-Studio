#include "canvas_renderer.h"
#include <algorithm>
#include <cmath>

namespace
{
using Point = CanvasGeometry::Point;
}

CanvasRenderer::CanvasRenderer(wxWindow& window, wxDC& dc, CanvasViewport viewport)
    : m_window(window), m_dc(dc), m_viewport(viewport)
{
}

void CanvasRenderer::Flush()
{
    if (m_graphics)
    {
        m_graphics->Flush();
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
        double step = std::pow(10.0, std::floor(std::log10(50.0 / m_viewport.pixelsPerMm)));
        if (step * m_viewport.pixelsPerMm < 20.0)
        {
            step *= 5.0;
        }
        else if (step * m_viewport.pixelsPerMm < 35.0)
        {
            step *= 2.0;
        }
        m_dc.SetPen(wxPen(wxColour(230, 234, 239), 1));
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
    m_dc.SetPen(wxPen(wxColour(151, 163, 176), 1));
    if (origin.x >= 0 && origin.x <= size.x)
    {
        m_dc.DrawLine(origin.x, 0, origin.x, size.y);
    }
    if (origin.y >= 0 && origin.y <= size.y)
    {
        m_dc.DrawLine(0, origin.y, size.x, origin.y);
    }
    m_dc.SetTextForeground(wxColour(94, 107, 121));
    m_dc.DrawText("X / mm", std::max(2, size.x - FromDIP(60)),
                  std::clamp(origin.y + 4, 2, std::max(2, size.y - FromDIP(22))));
    m_dc.DrawText("Y / mm", std::clamp(origin.x + 4, 2, std::max(2, size.x - FromDIP(60))), FromDIP(4));
}

/** @brief 기판 외곽은 도체와 별도 배경으로 표시한다. */
void CanvasRenderer::DrawBoard(const CanvasScene::Model& scene)
{
    if (scene.hasBoard)
    {
        const wxPoint leftTop = WorldToScreen(scene.circularBoard ? Point{scene.boardCenter.x - scene.boardRadius,
                                                                          scene.boardCenter.y + scene.boardRadius}
                                                                  : Point{0.0, scene.boardHeight});
        const wxPoint rightBottom = WorldToScreen(scene.circularBoard ? Point{scene.boardCenter.x + scene.boardRadius,
                                                                              scene.boardCenter.y - scene.boardRadius}
                                                                      : Point{scene.boardWidth, 0.0});
        m_dc.SetPen(wxPen(wxColour(105, 153, 117), FromDIP(2)));
        m_dc.SetBrush(wxBrush(wxColour(232, 243, 235), wxBRUSHSTYLE_BDIAGONAL_HATCH));
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
bool CanvasRenderer::DrawShape(const CanvasScene::Shape& shape, Point offset, const wxColour& colour, bool highlight)
{
    if (!m_viewport.Renderable(shape, offset))
    {
        return false;
    }
    if (!m_graphics)
    {
        m_graphics.reset(wxGraphicsContext::CreateFromUnknownDC(m_dc));
        if (m_graphics)
        {
            m_graphics->Clip(0, 0, m_viewport.width, m_viewport.height);
        }
    }
    auto* graphics = m_graphics.get();
    if (!graphics)
    {
        return false;
    }
    wxGraphicsPath path = graphics->CreatePath();
    if (shape.kind == "line_path")
    {
        CanvasGeometry::Point start = m_viewport.Project(shape.start, offset);
        CanvasGeometry::Point end = m_viewport.Project(shape.end, offset);
        const double padding = std::max(1.0, shape.width * m_viewport.pixelsPerMm) / 2.0 + FromDIP(8);
        if (!CanvasGeometry::ClipSegment(start, end, -padding, -padding, m_viewport.width + padding,
                                         m_viewport.height + padding))
        {
            return true;
        }
        path.MoveToPoint(start.x, start.y);
        path.AddLineToPoint(end.x, end.y);
    }
    else if (shape.kind == "arc_path")
    {
        const Point center = m_viewport.Project(shape.center, offset);
        path.AddArc(center.x, center.y, shape.radius * m_viewport.pixelsPerMm,
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
                wxPen(highlight ? wxColour(36, 141, 225) : wxColour(105, 113, 121), FromDIP(2), wxPENSTYLE_SHORT_DASH));
            graphics->StrokePath(marker);
        }
    }
    if (shape.kind != "line_path" && shape.kind != "arc_path")
    {
        Flush();
        if (highlight)
        {
            graphics->SetPen(wxPen(wxColour(36, 141, 225), FromDIP(5)));
            graphics->StrokePath(path);
        }
        graphics->SetPen(wxPen(colour, FromDIP(1)));
        graphics->SetBrush(wxBrush(colour));
        if (shape.kind == "via" && (shape.incomplete || shape.holeRadius >= shape.radius))
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
            graphics->SetBrush(wxBrush(wxColour(250, 251, 253)));
            graphics->DrawEllipse(center.x - radius, center.y - radius, radius * 2.0, radius * 2.0);
        }
        return true;
    }
    const double width = std::max(shape.width * m_viewport.pixelsPerMm, 1.0);
    if (highlight)
    {
        Flush();
        wxGraphicsPenInfo halo(wxColour(36, 141, 225), width + FromDIP(5));
        halo.Cap(wxCAP_ROUND);
        graphics->SetPen(graphics->CreatePen(halo));
        graphics->StrokePath(path);
    }
    wxGraphicsPenInfo pen(colour, width);
    pen.Cap(wxCAP_ROUND);
    graphics->SetPen(graphics->CreatePen(pen));
    graphics->StrokePath(path);
    return true;
}
