/** @file @brief 실제 해석 격자선과 입력 형상의 투영을 표시한다. */
#pragma once

#include <wx/panel.h>
#include <nlohmann/json.hpp>
#include <array>
#include <optional>
#include <string>

class wxPaintEvent;

/** @brief 한 축에 배치된 두 실제 격자선이다. */
struct SolverMeshBand
{
    int axis;
    std::array<double, 2> bounds;
};

/** @brief 설계 장면과 독립된 읽기 전용 Cartesian 격자 보기다. */
class SolverMeshView final : public wxPanel
{
public:
    explicit SolverMeshView(wxWindow* parent);
    void DisplayPlan(const nlohmann::json* review);
    void SetView(int plane, bool full);
    void Highlight(const std::string& id);
    /** @brief 선택한 국부 격자 구간의 양쪽 실제 격자선을 강조한다. */
    void HighlightBand(int axis, const std::array<double, 2>& bounds, bool applied,
                       std::optional<SolverMeshBand> comparison = std::nullopt);

private:
    void Paint(wxPaintEvent& event);
    const nlohmann::json* m_review = nullptr;
    int m_plane = 0;
    bool m_full = false;
    std::string m_highlight;
    int m_bandAxis = -1;
    std::array<double, 2> m_bandBounds{};
    bool m_bandApplied = false;
    std::optional<SolverMeshBand> m_comparison;
};
