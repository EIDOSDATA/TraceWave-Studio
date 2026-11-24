/** @file @brief 연구 화면의 서비스 요청과 수명/지연 응답을 관리한다. */
#include "project_study_dialog.h"
#include "studio_support.h"
#include "studio_theme.h"
#include "frequency_display.h"
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
    StudioTheme::ApplyTypography(*this);
    StudioTheme::BindSurface(*this);
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
                 if (m_view.empty())
                 {
                     ReloadStudies();
                 }
                 else if (m_view.value("state", std::string()) != "completed")
                 {
                     ReadSelected();
                 }
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
        [self, method](const Json& error)
        {
            if (self && !self->m_closing)
            {
                self->m_pending = false;
                self->m_lastError = DiagnosticMessage(error);
                self->m_status->SetLabel(Display(self->m_lastError));
                if (method == "study.create")
                {
                    const auto details = error.value("details", Json::object());
                    if (details.is_object())
                    {
                        const auto path = details.value("field_path", std::string());
                        std::string key = path.substr(path.find_last_of('.') + 1);
                        if (path == "settings.radiation.frequency_hz")
                        {
                            key = "frequencies";
                        }
                        else if (path == "settings.power_balance")
                        {
                            key = "max_relative_residual";
                        }
                        else if (path == "settings.frequency_hz")
                        {
                            key = "start";
                        }
                        self->FocusField(key);
                    }
                }
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
             UpdateBandLabels();
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
                 const auto& specification = result.at("specification");
                 SetSpecification(specification.contains("field_adaptive") ? m_context.at("initial_specification") : specification);
                 if (specification.contains("field_adaptive"))
                 {
                     m_pages->SetSelection(3);
                 }
             }
             Render(result);
         });
}

void ProjectStudyDialog::SelectStudy(const std::string& identity)
{
    if (!identity.empty())
    {
        m_selected = identity;
        m_view = Json::object();
        ReloadStudies();
    }
}

/** @brief 갱신된 설계 개정의 급전 대역을 두 입력 탭에 표시한다. */
void ProjectStudyDialog::UpdateBandLabels()
{
    const auto band = m_context.value("port_band_hz", Json(nullptr));
    const auto caption = band.is_object()
        ? "급전 유효 대역  " + StudioFrequency::Range(band.at("min"), band.at("max"))
        : "급전 유효 대역 미정. 프로젝트의 급전 속성에서 확인하세요.";
    for (auto* label : {m_analysisBand, m_radiationBand})
    {
        label->SetLabel(Display(caption));
        label->GetParent()->Layout();
    }
}

/** @brief 사용자가 입력한 원문을 유지하고 문제 입력 칸으로 이동한다. */
void ProjectStudyDialog::FocusField(const std::string& key)
{
    const auto field = m_fields.find(key);
    if (field == m_fields.end() || !field->second->IsEnabled())
    {
        return;
    }
    const auto page = m_pages->FindPage(field->second->GetParent());
    if (page != wxNOT_FOUND)
    {
        m_pages->SetSelection(page);
        field->second->SetFocus();
    }
}

void ProjectStudyDialog::CreateStudy()
{
    try
    {
        const Json specification = Draft(true);
        const auto band = m_context.value("port_band_hz", Json(nullptr));
        const auto& frequency = specification.at("settings").at("frequency_hz");
        if (band.is_object() && (frequency.at("start") < band.at("min") || frequency.at("stop") > band.at("max")))
        {
            m_lastError = "급전 유효 대역 " + StudioFrequency::Range(band.at("min"), band.at("max")) +
                " 안에서 시작과 끝 주파수를 입력하세요.";
            m_status->SetLabel(Display(m_lastError));
            FocusField(frequency.at("start") < band.at("min") ? "start" : "stop");
            return;
        }
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
    catch (const Studio::StudyFieldError& error)
    {
        m_lastError = error.what();
        m_status->SetLabel(Display(m_lastError));
        FocusField(error.key);
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
        m_cases->SetItem(index, 5, row.contains("native_grid_points") ? Display(row.at("native_grid_points").dump()) : Display("미기록"));
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
    for (const auto* key : {"frequencies", "theta_step_deg", "phi_step_deg", "box_clearance_mm"})
    {
        m_fields.at(key)->Enable(m_radiation->GetValue());
    }
    m_fields.at("max_relative_residual")->Enable(m_losses->GetValue());
    bool matches = false;
    try
    {
        matches = !m_view.empty() && (m_view.at("specification").contains("field_adaptive") || Draft() == m_view.at("specification"));
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
            names.Add(Display("수준 " + std::to_string(i) + " / 수준 " + std::to_string(i + 1) + " (" +
                              cases.at(i - 1).at("grid_mm").dump() + " mm / " + cases.at(i).at("grid_mm").dump() + " mm)"));
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
             StudioTheme::Table(*samples);
             const auto scale = StudioFrequency::ForSamples(result.at("rows"));
             samples->AppendColumn(Display("주파수 (" + scale.unit + ")"), wxLIST_FORMAT_RIGHT, FromDIP(155));
             samples->AppendColumn(Display("복소 S11 변화량"), wxLIST_FORMAT_RIGHT, FromDIP(155));
             samples->AppendColumn(Display("임피던스 변화 (ohm)"), wxLIST_FORMAT_RIGHT, FromDIP(165));
             samples->AppendColumn(Display("표본 기준"), wxLIST_FORMAT_LEFT, FromDIP(125));
             for (const auto& row : result.at("rows"))
             {
                 const long item = samples->InsertItem(samples->GetItemCount(),
                     Display(StudioFrequency::Value(row.at("frequency_hz"), scale, 9)));
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
