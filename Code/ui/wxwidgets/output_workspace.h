/** @file @brief 출력 작업의 공통 입력/이력과 형식별 native View를 조립한다. */
#pragma once
#include "studio_types.h"
#include <wx/panel.h>
#include <functional>
#include <vector>
class StudioNotebook;
class DrawingOutputView;
class HandoffOutputView;
class wxSizer;
class StepOutputView;
class PcbCamOutputView;
class OutputConditionsView;
class wxChoice;
class wxButton;
class wxCheckBox;
class wxStaticText;

class OutputWorkspace final : public wxPanel
{
public:
    OutputWorkspace(wxWindow* parent, wxWindow* conditions);
    wxWindow* ConditionsView() const;
    void SetContext(const Json& context, bool resetOptions);
    void SetStoredDrawingAnnotation(const Json& settings);
    void SetCatalog(const Json& catalog, const std::string& preferredJob = "");
    void SetPreview(const Json& review);
    void SetRecord(const Json& record, const wxString& workspace);
    void Clear(const std::string& message);
    void ClearPreview(const std::string& message);
    void ClearRecord(const std::string& message);
    void SetStatus(const std::string& message);
    void SetAvailable(bool available, bool busy, bool reviewed, bool canCancel, bool uncertain);
    /** @brief 전체 출력 패널의 상태를 다시 계산하기 전에 취소 버튼을 잠근다. */
    bool LockCancelButton();
    void SetImportAvailable(bool available);
    void SelectSnapshot(const Json& snapshot);
    Json Snapshot() const;
    HandoffOutputView* Handoff() const;
    void SetHandoffAvailable(bool available);
    void SetHandoffConditions(const Json& input, const Json& review);
    Json Input() const;
    Json PreviewInput() const;
    /** @brief 현재 형식을 기본 조회 범위에 사용한다. */
    std::string HistoryFormat() const;
    std::string SelectedJob() const;
    int Kind() const;
    void SelectKind(int kind);
    const Json& Record() const;
    const Json& Preview() const;
    wxStaticText* StatusLabel() const;
    std::function<void()> onRefresh, onSnapshot, onPreview, onBuild, onVerify, onCancel, onRecover, onOpenFolder, onOpenFile, onHistoryScope;
    std::function<void(const Json&)> onSelectSnapshot;
    std::function<void(const std::string&)> onSelectJob;
    std::function<void(int)> onSnapshotPage, onCatalogPage;
    std::function<void()> onChanged;
    std::function<void()> onImport, onManufacturing;
    std::function<void(const Json&)> onSaveDrawingAnnotations;

private:
    friend class StudioSmokeDriver;
    void ShowRecord(bool review);
    StudioNotebook* m_tabs = nullptr;
    DrawingOutputView* m_drawing = nullptr;
    StepOutputView* m_step = nullptr;
    HandoffOutputView* m_handoff = nullptr;
    wxSizer* m_history = nullptr;
    wxSizer* m_source = nullptr;
    PcbCamOutputView* m_pcb = nullptr;
    OutputConditionsView* m_conditions = nullptr;
    wxChoice* m_snapshots = nullptr;
    wxChoice* m_records = nullptr;
    wxButton* m_capture = nullptr;
    wxButton* m_refresh = nullptr;
    wxButton* m_snapshotPrevious = nullptr;
    wxButton* m_snapshotNext = nullptr;
    wxButton* m_catalogPrevious = nullptr;
    wxButton* m_catalogNext = nullptr;
    wxButton* m_details = nullptr;
    wxButton* m_verify = nullptr;
    wxButton* m_folder = nullptr;
    wxButton* m_file = nullptr;
    wxCheckBox* m_allFormats = nullptr;
    wxButton* m_cancel = nullptr;
    wxButton* m_recover = nullptr;
    wxStaticText* m_status = nullptr;
    std::vector<Json> m_snapshotValues;
    std::vector<std::string> m_jobIds;
    Json m_context = nullptr, m_catalog = nullptr, m_record = nullptr, m_preview = nullptr;
    Json m_selectedSnapshot = nullptr;
    std::string m_selectedJob;
    bool m_refreshing = false;
};
