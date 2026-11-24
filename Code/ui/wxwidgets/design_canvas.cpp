#include "design_canvas.h"
#include "canvas_geometry.h"
#include "canvas_renderer.h"

#include <wx/dcbuffer.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <memory>
#include <stdexcept>

namespace
{
using Point = wxPoint2DDouble;
using Json = nlohmann::json;
constexpr double MinimumScale = 0.0001;
constexpr double MaximumScale = 1000000.0;
constexpr double MinimumLength = 1e-9;

/** @brief 표시 계층 경계에서 UTF-8 문자열을 wx 문자열로 바꾼다. */
wxString Display(const std::string& value)
{
    return wxString::FromUTF8(value.data(), value.size());
}

CanvasGeometry::Point GeometryPoint(const Point& point)
{
    return {point.m_x, point.m_y};
}

CanvasGeometry::Point GeometryPoint(CanvasGeometry::Point point)
{
    return point;
}

bool Valid(const Point& point)
{
    return CanvasGeometry::Valid(GeometryPoint(point));
}

Json Coordinates(const CanvasGeometry::Point& point)
{
    return Json::array({point.x, point.y});
}

Point Subtract(const Point& left, const Point& right)
{
    return Point(left.m_x - right.m_x, left.m_y - right.m_y);
}

double Distance(const Point& left, const Point& right)
{
    return std::hypot(left.m_x - right.m_x, left.m_y - right.m_y);
}
}

DesignCanvas::DesignCanvas(wxWindow* parent)
    : wxPanel(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxWANTS_CHARS | wxBORDER_NONE),
      m_colours(StudioAppearance::CanvasColours::Read())
{
    m_routeTimer.SetOwner(this);
    Bind(wxEVT_TIMER, [this](wxTimerEvent&)
    {
        if (!onRouteReview || m_routePending || m_tool != "route" || m_points.empty())
        {
            return;
        }
        auto values = RouteDraft(true);
        if (values.at("points").size() >= 2)
        {
            m_routePending = m_routeVersion;
            onRouteReview(values, m_routePending);
        }
    }, m_routeTimer.GetId());
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    SetMinSize(FromDIP(wxSize(260, 220)));
    Bind(wxEVT_PAINT, &DesignCanvas::OnPaint, this);
    Bind(wxEVT_LEFT_DOWN, &DesignCanvas::OnLeftDown, this);
    Bind(wxEVT_LEFT_UP, &DesignCanvas::OnLeftUp, this);
    Bind(wxEVT_MOTION, &DesignCanvas::OnMotion, this);
    Bind(wxEVT_LEAVE_WINDOW,
         [this](wxMouseEvent& event)
         {
             if (!HasCapture() && m_snap)
             {
                 m_snap.reset();
                 Refresh(false);
             }
             event.Skip();
         });
    Bind(wxEVT_MIDDLE_DOWN, &DesignCanvas::OnMiddleDown, this);
    Bind(wxEVT_MIDDLE_UP, &DesignCanvas::OnMiddleUp, this);
    Bind(wxEVT_MOUSEWHEEL, &DesignCanvas::OnWheel, this);
    Bind(wxEVT_KEY_DOWN, &DesignCanvas::OnKeyDown, this);
    Bind(wxEVT_KEY_UP,
         [this](wxKeyEvent& event)
         {
             if (m_clockwise != event.ShiftDown())
             {
                 m_clockwise = event.ShiftDown();
                 if (m_tool == "arc" && !m_points.empty())
                 {
                     Refresh(false);
                 }
             }
             event.Skip();
         });
    Bind(wxEVT_MOUSE_CAPTURE_LOST, &DesignCanvas::OnCaptureLost, this);
    Bind(wxEVT_SIZE, &DesignCanvas::OnSize, this);
    Bind(wxEVT_SYS_COLOUR_CHANGED, [this](wxSysColourChangedEvent& event)
    {
        m_colours = StudioAppearance::CanvasColours::Read();
        Refresh(false);
        event.Skip();
    });
}

/** @brief 창 종료 중에도 자신이 얻은 마우스 capture를 남기지 않는다. */
DesignCanvas::~DesignCanvas()
{
    ReleaseOwnedCapture();
}

/** @brief 전체 표시 DTO를 검증한 뒤 교체하여 부분 해석된 화면을 남기지 않는다. */
void DesignCanvas::SetScene(const Json& scene)
{
    CanvasScene::Model parsed = CanvasScene::Model::Parse(scene);
    CancelGesture();
    m_pendingId.clear();
    m_pendingOffset = Point(0.0, 0.0);
    m_scene = std::move(parsed);
    m_dimensions = Json::array();
    if (SelectionInfo(m_selection).is_null())
    {
        m_selection.clear();
    }
    if (!m_fitted && (m_scene.hasBoard || !m_scene.shapes.empty()))
    {
        FitView();
    }
    Refresh(false);
}

std::string DesignCanvas::ConductorDisplayReason(const std::string& identity) const
{
    const auto* shape = FindShape(identity);
    if (shape == nullptr || !Renderable(*shape))
    {
        return "2D 표시 형상이 없습니다.";
    }
    return Visible(*shape) ? "" : "2D에서 도체층이 숨겨져 있습니다.";
}

