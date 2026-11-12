/** @file @brief 주 창의 solver 책임을 구현한다. */
#include "studio_internal.h"
#include "radiation_dialog.h"
#include "studio_theme.h"
#include <wx/wrapsizer.h>

/** @brief 해석 작업 상태와 결과 그래프를 기존 설계 탭과 분리하여 구성한다. */
void StudioFrame::BuildSolverInterface()
{
    auto* panel = new wxPanel(m_views);
    StudioTheme::BindSurface(*panel);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* tools = new wxWrapSizer(wxHORIZONTAL);
    AddTool(panel, tools, IdRunSolver, "설정 및 해석 실행");
    AddTool(panel, tools, IdCancelSolver, "해석 취소");
    m_recordRadiation = new wxCheckBox(panel, wxID_ANY, Display("NF2FF 기록"));
    tools->Add(m_recordRadiation, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(StudioTheme::Space));
    AddTool(panel, tools, IdRadiation, "방사 패턴 조회");
    AddTool(panel, tools, IdProjectStudy, "프로젝트 연구");
    layout->Add(tools, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::Space));
    m_solverMetric = new wxChoice(panel, wxID_ANY);
    for (const auto* name : {"S11 (dB)", "VSWR", "Z (ohm): Re / Im"})
    {
        m_solverMetric->Append(name);
    }
    m_solverMetric->SetSelection(0);
    layout->Add(m_solverMetric, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::InputGap));
    m_solverStatus = new wxStaticText(panel, wxID_ANY, Display("해석 환경 연결을 확인하고 있습니다."));
    layout->Add(m_solverStatus, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::InputGap));
    m_solverViewState =
        new wxStaticText(panel, wxID_ANY, Display("결과 없음 / 단일 포트 PCB 계산 / IFA 및 방사 정확도 검증 전"));
    StudioTheme::BindSecondary(*m_solverViewState);
    layout->Add(m_solverViewState, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(StudioTheme::InputGap));
    m_solverChart = new SolverChart(panel);
    layout->Add(m_solverChart, 1, wxEXPAND | wxALL, FromDIP(StudioTheme::Space));
    m_solverDetails = new wxTextCtrl(panel, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 110)),
                                     wxTE_MULTILINE | wxTE_READONLY);
    layout->Add(m_solverDetails, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::InputGap));
    panel->SetSizer(layout);
    m_views->AddPage(panel, Display("해석 결과"));
}

void StudioFrame::BindSolver()
{
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            ConfigureSolver();
        },
        IdRunSolver);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            CancelSolver();
        },
        IdCancelSolver);
    Bind(wxEVT_MENU, [this](wxCommandEvent&)
    {
        OpenRadiation();
    }, IdRadiation);
    m_solverMetric->Bind(wxEVT_CHOICE,
                         [this](wxCommandEvent& event)
                         {
                             m_solverChart->SetMetric(event.GetSelection());
                         });
}

