/** @file @brief 표시 보간과 실제 RF 표본을 구분하며 카메라만 변경한다. */
#include "result_radiation_canvas.h"
#include "result_radiation_plane.h"
#include "result_presentation.h"
#include "studio_theme.h"
#include "studio_support.h"
#include <wx/dcbuffer.h>
#include <wx/graphics.h>
#include <GL/gl.h>
#include <algorithm>
#include <array>
#include <cmath>
namespace
{
const int Attributes[]{WX_GL_RGBA, WX_GL_DOUBLEBUFFER, WX_GL_DEPTH_SIZE, 16, 0};
std::array<double, 3> Colour(double value, double low, double high)
{
    const double t = high > low ? std::clamp((value - low) / (high - low), 0.0, 1.0) : 0.5;
    return {std::clamp(1.5 - std::abs(4.0 * t - 3.0), 0.0, 1.0), std::clamp(1.5 - std::abs(4.0 * t - 2.0), 0.0, 1.0),
            std::clamp(1.5 - std::abs(4.0 * t - 1.0), 0.0, 1.0)};
}
}
RadiationResultCanvas::RadiationResultCanvas(wxWindow* parent)
    : wxGLCanvas(parent, wxID_ANY, Attributes), m_context(std::make_unique<wxGLContext>(this))
{
    SetMinSize(FromDIP(wxSize(330, 320)));
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    Bind(wxEVT_PAINT, &RadiationResultCanvas::Paint, this);
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Refresh(false);
             event.Skip();
         });
    Bind(wxEVT_LEFT_DOWN,
         [this](wxMouseEvent& event)
         {
             SetFocus();
             m_dragging = true;
             m_last = event.GetPosition();
             CaptureMouse();
         });
    Bind(wxEVT_LEFT_UP,
         [this](wxMouseEvent&)
         {
             m_dragging = false;
             if (HasCapture())
             {
                 ReleaseMouse();
             }
         });
    Bind(wxEVT_MOUSE_CAPTURE_LOST,
         [this](wxMouseCaptureLostEvent&)
         {
             m_dragging = false;
         });
    Bind(wxEVT_MOTION,
         [this](wxMouseEvent& event)
         {
             if (m_dragging && event.Dragging())
             {
                 const auto delta = event.GetPosition() - m_last;
                 m_yaw += delta.x * 0.5;
                 m_pitch = std::clamp(m_pitch + delta.y * 0.5, -89.0, 89.0);
                 m_last = event.GetPosition();
                 Refresh(false);
             }
         });
    Bind(wxEVT_MOUSEWHEEL,
         [this](wxMouseEvent& event)
         {
             if (event.GetWheelDelta() != 0)
             {
                 m_zoom = std::clamp(
                     m_zoom * std::pow(1.15, static_cast<double>(event.GetWheelRotation()) / event.GetWheelDelta()),
                     0.25, 6.0);
                 Refresh(false);
             }
         });
    Bind(wxEVT_KEY_DOWN,
         [this](wxKeyEvent& event)
         {
             if (event.GetKeyCode() == 'F')
             {
                 Fit();
             }
             else if (event.GetKeyCode() == WXK_ESCAPE)
             {
                 m_dragging = false;
                 if (HasCapture())
                 {
                     ReleaseMouse();
                 }
             }
             else
             {
                 event.Skip();
             }
         });
}
RadiationResultCanvas::~RadiationResultCanvas()
{
    if (HasCapture())
    {
        ReleaseMouse();
    }
}
bool RadiationResultCanvas::Ready() const
{
    return m_context && m_context->IsOK();
}
void RadiationResultCanvas::SetPattern(const Json& data)
{
    m_data = data;
    Refresh(false);
}
void RadiationResultCanvas::Clear()
{
    m_data = nullptr;
    Refresh(false);
}
void RadiationResultCanvas::Fit()
{
    m_yaw = -35.0;
    m_pitch = 55.0;
    m_zoom = 1.0;
    Refresh(false);
}
void RadiationResultCanvas::Paint(wxPaintEvent&)
{
    wxPaintDC dc(this);
    if (!Ready() || !IsShownOnScreen() || !SetCurrent(*m_context))
    {
        return;
    }
    const auto size = GetClientSize();
    const double scale = GetContentScaleFactor();
    glViewport(0, 0, std::max(1, static_cast<int>(size.x * scale)), std::max(1, static_cast<int>(size.y * scale)));
    const auto background = StudioTheme::Colours().content;
    glClearColor(background.Red() / 255.0f, background.Green() / 255.0f, background.Blue() / 255.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glEnable(GL_DEPTH_TEST);
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    const double aspect = static_cast<double>(std::max(1, size.x)) / std::max(1, size.y);
    const double range = 1.5 / m_zoom;
    glOrtho(-range * aspect, range * aspect, -range, range, -10.0, 10.0);
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    glRotated(m_pitch, 1.0, 0.0, 0.0);
    glRotated(m_yaw, 0.0, 0.0, 1.0);
    glLineWidth(2.0f);
    glBegin(GL_LINES);
    glColor3d(0.8, 0.2, 0.2);
    glVertex3d(0, 0, 0);
    glVertex3d(1.25, 0, 0);
    glColor3d(0.15, 0.6, 0.2);
    glVertex3d(0, 0, 0);
    glVertex3d(0, 1.25, 0);
    glColor3d(0.1, 0.35, 0.85);
    glVertex3d(0, 0, 0);
    glVertex3d(0, 0, 1.25);
    glEnd();
    if (m_data.is_object())
    {
        const auto& points = m_data.at("projection");
        const auto& limits = m_data.at("color_range");
        const double low = limits.at(0).is_number() ? limits[0].get<double>() : 0.0,
                     high = limits.at(1).is_number() ? limits[1].get<double>() : 1.0;
        const auto vertex = [low, high](const Json& point)
        {
            if (point.at("color").is_number())
            {
                const auto rgb = Colour(point.at("color").get<double>(), low, high);
                glColor3dv(rgb.data());
            }
            else
            {
                glColor3d(0.65, 0.65, 0.65);
            }
            const auto& xyz = point.at("xyz");
            glVertex3d(xyz[0].get<double>(), xyz[1].get<double>(), xyz[2].get<double>());
        };
        for (std::size_t row = 1; row < points.size(); ++row)
        {
            const auto columns = points[row].size();
            glBegin(GL_TRIANGLE_STRIP);
            for (std::size_t column = 0; column <= columns; ++column)
            {
                vertex(points[row - 1][column % columns]);
                vertex(points[row][column % columns]);
            }
            glEnd();
        }
        glPointSize(3.0f);
        glBegin(GL_POINTS);
        for (const auto& row : points)
        {
            for (const auto& point : row)
            {
                vertex(point);
            }
        }
        glEnd();
    }
    glFlush();
    SwapBuffers();
}
RadiationResultSlice::RadiationResultSlice(wxWindow* parent) : wxPanel(parent)
{
    SetMinSize(FromDIP(wxSize(330, 320)));
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    Bind(wxEVT_PAINT, &RadiationResultSlice::Paint, this);
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Refresh(false);
             event.Skip();
         });
}
void RadiationResultSlice::SetPattern(const Json& data, int phiIndex)
{
    m_data = data;
    m_phiIndex = phiIndex;
    Refresh(false);
}
void RadiationResultSlice::Clear()
{
    m_data = nullptr;
    Refresh(false);
}
void RadiationResultSlice::Paint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(this);
    const auto colours = StudioTheme::Colours();
    dc.SetBackground(wxBrush(colours.content));
    dc.Clear();
    std::unique_ptr<wxGraphicsContext> gc(wxGraphicsContext::Create(dc));
    if (!gc)
    {
        return;
    }
    const auto size = GetClientSize();
    const double cx = size.x * 0.5, cy = size.y * 0.46, radius = std::max(20.0, std::min(size.x, size.y) * 0.35);
    gc->SetPen(wxPen(colours.border, 1));
    gc->SetBrush(*wxTRANSPARENT_BRUSH);
    for (int ring = 1; ring <= 4; ++ring)
    {
        const double r = radius * ring / 4;
        gc->DrawEllipse(cx - r, cy - r, 2 * r, 2 * r);
    }
    gc->StrokeLine(cx - radius, cy, cx + radius, cy);
    gc->StrokeLine(cx, cy - radius, cx, cy + radius);
    gc->SetFont(GetFont(), colours.text);
    gc->DrawText(Display("theta 0 deg"), cx + 4, cy - radius - 20);
    gc->DrawText(Display("90 deg"), cx + radius + 4, cy);
    gc->DrawText(Display("180 deg"), cx + 4, cy + radius + 4);
    if (!m_data.is_object())
    {
        gc->DrawText(Display("방사 기록을 선택하세요."), FromDIP(16), FromDIP(16));
        return;
    }
    const auto plane = RadiationPlaneCut::Build(m_data, m_phiIndex);
    const auto draw =
        [&gc, cx, cy, radius](const std::vector<RadiationPlanePoint>& points, const wxColour& colour, wxPenStyle style)
    {
        gc->SetPen(wxPen(colour, 2, style));
        gc->SetBrush(wxBrush(colour));
        auto path = gc->CreatePath();
        bool first = true;
        for (const auto& point : points)
        {
            const double x = cx + radius * point.x, y = cy - radius * point.y;
            if (first)
            {
                path.MoveToPoint(x, y);
                first = false;
            }
            else
            {
                path.AddLineToPoint(x, y);
            }
            gc->DrawEllipse(x - 2, y - 2, 4, 4);
        }
        gc->StrokePath(path);
    };
    draw(plane.primary, colours.accent, wxPENSTYLE_SOLID);
    draw(plane.opposite, wxColour(208, 97, 18), wxPENSTYLE_SHORT_DASH);
    const auto primary = ResultUi::Number(m_data.at("phi_deg").at(static_cast<std::size_t>(m_phiIndex)));
    gc->SetFont(GetFont(), colours.accent);
    gc->DrawText(Display("오른쪽 실선: phi " + primary + " deg"), FromDIP(12), size.y - FromDIP(48));
    gc->SetFont(GetFont(), plane.oppositePhi >= 0 ? wxColour(208, 97, 18) : colours.secondary);
    const auto caption =
        plane.oppositePhi >= 0
            ? "왼쪽 점선: phi " +
                  ResultUi::Number(m_data.at("phi_deg").at(static_cast<std::size_t>(plane.oppositePhi))) +
                  " deg / 실제 기록"
            : "반대 방위각 미기록 / 임의 미러 또는 보간 없음";
    gc->DrawText(Display(caption), FromDIP(12), size.y - FromDIP(24));
}
