/** @file @brief PCB 기계/제조 객체의 명시 입력과 원자 후보 적용을 연결한다. */
#pragma once
#include "project_setup_dialog.h"
#include <memory>
#include <wx/collpane.h>

class PcbFeatureForm;
class StudioNotebook;
class DesignCanvas;
class wxChoice;
class wxListCtrl;
class wxTextCtrl;
class wxButton;

/** @brief 닫힘/재연결 이후에도 동일 ledger 요청만 조회하기 위한 표시 상태이다. */
struct PcbFeatureRecovery
{
    Json pending = nullptr;
    std::function<void()> resolved;
};

class PcbFeatureDialog final : public ProjectSetupDialog
{
public:
    PcbFeatureDialog(wxWindow* parent, const Json& context, DialogGateway gateway,
                     std::shared_ptr<PcbFeatureRecovery> recovery);

private:
    friend class StudioSmokeDriver;
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    void Load(const std::string& section, const Json& id, const Json& transition = Json::object());
    void Transition();
    void RefreshSelectors();
    void ChangeOperation();
    void Render(const Json& context);
    void Changed();
    Json Input() const;
    void Preview();
    void Apply();
    void Recover();
    void Accept(const Json& result);
    void ShowScene();
    Json m_context;
    Json m_review = nullptr, m_reviewInput = nullptr;
    Json m_recordIds = Json::array();
    std::vector<std::string> m_sections, m_operations;
    std::vector<std::string> m_shapeKinds;
    std::string m_sectionName;
    Json m_recordId = nullptr;
    bool m_loading = false, m_dirty = false, m_recovering = false;
    DialogGateway m_gateway;
    std::shared_ptr<PcbFeatureRecovery> m_recovery;
    StudioNotebook* m_tabs = nullptr;
    PcbFeatureForm* m_form = nullptr;
    wxChoice* m_section = nullptr;
    wxChoice* m_record = nullptr;
    wxChoice* m_operation = nullptr;
    wxChoice* m_shape = nullptr;
    wxChoice* m_definition = nullptr;
    wxChoice* m_envelope = nullptr;
    wxChoice* m_sceneChoice = nullptr;
    DesignCanvas* m_canvas = nullptr;
    wxListCtrl* m_changes = nullptr;
    wxTextCtrl* m_reason = nullptr;
    wxTextCtrl* m_issues = nullptr;
    wxTextCtrl* m_conditions = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxCollapsiblePane* m_advanced = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
    wxButton* m_recover = nullptr;
    int m_operationIndex = 0;
};
