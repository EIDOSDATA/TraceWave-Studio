#include "design_canvas.h"
#include "canvas_geometry.h"

#include <wx/dcbuffer.h>
#include <wx/graphics.h>

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
constexpr double MaximumNativeCoordinate = 1.0e6;
constexpr double MaximumClipCoordinate = 1.0e12;

/** @brief 원본이 잘못된 경우와 현재 화면의 표시 범위를 초과한 경우를 구분한다. */
class DisplayRangeError final : public std::runtime_error
{
public:
    explicit DisplayRangeError(const char* message) : std::runtime_error(message)
    {
    }
};

wxString Display(const std::string& value)
{
    return wxString::FromUTF8(value.data(), value.size());
}

CanvasGeometry::Point GeometryPoint(const Point& point)
{
    return {point.m_x, point.m_y};
}

bool Valid(const Point& point)
{
    return CanvasGeometry::Valid(GeometryPoint(point));
}

Point ReadPoint(const Json& value)
{
    if (!value.is_array() || value.size() != 2 || !value[0].is_number() || !value[1].is_number())
    {
        throw std::runtime_error("표시 좌표는 두 숫자의 배열이어야 합니다.");
    }
    const Point point(value[0].get<double>(), value[1].get<double>());
    if (!std::isfinite(point.m_x) || !std::isfinite(point.m_y))
    {
        throw std::runtime_error("표시 좌표는 유한해야 합니다.");
    }
    if (!Valid(point))
    {
        throw DisplayRangeError("현재 캔버스의 좌표 표시 범위를 초과했습니다.");
    }
    return point;
}

double Positive(const Json& value)
{
    if (!value.is_number())
    {
        throw std::runtime_error("표시 치수는 숫자여야 합니다.");
    }
    const double number = value.get<double>();
    if (!std::isfinite(number) || number <= 0.0)
    {
        throw std::runtime_error("표시 치수가 유한한 양수 범위를 벗어났습니다.");
    }
    if (number > CanvasGeometry::MaxCoordinate)
    {
        throw DisplayRangeError("현재 캔버스의 치수 표시 범위를 초과했습니다.");
    }
    return number;
}