bool DesignCanvas::PortMarkerVisible(const std::string& identity) const
{
    return std::any_of(m_scene.portMarkers.begin(), m_scene.portMarkers.end(), [this, &identity](const auto& marker)
    {
        return (identity.empty() || identity == marker.id) &&
            std::all_of(marker.terminals.begin(), marker.terminals.end(), [this](const std::string& id)
        {
            return ConductorDisplayReason(id).empty();
        });
    });
}

void DesignCanvas::SetInspection(const std::vector<std::string>& identities, std::optional<wxPoint2DDouble> location)
{
    if (m_inspection != identities || m_inspectionLocation != location)
    {
        m_inspection = identities;
        m_inspectionLocation = location;
        Refresh(false);
    }
}

void DesignCanvas::SetSelection(const std::string& identity)
{
    const Shape* shape = FindShape(identity);
    const bool owner = std::any_of(m_scene.shapes.begin(), m_scene.shapes.end(),
                                   [&identity, this](const Shape& item)
                                   {
                                       return !identity.empty() && item.ownerFootprint == identity && Visible(item) &&
                                              Renderable(item);
                                   });
    const std::string selected =
        (shape != nullptr && Visible(*shape) && Renderable(*shape)) || owner ||
        m_scene.HasPortMarker(identity) ? identity : std::string();
    if (m_selection != selected)
    {
        if (m_gesture.Reshaping())
        {
            CancelGesture();
        }
        m_selection = selected;
        m_dimensions = Json::array();
        Refresh(false);
    }
}

DesignCanvas::Json DesignCanvas::SelectionInfo(const std::string& identity) const
{
    if (identity.empty())
    {
        return nullptr;
    }
    if (m_scene.HasPortMarker(identity))
    {
        return {{"kind", "port"}, {"id", identity}};
    }
    if (const auto* shape = FindShape(identity))
    {
        return {{"kind", shape->selectionKind}, {"id", identity}};
    }
    for (const auto& shape : m_scene.shapes)
    {
        if (shape.ownerFootprint == identity)
        {
            return {{"kind", "footprint"}, {"id", identity}};
        }
    }
    return nullptr;
}

void DesignCanvas::SetTool(const std::string& tool)
{
    if (tool != "select" && tool != "line" && tool != "arc" && tool != "route")
    {
        throw std::runtime_error("지원하지 않는 캔버스 도구입니다.");
    }
    if (m_tool == tool)
    {
        return;
    }
    CancelGesture();
    m_tool = tool;
    SetCursor(wxCursor(tool == "select" ? wxCURSOR_ARROW : wxCURSOR_CROSS));
    if (tool == "route")
    {
        Status("배선 시작 도체와 경유점을 클릭한 뒤 Enter로 적용하세요. Esc로 취소합니다.");
        return;
    }
    Status(tool == "line" ? "선: 시작점과 끝점을 클릭하세요. Esc로 취소합니다."
                          : (tool == "arc" ? "원호: 중심, 시작점, 끝 방향을 클릭하세요. 기본 CCW, Shift는 CW입니다."
                                           : "선택: 파란 끝점은 끝점 편집, 도체 본체는 전체 이동. Esc로 취소합니다."));
}

void DesignCanvas::SetRouteClearance(double gap)
{
    if (m_routeClearance != gap)
    {
        m_routeClearance = gap;
        QueueRouteReview();
    }
}

void DesignCanvas::QueueRouteReview()
{
    if (m_tool == "route" && !m_points.empty())
    {
        ++m_routeVersion;
        m_routeConflict = false;
        m_routeTimer.StartOnce(180);
    }
}

void DesignCanvas::PresentRouteReview(unsigned long version, bool valid, const std::string& message)
{
    if (m_routePending != version)
    {
        return;
    }
    m_routePending = 0;
    if (m_tool != "route" || m_points.empty() || !m_editingEnabled)
    {
        return;
    }
    if (version != m_routeVersion)
    {
        m_routeTimer.StartOnce(180);
        return;
    }
    m_routeConflict = !valid;
    Status(message + ". V로 층 전환, Enter로 적용, Backspace로 되돌리기");
    Refresh(false);
}

DesignCanvas::Json DesignCanvas::RouteDraft(bool includeCursor) const
{
    Json points = Json::array();
    for (const auto& point : m_points)
    {
        points.push_back(Coordinates(GeometryPoint(point)));
    }
    if (includeCursor && !m_points.empty() && m_points.size() < 33 && Distance(m_points.back(), m_cursor) > MinimumLength)
    {
        points.push_back(Coordinates(GeometryPoint(m_cursor)));
    }
    Json values{{"source_id", m_routeSource}, {"layer_id", m_drawingLayer}, {"width_mm", m_strokeWidth},
                {"clearance_mm", m_routeClearance}, {"points", points}};
    if (!m_routeTransitions.empty())
    {
        values["transitions"] = m_routeTransitions;
    }
    return values;
}

void DesignCanvas::SetRouteTransition(const Json& settings)
{
    if (m_tool != "route" || m_points.size() < 2)
    {
        return;
    }
    const auto index = m_points.size() - 1;
    if (!m_routeTransitions.empty() && m_routeTransitions.back().at("index") == index)
    {
        m_routeTransitions.erase(m_routeTransitions.end() - 1);
    }
    if (m_routeTransitions.size() >= 8)
    {
        Status("한 배선에서 층 전환은 8개까지 가능합니다.");
        return;
    }
    auto row = settings;
    row["index"] = index;
    m_routeTransitions.push_back(row);
    QueueRouteReview();
    SetFocus();
    Refresh(false);
}

