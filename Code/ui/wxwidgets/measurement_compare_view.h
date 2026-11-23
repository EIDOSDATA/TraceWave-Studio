/** @file @brief 기존 결과 곡선 View 위에 측정 기록의 명시 선택과 도구 진입을 더한다. */
#pragma once
#include "studio_types.h"
#include <wx/panel.h>
#include <functional>

class ResultCompareView;
class wxChoice;
class wxButton;
class wxStaticText;

/** @brief 시료 기록을 자료 원본과 별도로 고정하며 그래프 계산은 기존 View에 맡긴다. */
class MeasurementCompareView final : public wxPanel
{
public:
    explicit MeasurementCompareView(wxWindow* parent);
    ResultCompareView* Comparison() const;
    void SetRecords(const Json& context, const Json& preferred);
    void SetAvailable(bool available);
    void SetSelectionAvailable(bool selected);
    void SetStatus(const std::string& message);
    void Clear();
    Json RecordRef() const;
    std::function<void()> onRefresh;
    std::function<void()> onRecover;
    std::function<void(const Json&)> onHistory;
    std::function<void(const Json&)> onAddRecord;
    std::function<void(const Json&)> onEditRecord;
    std::function<void()> onNewRecord;
    std::function<void()> onImport;
    std::function<void()> onAlign;
    std::function<void()> onSaveComparison;

private:
    friend class StudioSmokeDriver;
    void Actions();
    Json m_records = Json::array(), m_histories = Json::array();
    bool m_available = false, m_selectedSource = false;
    ResultCompareView* m_compare = nullptr;
    wxChoice* m_history = nullptr;
    wxButton* m_readHistory = nullptr;
    wxButton* m_recover = nullptr;
    wxChoice* m_record = nullptr;
    wxButton* m_refresh = nullptr;
    wxButton* m_add = nullptr;
    wxButton* m_edit = nullptr;
    wxButton* m_new = nullptr;
    wxButton* m_import = nullptr;
    wxButton* m_align = nullptr;
    wxButton* m_save = nullptr;
    wxStaticText* m_status = nullptr;
};
