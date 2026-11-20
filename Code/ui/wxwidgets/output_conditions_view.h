/** @file @brief 출력 입력/검수/미정값을 원문과 구별하여 보여주는 우측 패널이다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <wx/collpane.h>
class wxTextCtrl;

class OutputConditionsView final : public wxScrolledWindow
{
public:
    explicit OutputConditionsView(wxWindow* parent);
    void SetRecord(const Json& record, const std::string& sourceName);
    void SetHandoff(const Json& snapshot, const Json& review, bool archive);
    void Clear(const std::string& message);

private:
    friend class StudioSmokeDriver;
    wxTextCtrl* Group(const std::string& title, bool collapsed = false);
    wxTextCtrl* m_input = nullptr;
    wxTextCtrl* m_limits = nullptr;
    wxTextCtrl* m_verification = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxCollapsiblePane* m_advanced = nullptr;
};