/** @brief 해석 조건은 사용자가 확인한 입력이며 보드 물성을 대신 생성하지 않는다. */
void StudioFrame::ConfigureSolver()
{
    if (m_busy || !m_solverConfigured || m_project.empty() || m_solverWorkflow.Active() || m_solverRestoring)
    {
        return;
    }
    Json values = m_solverDraft;
    if (!AskNumbers("PCB 해석 조건 / 재료와 급전은 선택 속성에서 입력",
                    {{"start_hz", "시작 주파수 (Hz)", 2.4e9},
                     {"stop_hz", "끝 주파수 (Hz)", 2.4835e9},
                     {"count", "주파수 표본 수 (정수)", 101},
                     {"grid_mm", "최대 격자 간격 (mm)", 1.0},
                     {"air_padding_mm", "외부 공기 여유 (mm)", 30.0},
                     {"curve_tolerance_mm", "곡선 근사 허용오차 (mm)", 0.05},
                     {"max_timesteps", "최대 시간 단계 (정수)", 30000},
                     {"end_criterion", "종료 에너지 비율", 1e-5}},
                    values))
    {
        return;
    }
    for (const auto* key : {"count", "max_timesteps"})
    {
        const double value = values.at(key);
        if (value != std::floor(value) || value < 1 || value > 10000000)
        {
            wxMessageBox(Display("표본 수와 최대 시간 단계에는 양의 정수를 입력하세요."), Display("해석 조건"),
                         wxOK | wxICON_WARNING, this);
            return;
        }
    }
    m_solverDraft = values;
    m_solverSettings = Json{{"frequency_hz", Json{{"start", values.at("start_hz")},
                                                  {"stop", values.at("stop_hz")},
                                                  {"count", static_cast<int>(values.at("count").get<double>())}}},
                            {"grid_mm", values.at("grid_mm")},
                            {"air_padding_mm", values.at("air_padding_mm")},
                            {"curve_tolerance_mm", values.at("curve_tolerance_mm")},
                            {"max_timesteps", static_cast<int>(values.at("max_timesteps").get<double>())},
                            {"end_criterion", values.at("end_criterion")}};
    if (m_recordRadiation->GetValue())
    {
        Json radiation = m_radiationDraft;
        if (!AskNumbers("방사 기록 조건 / 계산 결과이며 제작 및 측정 검증 전",
                        {{"frequency_hz", "방사 계산 주파수 (Hz)", (values.at("start_hz").get<double>() + values.at("stop_hz").get<double>()) / 2},
                         {"theta_step_deg", "theta 간격 (5/10/15/30 deg)", 15},
                         {"phi_step_deg", "phi 간격 (5/10/15/30 deg)", 15}}, radiation))
        {
            return;
        }
        const std::vector<double> allowed = {5, 10, 15, 30};
        if (radiation.at("frequency_hz").get<double>() < values.at("start_hz").get<double>() ||
            radiation.at("frequency_hz").get<double>() > values.at("stop_hz").get<double>() ||
            std::find(allowed.begin(), allowed.end(), radiation.at("theta_step_deg").get<double>()) == allowed.end() ||
            std::find(allowed.begin(), allowed.end(), radiation.at("phi_step_deg").get<double>()) == allowed.end())
        {
            wxMessageBox(Display("방사 주파수는 해석 대역 안에, 각도 간격은 5/10/15/30 중에서 지정하세요."), Display("방사 조건"), wxOK | wxICON_WARNING, this);
            return;
        }
        m_radiationDraft = radiation;
        m_solverSettings["radiation"] = Json{{"frequency_hz", Json::array({radiation.at("frequency_hz")})},
                                             {"theta_step_deg", static_cast<int>(radiation.at("theta_step_deg").get<double>())},
                                             {"phi_step_deg", static_cast<int>(radiation.at("phi_step_deg").get<double>())}};
    }
    StartSolver();
}

void StudioFrame::OpenRadiation()
{
    if (m_solverSamples.empty() || !m_solverSamples.at("metadata").contains("radiation_summary"))
    {
        return;
    }
    const std::string project = m_project;
    auto* dialog = new RadiationDialog(this, m_solverSamples,
        m_solverSamples.at("snapshot").at("revision_id") != m_revision,
        [this, project](const Json& input, std::function<void(const Json&)> completed, std::function<void(const Json&)> rejected)
        {
            if (!m_connected || project != m_project || m_closing)
            {
                rejected(Json{{"message", "프로젝트 연결이 바뀌었습니다. 화면을 다시 여십시오."}});
                return;
            }
            Send("solver.radiation", input, false, Context(), std::move(completed), std::move(rejected));
        });
    dialog->Show();
}

void StudioFrame::SolverStatus(const std::string& state, const std::string& message)
{
    ShowWorkspaceJob(1, state, message);
    m_solverState = state;
    m_solverStatus->SetLabel(Display(message));
    m_solverStatus->GetParent()->Layout();
    m_solverDetails->AppendText(Display(state + ": " + message + "\n"));
    if (m_solverDetails->GetLastPosition() > 24000)
    {
        m_solverDetails->Remove(0, m_solverDetails->GetLastPosition() - 16000);
    }
}

