/** @file @brief 불변 측정 기록의 새 개정을 검토하고 한 명령으로 저장한다. */
#pragma once
#include "project_setup_dialog.h"
#include "measurement_recovery.h"
#include <memory>
#include <wx/collpane.h>
class MeasurementRecordForm;
class NetworkChart;
class StudioNotebook;
class wxListCtrl;
class wxTextCtrl;
class wxButton;

class MeasurementRecordDialog final : public ProjectSetupDialog
{
public:
    MeasurementRecordDialog(wxWindow* parent, const Json& context, const Json& selection, DialogGateway gateway,
                            std::shared_ptr<MeasurementRecovery> recovery);

private:
    friend class StudioSmokeDriver;
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    void Changed();
    Json Input() const;
    void Preview();
    void Apply();
    void Recover();
    void Accept(const Json& response);
    void Render(const Json& response);
    Json m_context, m_selection;
    Json m_review = nullptr, m_reviewInput = nullptr;
    std::string m_draftTime;
    DialogGateway m_gateway;
    std::shared_ptr<MeasurementRecovery> m_recovery;
    bool m_recovering = false;
    StudioNotebook* m_tabs = nullptr;
    MeasurementRecordForm* m_form = nullptr;
    NetworkChart* m_chart = nullptr;
    wxListCtrl* m_changes = nullptr;
    wxTextCtrl* m_summary = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxCollapsiblePane* m_advanced = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
    wxButton* m_recover = nullptr;
};
