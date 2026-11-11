/** @file @brief 작업 공간 스타일을 native 위젯의 입력 동작과 독립적으로 적용한다. */
#include "studio_theme.h"

#include <wx/aui/aui.h>
#include <wx/settings.h>
#include <wx/stattext.h>
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
        return {wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOW),
                wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOW),
                wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOWFRAME),
                wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOWTEXT),
                wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOWTEXT)};
    }
    return {wxColour(243, 245, 248), wxColour(255, 255, 255), wxColour(216, 222, 232),
            wxColour(32, 39, 51), wxColour(83, 97, 116)};
}

void BindSurface(wxWindow& window, Surface surface)
{
    ApplySurface(window, surface);
    window.Bind(wxEVT_SYS_COLOUR_CHANGED, [&window, surface](wxSysColourChangedEvent& event)
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
    label.Bind(wxEVT_SYS_COLOUR_CHANGED, [&label](wxSysColourChangedEvent& event)
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
                   std::max(window.FromDIP(28), window.GetCharHeight() + window.FromDIP(InputGap)));
}
}
