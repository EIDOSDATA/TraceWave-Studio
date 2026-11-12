/** @file @brief 외부 이미지 의존성 없이 native 버튼의 편집 아이콘을 그린다. */
#include "drawing_rail.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/dcmemory.h>

void StyleDrawingRail(const std::vector<wxButton*>& buttons)
{
    for (std::size_t index = 0; index < buttons.size(); ++index)
    {
        auto* button = buttons[index];
        const auto colours = StudioTheme::Colours();
        wxBitmap bitmap(button->FromDIP(24), button->FromDIP(24));
        wxMemoryDC dc(bitmap);
        dc.SetBackground(wxBrush(colours.panel));
        dc.Clear();
        dc.SetUserScale(bitmap.GetWidth() / 24.0, bitmap.GetHeight() / 24.0);
        dc.SetPen(wxPen(colours.text, 2));
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
        button->SetToolTip(button->GetLabel());
        button->SetBitmap(bitmap);
        button->SetBitmapPosition(wxTOP);
        button->SetMinSize(button->FromDIP(wxSize(62, 50)));
    }
}
