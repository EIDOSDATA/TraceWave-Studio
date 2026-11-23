/** @file @brief 외부 이상 RLC 정의와 결합 후보를 원본과 구분하여 편집한다. */
#pragma once

#include "project_setup_dialog.h"
#include <vector>

class StudioNotebook;
class NetworkCircuitDrawing;
class NetworkChart;
class wxButton;
class wxChoice;
class wxListCtrl;
class wxPanel;
class wxTextCtrl;

/** @brief 서비스의 원자 저장과 불변 회로 사본을 연결하는 정합망 화면이다. */
class NetworkCircuitDialog final : public ProjectSetupDialog
{
public:
    NetworkCircuitDialog(wxWindow* parent, const Json& context, const Json& selection, DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    void BuildInterface();
    void LoadCircuit(int index);
    void RefreshLibrary(const std::string& selectedId);
    void RenderElements();
    void RenderElement();
    void RenderData();
    void RenderResult(const Json& result);
    void AddElement(const std::string& connection);
    void RemoveElement();
    void MoveElement(int direction);
    void EditElement(bool valueChanged = false, bool kindChanged = false);
    void ChangeUnit();
    void ChangeDefinition();
    void InvalidateReview();
    void SelectDataset();
    void Preview(bool calculate);
    void Apply();
    Json Definition() const;
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;

    Json m_context;
    Json m_selection;
    Json m_elements = Json::array();
    Json m_definition = Json::object();
    Json m_review = nullptr;
    Json m_reviewInput = nullptr;
    std::string m_savedCircuitId;
    int m_circuitIndex = 0;
    int m_elementIndex = -1;
    bool m_loading = false;
    bool m_dirty = false;
    StudioNotebook* m_tabs = nullptr;
    wxChoice* m_circuits = nullptr;
    wxChoice* m_datasets = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_inputPlane = nullptr;
    wxTextCtrl* m_loadPlane = nullptr;
    wxTextCtrl* m_resultName = nullptr;
    wxListCtrl* m_table = nullptr;
    wxPanel* m_elementFields = nullptr;
    wxTextCtrl* m_elementName = nullptr;
    wxTextCtrl* m_value = nullptr;
    wxChoice* m_kind = nullptr;
    wxChoice* m_connection = nullptr;
    wxChoice* m_state = nullptr;
    wxChoice* m_unit = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxTextCtrl* m_dataDetails = nullptr;
    wxListCtrl* m_results = nullptr;
    wxTextCtrl* m_resultDetails = nullptr;
    wxStaticText* m_pageLabel = nullptr;
    NetworkCircuitDrawing* m_drawing = nullptr;
    NetworkChart* m_resultGraph = nullptr;
    wxButton* m_reviewDefinition = nullptr;
    wxButton* m_useLoadPlane = nullptr;
    wxStaticText* m_step = nullptr;
    wxButton* m_reviewCalculation = nullptr;
    wxButton* m_apply = nullptr;
    std::vector<wxButton*> m_editButtons;
};
