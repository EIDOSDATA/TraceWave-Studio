/** @file @brief 종이 좌표를 화면 픽셀에만 투영하며 출력 형상은 수정하지 않는다. */
#include "drawing_sheet_canvas.h"
#include "drawing_sheet_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/dcbuffer.h>
#include <wx/graphics.h>
#include <algorithm>
#include <cmath>
#include <memory>

namespace
{
constexpr double Pi = 3.14159265358979323846;
wxColour Colour(const Json& value, const wxColour& fallback)
{
    if (!value.is_array())
    {
        return fallback;
    }
    return wxColour(value.at(0).get<unsigned char>(), value.at(1).get<unsigned char>(),
                    value.at(2).get<unsigned char>());
}

/** @brief 부호 있는 원호의 화면 벡터를 구성하며 원문 원호/출력 공차는 바꾸지 않는다. */
void Arc(wxGraphicsPath& path, const Json& value, bool move = true)
{
    const double cx = value.at("center").at(0), cy = value.at("center").at(1), radius = value.at("radius");
    const double start = value.at("start_deg").get<double>() * Pi / 180.0;
    const double sweep = value.at("sweep_deg").get<double>() * Pi / 180.0;
    const int pieces = std::max(1, static_cast<int>(std::ceil(std::abs(sweep) / (Pi / 2))));
    const double step = sweep / pieces;
    if (move)
    {
        path.MoveToPoint(cx + radius * std::cos(start), cy + radius * std::sin(start));
    }
    for (int index = 0; index < pieces; ++index)
    {
        const double from = start + index * step, to = from + step;
        const double factor = (4.0 / 3.0) * std::tan(step / 4.0);
        path.AddCurveToPoint(cx + radius * (std::cos(from) - factor * std::sin(from)),
                             cy + radius * (std::sin(from) + factor * std::cos(from)),
                             cx + radius * (std::cos(to) + factor * std::sin(to)),
                             cy + radius * (std::sin(to) - factor * std::cos(to)), cx + radius * std::cos(to),
                             cy + radius * std::sin(to));
    }
}

void Shape(wxGraphicsContext& graphics, const Json& primitive)
{
    auto path = graphics.CreatePath();
    const auto kind = primitive.at("kind").get<std::string>();
    if (kind == "line")
    {
        path.MoveToPoint(primitive.at("start").at(0), primitive.at("start").at(1));
        path.AddLineToPoint(primitive.at("end").at(0), primitive.at("end").at(1));
    }
    else if (kind == "circle")
    {
        const double radius = primitive.at("radius");
        path.AddCircle(primitive.at("center").at(0), primitive.at("center").at(1), radius);
    }
    else if (kind == "arc")
    {
        Arc(path, primitive);
    }
    else if (kind == "path")
    {
        if (primitive.contains("loops"))
        {
            for (const auto& loop : primitive.at("loops"))
            {
                bool first = true;
                for (const auto& segment : loop)
                {
                    if (segment.at("kind") == "arc")
                    {
                        Arc(path, segment, first);
                    }
                    else
                    {
                        if (first)
                        {
                            path.MoveToPoint(segment.at("start").at(0), segment.at("start").at(1));
                        }
                        path.AddLineToPoint(segment.at("end").at(0), segment.at("end").at(1));
                    }
                    first = false;
                }
                path.CloseSubpath();
            }
        }
        else
        {
            for (const auto& ring : primitive.at("rings"))
            {
                path.MoveToPoint(ring.at(0).at(0), ring.at(0).at(1));
                for (std::size_t index = 1; index < ring.size(); ++index)
                {
                    path.AddLineToPoint(ring.at(index).at(0), ring.at(index).at(1));
                }
                if (primitive.value("closed", true))
                {
                    path.CloseSubpath();
                }
            }
        }
    }
    const auto fill = primitive.value("fill", Json(nullptr));
    if (!fill.is_null())
    {
        graphics.SetBrush(wxBrush(Colour(fill, *wxWHITE)));
        graphics.FillPath(path, wxODDEVEN_RULE);
    }
    const auto stroke = primitive.value("stroke", Json(nullptr));
    if (!stroke.is_null() && primitive.value("stroke_width_mm", 0.0) > 0)
    {
        wxGraphicsPenInfo pen(Colour(stroke, *wxBLACK));
        pen.Width(primitive.at("stroke_width_mm").get<double>()).Cap(wxCAP_ROUND).Join(wxJOIN_ROUND);
        graphics.SetPen(graphics.CreatePen(pen));
        graphics.StrokePath(path);
    }
}
}

