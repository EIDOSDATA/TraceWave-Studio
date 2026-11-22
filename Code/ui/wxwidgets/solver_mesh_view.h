/** @file @brief 실제 해석 격자선과 입력 형상의 투영을 표시한다. */
#pragma once

#include <wx/panel.h>
#include <nlohmann/json.hpp>
#include <string>

class wxPaintEvent;

/** @brief 설계 장면과 독립된 읽기 전용 Cartesian 격자 보기다. */
class SolverMeshView final : public wxPanel
{
public:
    explicit SolverMeshView(wxWindow* parent);
    void DisplayPlan(const nlohmann::json* review);
    void SetView(int plane, bool full);
    void Highlight(const std::string& id);

private:
    void Paint(wxPaintEvent& event);
    const nlohmann::json* m_review = nullptr;
    int m_plane = 0;
    bool m_full = false;
    std::string m_highlight;
};
