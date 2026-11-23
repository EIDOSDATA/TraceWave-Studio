/** @file @brief 보존 파일 전송/명시 대응/손실 검토와 원자 가져오기를 연결한다. */
#pragma once
#include "project_setup_dialog.h"
#include <wx/timer.h>
#include <wx/collpane.h>
#include <memory>
class StudioNotebook;
class DesignCanvas;
class wxButton;
class wxChoice;
class wxListCtrl;
class wxTextCtrl;
class wxCheckListBox;
class wxCheckBox;
class wxPanel;

/** @brief 확인된 전송 위치와 결과 불명 요청을 구분해 같은 원문만 재개한다. */
struct PcbImportRecovery
{
    Json checkpoint = nullptr;
    std::function<void(const Json&)> confirmed;
    std::function<void()> clear;
};

class PcbImportDialog final : public ProjectSetupDialog
{
public:
    PcbImportDialog(wxWindow* parent, const Json& context, DialogGateway gateway,
                    std::shared_ptr<PcbImportRecovery> recovery);
    ~PcbImportDialog();

private:
    friend class StudioSmokeDriver;
    struct File
    {
        std::string name, bytes, sha256;
    };
    struct MappingRow
    {
        std::string source;
        bool contactsOnly = false;
        bool regionsOnly = false;
        /** @brief 선택한 도형 종류가 사용하는 층 또는 넷의 대응 행인지 확인한다. */
        bool Included(bool contacts, bool regions) const
        {
            return (!contactsOnly && !regionsOnly) || (contacts && contactsOnly) || (regions && regionsOnly);
        }
        wxChoice* choice = nullptr;
        std::vector<Json> targets;
    };
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    void BuildSource(wxWindow* page);
    void BuildMapping(wxWindow* page);
    void BuildReview(wxWindow* page);
    void BuildOriginal(wxWindow* page);
    void Browse();
    bool LoadFiles(const std::vector<wxString>& paths);
    void Upload();
    void UploadNext();
    void Parse();
    void ReadUpload(const std::string& identity, bool resume = false);
    void RenderUpload(const Json& response);
    void RenderMapping(const Json& response);
    void RenderFiles();
    bool Uncertain() const;
    void Changed();
    Json Input() const;
    void Preview();
    void Apply();
    void Accept(const Json& result);
    void Recover();
    void Confirmed(const std::string& method, const Json& result);
    void ShowScene();
    void Poll(wxTimerEvent&);
    std::string Format() const;
    bool VendorFormat() const;
    void DescribeFormat();
    Json m_context, m_uploadState = nullptr, m_review = nullptr, m_reviewInput = nullptr;
    DialogGateway m_gateway;
    std::shared_ptr<PcbImportRecovery> m_recovery;
    std::vector<File> m_files;
    std::vector<std::string> m_uploadIds, m_formats;
    std::vector<MappingRow> m_layerRows, m_netRows;
    std::vector<std::string> m_lossKeys;
    std::string m_upload;
    bool m_loading = false, m_dirty = false, m_recovering = false, m_uploading = false;
    bool m_mappingLoaded = false;
    wxTimer m_poll;
    StudioNotebook* m_tabs = nullptr;
    wxChoice* m_format = nullptr;
    wxChoice* m_uploadChoice = nullptr;
    wxChoice* m_sceneChoice = nullptr;
    wxChoice* m_side = nullptr;
    wxTextCtrl* m_x = nullptr;
    wxTextCtrl* m_y = nullptr;
    wxTextCtrl* m_rotation = nullptr;
    wxChoice* m_lengthUnit = nullptr;
    wxChoice* m_angleUnit = nullptr;
    wxPanel* m_placement = nullptr;
    wxCheckBox* m_contacts = nullptr;
    wxCheckBox* m_regions = nullptr;
    wxCheckBox* m_adoptStack = nullptr;
    wxCheckBox* m_components = nullptr;
    wxCheckBox* m_boardConfirmed = nullptr;
    wxWindow* m_mappingPage = nullptr;
    wxWindow* m_mappingRows = nullptr;
    wxListCtrl* m_fileTable = nullptr;
    wxListCtrl* m_changes = nullptr;
    wxCheckListBox* m_losses = nullptr;
    wxTextCtrl* m_reason = nullptr;
    wxTextCtrl* m_issues = nullptr;
    wxTextCtrl* m_raw = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxTextCtrl* m_summary = nullptr;
    wxTextCtrl* m_formatDetail = nullptr;
    DesignCanvas* m_canvas = nullptr;
    wxCollapsiblePane* m_advanced = nullptr;
    wxButton* m_browse = nullptr;
    wxButton* m_uploadButton = nullptr;
    wxButton* m_parseButton = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_apply = nullptr;
    wxButton* m_recover = nullptr;
};
