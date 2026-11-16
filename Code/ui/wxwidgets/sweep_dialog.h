/** @file @brief 후보 조합과 예산을 검토한 뒤 불변 연구만 저장하는 네 탭 설정 화면이다. */
#pragma once
#include "project_setup_dialog.h"
#include <map>
#include <vector>

class StudioNotebook;
class wxButton;
class wxChoice;
class wxCheckBox;
class wxCheckListBox;
class wxListCtrl;
class wxListBox;
class wxTextCtrl;
class wxSpinCtrl;
class wxGrid;
class wxSizer;

/** @brief 원문 입력을 보관하고 수량/후보/예산 판단을 서비스로 보내는 View이다. */
class SweepDialog final : public ProjectSetupDialog
{
public:
    SweepDialog(wxWindow* parent, const Json& context, DialogGateway gateway);
    Json Specification() const;
    void Preview();
    void Create();

private:
    friend class StudioSmokeDriver;
    struct SettingInput
    {
        wxTextCtrl* text = nullptr;
        wxChoice* unit = nullptr;
        Json quantity = nullptr;
        std::string displayUnit;
        bool dirty = false;
        bool eligible = true;
        bool quantityCurrent = true;
    };
    void BuildInterface();
    void BuildVariables(wxWindow* page, wxSizer* layout);
    void BuildSettings(wxWindow* page, wxSizer* layout);
    void BuildBudget(wxWindow* page, wxSizer* layout);
    void BuildReview(wxWindow* page, wxSizer* layout);
    void Changed();
    void LoadCatalog();
    void SelectVariable(int index);
    void RenderVariables();
    void RenderRows();
    void RenderReview(const Json& result);
    void AddVariable();
    void AddValue();
    void UpdateRange();
    void ChangeSettingUnit(const std::string& id);
    void ChangeRadiationUnit(std::size_t index);
    void RefreshOptionalInputs();
    void RefreshPorts();
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    Json m_context;
    Json m_basis;
    Json m_variables = Json::array();
    Json m_catalog = Json::array();
    Json m_review = nullptr;
    Json m_reviewInput = nullptr;
    std::vector<std::string> m_variableNames;
    std::vector<std::string> m_portIds;
    std::map<std::string, SettingInput> m_settings;
    std::vector<SettingInput> m_radiationFields;
    wxCheckBox* m_recordRadiation = nullptr;
    wxCheckBox* m_featureSubdivisions = nullptr;
    wxCheckBox* m_recordLosses = nullptr;
    wxSpinCtrl* m_radiationCount = nullptr;
    bool m_radiationDirty = false;
    std::map<std::string, wxTextCtrl*> m_budgetText;
    std::map<std::string, std::string> m_budgetUnits;
    std::map<std::string, bool> m_budgetDirty;
    StudioNotebook* m_pages = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxChoice* m_type = nullptr;
    wxChoice* m_combination = nullptr;
    wxChoice* m_availableVariables = nullptr;
    wxListCtrl* m_variableList = nullptr;
    wxListBox* m_values = nullptr;
    wxChoice* m_valueMode = nullptr;
    wxTextCtrl* m_valueText = nullptr;
    wxChoice* m_valueUnit = nullptr;
    wxChoice* m_valueState = nullptr;
    wxTextCtrl* m_rangeStart = nullptr;
    wxTextCtrl* m_rangeStop = nullptr;
    wxSpinCtrl* m_rangeCount = nullptr;
    wxGrid* m_rows = nullptr;
    wxButton* m_addVariable = nullptr;
    wxButton* m_removeVariable = nullptr;
    wxButton* m_addValue = nullptr;
    wxButton* m_removeValue = nullptr;
    wxButton* m_addRow = nullptr;
    wxButton* m_removeRow = nullptr;
    wxChoice* m_datasets = nullptr;
    wxChoice* m_circuits = nullptr;
    wxCheckListBox* m_targets = nullptr;
    wxCheckBox* m_explicitContext = nullptr;
    wxChoice* m_port = nullptr;
    wxTextCtrl* m_referencePlane = nullptr;
    wxStaticText* m_sourceNotice = nullptr;
    wxStaticText* m_variableNotice = nullptr;
    wxSpinCtrl* m_candidateBudget = nullptr;
    wxSpinCtrl* m_nativeBudget = nullptr;
    wxListCtrl* m_previewRows = nullptr;
    wxTextCtrl* m_diagnostics = nullptr;
    wxStaticText* m_reviewSummary = nullptr;
    wxTextCtrl* m_sources = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_create = nullptr;
    wxButton* m_close = nullptr;
    int m_variableIndex = -1;
    int m_circuitIndex = -1;
    bool m_loading = false;
    bool m_dirty = false;
    bool m_saved = false;
};
