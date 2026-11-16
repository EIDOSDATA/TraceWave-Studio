/** @file @brief 기존 해석 자료의 명시 등록과 봉인된 계산 진단 조회 화면이다. */
#pragma once
#include "project_setup_dialog.h"

class wxChoice;
class wxTextCtrl;
class wxButton;
class NetworkChart;

/** @brief 이미 완료된 solver 자료만 검토 후 공통 복소 자료로 등록한다. */
class NetworkSolverDialog final : public ProjectSetupDialog
{
public:
    NetworkSolverDialog(wxWindow* parent, const Json& context, DialogGateway gateway);

private:
    bool HasDraft() const override;
    void UpdateActions() override;
    void Preview();
    void Apply();
    Json Parameters() const;
    Json m_context;
    Json m_review = nullptr;
    bool m_dirty = false;
    wxChoice* m_result = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_details = nullptr;
    NetworkChart* m_chart = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
};

/** @brief 요약에서 생략한 진단도 32개 페이지로 빠짐없이 조회한다. */
class NetworkDiagnosticsDialog final : public ProjectSetupDialog
{
public:
    NetworkDiagnosticsDialog(wxWindow* parent, const Json& context, const Json& selection, DialogGateway gateway);

private:
    bool HasDraft() const override
    {
        return false;
    }
    void UpdateActions() override;
    void Read(int offset);
    std::string m_dataset;
    int m_offset = 0;
    int m_nextOffset = -1;
    wxTextCtrl* m_details = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
};
