/** @file @brief 목표와 복소 자료의 명시 대응 및 불변 평가 기록을 조회한다. */
#pragma once
#include "project_setup_dialog.h"

class StudioNotebook;
class wxButton;
class wxChoice;
class wxListCtrl;
class wxTextCtrl;

/** @brief 표본 통과와 연속 대역/실물 검증을 구분하는 목표 평가 화면이다. */
class NetworkAssessmentDialog final : public ProjectSetupDialog
{
public:
    NetworkAssessmentDialog(wxWindow* parent, const Json& context, const Json& selection, DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    void BuildInterface();
    void Changed();
    void LoadDataset();
    void RenderSelection();
    void Preview();
    void Apply();
    void LoadHistory();
    void RenderAssessment(const Json& assessment);
    void RenderPoints(const Json& points, int offset, int total);
    void LoadPoints(int offset);
    void SelectCriterion(int index);
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;

    Json m_context;
    Json m_selection;
    Json m_review = nullptr;
    Json m_reviewInput = nullptr;
    Json m_assessment = nullptr;
    Json m_nextOffset = nullptr;
    std::string m_recordId;
    bool m_loading = false;
    bool m_dirty = false;
    int m_criterion = -1;
    int m_offset = 0;
    StudioNotebook* m_tabs = nullptr;
    wxChoice* m_datasets = nullptr;
    wxChoice* m_targets = nullptr;
    wxChoice* m_ports = nullptr;
    wxChoice* m_history = nullptr;
    wxTextCtrl* m_plane = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_conditions = nullptr;
    wxListCtrl* m_criteria = nullptr;
    wxListCtrl* m_points = nullptr;
    wxTextCtrl* m_summary = nullptr;
    wxStaticText* m_pageLabel = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
};
