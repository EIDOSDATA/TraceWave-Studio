/** @file @brief 명시 정렬과 비교 보고서의 후보/원자 저장을 연결한다. */
#pragma once
#include "project_setup_dialog.h"
#include "measurement_recovery.h"
#include <memory>
#include <vector>
class wxTextCtrl;
class wxChoice;
class wxCheckListBox;
class wxSpinCtrl;
class wxButton;
class wxListCtrl;
class StudioNotebook;
class NetworkChart;
class MeasurementQuantityGroup;

class MeasurementOperationDialog final : public ProjectSetupDialog
{
public:
    MeasurementOperationDialog(wxWindow* parent, const Json& context, const Json& selection,
                               const std::string& operation, DialogGateway gateway,
                               std::shared_ptr<MeasurementRecovery> recovery);

private:
    friend class StudioSmokeDriver;
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    void BuildAlignment(wxWindow* parent, wxSizer* layout);
    void Changed();
    void MoveOperation(int delta);
    Json Input() const;
    void Preview();
    void Apply();
    void Accept(const Json& response);
    void Recover();
    void Render(const Json& response);
    Json m_context, m_selection;
    Json m_review = nullptr, m_reviewInput = nullptr;
    std::string m_operation, m_draftTime;
    DialogGateway m_gateway;
    std::shared_ptr<MeasurementRecovery> m_recovery;
    bool m_dirty = false, m_recovering = false;
    StudioNotebook* m_tabs = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_reason = nullptr;
    wxCheckListBox* m_operations = nullptr;
    std::vector<std::string> m_order;
    std::vector<wxChoice*> m_ports;
    std::vector<wxTextCtrl*> m_references;
    std::shared_ptr<MeasurementQuantityGroup> m_frequencyInputs, m_gapInputs;
    wxChoice* m_frequencyMode = nullptr;
    wxChoice* m_frequencyUnit = nullptr;
    wxChoice* m_gapUnit = nullptr;
    wxTextCtrl* m_start = nullptr;
    wxTextCtrl* m_stop = nullptr;
    wxTextCtrl* m_explicit = nullptr;
    wxTextCtrl* m_gap = nullptr;
    wxSpinCtrl* m_count = nullptr;
    wxTextCtrl* m_sources = nullptr;
    wxTextCtrl* m_summary = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxListCtrl* m_points = nullptr;
    NetworkChart* m_chart = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
    wxButton* m_recover = nullptr;
};
