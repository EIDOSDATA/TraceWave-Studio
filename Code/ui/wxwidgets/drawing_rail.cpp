/** @file @brief 외부 이미지 의존성 없이 native 버튼의 DPI별 편집 아이콘을 그린다. */
#include "drawing_rail.h"
#include "studio_theme.h"
#include <wx/bmpbndl.h>
#include <wx/button.h>
#include <wx/dcmemory.h>
#include <wx/settings.h>
#include <algorithm>

namespace
{
/** @brief 같은 선 도형에서 실제 DPI에 맞는 비트맵과 투명 마스크를 만든다. */
wxBitmap ToolBitmap(std::size_t index, const wxColour& foreground, double scale)
{
    const wxColour mask(255, 0, 255);
    wxBitmap bitmap;
    bitmap.CreateWithDIPSize(18, 18, scale);
    wxMemoryDC dc(bitmap);
    dc.SetBackground(wxBrush(mask));
    dc.Clear();
    const wxSize size = bitmap.GetLogicalSize();
    dc.SetUserScale(size.GetWidth() / 24.0, size.GetHeight() / 24.0);
    dc.SetPen(wxPen(foreground, 2));
    dc.SetBrush(*wxTRANSPARENT_BRUSH);
    if (index == 0)
    {
        const wxPoint points[] = {{5, 3}, {5, 20}, {10, 15}, {15, 21}, {18, 19}, {13, 13}, {20, 12}};
        dc.DrawPolygon(7, points);
    }
    else if (index == 1)
    {
        dc.DrawLine(4, 20, 20, 4);
    }
    else if (index == 2)
    {
        dc.DrawEllipticArc(3, 4, 18, 18, 0, 180);
    }
    else if (index == 3)
    {
        dc.DrawLine(3, 12, 21, 12);
        dc.DrawLine(12, 3, 12, 21);
        dc.DrawCircle(12, 12, 4);
    }
    else if (index == 4)
    {
        dc.DrawRectangle(3, 3, 18, 18);
        dc.DrawLine(7, 12, 17, 12);
        dc.DrawLine(12, 7, 12, 17);
    }
    else
    {
        dc.DrawLine(5, 5, 19, 19);
        dc.DrawLine(5, 19, 19, 5);
    }
    dc.SelectObject(wxNullBitmap);
    bitmap.SetMask(new wxMask(bitmap, mask));
    return bitmap;
}

/** @brief 이전 비트맵을 변환하지 않고 고른 팔레트의 세 해상도를 한 묶음으로 건넨다. */
wxBitmapBundle ToolIcon(std::size_t index, const wxColour& foreground)
{
    wxVector<wxBitmap> bitmaps;
    for (const double scale : {1.0, 1.5, 2.0})
    {
        bitmaps.push_back(ToolBitmap(index, foreground, scale));
    }
    return wxBitmapBundle::FromBitmaps(bitmaps);
}
}

void StyleDrawingRail(const std::vector<wxButton*>& buttons)
{
    const auto colours = StudioTheme::Colours();
    for (std::size_t index = 0; index < buttons.size(); ++index)
    {
        auto& button = *buttons[index];
        button.SetToolTip(button.GetLabel());
        button.SetBitmap(ToolIcon(index, colours.text));
        button.SetBitmapPosition(wxLEFT);
        const auto best = button.GetBestSize();
        button.SetMinSize(wxSize(std::max(best.GetWidth(), button.FromDIP(64)),
                                 std::max(best.GetHeight(), button.FromDIP(StudioTheme::ToolHeight))));
        button.SetBackgroundColour(colours.content);
        button.SetForegroundColour(colours.text);
    }
}

void SelectDrawingRail(const std::vector<wxButton*>& buttons, std::size_t selected)
{
    const auto colours = StudioTheme::Colours();
    for (std::size_t index = 0; index < buttons.size(); ++index)
    {
        auto& button = *buttons[index];
        const bool active = index == selected && button.IsEnabled();
        const wxColour background =
            active ? colours.accent : (button.IsEnabled() ? colours.content : colours.workspace);
        const wxColour foreground = active ? wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHTTEXT) : colours.text;
        const auto weight = active ? wxFONTWEIGHT_BOLD : wxFONTWEIGHT_NORMAL;
        if (button.GetFont().GetWeight() != weight)
        {
            auto font = button.GetFont();
            font.SetWeight(weight);
            button.SetFont(font);
        }
        if (button.GetBackgroundColour() != background || button.GetForegroundColour() != foreground)
        {
            button.SetBitmap(ToolIcon(index, foreground));
            button.SetBackgroundColour(background);
            button.SetForegroundColour(foreground);
            button.Refresh();
        }
        const auto tip = button.GetLabel() + (active ? wxString::FromUTF8(" (현재 도구)") : wxString());
        if (button.GetToolTipText() != tip)
        {
            button.SetToolTip(tip);
        }
    }
}
