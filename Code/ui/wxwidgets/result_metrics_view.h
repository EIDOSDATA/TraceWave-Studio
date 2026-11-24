/** @file @brief 기록된 전력과 독립 손실의 값/분모/미확립 상태를 표시한다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <functional>
class NetworkChart;
class wxChoice;
class wxListCtrl;
class wxStaticText;
class wxButton;
class wxCheckBox;
class ResultMetricsView final : public wxScrolledWindow
{
public:
    explicit ResultMetricsView(wxWindow* parent);
    void SetDescription(const Json& description);
    void SetMetrics(const Json& result);
    void Clear(const std::string& reason);
    void SetValidationAvailable(bool available);
    std::function<void()> onSelectSource;
    std::function<void()> onValidation;

private:
    void Present();
    void SetNotice(const std::string& message);
    Json m_description = nullptr;
    Json m_result = nullptr;
    wxChoice* m_frequency = nullptr;
    wxStaticText* m_heading = nullptr;
    wxStaticText* m_notice = nullptr;
    wxListCtrl* m_table = nullptr;
    NetworkChart* m_chart = nullptr;
    wxButton* m_validationButton = nullptr;
    wxButton* m_rawButton = nullptr;
    wxCheckBox* m_details = nullptr;
    wxString m_noticeText;
};