Json Coordinates(const Point& point)
{
    return Json::array({point.m_x, point.m_y});
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
    std::vector<Shape> shapes;
    std::set<std::string> layers;
    std::set<std::string> identities;
    const Json& board = scene.at("board");
    bool hasBoard = !board.is_null() && !board.at("width").is_null() && !board.at("height").is_null();
    double boardWidth = 0.0;
    double boardHeight = 0.0;
    std::size_t rangeOmissions = 0;
    if (hasBoard)
    {
        try
        {
            boardWidth = Positive(board.at("width"));
            boardHeight = Positive(board.at("height"));
        }
        catch (const DisplayRangeError&)
        {
            hasBoard = false;
            ++rangeOmissions;
        }
    }
    for (const auto& layer : scene.at("layers"))
    {
        layers.insert(layer.at("id").get<std::string>());
    }
    if (!scene.at("shapes").is_array() || scene.at("shapes").size() > 4096)
    {
        throw std::runtime_error("초기 캔버스 표시 객체 수를 초과했습니다.");
    }
    for (const auto& item : scene.at("shapes"))
    {
        try
        {
            Shape shape;
            shape.id = item.at("id").get<std::string>();
            shape.kind = item.at("kind").get<std::string>();
            shape.label = item.value("label", shape.id);
            shape.layer = item.at("layer_id").get<std::string>();
            shape.role = item.value("role", std::string("conductor"));
            shape.width = Positive(item.at("width"));
            shape.movable = item.value("movable", false);
            if (shape.id.empty() || !identities.insert(shape.id).second || !layers.count(shape.layer))
            {
                throw std::runtime_error("표시 객체의 식별자 또는 층 참조가 유효하지 않습니다.");
            }
            if (shape.kind == "line_path")
            {
                shape.start = ReadPoint(item.at("start"));
                shape.end = ReadPoint(item.at("end"));
                if (Distance(shape.start, shape.end) == 0.0)
                {
                    throw std::runtime_error("0 길이 선을 표시할 수 없습니다.");
                }
            }
            else if (shape.kind == "arc_path")
            {
                shape.center = ReadPoint(item.at("center"));
                shape.radius = Positive(item.at("radius"));
                shape.startAngle = item.at("start_angle").get<double>();
                shape.sweepAngle = item.at("sweep_angle").get<double>();
                if (!std::isfinite(shape.startAngle) || !std::isfinite(shape.sweepAngle) ||
                    shape.sweepAngle == 0.0 || std::abs(shape.sweepAngle) > 360.0 + 1e-10)
                {
                    throw std::runtime_error("표시 원호의 각도 구간이 유효하지 않습니다.");
                }
                shape.startAngle = CanvasGeometry::NormalizeDegrees(shape.startAngle);
            }
            else
            {
                throw std::runtime_error("지원하지 않는 2D 표시 형상입니다.");
            }
            shapes.push_back(std::move(shape));
        }
        catch (const DisplayRangeError&)
        {
            ++rangeOmissions;
        }
    }
    CancelGesture();
    m_pendingId.clear();
    m_pendingOffset = Point(0.0, 0.0);
    m_shapes = std::move(shapes);
    m_layers = std::move(layers);
    m_hasBoard = hasBoard;
    m_boardWidth = boardWidth;
    m_boardHeight = boardHeight;
    m_omissionCount = scene.contains("omissions") && scene.at("omissions").is_array() ? scene.at("omissions").size() : 0;
    m_rangeOmissionCount = rangeOmissions;
    if (FindShape(m_selection) == nullptr)
    {
        m_selection.clear();
    }
    if (!m_fitted && (m_hasBoard || !m_shapes.empty()))
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
    double left = std::numeric_limits<double>::infinity();
    double bottom = left;
    double right = -left;
    double top = -left;
    auto include = [&](double x, double y, double padding)
    {
        if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(padding))
        {
            return;
        }
        left = std::min(left, x - padding);
        right = std::max(right, x + padding);
        bottom = std::min(bottom, y - padding);
        top = std::max(top, y + padding);
    };
    if (m_hasBoard)
    {
        include(0.0, 0.0, 0.0);
        include(m_boardWidth, m_boardHeight, 0.0);
    }
    for (const Shape& shape : m_shapes)
    {
        if (!Visible(shape))
        {
            continue;
        }
        if (shape.kind == "line_path")
        {
            include(shape.start.m_x, shape.start.m_y, shape.width / 2.0);
            include(shape.end.m_x, shape.end.m_y, shape.width / 2.0);
        }
        else
        {
            const auto first = CanvasGeometry::ArcPoint(GeometryPoint(shape.center), shape.radius, shape.startAngle);
            const auto last = CanvasGeometry::ArcPoint(GeometryPoint(shape.center), shape.radius, shape.startAngle + shape.sweepAngle);
            include(first.x, first.y, shape.width / 2.0);
            include(last.x, last.y, shape.width / 2.0);
            for (double angle : {0.0, 90.0, 180.0, 270.0})
            {
                if (CanvasGeometry::InSweep(angle, shape.startAngle, shape.sweepAngle))
                {
                    const auto point = CanvasGeometry::ArcPoint(GeometryPoint(shape.center), shape.radius, angle);
                    include(point.x, point.y, shape.width / 2.0);
                }
            }
        }
    }
    if (!std::isfinite(left))
    {
        left = -20.0;
        right = 20.0;
        bottom = -20.0;
        top = 20.0;
    }
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
    m_selecting = false;
    m_drawingClick = false;
    m_dragging = false;
    m_panning = false;
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
    const wxSize size = GetClientSize();
    const double x = size.x / 2.0 + (point.m_x - m_viewCenter.m_x) * m_pixelsPerMm;
    const double y = size.y / 2.0 - (point.m_y - m_viewCenter.m_y) * m_pixelsPerMm;
    return wxPoint(static_cast<int>(std::llround(std::clamp(x, -1e7, 1e7))),
        static_cast<int>(std::llround(std::clamp(y, -1e7, 1e7))));
}

Point DesignCanvas::ScreenToWorld(const wxPoint& point) const
{
    const wxSize size = GetClientSize();
    return Point(std::clamp(m_viewCenter.m_x + (point.x - size.x / 2.0) / m_pixelsPerMm,
        -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate),
        std::clamp(m_viewCenter.m_y - (point.y - size.y / 2.0) / m_pixelsPerMm,
        -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate));
}

const DesignCanvas::Shape* DesignCanvas::FindShape(const std::string& identity) const
{
    const auto found = std::find_if(m_shapes.begin(), m_shapes.end(), [&](const Shape& shape)
    {
        return shape.id == identity;
    });
    return found == m_shapes.end() ? nullptr : &*found;
}

bool DesignCanvas::Visible(const Shape& shape) const
{
    return m_hiddenLayers.count(shape.layer) == 0;
}