DrawingSheetCanvas::DrawingSheetCanvas(wxWindow* parent) : wxPanel(parent)
{
    SetBackgroundStyle(wxBG_STYLE_PAINT);
    SetMinSize(FromDIP(wxSize(280, 300)));
    SetName("output.paper-preview");
    Bind(wxEVT_PAINT, &DrawingSheetCanvas::Paint, this);
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Refresh(false);
             event.Skip();
         });
}

void DrawingSheetCanvas::SetPages(const Json& pages)
{
    DrawingSheet::ValidatePages(pages);
    m_pages = pages;
    m_page = std::min(m_page, pages.size() - 1);
    Refresh(false);
}

void DrawingSheetCanvas::SetPage(std::size_t page)
{
    if (page < m_pages.size())
    {
        m_page = page;
        Refresh(false);
    }
}

void DrawingSheetCanvas::Clear(const std::string& message)
{
    m_pages = Json::array();
    m_page = 0;
    m_message = message;
    Refresh(false);
}

std::size_t DrawingSheetCanvas::PageCount() const
{
    return m_pages.size();
}

const Json& DrawingSheetCanvas::Pages() const
{
    return m_pages;
}

void DrawingSheetCanvas::Paint(wxPaintEvent&)
{
    wxAutoBufferedPaintDC dc(this);
    const auto palette = StudioTheme::Colours();
    dc.SetBackground(wxBrush(palette.workspace));
    dc.Clear();
    if (m_pages.empty())
    {
        dc.SetTextForeground(palette.secondary);
        dc.DrawLabel(Display(m_message), GetClientRect().Deflate(FromDIP(16)), wxALIGN_CENTER);
        return;
    }
    const auto& page = m_pages.at(m_page);
    const auto place =
        DrawingSheet::Fit(page.at("width_mm"), page.at("height_mm"), GetClientSize().x, GetClientSize().y, FromDIP(16));
    if (place.scale <= 0)
    {
        return;
    }
    std::unique_ptr<wxGraphicsContext> graphics(wxGraphicsContext::Create(dc));
    if (!graphics)
    {
        dc.DrawLabel(Display("도면 표시 환경을 사용할 수 없습니다. 출력 원본은 변경하지 않았습니다."), GetClientRect());
        return;
    }
    graphics->SetBrush(*wxWHITE_BRUSH);
    graphics->SetPen(wxPen(palette.border));
    graphics->DrawRectangle(place.x, place.y, place.width, place.height);
    graphics->Clip(place.x, place.y, place.width, place.height);
    const auto box = page.value("view_box_mm", Json::array({0, 0, page.at("width_mm"), page.at("height_mm")}));
    const double originX = box.at(0), originY = box.at(1);
    for (const auto& primitive : page.at("primitives"))
    {
        graphics->PushState();
        if (primitive.contains("clip_rect_mm"))
        {
            const auto& clip = primitive.at("clip_rect_mm");
            graphics->Clip(place.x + (clip.at(0).get<double>() - originX) * place.scale,
                           place.y + place.height -
                               (clip.at(1).get<double>() + clip.at(3).get<double>() - originY) * place.scale,
                           clip.at(2).get<double>() * place.scale, clip.at(3).get<double>() * place.scale);
        }
        if (primitive.at("kind") == "text")
        {
            const auto position = primitive.at("position");
            const double x = place.x + (position.at(0).get<double>() - originX) * place.scale;
            const double y = place.y + place.height - (position.at(1).get<double>() - originY) * place.scale;
            auto font = GetFont();
            font.SetPixelSize(wxSize(0, static_cast<int>(std::lround(std::clamp(
                                            primitive.at("height_mm").get<double>() * place.scale, 1.0, 4096.0)))));
            graphics->SetFont(font,
                              Colour(primitive.value("fill", primitive.value("stroke", Json(nullptr))), *wxBLACK));
            const auto text = Display(primitive.at("text").get<std::string>());
            double width = 0, height = 0, descent = 0;
            graphics->GetTextExtent(text, &width, &height, &descent);
            const auto align = primitive.value("align", "left");
            const double dx = align == "right" ? -width : (align == "center" ? -width / 2 : 0);
            graphics->Translate(x, y);
            graphics->Rotate(-primitive.value("rotation_deg", 0.0) * Pi / 180.0);
            graphics->DrawText(text, dx, -(height - descent));
        }
        else
        {
            graphics->Translate(place.x, place.y + place.height);
            graphics->Scale(place.scale, -place.scale);
            graphics->Translate(-originX, -originY);
            Shape(*graphics, primitive);
        }
        graphics->PopState();
    }
}
