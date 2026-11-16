/** @file @brief 기록된 필드의 실제 단면 위치와 서비스 색 값을 표시한다. */
#pragma once

#include "studio_types.h"
#include <wx/panel.h>
#include <functional>
#include <string>
#include <vector>

/** @brief 공간 보간이나 전자기 계산 없이 유한한 단면 표본을 그리는 View다. */
class FieldSliceCanvas final : public wxPanel
{
public:
    explicit FieldSliceCanvas(wxWindow* parent);
    bool SetSlice(const Json& slice);
    void Clear(const std::string& message);
    void SetMarker(std::size_t index);
    std::function<void(std::size_t)> onMarker;

private:
    friend class StudioSmokeDriver;
    void Paint(wxPaintEvent& event);
    void Select(wxMouseEvent& event);
    void Key(wxKeyEvent& event);
    double PixelU(std::size_t index) const;
    double PixelV(std::size_t index) const;
    Json m_slice = nullptr;
    std::vector<double> m_u;
    std::vector<double> m_v;
    wxRect m_plot;
    std::size_t m_marker = 0;
    std::string m_message;
};
