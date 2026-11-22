/** @file @brief 주 창의 solver 책임을 구현한다. */
#include "studio_internal.h"
#include "radiation_dialog.h"
#include "studio_theme.h"
#include <wx/display.h>

namespace
{
/** @brief 종료·출력과 같은 계획의 자원값을 분리해 명시적인 실행 전 검토를 표시한다. */
bool ConfirmSolverPreview(wxWindow* parent, const Json& preview, const Json& scene, bool canRun)
{
    wxDialog dialog(parent, wxID_ANY, Display("해석 전 검토 / 메시와 기록"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    dialog.SetName("solver.preview.dialog");
    StudioTheme::ApplyTypography(dialog);
    StudioTheme::BindSurface(dialog);
    const int pad = dialog.FromDIP(StudioTheme::PanelPadding);
    auto* root = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(&dialog, wxID_ANY, Display("해석 입력과 출력 범위"));
    StudioTheme::Title(*title);
    root->Add(title, 0, wxLEFT | wxTOP, pad);
    auto* revision = new wxStaticText(&dialog, wxID_ANY,
        Display("검토한 개정  " + preview.at("revision_id").get<std::string>()));
    StudioTheme::BindSecondary(*revision);
    root->Add(revision, 0, wxEXPAND | wxALL, pad);
    auto* tabs = new StudioNotebook(&dialog);
    root->Add(tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, pad);
    const auto page = [&](const char* label)
    {
        auto* value = new wxPanel(tabs);
        StudioTheme::BindSurface(*value);
        value->SetSizer(new wxBoxSizer(wxVERTICAL));
        tabs->AddPage(value, Display(label));
        return value;
    };
    const auto info = [&](wxPanel* control, const std::string& label, const wxString& value)
    {
        auto* heading = new wxStaticText(control, wxID_ANY, Display(label));
        StudioTheme::Heading(*heading);
        control->GetSizer()->Add(heading, 0, wxLEFT | wxTOP, pad);
        auto* body = new wxStaticText(control, wxID_ANY, value);
        body->Wrap(dialog.FromDIP(590));
        control->GetSizer()->Add(body, 0, wxEXPAND | wxALL, pad);
    };
    auto* resource = page("메시 / 자원");
    const auto& settings = preview.at("settings");
    const auto estimate = preview.value("estimated", Json::object());
    info(resource, "격자 설정",
         wxString::Format(Display("최대 격자 간격 %.8g mm / 공기 여유 %.8g mm"),
                          settings.at("grid_mm").get<double>(), settings.at("air_padding_mm").get<double>()));
    if (!estimate.empty())
    {
        const auto count = estimate.at("estimated_grid_points").get<unsigned long long>();
        const double memory = estimate.at("estimated_memory_bytes").get<double>() / (1024.0 * 1024.0);
        info(resource, "계획에서 예상한 자원",
             wxString::Format(Display("격자 규모 %llu / 메모리 약 %.1f MiB. 준비된 실제 메시와 실행 실측은 별도입니다."),
                              count, memory));
    }
    else
    {
        info(resource, "자원 추정 보류", Display(preview.value("error", std::string())));
    }
    auto* geometry = new DesignCanvas(resource);
    geometry->SetEditingEnabled(false);
    geometry->SetScene(scene);
    resource->GetSizer()->Add(geometry, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    auto* geometryLabel = new wxStaticText(resource, wxID_ANY, Display("입력 형상 참고 / 아래 격자는 설계 눈금입니다."));
    StudioTheme::BindSecondary(*geometryLabel);
    resource->GetSizer()->Add(geometryLabel, 0, wxLEFT | wxBOTTOM, pad);

    auto* output = page("종료 / 기록 출력");
    info(output, "종료 기준",
         wxString::Format(Display("최대 %d 시간 단계 / 종료 에너지 비율 %.8g"),
                          settings.at("max_timesteps").get<int>(), settings.at("end_criterion").get<double>()));
    info(output, "기본 결과", Display("기록된 복소 표본, 원본 개정과 해석 조건을 보존합니다."));
    info(output, "방사 기록", Display(settings.contains("radiation") ? "NF2FF 기록 사용" : "NF2FF 기록 끔"));
    info(output, "독립 손실 기록",
         Display(settings.contains("power_balance") ? "전력 평형 기록 사용" : "이 조건에서는 독립 손실 기록을 요청하지 않았습니다."));
    info(output, "내부 전계 / 자계", Display("현재 기본 PCB 실행은 내부 필드를 자동 기록하지 않습니다. 보존한 필드 자료는 결과에서 조회합니다."));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    actions->AddStretchSpacer();
    auto* cancel = new wxButton(&dialog, wxID_CANCEL, Display("닫기"));
    StudioTheme::Button(*cancel);
    actions->Add(cancel, 0, wxALIGN_CENTER_VERTICAL);
    auto* run = new wxButton(&dialog, wxID_OK, Display("검토한 조건으로 실행"));
    StudioTheme::Button(*run, true);
    run->Enable(canRun);
    actions->Add(run, 0, wxALIGN_CENTER_VERTICAL | wxLEFT, pad);
    root->Add(actions, 0, wxEXPAND | wxALL, pad);
    dialog.SetSizer(root);
    const auto area = wxDisplay(parent).GetClientArea().Deflate(dialog.FromDIP(12));
    const auto ideal = dialog.FromDIP(wxSize(820, 660));
    dialog.SetSize(std::min(ideal.x, area.width), std::min(ideal.y, area.height));
    dialog.CentreOnParent();
    dialog.Layout();
    geometry->FitView();
    return dialog.ShowModal() == wxID_OK && canRun;
}

/** @brief 서비스의 내부 단계 이름을 긴 작업 설명과 분리한다. */
std::string PhaseLabel(const std::string& phase)
{
    if (phase == "snapshot")
    {
        return "설계 스냅샷";
    }
    if (phase == "plan")
    {
        return "해석 계획";
    }
    if (phase == "prepare")
    {
        return "계산 입력 준비";
    }
    return "해석";
}

/** @brief 승인을 기다리는 상태와 실제 계산, 저장 가능한 상태를 구분해 표시한다. */
std::string ProgressLabel(const std::string& phase, const std::string& state)
{
    if (state == "postprocessing")
    {
        return "해석 결과를 정리 중입니다. 편집과 저장을 계속할 수 있습니다.";
    }
    if (state == "cancel_requested")
    {
        return "취소를 요청했습니다. 작업 종료를 확인하고 있습니다.";
    }
    if (state == "preparing")
    {
        return PhaseLabel(phase) + " 작업을 준비 중입니다.";
    }
    if (state == "running")
    {
        return PhaseLabel(phase) + " 중입니다. 편집과 저장을 계속할 수 있습니다.";
    }
    return PhaseLabel(phase) + " 작업 상태를 확인하고 있습니다.";
}
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
    if (HasDraft())
    {
        Log("해석 검토 전에 현재 편집을 적용하거나 취소하세요.");
        return;
    }
    Json values = m_solverDraft;
    if (!AskNumbers("PCB 해석 조건",
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
    Json settings{{"frequency_hz", Json{{"start", values.at("start_hz")},
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
        settings["radiation"] = Json{{"frequency_hz", Json::array({radiation.at("frequency_hz")})},
                                             {"theta_step_deg", static_cast<int>(radiation.at("theta_step_deg").get<double>())},
                                             {"phi_step_deg", static_cast<int>(radiation.at("phi_step_deg").get<double>())}};
    }
    const auto project = m_project;
    const auto revision = m_revision;
    const auto preview = [this, project, revision, settings](const Json& result, bool canRun)
    {
        CallAfter([this, project, revision, settings, result, canRun]()
        {
            if (m_closing || !m_connected || m_project != project || m_revision != revision || HasDraft())
            {
                return;
            }
            if (ConfirmSolverPreview(this, result, m_scene, canRun) && m_revision == revision && !HasDraft())
            {
                m_solverSettings = settings;
                StartSolver();
            }
        });
    };
    Send("solver.preview", Json{{"expected_revision", revision}, {"settings", settings}}, false, Context(),
         [preview, revision](const Json& result)
         {
             if (result.at("revision_id") == revision)
             {
                 preview(result, true);
             }
         },
         [preview, revision, settings](const Json& error)
         {
             preview(Json{{"revision_id", revision}, {"settings", settings}, {"error", DiagnosticMessage(error)}}, false);
         });
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
    SolverStatus("accepting", PhaseLabel(phase) + " 작업을 접수 중입니다.");
    UpdateControls();
    Send(
        command.method, command.input, true, Context(),
        [this](const Json& accepted)
        {
            m_solverTask.Assign(accepted.at("job_id").get<std::string>());
            SolverStatus("queued", PhaseLabel(m_solverWorkflow.PhaseName()) + " 작업이 대기 중입니다.");
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
    // @brief 후속 상태·표 레이아웃보다 실제 취소 제어와 접수를 먼저 처리한다.
    m_tools.at(IdCancelSolver)->Disable();
    GetMenuBar()->Enable(IdCancelSolver, false);
    if (!m_solverTask.Id().empty())
    {
        const std::string job = m_solverTask.Id();
        if (m_options.solverSmoke)
        {
            m_smoke->RecordSolverCancellation(job, "control", Json{{"state", "cancel_requested"},
                {"button_enabled", m_tools.at(IdCancelSolver)->IsEnabled()}});
        }
        Send(
            "job.cancel", Json{{"job_id", job}, {"reason", "GUI 해석 작업 취소"}}, true, Json::object(),
            [this, job](const Json& result)
            {
                if (m_options.solverSmoke && result.value("job_id", "") == job)
                {
                    m_smoke->RecordSolverCancellation(job, "receipt", Json{{"state", result.at("state")},
                        {"events_cursor", result.at("events_cursor")}});
                }
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
    if (m_connected && m_solverWorkflow.CancellationRequested())
    {
        SolverStatus("cancel_requested", "취소 요청 중. 실제 WSL worker 종료 확인을 기다립니다.");
        UpdateControls();
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
            if (m_options.solverActiveCancelSmoke && status.value("guest_worker_attached", false))
            {
                m_smoke->ObserveSolverGuest(job);
            }
            if (m_options.solverSmoke && (state == "completed" || state == "failed" || state == "cancelled" ||
                                          state == "interrupted"))
            {
                const auto& terminal = status.at("events").back();
                m_smoke->RecordSolverCancellation(job, "terminal", Json{{"state", state},
                    {"events_cursor", status.at("events_cursor")},
                    {"termination_confirmed", terminal.value("termination_confirmed", Json(nullptr))},
                    {"outcome_unknown", terminal.value("outcome_unknown", Json(nullptr))}});
            }
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
                                                                    ? " WSL 작업 종료를 확인해 주세요."
                                                                    : ""));
                UpdateControls();
            }
            else if (state != m_solverState)
            {
                SolverStatus(state, ProgressLabel(m_solverWorkflow.PhaseName(), state));
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
            Log("해석 계획 ID: " + result.at("analysis_plan").at("plan_id").get<std::string>());
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
                    SolverStatus("completed", "해석 결과를 열었습니다.");
                    for (const auto& file : view.at("files"))
                    {
                        Log("해석 결과 파일: " + file.at("uri").get<std::string>());
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
