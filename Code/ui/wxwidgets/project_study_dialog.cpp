/** @file @brief 연구 화면의 서비스 요청과 수명/지연 응답을 관리한다. */
#include "project_study_dialog.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/choicdlg.h>
#include <wx/listctrl.h>
#include <wx/notebook.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>
#include <wx/sizer.h>
#include <algorithm>
#include <vector>

void ProjectStudyDialog::ServiceDisconnected(const std::string& message)
{
    m_disconnected = true;
    m_pending = false;
    m_timer.Stop();
    m_status->SetLabel(Display("연결 종료: 완료/취소 여부를 추정하지 않습니다. " + message));
    UpdateControls();
}

ProjectStudyDialog::ProjectStudyDialog(wxWindow* parent, const Json& context, StudyGateway gateway,
                                       std::function<void()> closed)
    : wxDialog(parent, wxID_ANY, Display("프로젝트 연구 / 격자와 방사·손실"), wxDefaultPosition, wxDefaultSize,
               wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
      m_gateway(std::move(gateway)), m_closed(std::move(closed)), m_context(context),
      m_basis(context.at("initial_specification")), m_timer(this)
{
    Build();
    SetSpecification(m_basis);
    Bind(wxEVT_CLOSE_WINDOW,
         [this](wxCloseEvent&)
         {
             m_closing = true;
             m_timer.Stop();
             if (m_closed)
             {
                 m_closed();
             }
             Destroy();
         });
    Bind(wxEVT_TIMER,
         [this](wxTimerEvent&)
         {
             if (!m_pending && !m_selected.empty())
             {
                 ReadSelected();
             }
         });
    m_timer.Start(1000);
    CallAfter(
        [this]()
        {
            ReloadStudies();
        });
}

void ProjectStudyDialog::Call(const std::string& method, const Json& input, bool mutation,
                              std::function<void(const Json&)> completed)
{
    if (m_pending || m_closing || m_disconnected)
    {
        return;
    }
    m_pending = true;
    UpdateControls();
    wxWeakRef<ProjectStudyDialog> self(this);
    m_gateway(
        method, input, mutation,
        [self, completed = std::move(completed)](const Json& result)
        {
            if (!self || self->m_closing)
            {
                return;
            }
            self->m_pending = false;
            completed(result);
            if (self && !self->m_closing)
            {
                self->UpdateControls();
            }
        },
        [self](const Json& error)
        {
            if (self && !self->m_closing)
            {
                self->m_pending = false;
                self->m_lastError = DiagnosticMessage(error);
                self->m_status->SetLabel(Display(self->m_lastError));
                self->UpdateControls();
            }
        });
}

Json ProjectStudyDialog::Draft(bool newStudy) const
{
    Studio::StudyFields fields;
    for (const auto& field : m_fields)
    {
        fields[field.first] = Utf8(field.second->GetValue());
    }
    return Studio::StudySpecification(m_basis, fields, m_radiation->GetValue(), m_losses->GetValue(), newStudy);
}

void ProjectStudyDialog::SetSpecification(const Json& specification)
{
    m_loading = true;
    m_basis = specification;
    for (const auto& field : Studio::StudyDraft(specification))
    {
        m_fields.at(field.first)->ChangeValue(Display(field.second));
    }
    m_radiation->SetValue(specification.at("settings").contains("radiation"));
    m_losses->SetValue(specification.at("settings").contains("power_balance"));
    m_loading = false;
    UpdateControls();
}

void ProjectStudyDialog::ReloadStudies()
{
    Call("study.context", Json::object(), false,
         [this](const Json& context)
         {
             m_context = context;
             Call("study.list", Json::object(), false,
                  [this](const Json& result)
                  {
                      m_studies = result.at("studies");
                      m_choice->Clear();
                      int selected = wxNOT_FOUND;
                      for (std::size_t i = 0; i < m_studies.size(); ++i)
                      {
                          const auto& study = m_studies.at(i);
                          m_choice->Append(Display(study.at("name").get<std::string>() + " / " +
                                                   Studio::StudyStatus(study.at("state"))));
                          if (study.at("study_id") == m_selected)
                          {
                              selected = static_cast<int>(i);
                          }
                      }
                      if (selected == wxNOT_FOUND && !m_studies.empty())
                      {
                          selected = 0;
                          m_selected = m_studies.at(0).at("study_id");
                      }
                      m_choice->SetSelection(selected);
                      if (selected != wxNOT_FOUND)
                      {
                          ReadSelected(m_view.empty() || m_view.value("study_id", std::string()) != m_selected);
                      }
                  });
         });
}

void ProjectStudyDialog::ReadSelected(bool loadFields)
{
    const std::string identity = m_selected;
    Call("study.get", Json{{"study_id", identity}}, false,
         [this, identity, loadFields](const Json& result)
         {
             if (identity != m_selected || result.at("study_id") != identity)
             {
                 return;
             }
             m_view = result;
             if (loadFields)
             {
                 SetSpecification(result.at("specification"));
             }
             Render(result);
         });
}

void ProjectStudyDialog::CreateStudy()
{
    try
    {
        const Json specification = Draft(true);
        m_lastError.clear();
        Call("study.create", Json{{"expected_revision", m_context.at("revision_id")}, {"specification", specification}},
             true,
             [this](const Json& created)
             {
                 m_selected = created.at("study_id");
                 m_status->SetLabel(Display("원본 스냅샷과 조건을 저장했습니다. 선택 연구 실행으로 시작하십시오."));
                 ReloadStudies();
             });
    }
    catch (const std::exception& error)
    {
        m_lastError = error.what();
        m_status->SetLabel(Display(m_lastError));
    }
}

void ProjectStudyDialog::Command(const std::string& action)
{
    if (!Studio::StudyActionAllowed(m_view, action, m_pending))
    {
        return;
    }
    Call("study." + action, Json{{"study_id", m_selected}}, true,
         [this](const Json&)
         {
             m_lastError.clear();
             m_pages->SetSelection(3);
             ReadSelected();
         });
}

void ProjectStudyDialog::Render(const Json& view)
{
    const int selected = m_choice->GetSelection();
    if (selected != wxNOT_FOUND)
    {
        m_choice->SetString(
            selected, Display(view.at("name").get<std::string>() + " / " + Studio::StudyStatus(view.at("state"))));
    }
    m_status->SetLabel(Display(Studio::StudyStatus(view.at("state")) + " / " + view.value("message", std::string())));
    m_cases->DeleteAllItems();
    for (const auto& row : view.at("cases"))
    {
        const long index = m_cases->InsertItem(m_cases->GetItemCount(), row.at("index").dump());
        m_cases->SetItem(index, 1, row.at("grid_mm").dump());
        m_cases->SetItem(index, 2, Display(Studio::StudyStatus(row.at("phase"))));
        m_cases->SetItem(index, 3, row.at("attempt_count").dump());
        m_cases->SetItem(index, 4, row.at("result_id").is_null() ? Display("계산 전") : Display("봉인 결과 있음"));
    }
    const wxString text = Display(Studio::StudySummary(view));
    if (m_details->GetValue() != text)
    {
        const long insertion = m_details->GetInsertionPoint();
        m_details->ChangeValue(text);
        m_details->SetInsertionPoint(std::min(insertion, m_details->GetLastPosition()));
    }
    Layout();
}

void ProjectStudyDialog::UpdateControls()
{
    if (m_loading || m_create == nullptr)
    {
        return;
    }
    bool matches = false;
    try
    {
        matches = !m_view.empty() && Draft() == m_view.at("specification");
    }
    catch (const std::exception&)
    {
    }
    m_create->Enable(!m_disconnected && !m_pending && m_context.value("runtime_configured", false));
    m_refresh->Enable(!m_disconnected && !m_pending);
    m_choice->Enable(!m_pending);
    m_samples->Enable(!m_disconnected && !m_pending && m_view.contains("cases") && m_view.at("cases").size() >= 2 &&
                      m_view.at("cases").at(0).at("phase") == "done" && m_view.at("cases").at(1).at("phase") == "done");
    m_start->Enable(!m_disconnected && matches && Studio::StudyActionAllowed(m_view, "start", m_pending));
    m_resume->Enable(!m_disconnected && matches && Studio::StudyActionAllowed(m_view, "resume", m_pending));
    m_cancel->Enable(!m_disconnected && Studio::StudyActionAllowed(m_view, "cancel", m_pending));
}

/** @brief 동일 개정에서 완료한 두 격자의 개별 주파수 표본을 보간 없이 표시한다. */
void ProjectStudyDialog::ShowPortSamples()
{
    const auto& cases = m_view.at("cases");
    wxArrayString names;
    std::vector<std::size_t> indices;
    for (std::size_t i = 1; i < cases.size(); ++i)
    {
        if (cases.at(i - 1).at("phase") == "done" && cases.at(i).at("phase") == "done")
        {
            names.Add(Display(cases.at(i - 1).at("grid_mm").dump() + " mm / " + cases.at(i).at("grid_mm").dump() + " mm"));
            indices.push_back(i);
        }
    }
    if (names.empty())
    {
        return;
    }
    wxSingleChoiceDialog choice(this, Display("비교할 인접 격자 수준"), Display("주파수별 포트 변화"), names);
    choice.SetSelection(static_cast<int>(indices.size() - 1));
    m_timer.Stop();
    const int selected = choice.ShowModal();
    m_timer.Start(1000);
    if (selected != wxID_OK)
    {
        return;
    }
    Call("study.sample_comparison", {{"study_id", m_selected}, {"right_case", indices.at(choice.GetSelection())}}, false,
         [this](const Json& result)
         {
             wxDialog dialog(this, wxID_ANY, Display("주파수별 포트 변화"), wxDefaultPosition,
                             FromDIP(wxSize(710, 480)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
             auto* layout = new wxBoxSizer(wxVERTICAL);
             auto* label = new wxStaticText(&dialog, wxID_ANY, Display("복소 S11 변화 허용값 " +
                 result.at("max_s11_complex_delta").dump() + " / 선택한 두 격자에서 직접 계산한 주파수 표본"));
             layout->Add(label, 0, wxALL, FromDIP(8));
             auto* samples = new wxListCtrl(&dialog, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT);
             int column = 0;
             for (const char* title : {"주파수 (GHz)", "복소 S11 변화량", "임피던스 변화 (옴)", "표본 기준"})
             {
                 samples->InsertColumn(column++, Display(title), wxLIST_FORMAT_LEFT, FromDIP(155));
             }
             for (const auto& row : result.at("rows"))
             {
                 const long item = samples->InsertItem(samples->GetItemCount(),
                     wxString::Format("%.12g", row.at("frequency_hz").get<double>() / 1e9));
                 samples->SetItem(item, 1, wxString::Format("%.8g", row.at("complex_s11_delta").get<double>()));
                 samples->SetItem(item, 2, wxString::Format("%.8g", row.at("impedance_delta_ohm").get<double>()));
                 samples->SetItem(item, 3, Display(row.at("within_threshold").get<bool>() ? "이내" : "초과"));
             }
             layout->Add(samples, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
             layout->Add(dialog.CreateSeparatedButtonSizer(wxOK), 0, wxEXPAND | wxALL, FromDIP(8));
             dialog.SetSizer(layout);
             dialog.CentreOnParent();
             m_timer.Stop();
             dialog.ShowModal();
             m_timer.Start(1000);
         });
}
