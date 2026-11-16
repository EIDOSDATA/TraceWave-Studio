/** @file @brief 시안 38의 큰 Smith 표시와 실제 M1 표본 수치표를 구성한다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <functional>

class SmithChart;
class wxChoice;
class wxListCtrl;
class wxStaticText;
class wxButton;

class SmithView final : public wxScrolledWindow
{
public:
    explicit SmithView(wxWindow* parent);
    void SetDescription(const Json& description);
    void SetPage(const Json& response);
    void SetBusy(bool busy);
    void Clear(const std::string& reason);
    int Port() const;
    std::string Chart() const;
    std::function<void(int, const std::string&, int)> onRequest;
    std::function<void()> onSelectSource;

private:
    friend class StudioSmokeDriver;
    void Request(int offset);
    void SelectMarker(int index);
    void UpdateActions();
    SmithChart* m_chart = nullptr;
    wxChoice* m_port = nullptr;
    wxChoice* m_chartKind = nullptr;
    wxStaticText* m_heading = nullptr;
    wxStaticText* m_notice = nullptr;
    wxStaticText* m_status = nullptr;
    wxListCtrl* m_markerValues = nullptr;
    wxButton* m_source = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxButton* m_markerPrevious = nullptr;
    wxButton* m_markerNext = nullptr;
    Json m_description = nullptr;
    Json m_response = nullptr;
    int m_markerIndex = -1;
    bool m_busy = false;
};