/** @brief 스냅샷부터 해석까지 별도 작업으로 추적하여 편집과 저장을 계속 허용한다. */
void StudioFrame::StartSolver()
{
    if (m_busy || m_project.empty() || !m_solverConfigured || m_solverWorkflow.Active() || m_solverRestoring)
    {
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this]()
            {
                StartSolver();
            });
        return;
    }
    m_canvas->CancelGesture();
    const auto command = m_solverWorkflow.Begin(m_revision, m_solverSettings);
    m_views->SetSelection(2);
    SubmitSolverPhase(command);
}

void StudioFrame::SubmitSolverPhase(const Studio::ServiceCommand& command)
{
    const std::string phase = m_solverWorkflow.PhaseName();
    SolverStatus("accepting", phase + " 작업을 접수하고 있습니다. 입력은 스냅샷으로 고정됩니다.");
    UpdateControls();
    Send(
        command.method, command.input, true, Context(),
        [this](const Json& accepted)
        {
            m_solverTask.Assign(accepted.at("job_id").get<std::string>());
            SolverStatus("queued", m_solverWorkflow.PhaseName() + " 대기 중. 편집과 저장을 계속할 수 있습니다.");
            UpdateControls();
            if (m_solverWorkflow.CancellationRequested())
            {
                m_solverWorkflow.AllowCancelRetry();
                CancelSolver();
            }
        },
        [this](const Json& error)
        {
            SolverRejected(error);
        });
}

void StudioFrame::SolverRejected(const Json& error)
{
    m_solverWorkflow.Stop();
    m_solverTask.Reset();
    m_solverTask.AbandonPoll();
    SolverStatus("failed", "해석 실패: " + DiagnosticMessage(error));
    m_views->SetSelection(2);
    UpdateControls();
}

/** @brief 취소 요청 뒤에는 다음 단계로 자동 진행하지 않는다. */
void StudioFrame::CancelSolver()
{
    if (!m_solverWorkflow.CanRequestCancel())
    {
        return;
    }
    m_solverWorkflow.RequestCancel();
    SolverStatus("cancel_requested", "취소 요청 중. 실제 WSL worker 종료 확인을 기다립니다.");
    UpdateControls();
    if (!m_solverTask.Id().empty())
    {
        const std::string job = m_solverTask.Id();
        Send(
            "job.cancel", Json{{"job_id", job}, {"reason", "GUI 해석 작업 취소"}}, true, Json::object(),
            [](const Json&)
            {
            },
            [this, job](const Json& error)
            {
                if (m_solverTask.Id() != job || !m_solverWorkflow.Active())
                {
                    return;
                }
                m_solverWorkflow.AllowCancelRetry();
                SolverStatus("cancel_error", "취소 요청을 확인하지 못했습니다: " + DiagnosticMessage(error));
                UpdateControls();
            });
    }
}

void StudioFrame::PollSolver(Clock::time_point now)
{
    UpdateSolverView();
    if (!m_connected || !m_solverTask.BeginPoll(now, std::chrono::milliseconds(250)))
    {
        return;
    }
    const std::string job = m_solverTask.Id();
    Send(
        "job.status", Json{{"job_id", job}}, false, Json::object(),
        [this, job](const Json& status)
        {
            if (!m_solverTask.EndPoll(job))
            {
                return;
            }
            const std::string state = status.at("state");
            if (state == "completed")
            {
                m_solverTask.Reset();
                if (m_solverWorkflow.CancellationRequested())
                {
                    m_solverWorkflow.Stop();
                    SolverStatus("cancelled", "취소 요청 이후 단계 실행을 멈췄습니다. 기존 결과는 보존했습니다.");
                    UpdateControls();
                    return;
                }
                SolverPhaseComplete(status.at("events").back().at("operation_result"));
            }
            else if (state == "failed" || state == "cancelled" || state == "interrupted")
            {
                m_solverTask.Reset();
                m_solverWorkflow.Stop();
                const auto terminal = status.at("events").back();
                const std::string reason = DiagnosticMessage(terminal.value("error", Json::object()));
                SolverStatus(state, state == "cancelled" ? "해석이 취소되었습니다. 기존 결과는 보존했습니다."
                                                         : "해석 중단: " + reason +
                                                               (terminal.value("outcome_unknown", false)
                                                                    ? " / guest 종료 확인 필요, 자동 재실행하지 않음"
                                                                    : ""));
                UpdateControls();
            }
            else if (state != m_solverState)
            {
                SolverStatus(state, m_solverWorkflow.PhaseName() + " / " + state + " / 편집 및 저장 가능");
            }
        },
        [this, job](const Json& error)
        {
            if (!m_solverTask.EndPoll(job))
            {
                return;
            }
            SolverStatus("query_error", "해석 상태 조회 실패: " + DiagnosticMessage(error));
        });
}