void DesignCanvas::SetDrawingLayer(const std::string& identity)
{
    if (m_drawingLayer != identity)
    {
        CancelGesture();
        m_drawingLayer = identity;
    }
}

void DesignCanvas::SetStrokeWidth(double widthMm)
{
    if (!std::isfinite(widthMm) || widthMm <= 0.0 || widthMm > CanvasGeometry::MaxCoordinate)
    {
        throw std::runtime_error("선 폭은 유한한 양수여야 합니다.");
    }
    if (m_strokeWidth != widthMm)
    {
        m_strokeWidth = widthMm;
        QueueRouteReview();
    }
    if (!m_points.empty())
    {
        Refresh(false);
    }
}

void DesignCanvas::SetEditingEnabled(bool enabled)
{
    if (!enabled)
    {
        CancelGesture();
    }
    else
    {
        m_pendingId.clear();
        m_pendingOffset = Point(0.0, 0.0);
    }
    m_editingEnabled = enabled;
    Refresh(false);
}

bool DesignCanvas::IsLayerVisible(const std::string& identity) const
{
    return m_hiddenLayers.count(identity) == 0;
}

void DesignCanvas::SetBoardVisible(bool visible)
{
    m_showBoard = visible;
    Refresh(false);
}

bool DesignCanvas::IsBoardVisible() const
{
    return m_showBoard;
}

void DesignCanvas::SetLayerVisible(const std::string& identity, bool visible)
{
    if (visible)
    {
        m_hiddenLayers.erase(identity);
    }
    else
    {
        m_hiddenLayers.insert(identity);
    }
    const Shape* shape = FindShape(m_selection);
    if (shape != nullptr && !Visible(*shape))
    {
        CancelGesture();
        m_selection.clear();
    }
    if (m_drawingLayer == identity && !visible)
    {
        CancelGesture();
    }
    Refresh(false);
}

void DesignCanvas::SetGridVisible(bool visible)
{
    m_showGrid = visible;
    m_snap.reset();
    Refresh(false);
}

/** @brief 두께와 실제 원호 구간을 포함한 유한 경계에 맞춘다. */
void DesignCanvas::FitView()
{
    CancelGesture();
    const auto bounds = m_scene.VisibleBounds(m_hiddenLayers);
    const double left = bounds.left, bottom = bounds.bottom, right = bounds.right, top = bounds.top;
    m_viewCenter =
        Point(std::clamp((left + right) / 2.0, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate),
              std::clamp((bottom + top) / 2.0, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate));
    const wxSize size = GetClientSize();
    const double availableX = std::max(20, size.x - FromDIP(70));
    const double availableY = std::max(20, size.y - FromDIP(70));
    m_pixelsPerMm =
        std::clamp(std::min(availableX / std::max(1e-6, right - left), availableY / std::max(1e-6, top - bottom)),
                   MinimumScale, MaximumScale);
    m_fitted = true;
    Refresh(false);
}

void DesignCanvas::ReleaseOwnedCapture()
{
    if (HasCapture())
    {
        ReleaseMouse();
    }
}

void DesignCanvas::CancelGesture()
{
    const bool changed = HasGesture() || m_snap.has_value();
    ++m_routeVersion;
    m_routePending = 0;
    m_routeTimer.Stop();
    m_routeTransitions.clear();
    m_routeConflict = false;
    m_points.clear();
    m_startSnap.reset();
    m_endpoint.reset();
    m_snap.reset();
    m_gesture.Reset();
    m_dragOffset = Point(0.0, 0.0);
    ReleaseOwnedCapture();
    if (changed)
    {
        Refresh(false);
    }
}

wxPoint DesignCanvas::WorldToScreen(const Point& point) const
{
    if (!Valid(point))
    {
        throw std::runtime_error("유효하지 않은 화면 변환 좌표입니다.");
    }
    const auto pixel = Viewport().Project(GeometryPoint(point));
    return wxPoint(static_cast<int>(std::llround(std::clamp(pixel.x, -1e7, 1e7))),
                   static_cast<int>(std::llround(std::clamp(pixel.y, -1e7, 1e7))));
}

Point DesignCanvas::ScreenToWorld(const wxPoint& point) const
{
    const auto world = Viewport().Unproject({static_cast<double>(point.x), static_cast<double>(point.y)});
    return Point(world.x, world.y);
}

const DesignCanvas::Shape* DesignCanvas::FindShape(const std::string& identity) const
{
    return m_scene.Find(identity);
}

bool DesignCanvas::Visible(const Shape& shape) const
{
    return CanvasScene::Visible(shape, m_hiddenLayers);
}

CanvasViewport DesignCanvas::Viewport() const
{
    const wxSize size = GetClientSize();
    return {size.x, size.y, GeometryPoint(m_viewCenter), m_pixelsPerMm};
}

bool DesignCanvas::Renderable(const Shape& shape, const Point& offset) const
{
    return Viewport().Renderable(shape, GeometryPoint(offset));
}

