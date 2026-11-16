/** @file @brief 최대 여덟 원본을 독립 표본 페이지와 명시 포트 대응으로 비교한다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <functional>
#include <vector>
class NetworkChart;
class wxChoice;
class wxListCtrl;
class wxStaticText;
class wxButton;
class ResultCompareView final : public wxScrolledWindow
{
public:
    explicit ResultCompareView(wxWindow* parent);
    bool Add(const Json& description);
    void SetPage(std::size_t index, const Json& response);
    void SetComparison(std::size_t index, const Json& response);
    void SetMarker(std::size_t index, const Json& response);
    void SetAvailable(bool available);
    /** @brief 탭 복귀 때도 선택 행과 같은 원본/비교 조건을 다시 표시한다. */
    void InspectSelection();
    void Clear();
    const std::vector<Json>& Descriptions() const
    {
        return m_descriptions;
    }
    Json PortOrder(std::size_t index) const;
    int Row() const;
    int Column() const;
    int Selected() const;
    std::function<void()> onAddSelected;
    std::function<void()> onChanged;
    std::function<void(std::size_t, int)> onPage;
    std::function<void(std::size_t)> onCompare;
    std::function<void(std::size_t, int)> onComparePage;
    std::function<void(double)> onMarkers;
    std::function<void(const Json&)> onConditions;
    std::function<void(const Json&)> onInspect;

private:
    friend class StudioSmokeDriver;
    void RefreshRows();
    void Present();
    void Actions();
    void MapPorts();
    void Remove();
    void ChannelChanged();
    wxListCtrl* m_sources = nullptr;
    wxListCtrl* m_markers = nullptr;
    wxListCtrl* m_differences = nullptr;
    NetworkChart* m_chart = nullptr;
    wxChoice* m_row = nullptr;
    wxChoice* m_column = nullptr;
    wxChoice* m_metric = nullptr;
    wxStaticText* m_status = nullptr;
    wxButton* m_add = nullptr;
    wxButton* m_remove = nullptr;
    wxButton* m_map = nullptr;
    wxButton* m_compare = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxButton* m_differencePrevious = nullptr;
    wxButton* m_differenceNext = nullptr;
    std::vector<Json> m_descriptions;
    std::vector<Json> m_pages;
    std::vector<Json> m_orders;
    std::vector<Json> m_comparisons;
    std::vector<int> m_markerIndices;
    bool m_loading = false;
    bool m_available = false;
};
