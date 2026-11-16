/** @file @brief 선택한 봉인 결과의 조건을 기본 요약과 접힌 원문으로 분리한다. */
#pragma once
#include "studio_types.h"
#include <wx/panel.h>
#include <wx/collpane.h>
#include <cstdint>
#include <functional>
class wxStaticText;
class wxTextCtrl;
class wxScrolledWindow;
class wxButton;

class ResultConditionsView final : public wxPanel
{
public:
    explicit ResultConditionsView(wxWindow* parent);
    void SetDescription(const Json& description);
    void SetComparison(const Json& response, const std::string& leftName = "", const std::string& rightName = "");
    void SetConditionPage(const Json& response);
    void ConditionsPending(bool pending);
    std::uint64_t ConditionGeneration() const
    {
        return m_conditionGeneration;
    }
    int ConditionTotal() const
    {
        return m_conditionPage.value("total", 0);
    }
    std::function<void(int)> onConditionPage;
    void Clear(const std::string& message);
    void SetValidationAvailable(bool available);
    std::function<void()> onValidation;

private:
    friend class StudioSmokeDriver;
    wxCollapsiblePane* AddGroup(const std::string& label, const std::string& name, wxTextCtrl*& text,
                                bool collapsed = false);
    void Relayout();
    void SetText(wxTextCtrl* control, const std::string& value, int maximumHeight);
    void PresentComparison();
    void PageActions();
    wxStaticText* m_heading = nullptr;
    wxScrolledWindow* m_scroll = nullptr;
    wxCollapsiblePane* m_originalGroup = nullptr;
    wxCollapsiblePane* m_basisGroup = nullptr;
    wxCollapsiblePane* m_validationGroup = nullptr;
    wxCollapsiblePane* m_advanced = nullptr;
    wxButton* m_copy = nullptr;
    wxButton* m_validationButton = nullptr;
    wxPanel* m_pager = nullptr;
    wxStaticText* m_pageLabel = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
    wxTextCtrl* m_summary = nullptr;
    wxTextCtrl* m_basis = nullptr;
    wxTextCtrl* m_validation = nullptr;
    wxTextCtrl* m_source = nullptr;
    std::string m_copyText;
    std::string m_leftName, m_rightName;
    Json m_comparison = nullptr;
    Json m_conditionPage = nullptr;
    std::uint64_t m_conditionGeneration = 0;
    bool m_conditionsPending = false;
};
