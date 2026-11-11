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
    : wxPanel(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxWANTS_CHARS | wxBORDER_NONE)
{
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    SetMinSize(FromDIP(wxSize(260, 220)));
    Bind(wxEVT_PAINT, &DesignCanvas::OnPaint, this);
    Bind(wxEVT_LEFT_DOWN, &DesignCanvas::OnLeftDown, this);
    Bind(wxEVT_LEFT_UP, &DesignCanvas::OnLeftUp, this);
    Bind(wxEVT_MOTION, &DesignCanvas::OnMotion, this);
    Bind(wxEVT_MIDDLE_DOWN, &DesignCanvas::OnMiddleDown, this);
    Bind(wxEVT_MIDDLE_UP, &DesignCanvas::OnMiddleUp, this);
    Bind(wxEVT_MOUSEWHEEL, &DesignCanvas::OnWheel, this);
    Bind(wxEVT_KEY_DOWN, &DesignCanvas::OnKeyDown, this);
    Bind(wxEVT_KEY_UP, [this](wxKeyEvent& event)
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
    if (FindShape(m_selection) == nullptr)
    {
        m_selection.clear();
    }
    if (!m_fitted && (m_scene.hasBoard || !m_scene.shapes.empty()))
    {
        FitView();
    }
    Refresh(false);
}

void DesignCanvas::SetSelection(const std::string& identity)
{
    const Shape* shape = FindShape(identity);
    const std::string selected = shape != nullptr && Visible(*shape) && Renderable(*shape) ? identity : std::string();
    if (m_selection != selected)
    {
        m_selection = selected;
        Refresh(false);
    }
}

void DesignCanvas::SetTool(const std::string& tool)
{
    if (tool != "select" && tool != "line" && tool != "arc")
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
    Status(tool == "line" ? "선: 시작점과 끝점을 클릭하세요. Esc로 취소합니다." :
        (tool == "arc" ? "원호: 중심, 시작점, 끝 방향을 클릭하세요. 기본 CCW, Shift는 CW입니다." : "선택: 클릭 또는 드래그. 휠 확대, 가운데 버튼 이동."));
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
    m_strokeWidth = widthMm;
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
    Refresh(false);
}

/** @brief 두께와 실제 원호 구간을 포함한 유한 경계에 맞춘다. */
void DesignCanvas::FitView()
{
    CancelGesture();
    const auto bounds = m_scene.VisibleBounds(m_hiddenLayers);
    const double left = bounds.left, bottom = bounds.bottom, right = bounds.right, top = bounds.top;
    m_viewCenter = Point(std::clamp((left + right) / 2.0, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate),
        std::clamp((bottom + top) / 2.0, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate));
    const wxSize size = GetClientSize();
    const double availableX = std::max(20, size.x - FromDIP(70));
    const double availableY = std::max(20, size.y - FromDIP(70));
    m_pixelsPerMm = std::clamp(std::min(availableX / std::max(1e-6, right - left),
        availableY / std::max(1e-6, top - bottom)), MinimumScale, MaximumScale);
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
    const bool changed = HasGesture();
    m_points.clear();
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
std::string DesignCanvas::HitTest(const wxPoint& point) const
{
    const Point world = ScreenToWorld(point);
    for (auto shape = m_scene.shapes.rbegin(); shape != m_scene.shapes.rend(); ++shape)
    {
        if (!Visible(*shape) || !Renderable(*shape))
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

std::size_t DesignCanvas::DisplayOmissionCount() const
{
    return m_scene.omissionCount + m_scene.rangeOmissionCount + static_cast<std::size_t>(std::count_if(m_scene.shapes.begin(), m_scene.shapes.end(), [&](const Shape& shape)
    {
        const Point offset = m_gesture.Dragging() && shape.id == m_selection ? m_dragOffset :
            (shape.id == m_pendingId ? m_pendingOffset : Point(0.0, 0.0));
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

void DesignCanvas::OnPaint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(this);
    dc.SetBackground(wxBrush(wxColour(250, 251, 253)));
    dc.Clear();
    CanvasRenderer renderer(*this, dc, Viewport());
    renderer.DrawGrid(m_showGrid);
    renderer.DrawBoard(m_scene);
    const wxColour colours[] = {wxColour(189, 109, 36), wxColour(117, 87, 173), wxColour(27, 144, 138), wxColour(177, 74, 96)};
    std::size_t nativeOmissions = m_scene.rangeOmissionCount;
    for (const Shape& shape : m_scene.shapes)
    {
        if (!Visible(shape))
        {
            continue;
        }
        const auto layer = m_scene.layers.find(shape.layer);
        const std::size_t index = static_cast<std::size_t>(std::distance(m_scene.layers.begin(), layer)) % 4;
        Point offset(0.0, 0.0);
        if (m_gesture.Dragging() && shape.id == m_selection)
        {
            offset = m_dragOffset;
        }
        else if (shape.id == m_pendingId)
        {
            offset = m_pendingOffset;
        }
        if (!renderer.DrawShape(shape, GeometryPoint(offset), colours[index], shape.id == m_selection))
        {
            ++nativeOmissions;
        }
    }
    renderer.Flush();
    DrawPreview(dc, renderer);
    renderer.Flush();
    dc.SetTextForeground(wxColour(73, 86, 103));
    dc.DrawText(Display("2D 설계 / mm"), FromDIP(10), FromDIP(10));
    if (m_scene.omissionCount > 0)
    {
        dc.DrawText(Display("표시 생략 " + std::to_string(m_scene.omissionCount) + "개"), FromDIP(10), FromDIP(30));
    }
    if (nativeOmissions > 0)
    {
        dc.DrawText(Display("표시 범위를 초과한 형상 " + std::to_string(nativeOmissions) + "개"), FromDIP(10), FromDIP(50));
    }
}

DesignCanvas::Shape DesignCanvas::ArcPreview(bool clockwise) const
{
    Shape arc;
    arc.kind = "arc_path";
    arc.center = GeometryPoint(m_points.at(0));
    arc.radius = Distance(m_points.at(0), m_points.at(1));
    arc.startAngle = CanvasGeometry::NormalizeDegrees(std::atan2(m_points[1].m_y - arc.center.y,
        m_points[1].m_x - arc.center.x) * 180.0 / CanvasGeometry::Pi);
    arc.sweepAngle = CanvasGeometry::SweepDegrees(GeometryPoint(arc.center), GeometryPoint(m_points[1]), GeometryPoint(m_cursor), clockwise);
    arc.width = m_strokeWidth;
    return arc;
}

void DesignCanvas::DrawPreview(wxDC& dc, CanvasRenderer& renderer) const
{
    if (m_points.empty())
    {
        return;
    }
    dc.SetPen(wxPen(wxColour(41, 132, 202), FromDIP(1), wxPENSTYLE_SHORT_DASH));
    dc.SetBrush(*wxTRANSPARENT_BRUSH);
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
    m_cursor = ScreenToWorld(m_mouseDown);
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
        m_selection = HitTest(m_mouseDown);
        m_gesture.BeginSelection();
        m_dragAnchor = m_cursor;
        m_dragOffset = Point(0.0, 0.0);
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
    m_cursor = ScreenToWorld(event.GetPosition());
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
    if (m_points.empty())
    {
        m_points.push_back(m_cursor);
        Status(m_tool == "line" ? "선의 끝점을 클릭하세요." : "원호의 시작점을 클릭하세요.");
    }
    else if (m_tool == "line")
    {
        if (Distance(m_points[0], m_cursor) <= MinimumLength)
        {
            Status("시작점과 다른 끝점을 선택하세요.");
            return;
        }
        const Json action{{"type", "create_line"}, {"layer_id", m_drawingLayer}, {"width", m_strokeWidth},
            {"start", Coordinates(GeometryPoint(m_points[0]))}, {"end", Coordinates(GeometryPoint(m_cursor))}};
        m_points.clear();
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
        const Json action{{"type", "create_arc"}, {"layer_id", m_drawingLayer}, {"width", m_strokeWidth},
            {"center", Coordinates(arc.center)}, {"radius", arc.radius}, {"start_angle", arc.startAngle}, {"sweep_angle", arc.sweepAngle}};
        m_points.clear();
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

void DesignCanvas::OnMotion(wxMouseEvent& event)
{
    const wxPoint point = event.GetPosition();
    m_cursor = ScreenToWorld(point);
    m_clockwise = event.ShiftDown();
    if (m_gesture.Panning())
    {
        const wxPoint movement = point - m_panLast;
        m_viewCenter.m_x = std::clamp(m_viewCenter.m_x - movement.x / m_pixelsPerMm, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate);
        m_viewCenter.m_y = std::clamp(m_viewCenter.m_y + movement.y / m_pixelsPerMm, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate);
        m_panLast = point;
        Refresh(false);
    }
    else if (m_editingEnabled && m_gesture.Selecting() && !m_selection.empty())
    {
        const Shape* shape = FindShape(m_selection);
        const wxPoint distance = point - m_mouseDown;
        if (shape != nullptr && shape->movable &&
            (m_gesture.Dragging() || std::hypot(static_cast<double>(distance.x), static_cast<double>(distance.y)) >= FromDIP(3)))
        {
            m_gesture.BeginDrag();
            m_dragOffset = Subtract(m_cursor, m_dragAnchor);
            Refresh(false);
        }
        else if (shape != nullptr && !shape->movable)
        {
            Status("참조나 표현식에 연결된 형상은 속성에서 편집하세요.");
        }
    }
    else if (!m_points.empty())
    {
        Refresh(false);
    }
}

void DesignCanvas::OnMiddleDown(wxMouseEvent& event)
{
    if (m_gesture.Selecting() || m_gesture.DrawingClick())
    {
        CancelGesture();
    }
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
    if (m_gesture.Selecting() || m_gesture.DrawingClick())
    {
        CancelGesture();
    }
    const wxPoint point = event.GetPosition();
    const Point anchor = ScreenToWorld(point);
    const double turns = std::clamp(static_cast<double>(event.GetWheelRotation()) / event.GetWheelDelta(), -12.0, 12.0);
    const double scale = std::clamp(m_pixelsPerMm * std::pow(1.2, turns), MinimumScale, MaximumScale);
    const wxSize size = GetClientSize();
    m_pixelsPerMm = scale;
    m_viewCenter = Point(std::clamp(anchor.m_x - (point.x - size.x / 2.0) / scale, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate),
        std::clamp(anchor.m_y + (point.y - size.y / 2.0) / scale, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate));
    m_cursor = ScreenToWorld(point);
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
    if (event.GetKeyCode() == WXK_DELETE && m_editingEnabled && m_tool == "select" && !m_selection.empty())
    {
        CancelGesture();
        const Shape* shape = FindShape(m_selection);
        if (shape != nullptr && Visible(*shape) && Renderable(*shape))
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
    m_dragOffset = Point(0.0, 0.0);
    Status("입력 초점을 잃어 진행 중인 제스처를 취소했습니다.");
    Refresh(false);
}

void DesignCanvas::OnSize(wxSizeEvent& event)
{
    if (m_gesture.Selecting() || m_gesture.DrawingClick() || m_gesture.Panning())
    {
        CancelGesture();
    }
    Refresh(false);
    event.Skip();
}
