/** @file @brief 기준점과 축에서 스케치의 독립 후보와 저장 관계를 확인한다. */
#pragma once
#include "project_setup_dialog.h"

class DesignCanvas;
class wxButton;
class wxCheckListBox;
class wxChoice;
class wxTextCtrl;

class SketchConstraintDialog final : public ProjectSetupDialog
{
public:
    SketchConstraintDialog(wxWindow* parent, const Json& context, const Json& scene, const Json& selection,
                           DialogGateway gateway);

private:
    bool HasDraft() const override;
    void UpdateActions() override;
    void LoadGroup();
    void FillPoints();
    void ShowGeometry();
    void SetupChanged();
    Json SelectedShapes() const;
    Json Requested() const;
    void Preview(bool automatic = false, bool remove = false);
    void EditDimensions();
    void SubmitPreview(const Json& input);
    void Apply();
    void Present(const Json& result);

    Json m_context, m_points = Json::array(), m_rows = Json::array(), m_review, m_reviewInput;
    wxChoice *m_group = nullptr, *m_datum = nullptr, *m_axis = nullptr;
    wxCheckListBox *m_shapes = nullptr, *m_proposals = nullptr;
    wxTextCtrl *m_name = nullptr, *m_report = nullptr;
    wxStaticText* m_freedom = nullptr;
    wxButton *m_preview = nullptr, *m_automatic = nullptr, *m_remove = nullptr, *m_solve = nullptr, *m_apply = nullptr;
    DesignCanvas* m_canvas = nullptr;
    int m_groupIndex = 0;
    bool m_dirty = false;
};
