/** @file @brief 연구 후보를 별도 작업 사본으로 검토하고 명시적으로 여는 화면이다. */
#pragma once
#include "project_setup_dialog.h"
#include <memory>
#include <wx/collpane.h>

class DesignCanvas;
class StudioNotebook;
class wxChoice;
class wxListCtrl;
class wxTextCtrl;
class wxButton;

/** @brief 기존 요청 영수증의 키와 원래 입력을 보관하며 새 변경 명령과 구분한다. */
struct SweepSelectionRecovery
{
    Json context = nullptr;
    Json input = nullptr;
    Json response = nullptr;
    std::string requestKey;
    std::string epoch;
    bool uncertain = false;
};

/** @brief 원본 개정을 바꾸지 않고 검토한 후보의 새 프로젝트 생성만 요청한다. */
class SweepSelectionDialog final : public ProjectSetupDialog
{
public:
    SweepSelectionDialog(wxWindow* parent, const Json& context, DialogGateway gateway,
                         std::shared_ptr<SweepSelectionRecovery> recovery);
    bool OpenRequested() const;

private:
    friend class StudioSmokeDriver;
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    Json Input() const;
    void Changed();
    void Preview();
    void Apply();
    void Recover();
    void AcceptCopy(const Json& result);
    void Render(const Json& review);
    void ShowScene();
    Json m_context;
    Json m_review = nullptr;
    Json m_reviewInput = nullptr;
    DialogGateway m_recoveryGateway;
    std::shared_ptr<SweepSelectionRecovery> m_recovery;
    bool m_dirty = false;
    bool m_openRequested = false;
    bool m_recovering = false;
    StudioNotebook* m_tabs = nullptr;
    DesignCanvas* m_canvas = nullptr;
    wxChoice* m_sceneChoice = nullptr;
    wxListCtrl* m_changes = nullptr;
    wxTextCtrl* m_conditions = nullptr;
    wxTextCtrl* m_issues = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_path = nullptr;
    wxTextCtrl* m_reason = nullptr;
    wxTextCtrl* m_copySummary = nullptr;
    wxCollapsiblePane* m_advanced = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
    wxButton* m_recover = nullptr;
    wxButton* m_open = nullptr;
};