/** @brief 실제 선분과 원호 구간까지의 거리로 위에 그린 객체를 먼저 선택한다. */
std::string DesignCanvas::HitTest(const wxPoint& point, bool conductorOnly) const
{
    if (!conductorOnly)
    {
        double nearest = FromDIP(6);
        std::string result;
        for (const auto& marker : m_scene.portMarkers)
        {
            const auto center = WorldToScreen(Point(marker.point.x, marker.point.y));
            const double distance = std::hypot(point.x - center.x, point.y - center.y);
            if (distance <= nearest && PortMarkerVisible(marker.id))
            {
                nearest = distance;
                result = marker.id;
            }
        }
        if (!result.empty())
        {
            return result;
        }
    }
    const Point world = ScreenToWorld(point);
    for (auto shape = m_scene.shapes.rbegin(); shape != m_scene.shapes.rend(); ++shape)
    {
        if (!Renderable(*shape) || (conductorOnly && m_tool == "route" && shape->layer != m_drawingLayer) ||
            (conductorOnly ? shape->selectionKind != "geometry" || !Visible(*shape) : !Selectable(*shape)))
        {
            continue;
        }
        const double tolerance = shape->width / 2.0 + FromDIP(6) / m_pixelsPerMm;
        const double distance = CanvasScene::DistanceTo(*shape, GeometryPoint(world));
        if (distance <= tolerance)
        {
            return shape->id;
        }
    }
    return {};
}

std::string DesignCanvas::Selection() const
{
    return m_selection;
}

bool DesignCanvas::HasGesture() const
{
    return !m_points.empty() || m_gesture.Active();
}

/** @brief 구속 묶음의 모든 형상에 현재 또는 적용 대기 중인 이동량을 표시한다. */
wxPoint2DDouble DesignCanvas::TranslationOffset(const Shape& shape, const Shape* active) const
{
    if (active && (shape.id == active->id ||
                   (!shape.translationGroup.empty() && shape.translationGroup == active->translationGroup)))
    {
        return m_gesture.Dragging() ? m_dragOffset : m_pendingOffset;
    }
    return Point(0.0, 0.0);
}

std::size_t DesignCanvas::DisplayOmissionCount() const
{
    const auto* active = FindShape(m_gesture.Dragging() ? m_selection : m_pendingId);
    return m_scene.omissionCount + m_scene.rangeOmissionCount +
           static_cast<std::size_t>(std::count_if(
               m_scene.shapes.begin(), m_scene.shapes.end(),
               [&](const Shape& shape)
               {
                   const Point offset = TranslationOffset(shape, active);
                   return Visible(shape) && !Renderable(shape, offset);
               }));
}

void DesignCanvas::Status(const std::string& message)
{
    if (onStatus)
    {
        onStatus(message);
    }
}

void DesignCanvas::SetDisplayMarker(wxRect bounds, std::function<void(wxDC&)> draw)
{
    m_displayMarkerBounds = bounds;
    m_drawDisplayMarker = std::move(draw);
}

void DesignCanvas::OnPaint(wxPaintEvent&)
{
    {
        wxAutoBufferedPaintDC dc(this);
        wxRegion damage = GetUpdateRegion();
        if (m_drawDisplayMarker)
        {
            damage.Subtract(m_displayMarkerBounds);
        }
        if (!damage.IsEmpty())
        {
            const wxRect bounds = damage.GetBox();
            wxDCClipper clip(dc, bounds);
            PaintScene(dc, bounds);
        }
        if (m_drawDisplayMarker && GetUpdateRegion().Contains(m_displayMarkerBounds) == wxInRegion)
        {
            m_drawDisplayMarker(dc);
        }
    }
    if (!onFirstVisiblePaint || !IsShownOnScreen())
    {
        return;
    }
    const auto size = GetClientSize();
    if (size.GetWidth() > 0 && size.GetHeight() > 0)
    {
        auto painted = std::move(onFirstVisiblePaint);
        onFirstVisiblePaint = {};
        painted();
    }
}

