/** @file @brief 봉인한 방사 패턴의 주파수와 phi 절단면을 읽기 전용으로 표시한다. */
#pragma once

#include "radiation_pattern.h"
#include <wx/dialog.h>
#include <wx/timer.h>
#include <functional>

class wxChoice;
class wxStaticText;
class wxTextCtrl;
class wxPanel;

/** @brief 프로젝트 편집과 native 실행 없이 공개 조회 API만 사용한다. */
using RadiationGateway = std::function<void(const Json&, std::function<void(const Json&)>, std::function<void(const Json&)>)>;

class RadiationDialog final : public wxDialog
{
public:
    RadiationDialog(wxWindow* parent, const Json& result, bool stale, RadiationGateway gateway);

private:
    friend class StudioSmokeDriver;
    void Load(int frequency);
    void Fetch(int frequency, int offset, std::size_t generation);
    void ShowPattern();
    void Paint(wxPaintEvent& event);
    void Failed(const std::string& message);

    RadiationGateway m_gateway;
    Studio::RadiationPattern m_pattern;
    std::string m_artifact;
    std::size_t m_generation = 0;
    std::size_t m_renderedFrames = 0;
    wxChoice* m_frequency = nullptr;
    wxChoice* m_phi = nullptr;
    wxChoice* m_metric = nullptr;
    wxStaticText* m_status = nullptr;
    wxTextCtrl* m_details = nullptr;
    wxPanel* m_chart = nullptr;
    wxTimer m_timeout;
};
