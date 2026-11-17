/** @file @brief 서비스의 실제 종이 배치 DTO를 표시하는 읽기 전용 native 캔버스이다. */
#pragma once
#include "studio_types.h"
#include <wx/panel.h>

class DrawingSheetCanvas final : public wxPanel
{
public:
    explicit DrawingSheetCanvas(wxWindow* parent);
    void SetPages(const Json& pages);
    void SetPage(std::size_t page);
    void Clear(const std::string& message);
    std::size_t PageCount() const;
    const Json& Pages() const;

private:
    friend class StudioSmokeDriver;
    void Paint(wxPaintEvent& event);
    Json m_pages = Json::array();
    std::size_t m_page = 0;
    std::string m_message = "출력 내용을 검토하면 실제 용지 배치를 표시합니다.";
};
