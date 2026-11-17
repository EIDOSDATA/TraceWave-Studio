/** @file @brief 자유 입력, 스냅 후보 및 끝점 드래그를 2D 표시 장면에 연결한다. */
#include "design_canvas.h"

namespace
{
using namespace CanvasPrecision;
using WxPoint = wxPoint2DDouble;

Point GeometryPoint(const WxPoint& point)
{
    return {point.m_x, point.m_y};
}

WxPoint DisplayPoint(Point point)
{
    return {point.x, point.y};
}
}

void DesignCanvas::SetSnapEnabled(bool enabled)
{
    m_snapEnabled = enabled;
    m_snap.reset();
    Refresh(false);
}

const DesignCanvas::Shape* DesignCanvas::SelectedPath() const
{
    const auto* shape = FindShape(m_selection);
    return m_editingEnabled && m_tool == "select" && shape && shape->selectionKind == "geometry" &&
                   CanvasPrecision::HasEndpoints(*shape) && Selectable(*shape) && Renderable(*shape)
               ? shape
               : nullptr;
}

std::optional<CanvasPrecision::Endpoint> DesignCanvas::HitEndpoint(const Shape& shape, const wxPoint& pixel) const
{
    using namespace CanvasPrecision;
    const auto viewport = Viewport();
    Nearest nearest(GeometryPoint(ScreenToWorld(pixel)), FromDIP(8) / viewport.pixelsPerMm, std::nullopt);
    const auto end = At(shape, Endpoint::End);
    nearest.Consider(end, SnapKind::Endpoint);
    nearest.Consider(At(shape, Endpoint::Start), SnapKind::Endpoint);
    const auto found = nearest.Result();
    if (!found)
    {
        return std::nullopt;
    }
    return Distance(found->point, end) == 0.0 ? Endpoint::End : Endpoint::Start;
}

void DesignCanvas::UpdateCursor(const wxPoint& pixel)
{
    using namespace CanvasPrecision;
    m_cursor = ScreenToWorld(pixel);
    m_snap.reset();
    if (!m_snapEnabled || !m_editingEnabled || !GetClientRect().Contains(pixel))
    {
        return;
    }
    const Shape* editing = m_gesture.Reshaping() ? SelectedPath() : nullptr;
    const std::string& layer = editing ? editing->layer : m_drawingLayer;
    if ((!editing && m_tool == "select") || layer.empty() || !m_scene.layers.count(layer) || !IsLayerVisible(layer))
    {
        return;
    }
    std::optional<Circle> circle;
    if (editing && editing->kind == "arc_path")
    {
        circle = Circle{editing->center, editing->radius};
    }
    else if (m_tool == "arc" && m_points.size() == 2)
    {
        const auto center = GeometryPoint(m_points.front());
        circle = Circle{center, Distance(center, GeometryPoint(m_points.back()))};
    }
    const auto viewport = Viewport();
    const auto cursor = GeometryPoint(m_cursor);
    Nearest nearest(cursor, FromDIP(8) / viewport.pixelsPerMm, circle);
    for (auto shape = m_scene.shapes.rbegin(); shape != m_scene.shapes.rend(); ++shape)
    {
        if (shape->layer != layer || (editing && shape->id == editing->id) || !HasEndpoints(*shape) ||
            !Visible(*shape) || !Renderable(*shape))
        {
            continue;
        }
        for (const auto end : {Endpoint::End, Endpoint::Start})
        {
            const auto candidate = At(*shape, end);
            const auto projected = viewport.Project(candidate);
            if (projected.x >= 0 && projected.x < viewport.width && projected.y >= 0 && projected.y < viewport.height)
            {
                nearest.Consider(candidate, SnapKind::Endpoint);
            }
        }
    }
    m_snap = nearest.Result();
    if (!m_snap && m_showGrid)
    {
        nearest.Consider(GridPoint(cursor, viewport.GridStep()), SnapKind::Grid);
        m_snap = nearest.Result();
    }
    if (m_snap)
    {
        m_cursor = DisplayPoint(m_snap->point);
    }
}

std::optional<DesignCanvas::Shape> DesignCanvas::EndpointPreview() const
{
    const auto* current = SelectedPath();
    if (!m_gesture.Reshaping() || !m_endpoint || !current)
    {
        return std::nullopt;
    }
    Shape preview = *current;
    if (!CanvasPrecision::Preview(preview, *m_endpoint, GeometryPoint(m_cursor)) || !Renderable(preview))
    {
        return std::nullopt;
    }
    return preview;
}

void DesignCanvas::FinishEndpoint(const wxPoint& pixel)
{
    const auto candidate = EndpointPreview();
    const auto endpoint = m_endpoint;
    const double distance =
        std::hypot(static_cast<double>(pixel.x - m_mouseDown.x), static_cast<double>(pixel.y - m_mouseDown.y));
    const bool dropped = GetClientRect().Contains(pixel) && distance >= FromDIP(3);
    const wxPoint2DDouble cursor = m_cursor;
    const auto* current = SelectedPath();
    const bool unchanged =
        current && endpoint && CanvasPrecision::EndpointUnchanged(*current, *endpoint, GeometryPoint(cursor));
    CancelGesture();
    if (!dropped)
    {
        return;
    }
    if (unchanged)
    {
        Status("끝점 위치가 같아 변경하지 않았습니다.");
        return;
    }
    if (!candidate || !endpoint)
    {
        Status("끝점 위치를 적용할 수 없습니다. 반대쪽 끝점과 원호 중심을 확인하세요.");
        return;
    }
    Emit(Json{{"type", "move_endpoint"},
              {"id", candidate->id},
              {"endpoint", *endpoint == CanvasPrecision::Endpoint::Start ? "start" : "end"},
              {"point", Json::array({cursor.m_x, cursor.m_y})}});
}

void DesignCanvas::DrawPrecision(wxDC& dc, const Shape* selected) const
{
    using namespace CanvasPrecision;
    if (selected)
    {
        const int half = FromDIP(4);
        for (const auto end : {Endpoint::Start, Endpoint::End})
        {
            const auto position = At(*selected, end);
            if (!CanvasGeometry::Valid(position))
            {
                continue;
            }
            const auto pixel = WorldToScreen(DisplayPoint(position));
            if (!GetClientRect().Contains(pixel))
            {
                continue;
            }
            const auto colour = Editable(*selected, end) ? wxColour(34, 113, 213) : wxColour(104, 113, 123);
            dc.SetPen(wxPen(colour, FromDIP(1)));
            dc.SetBrush(wxBrush(Editable(*selected, end) ? colour : wxColour(249, 251, 255)));
            dc.DrawRectangle(pixel.x - half, pixel.y - half, 2 * half + 1, 2 * half + 1);
        }
    }
    if (m_snap)
    {
        const auto pixel = WorldToScreen(DisplayPoint(m_snap->point));
        const int radius = FromDIP(7);
        dc.SetPen(wxPen(wxColour(13, 113, 100), FromDIP(2)));
        dc.SetBrush(*wxTRANSPARENT_BRUSH);
        if (m_snap->kind == SnapKind::Endpoint)
        {
            const wxPoint diamond[] = {{pixel.x, pixel.y - radius},
                                       {pixel.x + radius, pixel.y},
                                       {pixel.x, pixel.y + radius},
                                       {pixel.x - radius, pixel.y}};
            dc.DrawPolygon(4, diamond);
        }
        else
        {
            dc.DrawLine(pixel.x - radius, pixel.y, pixel.x + radius + 1, pixel.y);
            dc.DrawLine(pixel.x, pixel.y - radius, pixel.x, pixel.y + radius + 1);
        }
    }
}
