/** @file @brief 원문 파일, 열 대응과 명시 조건을 검토하는 복소 자료 가져오기 화면이다. */
#pragma once

#include "project_setup_dialog.h"
#include <array>
#include <string>

class wxButton;
class wxCheckBox;
class wxChoice;
class wxGrid;
class wxListCtrl;
class wxNotebook;
class wxPanel;
class wxSpinCtrl;
class wxTextCtrl;
class NetworkChart;

/** @brief 수치 해석은 서비스에 맡기고 동일 검토 해시의 후보만 한 명령으로 가져온다. */
class NetworkImportDialog final : public ProjectSetupDialog
{
public:
    NetworkImportDialog(wxWindow* parent, const Json& context, DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    /** @brief 원문 조건을 유지하는 기본 선택과 사용자가 명시한 변경을 분리한다. */
    struct PortInputs
    {
        wxPanel* panel = nullptr;
        wxChoice* project = nullptr;
        wxChoice* mode = nullptr;
        wxChoice* orientation = nullptr;
        wxCheckBox* planeChanged = nullptr;
        wxTextCtrl* plane = nullptr;
    };

    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    void BuildFilePage(wxWindow* page);
    void BuildMappingPage(wxWindow* page);
    void BuildReviewPage(wxWindow* page);
    void RebuildPairs();
    void ResetConditions();
    void ChangeInputs(bool sourceChanged = false);
    void Browse();
    bool LoadFile(const wxString& path);
    std::string Format() const;
    Json Mapping() const;
    Json Declarations() const;
    Json Input() const;
    void Preview();
    void RenderReview(const Json& result);
    void Apply();

    Json m_context;
    Json m_review = nullptr;
    Json m_reviewInput = nullptr;
    Json m_sourceDescriptor = nullptr;
    bool m_dirty = false;
    bool m_loading = true;
    std::string m_fileName;
    std::string m_encoded;
    wxNotebook* m_tabs = nullptr;
    wxPanel* m_csv = nullptr;
    wxPanel* m_conditions = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_path = nullptr;
    wxTextCtrl* m_raw = nullptr;
    wxTextCtrl* m_summary = nullptr;
    wxListCtrl* m_samples = nullptr;
    NetworkChart* m_chart = nullptr;
    wxChoice* m_format = nullptr;
    wxChoice* m_delimiter = nullptr;
    wxChoice* m_frequencyUnit = nullptr;
    wxChoice* m_parameter = nullptr;
    wxChoice* m_representation = nullptr;
    wxChoice* m_portCount = nullptr;
    wxChoice* m_wave = nullptr;
    wxChoice* m_phasor = nullptr;
    wxCheckBox* m_header = nullptr;
    wxCheckBox* m_mappingConfirmed = nullptr;
    wxCheckBox* m_z0Known = nullptr;
    wxSpinCtrl* m_frequencyColumn = nullptr;
    wxTextCtrl* m_ignored = nullptr;
    wxGrid* m_pairs = nullptr;
    std::array<wxTextCtrl*, 2> m_z0{};
    std::array<PortInputs, 2> m_ports{};
    wxButton* m_browse = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
};