void DesignCanvas::PaintScene(wxDC& dc, const wxRect& damage)
{
    dc.SetBackground(wxBrush(m_colours.background));
    dc.Clear();
    CanvasRenderer renderer(*this, dc, Viewport(), m_colours, damage);
    renderer.DrawGrid(m_showGrid);
    if (m_showBoard)
    {
        renderer.DrawBoard(m_scene);
    }
    const wxColour colours[] = {wxColour(249, 164, 84), wxColour(117, 87, 173), wxColour(27, 144, 138),
                                wxColour(177, 74, 96)};
    const auto preview = EndpointPreview();
    std::size_t nativeOmissions = m_scene.rangeOmissionCount;
    const auto* active = FindShape(m_gesture.Dragging() ? m_selection : m_pendingId);
    for (const Shape& shape : m_scene.shapes)
    {
        if (!Visible(shape))
        {
            continue;
        }
        const auto layer = m_scene.layers.find(shape.layer);
        const std::size_t index = static_cast<std::size_t>(std::distance(m_scene.layers.begin(), layer)) % 4;
        const Point offset = TranslationOffset(shape, active);
        const bool highlighted = shape.id == m_selection ||
                                 (!m_selection.empty() && shape.ownerFootprint == m_selection) ||
                                 std::find(m_inspection.begin(), m_inspection.end(), shape.id) != m_inspection.end();
        const auto& drawn = preview && preview->id == shape.id ? *preview : shape;
        if (!renderer.DrawShape(drawn, GeometryPoint(offset), colours[index], highlighted))
        {
            ++nativeOmissions;
        }
    }
    renderer.Flush();
    DrawPreview(dc, renderer);
    renderer.Flush();
    if (!m_gesture.Dragging())
    {
        DrawPrecision(dc, preview ? &*preview : SelectedPath());
        if (!HasGesture())
        {
            DrawDimensions(dc);
        }
    }
    for (const auto& marker : m_scene.portMarkers)
    {
        if (!PortMarkerVisible(marker.id))
        {
            continue;
        }
        const auto center = WorldToScreen(Point(marker.point.x, marker.point.y));
        if (GetClientRect().Contains(center))
        {
            const int radius = FromDIP(6);
            const wxColour color = m_colours.Focus(wxColour(38, 100, 163));
            dc.SetPen(wxPen(color, FromDIP(2)));
            dc.SetBrush(wxBrush(marker.id == m_selection ? color : m_colours.background));
            const wxPoint diamond[] = {{center.x, center.y - radius}, {center.x + radius, center.y},
                                       {center.x, center.y + radius}, {center.x - radius, center.y}};
            dc.DrawPolygon(4, diamond);
        }
    }
    if (m_inspectionLocation)
    {
        const wxPoint point = WorldToScreen(*m_inspectionLocation);
        const int radius = FromDIP(7);
        dc.SetPen(wxPen(m_colours.Focus(wxColour(174, 52, 42)), FromDIP(2)));
        dc.SetBrush(*wxTRANSPARENT_BRUSH);
        dc.DrawCircle(point, radius);
        dc.DrawLine(point.x - radius, point.y, point.x + radius, point.y);
        dc.DrawLine(point.x, point.y - radius, point.x, point.y + radius);
    }
    dc.SetTextForeground(m_colours.Detail(wxColour(73, 86, 103)));
    dc.DrawText(Display("2D 설계 (mm)"), FromDIP(10), FromDIP(10));
    if (m_scene.omissionCount > 0)
    {
        dc.DrawText(Display("표시 생략 " + std::to_string(m_scene.omissionCount) + "개"), FromDIP(10), FromDIP(30));
    }
    if (nativeOmissions > 0)
    {
        dc.DrawText(Display("표시 범위를 초과한 형상 " + std::to_string(nativeOmissions) + "개"), FromDIP(10),
                    FromDIP(50));
    }
}

DesignCanvas::Shape DesignCanvas::ArcPreview(bool clockwise) const
{
    Shape arc;
    arc.kind = "arc_path";
    arc.center = GeometryPoint(m_points.at(0));
    arc.radius = Distance(m_points.at(0), m_points.at(1));
    arc.startAngle = CanvasGeometry::NormalizeDegrees(
        std::atan2(m_points[1].m_y - arc.center.y, m_points[1].m_x - arc.center.x) * 180.0 / CanvasGeometry::Pi);
    arc.sweepAngle = CanvasGeometry::SweepDegrees(GeometryPoint(arc.center), GeometryPoint(m_points[1]),
                                                  GeometryPoint(m_cursor), clockwise);
    arc.width = m_strokeWidth;
    return arc;
}

void DesignCanvas::DrawPreview(wxDC& dc, CanvasRenderer& renderer) const
{
    if (m_points.empty())
    {
        return;
    }
    dc.SetPen(wxPen(m_colours.Focus(wxColour(41, 132, 202)), FromDIP(1), wxPENSTYLE_SHORT_DASH));
    dc.SetBrush(*wxTRANSPARENT_BRUSH);
    if (m_tool == "route")
    {
        auto points = m_points;
        points.push_back(m_cursor);
        for (std::size_t index = 1; index < points.size(); ++index)
        {
            const auto& a = points[index - 1];
            const auto& b = points[index];
            if (Distance(a, b) > MinimumLength)
            {
                Shape line;
                line.kind = "line_path";
                line.start = GeometryPoint(a);
                line.end = GeometryPoint(b);
                line.width = m_strokeWidth;
                renderer.DrawShape(line, {0.0, 0.0}, m_routeConflict ? wxColour(186, 56, 50) : wxColour(64, 148, 209), false);
            }
        }
        for (const auto& via : m_routeTransitions)
        {
            const auto index = via.at("index").get<std::size_t>();
            if (index < m_points.size())
            {
                dc.DrawCircle(WorldToScreen(m_points[index]), std::max(FromDIP(3),
                              static_cast<int>(via.at("pad_diameter_mm").get<double>() * m_pixelsPerMm / 2)));
            }
        }
        return;
    }
    const wxPoint first = WorldToScreen(m_points[0]);
    const wxPoint cursor = WorldToScreen(m_cursor);
    dc.DrawLine(first, cursor);
    dc.DrawCircle(first, FromDIP(4));
    if (m_tool == "line" && Distance(m_points[0], m_cursor) > MinimumLength)
    {
        Shape line;
        line.kind = "line_path";
        line.start = GeometryPoint(m_points[0]);
        line.end = GeometryPoint(m_cursor);
        line.width = m_strokeWidth;
        renderer.DrawShape(line, {0.0, 0.0}, wxColour(64, 148, 209), false);
    }
    else if (m_tool == "arc" && m_points.size() == 2)
    {
        const Shape arc = ArcPreview(m_clockwise);
        dc.DrawLine(first, WorldToScreen(m_points[1]));
        if (std::abs(arc.sweepAngle) > 1e-10)
        {
            renderer.DrawShape(arc, {0.0, 0.0}, wxColour(64, 148, 209), false);
        }
    }
}

