/** @file @brief 네트워크 목록/곡선/표/조건을 공통 도킹 공간에 표시한다. */
#pragma once

#include "studio_types.h"
#include <wx/panel.h>
#include <wx/weakref.h>
#include <functional>
#include <map>
#include <string>
#include <vector>

class NetworkChart;
class StudioNotebook;
class wxButton;
class wxChoice;
class wxListCtrl;
class wxStaticText;
class wxTextCtrl;

enum class NetworkAction
{
    Import,
    Solver,
    Circuit,
    Assessment,
    Transform,
    Export,
    Diagnostics
};

/** @brief 영구 원본과 비동기 요청은 프레임/서비스에 맡기는 표시 전용 결과 View다. */
class NetworkPanel final : public wxPanel
{
public:
    NetworkPanel(wxWindow* centerParent, wxWindow* navigationParent, wxWindow* conditionsParent);
    ~NetworkPanel() override;
    wxWindow* NavigationView() const;
    wxWindow* ConditionsView() const;
    void SetLibrary(const Json& context, const std::string& preferredId = "");
    void SetResult(const Json& result);
    void Clear(const std::string& message);
    void ClearSelection(const std::string& message);
    void SetEnabledState(bool available, bool busy);
    void SetStatus(const std::string& message);
    const Json& Library() const;
    const Json& Selection() const;
    const std::string& DatasetId() const;
    void RequestSelected(int offset = 0);
    std::function<void(const std::string&, int, int, int)> onSelect;
    std::function<void(NetworkAction)> onAction;
    std::function<void()> onRefresh;

private:
    friend class StudioSmokeDriver;
    void BuildNavigation(wxWindow* parent);
    void BuildConditions(wxWindow* parent);
    void ShowConditions();
    void ShowSamples();
    void UpdateActions();
    void UpdateMetric();
    void UpdateFrequencyDisplay();
    std::string FrequencyUnit() const;
    void SelectMarker(long row);
    wxWeakRef<wxPanel> m_navigation;
    wxWeakRef<wxPanel> m_conditions;
    wxListCtrl* m_results = nullptr;
    wxListCtrl* m_samples = nullptr;
    wxStaticText* m_heading = nullptr;
    wxStaticText* m_status = nullptr;
    wxStaticText* m_pageLabel = nullptr;
    wxStaticText* m_marker = nullptr;
    wxStaticText* m_conditionHeading = nullptr;
    wxStaticText* m_conditionSummary = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxChoice* m_channel = nullptr;
    wxChoice* m_metric = nullptr;
    wxChoice* m_frequencyUnit = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxButton* m_refresh = nullptr;
    NetworkChart* m_chart = nullptr;
    std::map<NetworkAction, wxButton*> m_actions;
    std::vector<std::string> m_ids;
    std::vector<std::pair<int, int>> m_channels;
    Json m_library = Json::object();
    Json m_selection = nullptr;
    std::string m_dataset;
    bool m_available = false;
    bool m_busy = false;
    bool m_rebuilding = false;
    long m_markerRow = -1;
};
