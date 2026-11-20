/** @file @brief 서비스가 유도한 연관 치수와 선택 필터를 표시한다. */
#include "design_canvas.h"
#include "studio_support.h"
#include <cmath>

void DesignCanvas::SetSelectionFilter(const std::string& kind, bool activeLayerOnly)
{
    CancelGesture();
    m_selectionKind = kind;
    m_activeLayerOnly = activeLayerOnly;
    Refresh(false);
}

bool DesignCanvas::Selectable(const Shape& shape) const
{
    return Visible(shape) && (m_selectionKind.empty() || shape.kind == m_selectionKind) &&
        (!m_activeLayerOnly || shape.layer == m_drawingLayer || shape.spanLayers.count(m_drawingLayer) != 0);
}

void DesignCanvas::SetDimensions(const Json& dimensions)
{
    m_dimensions = dimensions.is_array() ? dimensions : Json::array();
    Refresh(false);
}

void DesignCanvas::DrawDimensions(wxDC& dc) const
{
    if (m_dimensions.empty() || m_selection.empty())
    {
        return;
    }
    const auto* shape = FindShape(m_selection);
    if (!shape || !Visible(*shape))
    {
        return;
    }
    const auto& dimension = m_dimensions.front();
    if (dimension.value("object_id", "") != m_selection)
    {
        return;
    }
    const auto anchors = dimension.value("anchors_mm", Json::array());
    if (anchors.size() < 2 || dimension.at("value").is_null())
    {
        return;
    }
    const wxPoint first = WorldToScreen({anchors.at(0).at(0).get<double>(), anchors.at(0).at(1).get<double>()});
    const wxPoint last = WorldToScreen({anchors.at(1).at(0).get<double>(), anchors.at(1).at(1).get<double>()});
    if (!GetClientRect().Contains(first) || !GetClientRect().Contains(last))
    {
        return;
    }
    /** @brief 물리 치수를 재계산하지 않고 화면 선분의 법선으로 표기만 배치한다. */
    const double dx = last.x - first.x;
    const double dy = last.y - first.y;
    const double length = std::hypot(dx, dy);
    if (length < 1.0)
    {
        return;
    }
    double nx = -dy / length;
    double ny = dx / length;
    if (ny > 0.0 || (std::abs(ny) < 1e-9 && nx > 0.0))
    {
        nx = -nx;
        ny = -ny;
    }
    const wxPoint offset(wxRound(nx * FromDIP(22)), wxRound(ny * FromDIP(22)));
    const wxPoint extension(wxRound(nx * FromDIP(27)), wxRound(ny * FromDIP(27)));
    dc.SetPen(wxPen(m_colours.Detail(wxColour(48, 70, 94)), FromDIP(1)));
    dc.DrawLine(first, first + extension);
    dc.DrawLine(last, last + extension);
    dc.DrawLine(first + offset, last + offset);
    for (const auto& point : {first + offset, last + offset})
    {
        dc.DrawLine(point - wxPoint(FromDIP(4), -FromDIP(4)), point + wxPoint(FromDIP(4), -FromDIP(4)));
    }
    const wxString value = Display(dimension.value("label", "치수") + " ") +
        wxString::Format("%.6g", dimension.at("value").get<double>()) + Display(" " + dimension.value("unit", ""));
    const auto size = dc.GetTextExtent(value);
    const double labelOffset = FromDIP(28) + (std::abs(nx) * size.x + std::abs(ny) * size.y) / 2.0;
    wxPoint text(wxRound((first.x + last.x - size.x) / 2.0 + nx * labelOffset),
                 wxRound((first.y + last.y - size.y) / 2.0 + ny * labelOffset));
    text.x = std::max(FromDIP(4), std::min(text.x, GetClientSize().x - size.x - FromDIP(4)));
    text.y = std::max(FromDIP(28), text.y);
    dc.SetBrush(wxBrush(m_colours.HighContrast() ? m_colours.background : *wxWHITE));
    dc.SetPen(*wxTRANSPARENT_PEN);
    dc.DrawRectangle(text.x - FromDIP(3), text.y, size.x + FromDIP(6), size.y);
    dc.SetTextForeground(m_colours.Detail(wxColour(28, 52, 80)));
    dc.DrawText(value, text);
}
