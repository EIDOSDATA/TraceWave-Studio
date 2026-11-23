/** @file @brief 실제 보존 개정과 연구 후보를 이름으로 선택하는 공통 탐색 View다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <functional>
#include <string>

class wxChoice;
class wxListCtrl;
class wxStaticText;
class wxButton;

class ResultSourceBrowser final : public wxScrolledWindow
{
public:
    explicit ResultSourceBrowser(wxWindow* parent);
    std::string Kind() const;
    Json Anchor() const;
    std::string StudyId() const;
    Json SelectedSource() const;
    void SetAnchors(const Json& response);
    void SetStudies(const Json& response);
    void SetCatalog(const Json& response, const Json& selected = nullptr);
    void SetStatus(const std::string& message);
    void SetAvailable(bool available);
    void ClearCatalog(const std::string& message);
    void Reset();
    /** @brief 직접 연 보존 해석 원본의 종류를 바꾸되 다른 결과를 자동 선택하지 않는다. */
    void SetSolverContext();
    /** @brief 최근 작업 직후 현재 개정의 통합 목록으로 이동한다. */
    void SetCurrentContext();
    std::function<void()> onContextChanged;
    std::function<void()> onRefresh;
    std::function<void(int)> onPage;
    std::function<void(int)> onAnchorPage;
    std::function<void(const Json&)> onSelect;

private:
    friend class StudioSmokeDriver;
    void UpdateLayout();
    /** @brief 현재 탐색 창 너비로 안내문을 접고 전체 줄 높이를 반영한다. */
    void UpdateStatusLayout();
    wxChoice* m_kind = nullptr;
    wxChoice* m_anchor = nullptr;
    wxChoice* m_study = nullptr;
    wxListCtrl* m_items = nullptr;
    wxStaticText* m_status = nullptr;
    wxStaticText* m_anchorLabel = nullptr;
    wxStaticText* m_studyLabel = nullptr;
    wxString m_statusText;
    wxStaticText* m_page = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxButton* m_anchorPrevious = nullptr;
    wxButton* m_anchorNext = nullptr;
    wxButton* m_refresh = nullptr;
    Json m_anchors = Json::array();
    Json m_studies = Json::array();
    Json m_catalog = Json::object();
    int m_anchorOffset = 0;
    int m_anchorNextOffset = -1;
    bool m_loading = false;
    bool m_available = false;
};
