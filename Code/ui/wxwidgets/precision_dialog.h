/** @file @brief 치수, 변환과 평면 연산의 서비스 후보를 검토하는 화면이다. */
#pragma once
#include "project_setup_dialog.h"
#include <map>
#include <vector>

class DesignCanvas;
class wxCheckListBox;
class wxChoice;
class wxTextCtrl;
class wxButton;
class wxPanel;
class wxStaticText;

/** @brief 입력을 바꾸면 검토를 무효화하고 일치하는 후보만 원자 적용한다. */
class PrecisionDialog final : public ProjectSetupDialog
{
public:
    PrecisionDialog(wxWindow* parent, const Json& context, const Json& objects, const Json& scene, DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    bool HasDraft() const override;
    void UpdateActions() override;
    void ChangeInputs();
    void LoadContext(const Json& context);
    void BuildFields();
    Json SelectionIds() const;
    Json Input() const;
    void Preview();
    void Apply();
    void ShowRequestFailure(const Json& error) override;
    Json m_context;
    Json m_objects;
    Json m_originalScene;
    Json m_review = nullptr;
    Json m_reviewInput = nullptr;
    bool m_dirty = false;
    bool m_loadingFields = false;
    wxCheckListBox* m_selection = nullptr;
    wxChoice* m_operation = nullptr;
    wxChoice* m_dimension = nullptr;
    wxChoice* m_parameter = nullptr;
    wxChoice* m_axis = nullptr;
    wxChoice* m_trimTarget = nullptr;
    wxTextCtrl* m_patternExclusions = nullptr;
    wxChoice* m_join = nullptr;
    wxChoice* m_unit = nullptr;
    wxPanel* m_fields = nullptr;
    wxTextCtrl* m_reason = nullptr;
    wxTextCtrl* m_summary = nullptr;
    wxStaticText* m_dimensionNote = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
    DesignCanvas* m_canvas = nullptr;
    std::map<std::string, wxTextCtrl*> m_numbers;
    std::vector<std::string> m_parameterIds;
};
