/** @file @brief 주 창의 solver 책임을 구현한다. */
#include "studio_internal.h"
#include "radiation_dialog.h"
#include "solver_review_dialog.h"

namespace
{
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
    m_solverRepairBack->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        if (m_solverRepairPending && GetMenuBar()->IsEnabled(IdRunSolver))
        {
            ApplyCurrent([this]() { ConfigureSolver(); });
        }
    });
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            ConfigureSolver();
        },
        IdRunSolver);
    Bind(wxEVT_MENU, [this](wxCommandEvent&)
    {
        if (!m_solverSamples.empty())
        {
            ConfigureSolver(m_solverSamples.at("artifact_id").get<std::string>());
        }
    }, IdReuseSolverConditions);
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

/** @brief 프로젝트의 저장 조건과 과거 결과 목록을 현재 검토에 연결한다. */
void StudioFrame::ConfigureSolver(const std::string& resultId)
{
    if (m_busy || !m_connected || !m_solverConfigured || m_project.empty() || m_solverWorkflow.Active() || m_solverRestoring)
    {
        return;
    }
    if (HasDraft())
    {
        Log("해석 검토 전에 현재 편집을 적용하거나 취소하세요.");
        return;
    }
    const auto project = m_project;
    const auto revision = m_revision;
    m_busy = true;
    UpdateControls();
    Send("solver.conditions", Json{{"expected_revision", revision}}, false, Context(),
        [this, project, revision, resultId](const Json& catalog)
        {
            CallAfter([this, project, revision, resultId, catalog]()
            {
                m_busy = false;
                const bool current = m_connected && !m_closing && m_project == project && m_revision == revision;
                if (current)
                {
                    m_solverRepairPending = false;
                }
                UpdateControls();
                if (current)
                {
                    OpenSolverReview(project, revision, catalog, resultId);
                }
            });
        },
        [this](const Json& error)
        {
            Failure("해석 조건 조회 실패. " + DiagnosticMessage(error));
        });
}

/** @brief 조건 저장은 프로젝트 개정에 반영하고 실행은 다시 검토한 입력으로 시작한다. */
void StudioFrame::OpenSolverReview(const std::string& project, const std::string& revision, const Json& catalog,
                                   const std::string& resultId)
{
    const auto decision = Studio::ShowSolverReview(this, revision, m_solverDraft, catalog, resultId,
        [this, project, revision](const char* method, const Json& input, auto accepted, auto rejected)
        {
            if (!m_connected || m_closing || m_project != project || m_revision != revision || HasDraft())
            {
                rejected(Json{{"message", "현재 개정 또는 서비스 연결이 바뀌었습니다. 다시 열어 검토하세요."}});
                return;
            }
            auto request = input;
            request["expected_revision"] = revision;
            Send(method, request, false, Context(), std::move(accepted), std::move(rejected));
        },
        [this](const std::string& path)
        {
            const auto target = DiagnosticSelection(path);
            if (target.is_null())
            {
                return false;
            }
            const std::string kind = target.at("kind");
            const std::string id = target.at("id");
            return kind == "material" || kind == "port" ||
                path == "stackup." + id + ".material_id" || path == "stackup." + id + ".thickness" ||
                path == "geometry." + id + ".material_ref";
        });
    if (!decision || !m_connected || m_closing || m_project != project || m_revision != revision || HasDraft())
    {
        return;
    }
    if (decision->repair)
    {
        const auto repair = *decision->repair;
        const auto target = DiagnosticSelection(repair.fieldPath);
        if (!target.is_null())
        {
            m_solverRepairPending = true;
            RefreshEditor(target, [this, repair]()
            {
                Ready("해석 오류의 속성으로 이동했습니다.");
                ShowDiagnosticField(repair.fieldPath, repair.message);
            });
        }
        return;
    }
    if (decision->saveName.empty())
    {
        m_solverSettings = decision->settings;
        StartSolver();
        return;
    }
    const bool clean = m_savedRevision == revision;
    m_busy = true;
    UpdateControls();
    Send("solver.conditions.save", Json{{"expected_revision", revision}, {"command_id", Uuid()},
                                       {"name", decision->saveName}, {"settings", decision->settings}}, true, Context(),
        [this, clean](const Json& result)
        {
            m_revision = result.at("new_revision").get<std::string>();
            RefreshEditor(m_selection, [this, clean]()
            {
                Ready("현재 프로젝트에 해석 조건을 추가했습니다.");
                if (clean)
                {
                    SaveProject();
                }
            });
        },
        [this](const Json& error)
        {
            Failure("해석 조건 저장 실패. " + DiagnosticMessage(error));
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
        }, [this, artifact = m_solverSamples.at("artifact_id").get<std::string>()](wxWindow* parent)
        {
            OpenSolverEvidence(artifact, parent);
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
                if (terminal.contains("execution_cost"))
                {
                    m_solverLastAttempt = terminal.at("execution_cost");
                    UpdateSolverView();
                }
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
            m_solverLastAttempt = response.value("last_attempt", Json::object());
            UpdateSolverView();
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
