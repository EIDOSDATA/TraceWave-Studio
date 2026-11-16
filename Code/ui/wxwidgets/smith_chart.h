/** @file @brief 실제 반사계수 표본을 표시 기하의 Smith 격자 위에 그린다. */
#pragma once
#include "studio_types.h"
#include <wx/panel.h>
#include <functional>
#include <vector>

/** @brief 반사/임피던스 계산 없이 서비스가 투영한 실제 점과 마커만 표시한다. */
class SmithChart final : public wxPanel
{
public:
    explicit SmithChart(wxWindow* parent);
    void SetPage(const Json& result);
    void SetMarker(int index);
    void Clear(const std::string& reason = "결과의 실제 반사 표본을 선택하세요.");
    std::function<void(int)> onMarker;

private:
    void Paint(wxPaintEvent& event);
    void Select(wxMouseEvent& event);
    Json m_result = nullptr;
    std::string m_reason;
    int m_marker = -1;
    std::vector<std::pair<wxPoint, int>> m_hits;
};