void StudioFrame::SolverPhaseComplete(const Json& result)
{
    const auto next = m_solverWorkflow.Complete(result);
    if (next)
    {
        if (result.contains("analysis_plan"))
        {
            m_solverDetails->AppendText(
                Display("계획: " + result.at("analysis_plan").at("plan_id").get<std::string>() + "\n"));
        }
        SubmitSolverPhase(*next);
    }
    else
    {
        AcceptSolver(result, true);
    }
}

void StudioFrame::AcceptSolver(const Json& result, bool show)
{
    const std::string project = m_project;
    const std::string artifact = result.at("artifact_id");
    m_solverRestoring = true;
    UpdateControls();
    Send(
        "result.open", Json{{"artifact_id", artifact}}, false, Context(),
        [this, project, artifact, result, show](const Json& view)
        {
            if (project != m_project)
            {
                m_solverRestoring = false;
                return;
            }
            Send(
                "solver.samples", Json{{"artifact_id", artifact}}, false, Context(),
                [this, project, result, view, show](const Json& samples)
                {
                    m_solverRestoring = false;
                    if (project != m_project || samples.at("snapshot").at("project_id") != m_project)
                    {
                        throw std::runtime_error("해석 표시 결과가 선택 프로젝트와 다릅니다.");
                    }
                    m_solverChart->SetResult(samples);
                    m_solverSamples = samples;
                    m_solverResult = result;
                    SolverStatus("completed", "계산 결과를 열었습니다. 사용자 안테나의 물리 정확도 검증과 구분합니다.");
                    for (const auto& file : view.at("files"))
                    {
                        m_solverDetails->AppendText(Display(file.at("uri").get<std::string>() + "\n"));
                    }
                    if (show)
                    {
                        m_views->SetSelection(2);
                    }
                    UpdateSolverView();
                    UpdateControls();
                },
                [this](const Json& error)
                {
                    m_solverRestoring = false;
                    SolverRejected(error);
                });
        },
        [this](const Json& error)
        {
            m_solverRestoring = false;
            SolverRejected(error);
        });
}

void StudioFrame::RestoreSolver()
{
    m_solverRestoring = true;
    Send(
        "solver.latest", Json::object(), false, Context(),
        [this](const Json& response)
        {
            m_solverRestoring = false;
            if (response.contains("result") && !response.at("result").is_null())
            {
                AcceptSolver(response.at("result"), false);
            }
            UpdateControls();
        },
        [this](const Json& error)
        {
            m_solverRestoring = false;
            Log("이전 해석 결과 조회 실패: " + DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::UpdateSolverView()
{
    if (m_solverSamples.empty())
    {
        return;
    }
    const bool stale = m_solverSamples.at("snapshot").at("revision_id") != m_revision;
    const std::string label = (stale ? "이전 설계의 결과 / " : "현재 적용 설계의 결과 / ") +
                              std::to_string(m_solverChart->SampleCount()) + "개 주파수 / IFA 및 NF2FF 정확도 검증 전";
    if (m_solverViewState->GetLabel() != Display(label))
    {
        m_solverViewState->SetLabel(Display(label));
    }
}
