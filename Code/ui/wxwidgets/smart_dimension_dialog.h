/** @file @brief 두 홀과 급전 양단의 안정 기준, 참조와 구동 치수를 편집한다. */
#pragma once
#include "project_setup_dialog.h"

class DesignCanvas;
class wxButton;
class wxChoice;
class wxMouseEvent;
class wxTextCtrl;

class SmartDimensionDialog final : public ProjectSetupDialog
{
public:
    SmartDimensionDialog(wxWindow* parent, const Json& context, const Json& scene, const Json& selection,
                         DialogGateway gateway);

private:
    bool HasDraft() const override;
    void UpdateActions() override;
    void LoadRecord();
    void ChangeInputs();
    void Preview(bool remove);
    void Apply();
    void Pick(wxMouseEvent& event);
    Json Anchors() const;
    Json Points() const;
    void Present(const Json& measurement, const std::string& heading);
    void Draw(const Json& measurement);
    void ShowSelection();

    Json m_context, m_scene, m_review, m_reviewInput;
    wxChoice *m_records = nullptr, *m_kind = nullptr, *m_first = nullptr, *m_second = nullptr,
             *m_port = nullptr, *m_mode = nullptr;
    wxTextCtrl *m_name = nullptr, *m_target = nullptr, *m_summary = nullptr;
    wxButton *m_preview = nullptr, *m_remove = nullptr, *m_apply = nullptr;
    DesignCanvas* m_canvas = nullptr;
    bool m_dirty = false;
    int m_record = 0;
    int m_firstPort = wxNOT_FOUND, m_firstEnd = wxNOT_FOUND;
};
