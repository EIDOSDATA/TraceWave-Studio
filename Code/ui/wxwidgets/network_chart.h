/** @file @brief 서비스가 제공한 복소 결과의 표시값을 실제 표본 곡선으로 그린다. */
#pragma once

#include "studio_types.h"
#include <wx/panel.h>
#include <string>
#include <vector>
#include <functional>

/** @brief 단위/물리 계산 없이 현재 표본 페이지의 값과 결측 구간을 표시한다. */
class NetworkChart final : public wxPanel
{
public:
    explicit NetworkChart(wxWindow* parent);
    void SetPage(const Json& page, const wxString& label = wxString());
    void SetComparison(const Json& originalPage, const Json& derivedPage, const wxString& originalLabel,
                       const wxString& derivedLabel);
    void SetMetric(const std::string& key, const wxString& axisLabel);
    void SetFrequencyUnit(const std::string& unit);
    void SetMarker(int sampleIndex);
    /** @brief 각 원본의 독립 페이지와 표본 마커를 공유 축에 표시한다. */
    void SetSeries(const std::vector<Json>& pages, const std::vector<wxString>& labels, bool externalLegend = true);
    void SetMarkers(const std::vector<int>& sampleIndices);
    /** @brief 곡선, 범례와 비교 목록이 같은 표시 색을 공유한다. */
    static wxColour SeriesColour(std::size_t index);
    /** @brief 선택 목록과 그래프의 선 및 점 모양을 같은 이름으로 표시한다. */
    static std::string SeriesStyleText(std::size_t index);
    std::function<void(std::size_t, int, double)> onMarker;
    void Clear();

private:
    struct Series
    {
        Json page;
        wxString label;
    };
    void ChooseDefaultMetric(const Json& page);
    void Paint(wxPaintEvent& event);
    void Select(wxMouseEvent& event);
    std::vector<Series> m_series;
    std::string m_metric = "magnitude_db";
    wxString m_axisLabel;
    bool m_explicitMetric = false;
    std::string m_frequencyUnit = "auto";
    int m_marker = -1;
    bool m_externalLegend = false;
    bool m_multiStyle = false;
    std::vector<int> m_markers;
    struct Hit
    {
        wxPoint position;
        std::size_t series = 0;
        int index = -1;
        double frequency = 0.0;
    };
    std::vector<Hit> m_hits;
};