Point DesignCanvas::PixelPoint(const Point& point, const Point& offset) const
{
    const wxSize size = GetClientSize();
    return Point(size.x / 2.0 + (point.m_x + offset.m_x - m_viewCenter.m_x) * m_pixelsPerMm,
        size.y / 2.0 - (point.m_y + offset.m_y - m_viewCenter.m_y) * m_pixelsPerMm);
}

/** @brief float 기반 native renderer에 넘길 수 없는 원호와 폭은 선택에서도 제외한다. */
bool DesignCanvas::Renderable(const Shape& shape, const Point& offset) const
{
    const double width = shape.width * m_pixelsPerMm;
    if (!std::isfinite(width) || width > MaximumNativeCoordinate)
    {
        return false;
    }
    if (shape.kind == "line_path")
    {
        const Point start = PixelPoint(shape.start, offset);
        const Point end = PixelPoint(shape.end, offset);
        return std::isfinite(start.m_x) && std::isfinite(start.m_y) && std::isfinite(end.m_x) && std::isfinite(end.m_y) &&
            std::max({std::abs(start.m_x), std::abs(start.m_y), std::abs(end.m_x), std::abs(end.m_y)}) <= MaximumClipCoordinate;
    }
    const Point center = PixelPoint(shape.center, offset);
    const double extent = shape.radius * m_pixelsPerMm + width / 2.0;
    return std::isfinite(extent) && std::isfinite(center.m_x) && std::isfinite(center.m_y) &&
        std::max(std::abs(center.m_x), std::abs(center.m_y)) + extent <= MaximumNativeCoordinate;
}

