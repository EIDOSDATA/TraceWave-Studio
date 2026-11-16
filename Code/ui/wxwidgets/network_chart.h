/** @file @brief 서비스가 제공한 복소 결과의 표시값을 실제 표본 곡선으로 그린다. */
#pragma once

#include "studio_types.h"
#include <wx/panel.h>
#include <string>
#include <vector>

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
    void Clear();

private:
    struct Series
    {
        Json page;
        wxString label;
    };
    void ChooseDefaultMetric(const Json& page);
    void Paint(wxPaintEvent& event);
    std::vector<Series> m_series;
    std::string m_metric = "magnitude_db";
    wxString m_axisLabel;
    bool m_explicitMetric = false;
    std::string m_frequencyUnit = "auto";
    int m_marker = -1;
};
