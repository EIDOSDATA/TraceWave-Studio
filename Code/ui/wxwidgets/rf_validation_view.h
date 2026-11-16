/** @file @brief 기존 Studio 안에서 불변 검증 보고서와 미확립 근거를 표시한다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <wx/collpane.h>
#include <functional>
#include <vector>
class wxButton;
class wxChoice;
class wxListCtrl;
class wxStaticText;
class wxTextCtrl;

class RfValidationView final : public wxScrolledWindow
{
public:
    RfValidationView(wxWindow* parent, wxWindow* navigation, wxWindow* conditions);
    wxWindow* NavigationView() const;
    wxWindow* ConditionsView() const;
    void SetCatalog(const Json& result, const std::string& selected);
    void SetReports(const Json& result, const Json& selectedReport);
    void SetRecord(const Json& result);
    void ClearRecord(const std::string& message);
    void Clear(const std::string& message);
    void SetAvailable(bool available);
    void SetPending(bool pending, const std::string& message = "");
    void SetStatus(const std::string& message);
    std::function<void()> onRefresh;
    std::function<void(int)> onCatalogPage;
    std::function<void(const std::string&, const Json&)> onSelect;
    std::function<void(const Json&)> onReport;
    std::function<void(int)> onReportPage;
    std::function<void(const Json&, const Json&)> onOpenResult;
    std::function<void()> onLegacyReport;

private:
    friend class StudioSmokeDriver;
    void UpdateActions();
    void ShowCase();
    void ShowMetric();
    void Relayout();
    static void Populate(wxListCtrl* table, const std::vector<std::vector<std::string>>& rows);
    wxTextCtrl* AddGroup(const std::string& label, bool collapsed = false);
    Json m_catalog = nullptr, m_reports = nullptr, m_record = nullptr;
    std::vector<Json> m_reportIds;
    bool m_rebuilding = false, m_available = false, m_pending = false;
    wxPanel* m_navigation = nullptr;
    wxScrolledWindow* m_conditions = nullptr;
    wxListCtrl* m_records = nullptr;
    wxButton* m_refresh = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxStaticText* m_catalogRange = nullptr;
    wxChoice* m_reportChoice = nullptr;
    wxButton* m_reportsPrevious = nullptr;
    wxButton* m_reportsNext = nullptr;
    wxStaticText* m_status = nullptr;
    wxStaticText* m_identity = nullptr;
    wxStaticText* m_reportRange = nullptr;
    wxListCtrl* m_cases = nullptr;
    wxListCtrl* m_states = nullptr;
    wxListCtrl* m_metrics = nullptr;
    wxButton* m_openResult = nullptr;
    wxTextCtrl* m_original = nullptr;
    wxTextCtrl* m_basis = nullptr;
    wxTextCtrl* m_limits = nullptr;
    wxTextCtrl* m_metricDetail = nullptr;
    wxTextCtrl* m_raw = nullptr;
    wxCollapsiblePane* m_advanced = nullptr;
};
