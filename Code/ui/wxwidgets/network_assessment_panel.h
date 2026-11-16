/** @file @brief 저장된 목표 판정을 Studio의 탐색/표/조건 세 영역에 표시한다. */
#pragma once

#include "studio_types.h"
#include <wx/scrolwin.h>
#include <wx/weakref.h>
#include <functional>
#include <string>
#include <vector>

class StudioNotebook;
class wxListCtrl;
class wxStaticText;
class wxTextCtrl;
class wxButton;

/** @brief 계산과 서비스 요청 없이 불변 평가 응답 및 현재 선택 상태만 표시한다. */
class NetworkAssessmentPanel final : public wxScrolledWindow
{
public:
    NetworkAssessmentPanel(wxWindow* centerParent, wxWindow* navigationParent, wxWindow* conditionsParent);
    ~NetworkAssessmentPanel() override;
    wxWindow* NavigationView() const;
    wxWindow* ConditionsView() const;
    void SetLibrary(const Json& context, const std::string& preferredId = "");
    void SetAssessment(const Json& result);
    void SetDataset(const Json& result);
    /** @brief 프레임이 평가 ID/기준/요청 세대를 확인한 표본 응답만 전달한다. */
    void SetPoints(const Json& result);
    void Clear(const std::string& message);
    void ClearSelection(const std::string& message);
    void SetEnabledState(bool available, bool busy);
    void SetStatus(const std::string& message);
    const Json& Library() const;
    const Json& Selection() const;
    const std::string& AssessmentId() const;
    int CriterionIndex() const;
    void RequestSelected();
    std::function<void(const std::string&)> onSelect;
    std::function<void(int, int)> onPoints;
    std::function<void()> onEvaluate;
    std::function<void()> onRefresh;

private:
    friend class StudioSmokeDriver;
    void BuildNavigation(wxWindow* parent);
    void BuildConditions(wxWindow* parent);
    void ShowConditions();
    void SelectCriterion(int index, bool request);
    void ShowPoints(const Json& points, int offset, int total, bool preview);
    void RequestPoints(int offset);
    void UpdateActions();
    /** @brief 표 최소 높이를 유지하고 내용이 긴 경우 세로 스크롤 범위를 갱신한다. */
    void UpdateLayout();
    std::string RecordName(const std::string& collection, const Json& identity) const;

    wxWeakRef<wxPanel> m_navigation;
    wxWeakRef<wxPanel> m_conditions;
    StudioNotebook* m_conditionTabs = nullptr;
    wxListCtrl* m_records = nullptr;
    wxListCtrl* m_criteria = nullptr;
    wxListCtrl* m_points = nullptr;
    wxStaticText* m_contextLabel = nullptr;
    wxStaticText* m_notice = nullptr;
    wxStaticText* m_validation = nullptr;
    wxStaticText* m_pointHeading = nullptr;
    wxStaticText* m_pageLabel = nullptr;
    wxStaticText* m_status = nullptr;
    wxStaticText* m_conditionSummary = nullptr;
    wxStaticText* m_reason = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxButton* m_refresh = nullptr;
    wxButton* m_evaluate = nullptr;
    wxButton* m_original = nullptr;
    wxButton* m_allPoints = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    Json m_library = Json::object();
    Json m_selection = nullptr;
    Json m_dataset = nullptr;
    Json m_displayedPoints = Json::array();
    std::vector<std::string> m_ids;
    std::string m_identity;
    int m_criterion = -1;
    int m_offset = 0;
    int m_total = 0;
    int m_nextOffset = -1;
    bool m_pointsPreview = true;
    bool m_available = false;
    bool m_busy = false;
    bool m_rebuilding = false;
};
