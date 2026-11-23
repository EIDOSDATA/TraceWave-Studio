/** @file @brief 제약, 연결과 제조 규칙의 편집 및 검사 화면이다. */
#pragma once
#include "project_setup_dialog.h"

class EditorPanel;
class DesignCanvas;
class wxButton;
class wxChoice;
class wxListCtrl;
class wxTextCtrl;

class DesignRulesDialog final : public ProjectSetupDialog
{
public:
    DesignRulesDialog(wxWindow* parent, const Json& context, DialogGateway gateway);
    static Json InitialSelection();

private:
    friend class StudioSmokeDriver;
    void Render(const Json& context);
    void Load(const Json& selection);
    void ChangeSelection();
    void Apply(bool remove);
    void Check();
    void ShowIssue(long index);
    /** @brief 전체 판정 집계를 유지한 채 선택한 상태의 표시 행만 바꾼다. */
    void RenderFindings();
    void ClearReport();
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;

    Json m_context;
    Json m_report = nullptr;
    Json m_findings = Json::array();
    bool m_loading = false;
    bool m_reloading = false;
    wxChoice* m_section = nullptr;
    wxChoice* m_subject = nullptr;
    wxChoice* m_parameter = nullptr;
    wxStaticText* m_parameterLabel = nullptr;
    wxChoice* m_inclusion = nullptr;
    EditorPanel* m_fields = nullptr;
    DesignCanvas* m_canvas = nullptr;
    wxListCtrl* m_issues = nullptr;
    wxChoice* m_filter = nullptr;
    wxChoice* m_connections = nullptr;
    wxButton* m_editRule = nullptr;
    wxTextCtrl* m_reason = nullptr;
    wxTextCtrl* m_detail = nullptr;
    wxButton* m_set = nullptr;
    wxButton* m_remove = nullptr;
    wxButton* m_check = nullptr;
};
