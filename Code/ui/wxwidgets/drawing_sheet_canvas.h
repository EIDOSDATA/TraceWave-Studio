/** @file @brief 서비스의 실제 종이 배치 DTO를 표시하는 읽기 전용 native 캔버스이다. */
#pragma once
#include "studio_types.h"
#include <wx/geometry.h>
#include <wx/panel.h>
#include <functional>

namespace DrawingSheet
{
struct Placement;
}

class DrawingSheetCanvas final : public wxPanel
{
public:
    explicit DrawingSheetCanvas(wxWindow* parent);
    void SetPages(const Json& pages);
    void SetPage(std::size_t page);
    void Clear(const std::string& message);
    std::size_t PageCount() const;
    const Json& Pages() const;
    void SetMovable(bool movable);
    std::function<void(const Json&, const wxPoint2DDouble&)> onMoveDimension;

private:
    friend class StudioSmokeDriver;
    void Paint(wxPaintEvent& event);
    DrawingSheet::Placement FitSheet() const;
    wxPoint2DDouble PaperPoint(const wxPoint& pixel) const;
    void StartMove(wxMouseEvent& event);
    void TrackMove(wxMouseEvent& event);
    void FinishMove(wxMouseEvent& event);
    void CancelMove();
    bool m_movable = false;
    Json m_drag = nullptr;
    wxPoint2DDouble m_press, m_dragPoint;
    wxPoint m_pressPixel;
    Json m_pages = Json::array();
    std::size_t m_page = 0;
    std::string m_message = "출력 내용을 검토하면 실제 용지 배치를 표시합니다.";
};
