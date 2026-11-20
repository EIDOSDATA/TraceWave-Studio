/** @file @brief 보존 ZIP의 수신, 검토와 명시 복원을 조립한다. */
#pragma once
#include "dialog_gateway.h"
#include <wx/dialog.h>

class wxButton;
class wxGauge;
class wxListCtrl;
class wxStaticText;
class wxTextCtrl;

class ArchiveRestoreDialog final : public wxDialog
{
public:
    ArchiveRestoreDialog(wxWindow* parent, wxString workspace, DialogGateway gateway);
    const std::string& OpenPath() const;

private:
    void Browse();
    void Receive();
    void ReceiveNext();
    void Review();
    void ShowReview(const Json& result);
    void Apply();
    void Check();
    void Complete(const Json& result);
    void Request(const std::string& method, const Json& input, bool mutation,
                 std::function<void(const Json&)> complete);
    void CloseDialog(int result);
    void Drop();
    void Actions();
    void Status(const std::string& text);
    Json Application() const;
    void ValidateProgress(const Json& result) const;

    DialogGateway m_gateway;
    std::string m_name, m_bytes, m_digest, m_upload, m_openPath;
    std::size_t m_received = 0;
    Json m_review = nullptr;
    bool m_busy = false, m_applying = false, m_uncertain = false, m_completed = false;
    bool m_leaveAfterResponse = false, m_live = true;
    wxButton *m_browse = nullptr, *m_apply = nullptr, *m_check = nullptr, *m_open = nullptr, *m_close = nullptr;
    wxStaticText* m_status = nullptr;
    wxGauge* m_progress = nullptr;
    wxListCtrl* m_values = nullptr;
    wxTextCtrl* m_details = nullptr;
};