void DesignCanvas::OnLeftDown(wxMouseEvent& event)
{
    SetFocus();
    if (!m_editingEnabled || m_gesture.Panning())
    {
        return;
    }
    m_mouseDown = event.GetPosition();
    if (onPickConductor)
    {
        const auto id = HitTest(m_mouseDown, true);
        if (!id.empty())
        {
            auto pick = onPickConductor;
            pick(id);
        }
        return;
    }
    UpdateCursor(m_mouseDown);
    m_clockwise = event.ShiftDown();
    if (m_tool != "select")
    {
        if (m_drawingLayer.empty() || !m_scene.layers.count(m_drawingLayer) || m_hiddenLayers.count(m_drawingLayer))
        {
            Status("표시 중인 그리기 층을 먼저 선택하세요.");
            return;
        }
        m_gesture.BeginDrawing();
    }
    else
    {
        const auto* selected = SelectedPath();
        const auto handle = selected ? HitEndpoint(*selected, m_mouseDown) : std::nullopt;
        if (handle)
        {
            if (!CanvasPrecision::Editable(*selected, *handle))
            {
                Status("참조나 미정값으로 잠긴 끝점은 속성에서 편집하세요.");
                return;
            }
            m_endpoint = handle;
            m_gesture.BeginReshape();
            const auto position = CanvasPrecision::At(*selected, *handle);
            m_cursor = Point(position.x, position.y);
            Status("끝점을 드래그하세요. Esc로 취소합니다.");
        }
        else
        {
            m_selection = HitTest(m_mouseDown);
            m_gesture.BeginSelection();
            m_dragAnchor = m_cursor;
            m_dragOffset = Point(0.0, 0.0);
        }
    }
    if (!HasCapture())
    {
        CaptureMouse();
    }
    Refresh(false);
}

void DesignCanvas::OnLeftUp(wxMouseEvent& event)
{
    if (!m_editingEnabled)
    {
        CancelGesture();
        return;
    }
    UpdateCursor(event.GetPosition());
    if (m_gesture.Reshaping())
    {
        FinishEndpoint(event.GetPosition());
        return;
    }
    if (m_gesture.DrawingClick())
    {
        m_gesture.Reset();
        ReleaseOwnedCapture();
        if (GetClientRect().Contains(event.GetPosition()))
        {
            CommitDrawing(event.ShiftDown());
        }
        return;
    }
    if (!m_gesture.Selecting())
    {
        return;
    }
    const bool translate = m_gesture.Dragging();
    const std::string identity = m_selection;
    const Point offset = Subtract(m_cursor, m_dragAnchor);
    m_gesture.Reset();
    m_dragOffset = Point(0.0, 0.0);
    ReleaseOwnedCapture();
    if (translate && Valid(offset) && Distance(offset, Point(0.0, 0.0)) > MinimumLength)
    {
        m_pendingId = identity;
        m_pendingOffset = offset;
        Emit(Json{{"type", "translate"}, {"id", identity}, {"delta", Coordinates(GeometryPoint(offset))}});
    }
    else if (onSelection)
    {
        onSelection(identity);
    }
    Refresh(false);
}

/** @brief 원호 끝점은 처음 선택한 반지름 위의 끝 방향으로 해석한다. */
void DesignCanvas::CommitDrawing(bool clockwise)
{
    if (!Valid(m_cursor))
    {
        Status("표시 좌표 범위를 벗어나 입력하지 않았습니다.");
        return;
    }
    if (m_tool == "route")
    {
        if (m_points.empty())
        {
            m_routeTransitions.clear();
            m_routeSource = HitTest(WorldToScreen(m_cursor), true);
            if (m_routeSource.empty())
            {
                Status("현재 도체층에서 넷이 지정된 시작 도체를 클릭하세요.");
                return;
            }
        }
        else if (Distance(m_points.back(), m_cursor) <= MinimumLength || m_points.size() >= 33)
        {
            Status("서로 다른 경유점을 최대 33개까지 선택하세요.");
            return;
        }
        m_points.push_back(m_cursor);
        QueueRouteReview();
        Status("다음 경유점을 클릭하세요. V 층 전환, Enter 적용, Backspace 되돌리기");
        Refresh(false);
        return;
    }
    const auto storeRelations = [this](Json& action)
    {
        if (!m_drawingRelations)
        {
            return;
        }
        using CanvasPrecision::SnapKind;
        auto relations = Json::array();
        const auto attach = [&](const auto& snap, const char* end)
        {
            if (snap && !snap->target.empty())
            {
                relations.push_back({{"kind", snap->kind == SnapKind::Midpoint ? "midpoint" : "coincident"},
                    {"endpoint", end}, {"target", {{"id", snap->target},
                    {"point", snap->endpoint == CanvasPrecision::Endpoint::End ? "end" : "start"}}}});
            }
        };
        attach(m_startSnap, "start");
        attach(m_snap, "end");
        if (m_snap && m_startSnap && m_snap->kind == SnapKind::Tangent)
        {
            relations.push_back({{"kind", "tangent"}, {"endpoint", "start"}, {"target",
                {{"id", m_startSnap->target},
                 {"point", m_startSnap->endpoint == CanvasPrecision::Endpoint::End ? "end" : "start"}}}});
        }
        if (m_snap && (m_snap->kind == SnapKind::Horizontal || m_snap->kind == SnapKind::Vertical))
        {
            relations.push_back({{"kind", "parallel"}, {"axis", m_snap->kind == SnapKind::Horizontal ? "x" : "y"}});
        }
        if (!relations.empty())
        {
            action["relations"] = std::move(relations);
        }
    };
    if (m_points.empty())
    {
        m_points.push_back(m_cursor);
        m_startSnap = m_tool == "line" ? m_snap : std::nullopt;
        Status(m_tool == "line" ? "선의 끝점을 클릭하세요." : "원호의 시작점을 클릭하세요.");
    }
    else if (m_tool == "line")
    {
        if (Distance(m_points[0], m_cursor) <= MinimumLength)
        {
            Status("시작점과 다른 끝점을 선택하세요.");
            return;
        }
        Json action{{"type", "create_line"},
                          {"layer_id", m_drawingLayer},
                          {"width", m_strokeWidth},
                          {"start", Coordinates(GeometryPoint(m_points[0]))},
                          {"end", Coordinates(GeometryPoint(m_cursor))}};
        storeRelations(action);
        m_points.clear();
        m_startSnap.reset();
        Emit(action);
    }
    else if (m_points.size() == 1)
    {
        if (Distance(m_points[0], m_cursor) <= MinimumLength)
        {
            Status("중심과 다른 시작점을 선택하세요.");
            return;
        }
        m_points.push_back(m_cursor);
        m_startSnap = m_snap;
        Status("원호의 끝 방향을 클릭하세요. 기본 CCW, Shift는 CW입니다.");
    }
    else
    {
        const Shape arc = ArcPreview(clockwise);
        if (Distance(m_points.at(0), m_cursor) <= MinimumLength || std::abs(arc.sweepAngle) <= 1e-10)
        {
            Status("중심이나 시작 방향과 다른 끝 방향을 선택하세요.");
            return;
        }
        Json action{{"type", "create_arc"},         {"layer_id", m_drawingLayer},
                          {"width", m_strokeWidth},       {"center", Coordinates(arc.center)},
                          {"radius", arc.radius},         {"start_angle", arc.startAngle},
                          {"sweep_angle", arc.sweepAngle}};
        storeRelations(action);
        m_points.clear();
        m_startSnap.reset();
        Emit(action);
    }
    Refresh(false);
}

