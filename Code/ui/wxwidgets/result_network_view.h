/** @file @brief 고정한 결과 원본의 복소 곡선과 실제 표본을 표시한다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <functional>
class NetworkChart;
class wxChoice;
class wxListCtrl;
class wxButton;
class wxStaticText;
class ResultNetworkView final : public wxScrolledWindow
{
public:
    explicit ResultNetworkView(wxWindow* parent);
    void SetDescription(const Json& description);
    void SetPage(const Json& response);
    void SetBusy(bool busy);
    void Clear(const std::string& message);
    std::function<void(int, int, int)> onRequest;
    std::function<void()> onSelectSource;
    std::function<void()> onOpenTools;
    std::function<void()> onExport;

private:
    friend class StudioSmokeDriver;
    void Request(int offset);
    void Present();
    void Marker(int index);
    NetworkChart* m_chart = nullptr;
    wxChoice* m_row = nullptr;
    wxChoice* m_column = nullptr;
    wxChoice* m_metric = nullptr;
    wxChoice* m_frequencyUnit = nullptr;
    wxListCtrl* m_samples = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxStaticText* m_heading = nullptr;
    wxStaticText* m_notice = nullptr;
    wxStaticText* m_marker = nullptr;
    Json m_description = nullptr;
    Json m_response = nullptr;
    bool m_busy = false;
    bool m_loading = false;
    int m_markerIndex = -1;
};
