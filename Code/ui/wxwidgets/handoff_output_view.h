/** @file @brief 고정 설계의 근거, 인계 검토와 발행 기록을 표시한다. */
#pragma once
#include "studio_types.h"
#include <wx/panel.h>
#include <functional>

class wxButton;
class wxCheckBox;
class wxChoice;
class wxListCtrl;
class wxStaticText;

class HandoffOutputView final : public wxPanel
{
public:
    explicit HandoffOutputView(wxWindow* parent);
    bool ArchiveMode() const;
    void SetArchiveMode(bool archive);
    void SetArchiveSupported(bool supported);
    void ResetEvidence();
    void SetEvidence(const Json& value);
    void SetCatalog(const Json& value, const std::string& preferred = "");
    void SetReview(const Json& value);
    void SetAvailable(bool available, bool snapshot);
    Json Input() const;
    Json SelectedPackage() const;
    const Json& Review() const;

    std::function<void()> onPreview, onBuild, onSave, onReviewChanged, onModeChanged;
    std::function<void(int)> onPage;

private:
    void UpdateActions();
    void FormatChanged();
    void ShowArchiveRows();
    void Select(bool include);
    void ShowDetails(bool files);
    wxListCtrl* m_list = nullptr;
    wxCheckBox* m_rights = nullptr;
    wxChoice* m_format = nullptr;
    wxChoice* m_history = nullptr;
    wxStaticText* m_summary = nullptr;
    wxButton *m_include = nullptr, *m_remove = nullptr, *m_previous = nullptr, *m_next = nullptr;
    wxButton *m_preview = nullptr, *m_build = nullptr, *m_report = nullptr, *m_files = nullptr, *m_save = nullptr;
    Json m_page = nullptr, m_review = nullptr, m_packages = Json::array(), m_selected = Json::array();
    bool m_available = false, m_snapshot = false, m_archiveSupported = false;
};