void DesignCanvas::Emit(const Json& action)
{
    if (!m_editingEnabled)
    {
        return;
    }
    if (onAction)
    {
        onAction(action);
    }
}

/** @brief 드래그 중 단순 도형의 이전 위치와 새 위치 및 강조 테두리만 다시 그린다. */
void DesignCanvas::RefreshDragPreview(const Shape& shape, const Point& offset)
{
    const auto view = Viewport();
    const auto previous = GeometryPoint(m_dragOffset);
    const auto next = GeometryPoint(offset);
    const bool line = shape.kind == "line_path";
    if (!m_gesture.Dragging() || !shape.translationGroup.empty() || shape.selectionKind != "geometry" ||
        (!line && shape.kind != "arc_path") ||
        !view.Renderable(shape, previous) || !view.Renderable(shape, next))
    {
        Refresh(false);
        return;
    }
    const auto a = view.Project(line ? shape.start : shape.center, previous);
    const auto b = view.Project(line ? shape.end : shape.center, previous);
    const auto c = view.Project(line ? shape.start : shape.center, next);
    const auto d = view.Project(line ? shape.end : shape.center, next);
    const double padding = std::max(shape.width * view.pixelsPerMm, 1.0) / 2.0 + FromDIP(8) +
                           (line ? 0.0 : shape.radius * view.pixelsPerMm);
    const auto bound = [](double value, int size)
    {
        return static_cast<int>(std::clamp(value, 0.0, static_cast<double>(size)));
    };
    const int left = bound(std::floor(std::min({a.x, b.x, c.x, d.x}) - padding), view.width);
    const int right = bound(std::ceil(std::max({a.x, b.x, c.x, d.x}) + padding), view.width);
    const int top = bound(std::floor(std::min({a.y, b.y, c.y, d.y}) - padding), view.height);
    const int bottom = bound(std::ceil(std::max({a.y, b.y, c.y, d.y}) + padding), view.height);
    if (left < right && top < bottom)
    {
        RefreshRect(wxRect(left, top, right - left, bottom - top), false);
        if (m_drawDisplayMarker)
        {
            RefreshRect(m_displayMarkerBounds, false);
        }
    }
}

void DesignCanvas::OnMotion(wxMouseEvent& event)
{
    const wxPoint point = event.GetPosition();
    const bool hadSnap = m_snap.has_value();
    const auto previous = m_cursor;
    UpdateCursor(point);
    if (Distance(previous, m_cursor) > MinimumLength)
    {
        QueueRouteReview();
    }
    m_clockwise = event.ShiftDown();
    if (m_gesture.Panning())
    {
        const wxPoint movement = point - m_panLast;
        m_viewCenter.m_x = std::clamp(m_viewCenter.m_x - movement.x / m_pixelsPerMm, -CanvasGeometry::MaxCoordinate,
                                      CanvasGeometry::MaxCoordinate);
        m_viewCenter.m_y = std::clamp(m_viewCenter.m_y + movement.y / m_pixelsPerMm, -CanvasGeometry::MaxCoordinate,
                                      CanvasGeometry::MaxCoordinate);
        m_panLast = point;
        Refresh(false);
    }
    else if (m_editingEnabled && m_gesture.Selecting() && !m_selection.empty())
    {
        const Shape* shape = FindShape(m_selection);
        const wxPoint distance = point - m_mouseDown;
        if (shape != nullptr && shape->movable &&
            (m_gesture.Dragging() ||
             std::hypot(static_cast<double>(distance.x), static_cast<double>(distance.y)) >= FromDIP(3)))
        {
            const auto offset = Subtract(m_cursor, m_dragAnchor);
            RefreshDragPreview(*shape, offset);
            m_gesture.BeginDrag();
            m_dragOffset = offset;
        }
        else if (shape != nullptr && !shape->movable)
        {
            Status(shape->translationBlock.empty() ? "참조나 표현식에 연결된 형상은 속성에서 편집하세요."
                                                   : shape->translationBlock);
        }
    }
    else if (m_gesture.Reshaping() || !m_points.empty() || hadSnap || m_snap)
    {
        Refresh(false);
    }
}

