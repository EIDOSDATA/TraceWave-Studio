/** @file @brief 적층 및 설치 환경의 실제 입력 폼과 표시 상태를 연결한다. */
#pragma once
#include "project_setup_dialog.h"
#include <map>

class wxButton;
class wxPanel;
class wxChoice;
class wxListCtrl;
class wxScrolledWindow;
class wxTextCtrl;

class PhysicalSetupDialog final : public ProjectSetupDialog
{
public:
    PhysicalSetupDialog(wxWindow* parent, const Json& context, DialogGateway gateway);
    /** @brief 최초 진입은 기본 적층 및 명목 두께 검토이다. */
    static Json InitialSelection();

private:
    friend class StudioSmokeDriver;
    void Render(const Json& context);
    void RenderReview();
    void DrawSection();
    void RenderFields();
    void Load(const std::string& section, const Json& identity);
    void Switch();
    void SelectCurrent();
    void BrowseStep();
    void ReviewStep(const wxString& path);
    void Apply(bool remove);
    Json Changes() const;
    std::string Value(const std::string& key) const;
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;

    bool m_refreshing = false;
    Json m_context;
    Json m_stepReview = nullptr;
    std::map<std::string, wxWindow*> m_inputs;
    wxChoice* m_section = nullptr;
    wxChoice* m_record = nullptr;
    wxPanel* m_sectionView = nullptr;
    wxListCtrl* m_stack = nullptr;
    wxTextCtrl* m_review = nullptr;
    wxScrolledWindow* m_form = nullptr;
    wxTextCtrl* m_reason = nullptr;
    wxButton* m_apply = nullptr;
    wxButton* m_remove = nullptr;
    wxButton* m_browse = nullptr;
    wxButton* m_storedStep = nullptr;
};
