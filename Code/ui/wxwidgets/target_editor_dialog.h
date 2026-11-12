/** @file @brief 다중 RF 목표 목록과 서비스 필드 폼을 연결한다. */
#pragma once

#include "project_setup_dialog.h"

class EditorPanel;
class wxButton;
class wxListBox;
class wxTextCtrl;

/** @brief 목표 저장과 해석/수렴 결과를 분리하는 편집 화면이다. */
class TargetEditorDialog final : public ProjectSetupDialog
{
public:
    TargetEditorDialog(wxWindow* parent, const Json& context, DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    void BuildInterface();
    void RenderContext(const Json& context);
    void Load(const Json& targetId);
    void Apply(bool remove);
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    bool HasDraft() const override;
    void RestoreSelection();

    Json m_context;
    Json m_targetId = nullptr;
    bool m_loading = false;
    bool m_reloadingContext = false;
    wxListBox* m_targets = nullptr;
    EditorPanel* m_fields = nullptr;
    wxTextCtrl* m_reason = nullptr;
    wxStaticText* m_summary = nullptr;
    wxButton* m_add = nullptr;
    wxButton* m_apply = nullptr;
    wxButton* m_remove = nullptr;
    wxButton* m_cancel = nullptr;
};
