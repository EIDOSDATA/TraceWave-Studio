/** @file @brief 실제 해석 격자선과 입력 형상의 투영을 표시한다. */
#pragma once

#include <wx/panel.h>
#include <nlohmann/json.hpp>
#include <array>
#include <functional>
#include <optional>
#include <string>
#include <vector>

class wxPaintEvent;

/** @brief 한 축에 배치된 두 실제 격자선이다. */
struct SolverMeshBand
{
    int axis;
    std::array<double, 2> bounds;
};

/** @brief 실제 도체 경계의 최근접 두 점을 지정한 평면과 셀에 투영한다. */
struct SolverMeshClearance
{
    int plane;
    std::array<std::array<double, 2>, 2> points;
    std::vector<std::array<std::size_t, 2>> cells;
};

/** @brief 설계 장면과 독립된 읽기 전용 Cartesian 격자 보기다. */
class SolverMeshView final : public wxPanel
{
public:
    explicit SolverMeshView(wxWindow* parent);
    void DisplayPlan(const nlohmann::json* review);
    void SetView(int plane, bool full);
    void Highlight(const std::string& id);
    void StartRegionPick(std::function<void(const nlohmann::json&)> selected);
    /** @brief 선택한 국부 격자 구간의 양쪽 실제 격자선을 강조한다. */
    void HighlightBand(int axis, const std::array<double, 2>& bounds, bool applied,
                       std::optional<SolverMeshBand> comparison = std::nullopt);

    /** @brief 선택한 간극의 평면에 위치를 확대 표시한다. */
    void HighlightClearance(SolverMeshClearance clearance);

private:
    void Paint(wxPaintEvent& event);
    void Pick(wxMouseEvent& event);
    std::function<void(const nlohmann::json&)> m_region;
    std::optional<std::array<double, 2>> m_corner;
    std::array<double, 2> m_leftBottom{};
    std::array<std::array<double, 2>, 2> m_visible{};
    double m_scale = 0;
    const nlohmann::json* m_review = nullptr;
    int m_plane = 0;
    bool m_full = false;
    std::string m_highlight;
    int m_bandAxis = -1;
    std::array<double, 2> m_bandBounds{};
    bool m_bandApplied = false;
    std::optional<SolverMeshBand> m_comparison;
    std::optional<SolverMeshClearance> m_clearance;
};
