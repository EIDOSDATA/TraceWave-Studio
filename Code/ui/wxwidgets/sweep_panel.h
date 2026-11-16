/** @file @brief 저장 연구의 목록/후보 진행/불변 조건을 공통 세 영역에 표시한다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <wx/weakref.h>
#include <functional>
#include <map>
#include <string>
#include <vector>

class wxListCtrl;
class wxStaticText;
class wxTextCtrl;
class wxButton;
class wxGauge;
class StudioSmokeDriver;

/** @brief 작업 실행과 후보 계산을 서비스에 맡기는 연구 View이다. */
class SweepPanel final : public wxScrolledWindow
{
public:
    SweepPanel(wxWindow* parent, wxWindow* navigation, wxWindow* conditions);
    ~SweepPanel() override;
    wxWindow* NavigationView() const;
    wxWindow* ConditionsView() const;
    void SetStudies(const Json& listing, const std::string& preferred = "");
    /** @brief 다른 연구의 상세를 읽을 때 이전 후보와 조건을 즉시 분리한다. */
    void BeginRead(const std::string& id);
    void SetStudy(const Json& study);
    void SetPage(const Json& page);
    void SetEnabledState(bool available, bool busy, bool uncertain = false);
    void SetStatus(const std::string& text);
    void Clear(const std::string& text);
    void ClearSelection(const std::string& text);
    const std::string& StudyId() const;
    const Json& Selection() const;
    int Offset() const;
    std::function<void()> onRefresh;
    std::function<void()> onCreate;
    std::function<void(const std::string&)> onSelect;
    std::function<void(const std::string&)> onCommand;
    std::function<void(int)> onPage;
    std::function<void(int)> onResult;

private:
    friend class StudioSmokeDriver;
    void UpdateActions();
    void ShowCandidate();
    void RefreshLayout();
    wxWeakRef<wxPanel> m_navigation;
    wxWeakRef<wxPanel> m_conditions;
    wxListCtrl* m_studies = nullptr;
    wxListCtrl* m_candidates = nullptr;
    wxStaticText* m_heading = nullptr;
    wxStaticText* m_notice = nullptr;
    wxStaticText* m_progressText = nullptr;
    wxStaticText* m_status = nullptr;
    wxStaticText* m_pageLabel = nullptr;
    wxTextCtrl* m_detail = nullptr;
    wxTextCtrl* m_conditionText = nullptr;
    wxGauge* m_progress = nullptr;
    wxButton* m_refresh = nullptr;
    wxButton* m_create = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxButton* m_result = nullptr;
    std::map<std::string, wxButton*> m_actions;
    std::vector<std::string> m_ids;
    std::string m_id;
    Json m_study = nullptr;
    Json m_rows = Json::array();
    int m_offset = 0;
    int m_nextOffset = -1;
    bool m_rebuilding = false;
    bool m_available = false;
    bool m_busy = false;
    bool m_uncertain = false;
};
