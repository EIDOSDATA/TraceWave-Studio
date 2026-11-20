/** @file @brief Windows 고대비 설정을 세션에서 현재 값으로 읽는다. */
#pragma once

#include <wx/settings.h>
#ifdef __WXMSW__
#include <wx/msw/wrapwin.h>
#endif

namespace StudioAppearance
{
/** @brief native 고대비 모드에서 사용자 색을 우선한다. */
inline bool HighContrast()
{
#ifdef __WXMSW__
    HIGHCONTRASTW value{};
    value.cbSize = sizeof(value);
    return SystemParametersInfoW(SPI_GETHIGHCONTRAST, sizeof(value), &value, 0) &&
           (value.dwFlags & HCF_HIGHCONTRASTON) != 0;
#else
    return false;
#endif
}

/** @brief 도면을 그릴 때마다 시스템 정보를 조회하지 않고 색 변경 시 교체한다. */
struct CanvasColours
{
    wxColour background{248, 251, 255};
    wxColour ink;
    wxColour focus;

    bool HighContrast() const
    {
        return ink.IsOk();
    }

    wxColour Detail(const wxColour& normal) const
    {
        return HighContrast() ? ink : normal;
    }

    wxColour Focus(const wxColour& normal) const
    {
        return HighContrast() ? focus : normal;
    }

    static CanvasColours Read()
    {
        if (StudioAppearance::HighContrast())
        {
            return {wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOW),
                    wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOWTEXT),
                    wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHT)};
        }
        return {};
    }
};
}
