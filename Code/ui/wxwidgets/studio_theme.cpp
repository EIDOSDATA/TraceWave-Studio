/** @file @brief 작업 공간 스타일을 native 위젯의 입력 동작과 독립적으로 적용한다. */
#include "studio_theme.h"

#include <wx/aui/aui.h>
#include <wx/settings.h>
#include <wx/stattext.h>
#include <wx/button.h>
#include <wx/dcmemory.h>
#include <wx/graphics.h>
#include <wx/listctrl.h>
#include <wx/imaglist.h>
#include <algorithm>

#ifdef __WXMSW__
#include <wx/msw/wrapwin.h>
#endif

namespace StudioTheme
{
namespace
{
/** @brief 접근성 색을 강제 라이트 팔레트로 덮지 않도록 검사한다. */
bool UsesHighContrast()
{
#ifdef __WXMSW__
    HIGHCONTRASTW settings{};
    settings.cbSize = sizeof(settings);
    if (SystemParametersInfoW(SPI_GETHIGHCONTRAST, sizeof(settings), &settings, 0))
    {
        return (settings.dwFlags & HCF_HIGHCONTRASTON) != 0;
    }
#endif
    return false;
}

/** @brief native 편집기/캔버스를 순회하지 않고 지정한 표면만 갱신한다. */
void ApplySurface(wxWindow& window, Surface surface)
{
    const auto colours = Colours();
    window.SetBackgroundColour(surface == Surface::Workspace ? colours.workspace : colours.panel);
    window.SetForegroundColour(colours.text);
    window.Refresh(false);
}
}

Palette Colours()
{
    if (UsesHighContrast())
    {
        return {
            wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOW),      wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOW),
            wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOWFRAME), wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOWTEXT),
            wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOWTEXT),  wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOW),
            wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHT),   wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHT)};
    }
    return {wxColour(239, 242, 246), wxColour(248, 250, 252), wxColour(208, 216, 227),
            wxColour(25, 42, 61),    wxColour(82, 101, 123),  *wxWHITE,
            wxColour(8, 102, 216),   wxColour(231, 240, 254)};
}

void ApplyTypography(wxWindow& window)
{
    wxFont font = wxSystemSettings::GetFont(wxSYS_DEFAULT_GUI_FONT);
    font.SetFractionalPointSize(std::max(11.0, font.GetFractionalPointSize()));
    window.SetFont(font);
}

void Title(wxStaticText& label)
{
    auto font = label.GetFont().Bold();
    font.SetFractionalPointSize(std::max(14.0, font.GetFractionalPointSize() + 2.0));
    label.SetFont(font);
}

void Button(wxButton& button, bool primary)
{
    const auto colours = Colours();
    button.SetBackgroundColour(primary ? colours.accent : colours.content);
    button.SetForegroundColour(primary ? wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHTTEXT) : colours.text);
    const auto best = button.GetBestSize();
    button.SetMinSize(wxSize(best.x + button.FromDIP(12), std::max(best.y, button.FromDIP(ToolHeight))));
    button.Bind(wxEVT_SYS_COLOUR_CHANGED,
                [&button, primary](wxSysColourChangedEvent& event)
                {
                    const auto colours = Colours();
                    button.SetBackgroundColour(primary ? colours.accent : colours.content);
                    button.SetForegroundColour(primary ? wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHTTEXT)
                                                       : colours.text);
                    event.Skip();
                });
    button.Bind(wxEVT_UPDATE_UI,
                [&button, primary](wxUpdateUIEvent& event)
                {
                    const auto colours = Colours();
                    const bool active = primary && button.IsEnabled();
                    const wxColour background =
                        active ? colours.accent : (button.IsEnabled() ? colours.content : colours.workspace);
                    if (button.GetBackgroundColour() != background)
                    {
                        button.SetBackgroundColour(background);
                        button.SetForegroundColour(active ? wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHTTEXT)
                                                          : colours.text);
                        button.Refresh();
                    }
                    event.Skip();
                });
}

void Table(wxListCtrl& list)
{
    const wxColour transparent(255, 0, 255);
    wxBitmap spacer(list.FromDIP(1), std::max(list.FromDIP(34), list.GetCharHeight() + list.FromDIP(12)));
    wxMemoryDC dc(spacer);
    dc.SetBackground(wxBrush(transparent));
    dc.Clear();
    dc.SelectObject(wxNullBitmap);
    spacer.SetMask(new wxMask(spacer, transparent));
    auto* images = new wxImageList(spacer.GetWidth(), spacer.GetHeight(), true);
    images->Add(spacer);
    list.AssignImageList(images, wxIMAGE_LIST_SMALL);
    list.SetBackgroundColour(Colours().content);
    list.SetTextColour(Colours().text);
}

