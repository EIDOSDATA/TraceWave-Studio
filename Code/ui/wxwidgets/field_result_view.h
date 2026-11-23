/** @file @brief 기록 필드의 성분/단면/실제 표본 선택을 Studio 페이지에 표시한다. */
#pragma once

#include "studio_types.h"
#include <wx/panel.h>
#include <array>
#include <functional>
#include <string>

class FieldSliceCanvas;
class wxButton;
class wxChoice;
class wxScrolledWindow;
class wxSpinCtrl;
class wxStaticText;
class wxTextCtrl;

/** @brief source/pin과 서비스 수명은 외부 연결에 맡기는 필드 표시 View다. */
class FieldResultView final : public wxPanel
{
public:
    explicit FieldResultView(wxWindow* parent);
    void SetDescription(const Json& description);
    void SetFlux(const Json& response);
    void SetSlice(const Json& slice);
    void Clear(const std::string& message);
    void SetError(const std::string& message);
    void SetBusy(bool busy);
    std::function<void(const Json&)> onFlux;
    std::function<void(const Json&)> onSlice;
    std::function<void(const Json&)> onRefine;

private:
    friend class StudioSmokeDriver;
    friend class LargeResultDialog;
    void ResetFluxBounds();
    void RequestFlux();
    void RequestMeshFlux();
    void RebuildMonitor();
    void RebuildComponent();
    void RebuildPlane();
    void ClearSlice(const std::string& message);
    void RequestSlice();
    void ShowMarker(std::size_t index);
    void SetStatus(const std::string& message);
    void UpdatePosition();
    const Json* Monitor() const;
    const Json* Component() const;
    FieldSliceCanvas* m_canvas = nullptr;
    wxScrolledWindow* m_controls = nullptr;
    wxChoice* m_monitor = nullptr;
    wxChoice* m_frequency = nullptr;
    wxChoice* m_component = nullptr;
    wxChoice* m_normal = nullptr;
    wxSpinCtrl* m_planeIndex = nullptr;
    wxSpinCtrl* m_uStart = nullptr;
    wxSpinCtrl* m_uCount = nullptr;
    wxSpinCtrl* m_vStart = nullptr;
    wxSpinCtrl* m_vCount = nullptr;
    wxSpinCtrl* m_stride = nullptr;
    wxSpinCtrl* m_point = nullptr;
    wxStaticText* m_status = nullptr;
    wxStaticText* m_position = nullptr;
    wxStaticText* m_uLabel = nullptr;
    wxStaticText* m_vLabel = nullptr;
    wxStaticText* m_notice = nullptr;
    wxPanel* m_fluxPanel = nullptr;
    wxChoice* m_fluxFace = nullptr;
    std::array<std::array<wxTextCtrl*, 2>, 3> m_fluxBounds{};
    wxButton* m_flux = nullptr;
    wxTextCtrl* m_fluxReport = nullptr;
    wxTextCtrl* m_marker = nullptr;
    wxButton* m_load = nullptr;
    wxPanel* m_refineOptions = nullptr;
    wxButton* m_refine = nullptr;
    wxButton* m_study = nullptr;
    wxSpinCtrl* m_changePercent = nullptr;
    wxSpinCtrl* m_ruleLimit = nullptr;
    wxSpinCtrl* m_memoryLimit = nullptr;
    Json m_description = nullptr;
    Json m_slice = nullptr;
    Json m_request = nullptr;
    std::string m_statusText;
    std::string m_uAxis;
    std::string m_vAxis;
    bool m_busy = false;
    bool m_rebuilding = false;
    bool m_markerUpdating = false;
};