void DesignCanvas::OnMiddleDown(wxMouseEvent& event)
{
    if (m_gesture.Selecting() || m_gesture.DrawingClick() || m_gesture.Reshaping())
    {
        CancelGesture();
    }
    m_snap.reset();
    m_gesture.BeginPan();
    m_panLast = event.GetPosition();
    SetFocus();
    if (!HasCapture())
    {
        CaptureMouse();
    }
}

void DesignCanvas::OnMiddleUp(wxMouseEvent&)
{
    if (m_gesture.Panning())
    {
        m_gesture.Reset();
        ReleaseOwnedCapture();
    }
}

/** @brief 커서 아래의 world 좌표가 같은 화면 위치에 남도록 배율과 중심을 함께 바꾼다. */
void DesignCanvas::OnWheel(wxMouseEvent& event)
{
    if (event.GetWheelDelta() == 0)
    {
        return;
    }
    if (m_gesture.Selecting() || m_gesture.DrawingClick() || m_gesture.Reshaping())
    {
        CancelGesture();
    }
    const wxPoint point = event.GetPosition();
    const Point anchor = ScreenToWorld(point);
    const double turns = std::clamp(static_cast<double>(event.GetWheelRotation()) / event.GetWheelDelta(), -12.0, 12.0);
    const double scale = std::clamp(m_pixelsPerMm * std::pow(1.2, turns), MinimumScale, MaximumScale);
    const wxSize size = GetClientSize();
    m_pixelsPerMm = scale;
    m_viewCenter = Point(std::clamp(anchor.m_x - (point.x - size.x / 2.0) / scale, -CanvasGeometry::MaxCoordinate,
                                    CanvasGeometry::MaxCoordinate),
                         std::clamp(anchor.m_y + (point.y - size.y / 2.0) / scale, -CanvasGeometry::MaxCoordinate,
                                    CanvasGeometry::MaxCoordinate));
    UpdateCursor(point);
    Refresh(false);
}

void DesignCanvas::OnKeyDown(wxKeyEvent& event)
{
    if (event.GetKeyCode() == WXK_ESCAPE)
    {
        const bool gesture = HasGesture();
        CancelGesture();
        if (gesture)
        {
            Status("캔버스 입력을 취소했습니다.");
        }
        return;
    }
    if (m_tool == "route" && m_editingEnabled && m_points.size() >= 2 && event.GetKeyCode() == 'V' && onRouteLayer)
    {
        auto count = m_routeTransitions.size();
        if (count > 0 && m_routeTransitions.back().at("index") == m_points.size() - 1)
        {
            --count;
        }
        onRouteLayer(count == 0 ? m_drawingLayer : m_routeTransitions[count - 1].at("layer_id").get<std::string>());
        return;
    }
    if (m_tool == "route" && !m_points.empty() && event.GetKeyCode() == WXK_BACK)
    {
        if (!m_routeTransitions.empty() && m_routeTransitions.back().at("index") == m_points.size() - 1)
        {
            m_routeTransitions.erase(m_routeTransitions.end() - 1);
        }
        else
        {
            m_points.pop_back();
        }
        QueueRouteReview();
        Refresh(false);
        return;
    }
    if (m_tool == "route" && m_editingEnabled && m_points.size() >= 2 &&
        (event.GetKeyCode() == WXK_RETURN || event.GetKeyCode() == WXK_NUMPAD_ENTER))
    {
        auto values = RouteDraft(false);
        values["type"] = "create_route";
        Emit(values);
        return;
    }
    if (event.GetKeyCode() == WXK_DELETE && m_editingEnabled && m_tool == "select" && !m_selection.empty())
    {
        CancelGesture();
        const Shape* shape = FindShape(m_selection);
        if (shape != nullptr && shape->selectionKind == "geometry" && Visible(*shape) && Renderable(*shape))
        {
            Emit(Json{{"type", "remove"}, {"id", m_selection}});
        }
        return;
    }
    if (m_clockwise != event.ShiftDown())
    {
        m_clockwise = event.ShiftDown();
        if (m_tool == "arc" && !m_points.empty())
        {
            Refresh(false);
        }
    }
    event.Skip();
}

void DesignCanvas::OnCaptureLost(wxMouseCaptureLostEvent&)
{
    m_gesture.Reset();
    m_points.clear();
    m_startSnap.reset();
    m_endpoint.reset();
    m_snap.reset();
    m_dragOffset = Point(0.0, 0.0);
    Status("입력 초점을 잃어 진행 중인 제스처를 취소했습니다.");
    Refresh(false);
}

void DesignCanvas::OnSize(wxSizeEvent& event)
{
    if (m_gesture.Active())
    {
        CancelGesture();
    }
    Refresh(false);
    event.Skip();
}
