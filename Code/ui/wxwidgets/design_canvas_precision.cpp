/** @file @brief 자유 입력, 스냅 후보 및 끝점 드래그를 2D 표시 장면에 연결한다. */
#include "design_canvas.h"

#include <algorithm>

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

/** @brief 스냅 안내에서 채택한 관계를 보존하는 입력 모드를 전환한다. */
void DesignCanvas::SetDrawingRelations(bool enabled)
{
    m_drawingRelations = enabled;
    m_startSnap.reset();
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
    const bool infer = m_drawingRelations && (m_tool == "arc" || m_tool == "line");
    if ((!m_snapEnabled && !infer) || !m_editingEnabled || !GetClientRect().Contains(pixel))
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
    const double tolerance = FromDIP(8) / viewport.pixelsPerMm;
    Nearest nearest(cursor, tolerance, circle);
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
                nearest.Consider(candidate, SnapKind::Endpoint, shape->id, end);
            }
        }
    }
    m_snap = nearest.Result();
    if (!m_snap && infer && (m_tool == "line" || !m_points.empty()))
    {
        for (auto shape = m_scene.shapes.rbegin(); shape != m_scene.shapes.rend(); ++shape)
        {
            if (shape->layer == layer && shape->kind == "line_path" && Visible(*shape) && Renderable(*shape))
            {
                const Point middle{(shape->start.x + shape->end.x) / 2, (shape->start.y + shape->end.y) / 2};
                const auto screen = viewport.Project(middle);
                if (screen.x >= 0 && screen.x < viewport.width && screen.y >= 0 && screen.y < viewport.height)
                {
                    nearest.Consider(middle, SnapKind::Midpoint, shape->id);
                }
            }
        }
        m_snap = nearest.Result();
    }
    if (!m_snap && infer && m_tool == "line" && m_points.size() == 1)
    {
        const auto start = GeometryPoint(m_points.front());
        if (m_startSnap && m_startSnap->kind == SnapKind::Endpoint)
        {
            const auto* guide = FindShape(m_startSnap->target);
            if (guide && guide->kind == "arc_path" && guide->layer == layer && Visible(*guide))
            {
                const auto point = TangentPoint(guide->center, start, cursor, tolerance);
                if (point)
                {
                    m_snap = Snap{*point, SnapKind::Tangent, {}};
                }
            }
        }
        const double dx = std::abs(cursor.x - start.x);
        const double dy = std::abs(cursor.y - start.y);
        if (!m_snap && dx >= 2 * tolerance && dy <= tolerance)
        {
            m_snap = Snap{{cursor.x, start.y}, SnapKind::Horizontal, {}};
        }
        else if (!m_snap && dy >= 2 * tolerance && dx <= tolerance)
        {
            m_snap = Snap{{start.x, cursor.y}, SnapKind::Vertical, {}};
        }
    }
    if (!m_snap && m_snapEnabled && m_showGrid)
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
            const auto colour = Editable(*selected, end) ? m_colours.Focus(wxColour(34, 113, 213))
                                                         : m_colours.Detail(wxColour(104, 113, 123));
            dc.SetPen(wxPen(colour, FromDIP(1)));
            dc.SetBrush(wxBrush(Editable(*selected, end) ? colour
                                                       : m_colours.HighContrast() ? m_colours.background
                                                                                  : wxColour(249, 251, 255)));
            dc.DrawRectangle(pixel.x - half, pixel.y - half, 2 * half + 1, 2 * half + 1);
        }
    }
    if (m_snap)
    {
        const auto pixel = WorldToScreen(DisplayPoint(m_snap->point));
        const int radius = FromDIP(7);
        dc.SetPen(wxPen(m_colours.Focus(wxColour(13, 113, 100)), FromDIP(2)));
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
        const auto kind = m_snap->kind;
        const char* description = kind == SnapKind::Horizontal ? "수평 관계" : kind == SnapKind::Vertical ? "수직 관계" :
            kind == SnapKind::Midpoint ? "중점 관계" : kind == SnapKind::Tangent ? "접선 관계" : kind == SnapKind::Endpoint ?
            (m_drawingRelations && m_tool != "select" && (m_tool != "arc" || !m_points.empty()) ? "끝점 일치 관계" : "끝점 스냅") :
            "격자 스냅";
        const wxString label = wxString::FromUTF8(description);
        const wxSize size = dc.GetTextExtent(label);
        const int padding = FromDIP(4);
        const auto client = GetClientSize();
        const int left = std::clamp(pixel.x + radius + padding, 0,
                                    std::max(0, client.x - size.x - 2 * padding));
        const int top = std::clamp(pixel.y - size.y - 2 * padding, 0,
                                   std::max(0, client.y - size.y - 2 * padding));
        dc.SetBrush(wxBrush(m_colours.background));
        dc.SetTextForeground(m_colours.Focus(wxColour(13, 113, 100)));
        dc.DrawRectangle(left, top, size.x + 2 * padding, size.y + 2 * padding);
        dc.DrawText(label, left + padding, top + padding);
    }
}
