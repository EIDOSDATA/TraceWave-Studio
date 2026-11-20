/** @file @brief 과거 정렬/비교의 봉인 보고서를 재계산하지 않고 조회한다. */
#pragma once
#include "project_setup_dialog.h"
class StudioNotebook;
class NetworkChart;
class wxTextCtrl;
class wxListCtrl;
class wxButton;
class wxChoice;

class MeasurementHistoryDialog final : public ProjectSetupDialog
{
public:
    MeasurementHistoryDialog(wxWindow* parent, const Json& context, const Json& entry, DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    /** @brief 보존 이력 화면에는 적용할 편집 초안이 없다. */
    bool HasDraft() const override
    {
        return false;
    }
    void UpdateActions() override;
    void LoadSummary();
    void LoadSection(int offset);
    void RenderSection(const Json& response);
    void LoadAlignment(const Json& summary);
    Json m_entry, m_summaryData = nullptr;
    Json m_sourcePin = nullptr;
    std::string m_collection;
    int m_offset = 0, m_next = -1;
    StudioNotebook* m_tabs = nullptr;
    wxTextCtrl* m_summary = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxChoice* m_section = nullptr;
    wxListCtrl* m_items = nullptr;
    NetworkChart* m_chart = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_nextButton = nullptr;
};
