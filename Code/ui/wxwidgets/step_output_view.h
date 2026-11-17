/** @file @brief STEP 생성과 새 reader 검수의 범위를 분리하는 native View이다. */
#pragma once
#include "studio_types.h"
#include "output_model.h"
#include <wx/scrolwin.h>
#include <wx/timer.h>
#include <functional>
class ModelView;
class wxListCtrl;
class wxButton;
class wxStaticText;

class StepOutputView final : public wxScrolledWindow
{
public:
    explicit StepOutputView(wxWindow* parent);
    void SetPreview(const Json& review);
    void SetResult(const Json& result, const wxString& workspace);
    void Clear(const std::string& message);
    void SetAvailable(bool available, bool busy, bool reviewed, bool canVerify);
    std::function<void()> onPreview;
    std::function<void()> onBuild;
    std::function<void()> onVerify;
    std::function<void()> onDetails;

private:
    friend class StudioSmokeDriver;
    void LoadQueued();
    ModelView* m_model = nullptr;
    wxListCtrl* m_scope = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_build = nullptr;
    wxButton* m_verify = nullptr;
    wxButton* m_details = nullptr;
    wxStaticText* m_notice = nullptr;
    std::string m_loadedHash;
    OutputUi::DeferredDisplay m_pendingDisplay;
    wxTimer m_displayRetry;
    wxString m_workspace;
};