/** @brief 실제 선분과 원호 구간까지의 거리로 위에 그린 객체를 먼저 선택한다. */
std::string DesignCanvas::HitTest(const wxPoint& point) const
{
    const Point world = ScreenToWorld(point);
    for (auto shape = m_shapes.rbegin(); shape != m_shapes.rend(); ++shape)
    {
        if (!Visible(*shape) || !Renderable(*shape))
        {
            continue;
        }
        const double tolerance = shape->width / 2.0 + FromDIP(6) / m_pixelsPerMm;
        const double distance = shape->kind == "line_path" ?
            CanvasGeometry::SegmentDistance(GeometryPoint(world), GeometryPoint(shape->start), GeometryPoint(shape->end)) :
            CanvasGeometry::ArcDistance(GeometryPoint(world), GeometryPoint(shape->center), shape->radius, shape->startAngle, shape->sweepAngle);
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
    return !m_points.empty() || m_selecting || m_drawingClick || m_dragging || m_panning;
}

std::size_t DesignCanvas::DisplayOmissionCount() const
{
    return m_omissionCount + m_rangeOmissionCount + static_cast<std::size_t>(std::count_if(m_shapes.begin(), m_shapes.end(), [&](const Shape& shape)
    {
        const Point offset = m_dragging && shape.id == m_selection ? m_dragOffset :
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

void DesignCanvas::DrawGrid(wxDC& dc) const
{
    const wxSize size = GetClientSize();
    const Point low = ScreenToWorld(wxPoint(0, size.y));
    const Point high = ScreenToWorld(wxPoint(size.x, 0));
    if (m_showGrid)
    {
        double step = std::pow(10.0, std::floor(std::log10(50.0 / m_pixelsPerMm)));
        if (step * m_pixelsPerMm < 20.0)
        {
            step *= 5.0;
        }
        else if (step * m_pixelsPerMm < 35.0)
        {
            step *= 2.0;
        }
        dc.SetPen(wxPen(wxColour(230, 234, 239), 1));
        const double startX = std::ceil(low.m_x / step) * step;
        const double startY = std::ceil(low.m_y / step) * step;
        for (int i = 0; i < 400 && startX + i * step <= high.m_x; ++i)
        {
            const int x = WorldToScreen(Point(startX + i * step, 0.0)).x;
            dc.DrawLine(x, 0, x, size.y);
        }
        for (int i = 0; i < 400 && startY + i * step <= high.m_y; ++i)
        {
            const int y = WorldToScreen(Point(0.0, startY + i * step)).y;
            dc.DrawLine(0, y, size.x, y);
        }
    }
    const wxPoint origin = WorldToScreen(Point(0.0, 0.0));
    dc.SetPen(wxPen(wxColour(151, 163, 176), 1));
    if (origin.x >= 0 && origin.x <= size.x)
    {
        dc.DrawLine(origin.x, 0, origin.x, size.y);
    }
    if (origin.y >= 0 && origin.y <= size.y)
    {
        dc.DrawLine(0, origin.y, size.x, origin.y);
    }
    dc.SetTextForeground(wxColour(94, 107, 121));
    dc.DrawText("X / mm", std::max(2, size.x - FromDIP(60)), std::clamp(origin.y + 4, 2, std::max(2, size.y - FromDIP(22))));
    dc.DrawText("Y / mm", std::clamp(origin.x + 4, 2, std::max(2, size.x - FromDIP(60))), FromDIP(4));
}

/** @brief Y-up 좌표를 화면으로 변환하고 원호는 부호 있는 곡선으로 그린다. */
bool DesignCanvas::DrawShape(wxDC& dc, const Shape& shape, const Point& offset, const wxColour& colour, bool highlight) const
{
    if (!Renderable(shape, offset))
    {
        return false;
    }
    std::unique_ptr<wxGraphicsContext> graphics(wxGraphicsContext::CreateFromUnknownDC(dc));
    if (!graphics)
    {
        return false;
    }
    graphics->Clip(0, 0, GetClientSize().x, GetClientSize().y);
    wxGraphicsPath path = graphics->CreatePath();
    if (shape.kind == "line_path")
    {
        CanvasGeometry::Point start = GeometryPoint(PixelPoint(shape.start, offset));
        CanvasGeometry::Point end = GeometryPoint(PixelPoint(shape.end, offset));
        const double padding = std::max(1.0, shape.width * m_pixelsPerMm) / 2.0 + FromDIP(8);
        if (!CanvasGeometry::ClipSegment(start, end, -padding, -padding, GetClientSize().x + padding, GetClientSize().y + padding))
        {
            return true;
        }
        path.MoveToPoint(start.x, start.y);
        path.AddLineToPoint(end.x, end.y);
    }
    else
    {
        const Point center = PixelPoint(shape.center, offset);
        path.AddArc(center.m_x, center.m_y, shape.radius * m_pixelsPerMm,
            -shape.startAngle * CanvasGeometry::Pi / 180.0,
            -(shape.startAngle + shape.sweepAngle) * CanvasGeometry::Pi / 180.0, shape.sweepAngle < 0.0);
    }
    const double width = std::max(shape.width * m_pixelsPerMm, 1.0);
    if (highlight)
    {
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

void DesignCanvas::OnPaint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(this);
    dc.SetBackground(wxBrush(wxColour(250, 251, 253)));
    dc.Clear();
    DrawGrid(dc);
    if (m_hasBoard)
    {
        const wxPoint leftTop = WorldToScreen(Point(0.0, m_boardHeight));
        const wxPoint rightBottom = WorldToScreen(Point(m_boardWidth, 0.0));
        dc.SetPen(wxPen(wxColour(105, 153, 117), FromDIP(2)));
        dc.SetBrush(wxBrush(wxColour(232, 243, 235), wxBRUSHSTYLE_BDIAGONAL_HATCH));
        dc.DrawRectangle(wxRect(leftTop, rightBottom));
    }
    const wxColour colours[] = {wxColour(189, 109, 36), wxColour(117, 87, 173), wxColour(27, 144, 138), wxColour(177, 74, 96)};
    std::size_t nativeOmissions = m_rangeOmissionCount;
    for (const Shape& shape : m_shapes)
    {
        if (!Visible(shape))
        {
            continue;
        }
        const auto layer = m_layers.find(shape.layer);
        const std::size_t index = static_cast<std::size_t>(std::distance(m_layers.begin(), layer)) % 4;
        Point offset(0.0, 0.0);
        if (m_dragging && shape.id == m_selection)
        {
            offset = m_dragOffset;
        }
        else if (shape.id == m_pendingId)
        {
            offset = m_pendingOffset;
        }
        if (!DrawShape(dc, shape, offset, colours[index], shape.id == m_selection))
        {
            ++nativeOmissions;
        }
    }
    DrawPreview(dc);
    dc.SetTextForeground(wxColour(73, 86, 103));
    dc.DrawText(Display("2D 설계 / mm"), FromDIP(10), FromDIP(10));
    if (m_omissionCount > 0)
    {
        dc.DrawText(Display("표시 생략 " + std::to_string(m_omissionCount) + "개"), FromDIP(10), FromDIP(30));
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
    arc.center = m_points.at(0);
    arc.radius = Distance(m_points.at(0), m_points.at(1));
    arc.startAngle = CanvasGeometry::NormalizeDegrees(std::atan2(m_points[1].m_y - arc.center.m_y,
        m_points[1].m_x - arc.center.m_x) * 180.0 / CanvasGeometry::Pi);
    arc.sweepAngle = CanvasGeometry::SweepDegrees(GeometryPoint(arc.center), GeometryPoint(m_points[1]), GeometryPoint(m_cursor), clockwise);
    arc.width = m_strokeWidth;
    return arc;
}

void DesignCanvas::DrawPreview(wxDC& dc) const
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
        line.start = m_points[0];
        line.end = m_cursor;
        line.width = m_strokeWidth;
        DrawShape(dc, line, Point(0.0, 0.0), wxColour(64, 148, 209), false);
    }
    else if (m_tool == "arc" && m_points.size() == 2)
    {
        const Shape arc = ArcPreview(m_clockwise);
        dc.DrawLine(first, WorldToScreen(m_points[1]));
        if (std::abs(arc.sweepAngle) > 1e-10)
        {
            DrawShape(dc, arc, Point(0.0, 0.0), wxColour(64, 148, 209), false);
        }
    }
}

void DesignCanvas::OnLeftDown(wxMouseEvent& event)
{
    SetFocus();
    if (!m_editingEnabled || m_panning)
    {
        return;
    }
    m_mouseDown = event.GetPosition();
    m_cursor = ScreenToWorld(m_mouseDown);
    m_clockwise = event.ShiftDown();
    if (m_tool != "select")
    {
        if (m_drawingLayer.empty() || !m_layers.count(m_drawingLayer) || m_hiddenLayers.count(m_drawingLayer))
        {
            Status("표시 중인 그리기 층을 먼저 선택하세요.");
            return;
        }
        m_drawingClick = true;
    }
    else
    {
        m_selection = HitTest(m_mouseDown);
        m_selecting = true;
        m_dragging = false;
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
    if (m_drawingClick)
    {
        m_drawingClick = false;
        ReleaseOwnedCapture();
        if (GetClientRect().Contains(event.GetPosition()))
        {
            CommitDrawing(event.ShiftDown());
        }
        return;
    }
    if (!m_selecting)
    {
        return;
    }
    const bool translate = m_dragging;
    const std::string identity = m_selection;
    const Point offset = Subtract(m_cursor, m_dragAnchor);
    m_selecting = false;
    m_dragging = false;
    m_dragOffset = Point(0.0, 0.0);
    ReleaseOwnedCapture();
    if (translate && Valid(offset) && Distance(offset, Point(0.0, 0.0)) > MinimumLength)
    {
        m_pendingId = identity;
        m_pendingOffset = offset;
        Emit(Json{{"type", "translate"}, {"id", identity}, {"delta", Coordinates(offset)}});
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
            {"start", Coordinates(m_points[0])}, {"end", Coordinates(m_cursor)}};
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
        if (Distance(arc.center, m_cursor) <= MinimumLength || std::abs(arc.sweepAngle) <= 1e-10)
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
    if (m_panning)
    {
        const wxPoint movement = point - m_panLast;
        m_viewCenter.m_x = std::clamp(m_viewCenter.m_x - movement.x / m_pixelsPerMm, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate);
        m_viewCenter.m_y = std::clamp(m_viewCenter.m_y + movement.y / m_pixelsPerMm, -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate);
        m_panLast = point;
        Refresh(false);
    }
    else if (m_editingEnabled && m_selecting && !m_selection.empty())
    {
        const Shape* shape = FindShape(m_selection);
        const wxPoint distance = point - m_mouseDown;
        if (shape != nullptr && shape->movable &&
            (m_dragging || std::hypot(static_cast<double>(distance.x), static_cast<double>(distance.y)) >= FromDIP(3)))
        {
            m_dragging = true;
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
    if (m_selecting || m_drawingClick)
    {
        CancelGesture();
    }
    m_panning = true;
    m_panLast = event.GetPosition();
    SetFocus();
    if (!HasCapture())
    {
        CaptureMouse();
    }
}

void DesignCanvas::OnMiddleUp(wxMouseEvent&)
{
    if (m_panning)
    {
        m_panning = false;
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
    if (m_selecting || m_drawingClick)
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
    m_selecting = false;
    m_drawingClick = false;
    m_dragging = false;
    m_panning = false;
    m_points.clear();
    m_dragOffset = Point(0.0, 0.0);
    Status("입력 초점을 잃어 진행 중인 제스처를 취소했습니다.");
    Refresh(false);
}

void DesignCanvas::OnSize(wxSizeEvent& event)
{
    if (m_selecting || m_drawingClick || m_panning)
    {
        CancelGesture();
    }
    Refresh(false);
    event.Skip();
}
