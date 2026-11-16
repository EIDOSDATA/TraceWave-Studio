/** @file @brief 방사 2D/3D/편파를 같은 기록과 명시 표시 조건에 연결한다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <functional>
class RadiationResultCanvas;
class RadiationResultSlice;
class StudioNotebook;
class wxChoice;
class wxSpinCtrl;
class wxListCtrl;
class wxStaticText;
class wxButton;
class RadiationResultView final : public wxScrolledWindow
{
public:
    explicit RadiationResultView(wxWindow* parent);
    void SetDescription(const Json& description);
    void SetPattern(const Json& data);
    void Clear(const std::string& reason);
    void SetBusy(bool busy, const std::string& message = "");
    void SetError(const std::string& message);
    Json Options() const;
    std::function<void(const Json&)> onRequest;
    std::function<void()> onSelectSource;
    std::function<void()> onInvalidate;

private:
    friend class StudioSmokeDriver;
    void Request();
    void PresentSamples();
    Json m_description = nullptr;
    Json m_data = nullptr;
    wxStaticText* m_heading = nullptr;
    wxStaticText* m_status = nullptr;
    wxStaticText* m_metrics = nullptr;
    wxStaticText* m_convention = nullptr;
    wxChoice* m_frequency = nullptr;
    wxChoice* m_observable = nullptr;
    wxChoice* m_scale = nullptr;
    wxChoice* m_basis = nullptr;
    wxChoice* m_phi = nullptr;
    wxSpinCtrl* m_floor = nullptr;
    StudioNotebook* m_tabs = nullptr;
    RadiationResultCanvas* m_canvas = nullptr;
    RadiationResultSlice* m_slice = nullptr;
    wxListCtrl* m_samples = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxPanel* m_colour = nullptr;
    int m_sampleOffset = 0;
    bool m_loading = false;
};
