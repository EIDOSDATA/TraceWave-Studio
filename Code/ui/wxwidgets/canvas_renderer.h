#pragma once

#include "canvas_viewport.h"
#include "system_appearance.h"
#include <wx/wx.h>
#include <wx/graphics.h>
#include <memory>

/** @brief 한 paint의 graphics context를 재사용하고 위젯 상태와 독립적으로 장면을 그린다. */
class CanvasRenderer final
{
public:
    CanvasRenderer(wxWindow& window, wxDC& dc, CanvasViewport viewport, StudioAppearance::CanvasColours colours = {});
    ~CanvasRenderer();
    void DrawGrid(bool visible);
    void DrawBoard(const CanvasScene::Model& scene);
    /** @brief 직접 DC 표시와 섞이는 경계에서 누적 graphics 명령을 한 번 반영한다. */
    void Flush();
    bool DrawShape(const CanvasScene::Shape& shape, CanvasGeometry::Point offset, const wxColour& colour,
                   bool highlight);

private:
    wxPoint WorldToScreen(CanvasGeometry::Point point) const;
    int FromDIP(int value) const;
    wxWindow& m_window;
    wxDC& m_dc;
    CanvasViewport m_viewport;
    StudioAppearance::CanvasColours m_colours;
    /** @brief 선택 강조와 안티앨리어싱을 포함하며 한 paint의 DPI에서 고정한다. */
    int m_pathPadding;
    std::unique_ptr<wxGraphicsContext> m_graphics;
    bool m_unflushed = false;
    wxGraphicsPen m_linePen;
    wxColour m_lineColour;
    double m_lineWidth = -1.0;
};
