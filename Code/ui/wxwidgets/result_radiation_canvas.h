/** @file @brief 서비스가 제공한 방사 표시 좌표를 그리는 OpenGL/2D View다. */
#pragma once
#include "studio_types.h"
#include <wx/glcanvas.h>
#include <wx/panel.h>
#include <memory>
class RadiationResultCanvas final : public wxGLCanvas
{
public:
    explicit RadiationResultCanvas(wxWindow* parent);
    ~RadiationResultCanvas() override;
    void SetPattern(const Json& data);
    void Clear();
    void Fit();
    bool Ready() const;

private:
    void Paint(wxPaintEvent& event);
    std::unique_ptr<wxGLContext> m_context;
    Json m_data = nullptr;
    double m_yaw = -35.0, m_pitch = 55.0, m_zoom = 1.0;
    wxPoint m_last;
    bool m_dragging = false;
};
class RadiationResultSlice final : public wxPanel
{
public:
    explicit RadiationResultSlice(wxWindow* parent);
    void SetPattern(const Json& data, int phiIndex);
    void Clear();

private:
    void Paint(wxPaintEvent& event);
    Json m_data = nullptr;
    int m_phiIndex = 0;
};
