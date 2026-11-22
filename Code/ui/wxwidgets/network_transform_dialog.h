/** @file @brief 원본 복소 자료를 유지하는 명시 변환 후보와 별도 저장 화면이다. */
#pragma once

#include "project_setup_dialog.h"

class StudioNotebook;
class NetworkChart;
class wxChoice;
class wxTextCtrl;
class wxButton;
class wxListCtrl;

/** @brief 물리 계산 없이 서비스의 변환 조건, 실제 표본과 검토 상태를 표시한다. */
class NetworkTransformDialog final : public ProjectSetupDialog
{
public:
    NetworkTransformDialog(wxWindow* parent, const Json& context, const Json& selection, DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    void BuildInterface();
    void SelectDataset();
    void Changed();
    void ClearReview();
    void RenderSource();
    void RenderResult(const Json& result);
    void Preview();
    void Apply();
    Json Input() const;
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;

    Json m_context;
    Json m_selection;
    Json m_review = nullptr;
    Json m_reviewInput = nullptr;
    bool m_dirty = false;
    bool m_loading = false;
    StudioNotebook* m_tabs = nullptr;
    wxChoice* m_datasets = nullptr;
    wxChoice* m_mode = nullptr;
    wxChoice* m_kind = nullptr;
    wxTextCtrl* m_reference = nullptr;
    wxTextCtrl* m_lines = nullptr;
    wxSizer* m_lineFields = nullptr;
    wxSizer* m_fixtureFields = nullptr;
    wxChoice* m_leftFixture = nullptr;
    wxChoice* m_rightFixture = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxTextCtrl* m_resultConditions = nullptr;
    wxTextCtrl* m_diagnostics = nullptr;
    NetworkChart* m_originalGraph = nullptr;
    NetworkChart* m_resultGraph = nullptr;
    wxListCtrl* m_samples = nullptr;
    wxStaticText* m_pageLabel = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
};
