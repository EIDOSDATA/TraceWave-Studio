/** @file @brief 일반 프로젝트 연구의 설정/실행/재개와 전력 표시 화면이다. */
#pragma once
#include "project_study_model.h"
#include <wx/dialog.h>
#include <wx/timer.h>
#include <functional>
#include <map>

class wxButton;
class wxCheckBox;
class wxChoice;
class wxListCtrl;
class wxNotebook;
class wxStaticText;
class wxTextCtrl;
class wxFlexGridSizer;

using StudyGateway = std::function<void(const std::string&, const Json&, bool, std::function<void(const Json&)>, std::function<void(const Json&)>)>;

/** @brief 서비스가 소유한 연구 상태를 표시하며 native 작업을 직접 실행하지 않는다. */
class ProjectStudyDialog final : public wxDialog
{
public:
    ProjectStudyDialog(wxWindow* parent, const Json& context, StudyGateway gateway, std::function<void()> closed);
    /** @brief 실제 GUI 시험도 제품과 같은 입력/동작/조회 경계를 사용한다. */
    void SetSpecification(const Json& specification);
    void CreateStudy();
    void Command(const std::string& action);
    const Json& CurrentView() const { return m_view; }
    bool Pending() const { return m_pending; }
    const std::string& LastError() const { return m_lastError; }
    /** @brief 전송 종료를 작업 취소/완료로 추정하지 않고 읽기 전용으로 전환한다. */
    void ServiceDisconnected(const std::string& message);

private:
    void Build();
    void AddField(wxWindow* parent, wxFlexGridSizer* grid, const std::string& key, const std::string& label);
    void Call(const std::string& method, const Json& input, bool mutation, std::function<void(const Json&)> completed);
    void ReloadStudies();
    void ReadSelected(bool loadFields = false);
    void Render(const Json& view);
    void UpdateControls();
    Json Draft() const;

    StudyGateway m_gateway;
    std::function<void()> m_closed;
    Json m_context;
    Json m_basis;
    Json m_view = Json::object();
    Json m_studies = Json::array();
    std::string m_selected;
    std::string m_lastError;
    bool m_pending = false;
    bool m_closing = false;
    bool m_loading = false;
    bool m_disconnected = false;
    std::map<std::string, wxTextCtrl*> m_fields;
    wxChoice* m_choice = nullptr;
    wxCheckBox* m_radiation = nullptr;
    wxCheckBox* m_losses = nullptr;
    wxStaticText* m_status = nullptr;
    wxTextCtrl* m_details = nullptr;
    wxListCtrl* m_cases = nullptr;
    wxNotebook* m_pages = nullptr;
    wxButton* m_create = nullptr;
    wxButton* m_start = nullptr;
    wxButton* m_resume = nullptr;
    wxButton* m_cancel = nullptr;
    wxButton* m_refresh = nullptr;
    wxTimer m_timer;
};
