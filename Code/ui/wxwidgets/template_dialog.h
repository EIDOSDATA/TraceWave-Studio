/** @file @brief 명시 치수 카드의 형상 미리보기와 적용을 분리한다. */
#pragma once

#include "project_setup_dialog.h"

class DesignCanvas;
class EditorPanel;
class wxButton;
class wxChoice;
class wxTextCtrl;

/** @brief 원호/IFA 카드의 입력을 추정하지 않고 서비스 후보만 표시한다. */
class TemplateDialog final : public ProjectSetupDialog
{
public:
    TemplateDialog(wxWindow* parent, const Json& context, DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    void BuildInterface();
    void RenderContext(const Json& context);
    void SelectCard(int index);
    Json Specification() const;
    void Changed();
    void Preview();
    void Apply();
    void UpdateActions() override;
    std::string CardDescription() const;
    bool HasDraft() const override;
    void StoreDraft();
    void ShowRequestFailure(const Json& error) override;

    Json m_context;
    Json m_drafts = Json::object();
    Json m_card = nullptr;
    Json m_reviewedInput = nullptr;
    Json m_preview = nullptr;
    bool m_loading = false;
    bool m_reloadingContext = false;
    wxChoice* m_cards = nullptr;
    wxChoice* m_binding = nullptr;
    wxChoice* m_target = nullptr;
    EditorPanel* m_inputs = nullptr;
    DesignCanvas* m_canvas = nullptr;
    wxTextCtrl* m_notes = nullptr;
    wxButton* m_previewButton = nullptr;
    wxButton* m_applyButton = nullptr;
    wxButton* m_cancel = nullptr;
};