wxBitmap Icon(wxWindow& window, const std::string& kind, int size, int rowHeight)
{
    const auto colours = Colours();
    const wxColour transparent(255, 0, 255);
    wxBitmap bitmap(window.FromDIP(size), window.FromDIP(rowHeight));
    wxMemoryDC dc(bitmap);
    dc.SetBackground(wxBrush(transparent));
    dc.Clear();
    dc.SetUserScale(bitmap.GetWidth() / 24.0, bitmap.GetWidth() / 24.0);
    dc.SetDeviceOrigin(0, (bitmap.GetHeight() - bitmap.GetWidth()) / 2);
    dc.SetPen(wxPen(kind == "geometry" || kind == "arc" || kind == "project" ? colours.accent : colours.secondary, 2));
    dc.SetBrush(*wxTRANSPARENT_BRUSH);
    if (kind == "project" || kind == "templates")
    {
        const wxPoint points[] = {{2, 7}, {2, 4}, {10, 4}, {13, 7}, {22, 7}, {20, 20}, {2, 20}};
        dc.DrawPolygon(7, points);
    }
    else if (kind == "board" || kind == "layer" || kind == "material")
    {
        for (int y : {6, 11, 16})
        {
            const wxPoint points[] = {{3, y}, {12, y - 4}, {21, y}, {12, y + 4}};
            dc.DrawPolygon(4, points);
        }
    }
    else if (kind == "targets" || kind == "rules")
    {
        dc.DrawCircle(12, 12, 8);
        dc.DrawCircle(12, 12, 4);
        dc.DrawLine(12, 1, 12, 23);
        dc.DrawLine(1, 12, 23, 12);
    }
    else if (kind == "geometry" || kind == "arc")
    {
        dc.DrawEllipticArc(3, 4, 18, 22, 0, 180);
    }
    else if (kind == "port" || kind == "net")
    {
        dc.DrawCircle(12, 6, 4);
        dc.DrawLine(12, 10, 12, 21);
        dc.DrawLine(7, 21, 17, 21);
    }
    else if (kind == "environment")
    {
        const wxPoint points[] = {{3, 7}, {12, 2}, {21, 7}, {21, 18}, {12, 23}, {3, 18}};
        dc.DrawPolygon(6, points);
        dc.DrawLine(3, 7, 12, 12);
        dc.DrawLine(12, 12, 21, 7);
        dc.DrawLine(12, 12, 12, 23);
    }
    else if (kind == "line")
    {
        dc.DrawLine(3, 21, 21, 3);
    }
    else if (kind == "region")
    {
        dc.DrawRectangle(3, 4, 18, 16);
        for (int x : {6, 11, 16})
        {
            dc.DrawLine(x, 19, std::min(21, x + 7), 5);
        }
    }
    else if (kind == "pad" || kind == "via")
    {
        dc.DrawCircle(12, 12, 8);
        if (kind == "via")
        {
            dc.DrawCircle(12, 12, 3);
        }
    }
    else
    {
        dc.DrawRectangle(5, 2, 14, 20);
        for (int y : {7, 12, 17})
        {
            dc.DrawLine(8, y, 16, y);
        }
    }
    dc.SelectObject(wxNullBitmap);
    bitmap.SetMask(new wxMask(bitmap, transparent));
    return bitmap;
}

void BindSurface(wxWindow& window, Surface surface)
{
    ApplySurface(window, surface);
    window.Bind(wxEVT_SYS_COLOUR_CHANGED,
                [&window, surface](wxSysColourChangedEvent& event)
                {
                    ApplySurface(window, surface);
                    event.Skip();
                });
}

void Heading(wxStaticText& label)
{
    label.SetFont(label.GetFont().Bold());
}

void BindSecondary(wxStaticText& label)
{
    label.SetForegroundColour(Colours().secondary);
    label.Bind(wxEVT_SYS_COLOUR_CHANGED,
               [&label](wxSysColourChangedEvent& event)
               {
                   label.SetForegroundColour(Colours().secondary);
                   event.Skip();
               });
}

void ConfigureDocking(wxAuiManager& manager, wxWindow& window)
{
    const auto colours = Colours();
    auto* art = manager.GetArtProvider();
    art->SetColour(wxAUI_DOCKART_BACKGROUND_COLOUR, colours.workspace);
    art->SetColour(wxAUI_DOCKART_SASH_COLOUR, colours.workspace);
    art->SetColour(wxAUI_DOCKART_BORDER_COLOUR, colours.border);
    art->SetColour(wxAUI_DOCKART_GRIPPER_COLOUR, colours.border);
    art->SetColour(wxAUI_DOCKART_ACTIVE_CAPTION_COLOUR, colours.panel);
    art->SetColour(wxAUI_DOCKART_ACTIVE_CAPTION_GRADIENT_COLOUR, colours.panel);
    art->SetColour(wxAUI_DOCKART_INACTIVE_CAPTION_COLOUR, colours.workspace);
    art->SetColour(wxAUI_DOCKART_INACTIVE_CAPTION_GRADIENT_COLOUR, colours.workspace);
    art->SetColour(wxAUI_DOCKART_ACTIVE_CAPTION_TEXT_COLOUR, colours.text);
    art->SetColour(wxAUI_DOCKART_INACTIVE_CAPTION_TEXT_COLOUR, colours.secondary);
    art->SetFont(wxAUI_DOCKART_CAPTION_FONT, window.GetFont().Bold());
    art->SetMetric(wxAUI_DOCKART_GRADIENT_TYPE, wxAUI_GRADIENT_NONE);
    art->SetMetric(wxAUI_DOCKART_PANE_BORDER_SIZE, window.FromDIP(1));
    art->SetMetric(wxAUI_DOCKART_SASH_SIZE, window.FromDIP(Space));
    art->SetMetric(wxAUI_DOCKART_CAPTION_SIZE,
                   std::max(window.FromDIP(34), window.GetCharHeight() + window.FromDIP(InputGap)));
}
}
