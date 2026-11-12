/** @file @brief 주 창의 session 책임을 구현한다. */
#include "studio_internal.h"

void StudioFrame::Connect()
{
    if (m_closing || m_finishing)
    {
        return;
    }
    m_busy = true;
    UpdateControls();
    std::string error;
    if (!m_client.Start(m_options.python.ToStdWstring(), m_options.source.ToStdWstring(),
                        m_options.workspace.ToStdWstring(), error, m_options.cadPython.ToStdWstring(),
                        m_options.openEmsWsl, m_options.catalog.ToStdWstring()))
    {
        Failure(error, true);
        return;
    }
    Send("capabilities.get", Json::object(), false, Json::object(),
         [this](const Json& result)
         {
             if (!result.at("idempotency_policy").value("mutations_enabled", false))
             {
                 Failure("Service does not enable project mutations.", true);
                 return;
             }
             m_epoch = result.at("idempotency_policy").at("request_key_epoch").get<std::string>();
             m_connected = true;
             m_studySupported = result.value("methods", Json::object()).contains("study.context");
             m_targetsSupported = result.value("methods", Json::object()).contains("target.editor.get") &&
                                  result.value("methods", Json::object()).contains("target.editor.apply");
             m_templatesSupported = result.value("methods", Json::object()).contains("template.context") &&
                                    result.value("methods", Json::object()).contains("template.apply");
             m_pcbSelectionSupported = result.contains("pcb_selection_profile") &&
                                       result.value("methods", Json::object()).contains("pcb.selection.context");
             m_cadConfigured = result.value("cad_profile", Json::object()).value("runtime_configured", false);
             m_solverConfigured = result.value("solver_profile", Json::object()).value("runtime_configured", false);
             SolverStatus("idle", m_solverConfigured
                                      ? "WSL openEMS 준비됨. 물성 및 급전 위치를 명시한 설계를 사용합니다."
                                      : "해석 환경 미연결. launch_gui.ps1 -OpenEmsWsl로 실행하세요.");
             CadStatus(
                 "idle",
                 m_cadConfigured
                     ? "준비됨. STEP 출력은 현재 적용된 설계의 스냅샷을 사용합니다."
                     : "CAD 환경이 연결되지 않았습니다. launch_gui.ps1 -CadPython으로 CAD Python 경로를 지정하세요.");
             m_busy = false;
             SetStatusText(Display("준비됨"), 0);
             Log("프로젝트 서비스에 연결했습니다.");
             UpdateControls();
             m_smoke->OnConnected();
             if (!m_options.smoke && !m_options.openProject.empty())
             {
                 OpenProject("open", Utf8(m_options.openProject));
             }
         });
}

void StudioFrame::Send(const std::string& method, const Json& input, bool mutation, const Json& context,
                       std::function<void(const Json&)> success, std::function<void(const Json&)> failure)
{
    if (m_requests.Size() >= 16)
    {
        const Json error{{"code", "E_LIMIT"}, {"message", "요청 대기열이 가득 차 전송하지 않았습니다."}};
        if (failure)
        {
            failure(error);
        }
        else
        {
            m_busy = false;
            Log(error.at("message").get<std::string>());
            SetStatusText(Display("요청 미전송 / 진행 중인 작업 확인 후 다시 시도하세요."), 0);
            UpdateControls();
            if (m_options.smoke)
            {
                m_smoke->FinishSmoke(false, "GUI request queue is full.");
            }
        }
        return;
    }
    const bool foreground =
        method.rfind("target.editor.", 0) != 0 && method.rfind("template.", 0) != 0 &&
        method.rfind("catalog.", 0) != 0 && method.rfind("pcb.selection.", 0) != 0 && method.rfind("study.", 0) != 0 &&
        method != "cad.latest" && method != "solver.latest" && method != "solver.samples" && method != "result.open" &&
        method != "job.cancel" && method != "solver.plan" && method != "solver.prepare" && method != "job.submit" &&
        !(method == "snapshot.create" && input.value("description", "") == "GUI PCB 해석 입력") &&
        !(method == "job.status" &&
          (input.value("job_id", "") == m_cadTask.Id() || input.value("job_id", "") == m_solverTask.Id()));
    const auto submitted = m_requests.Submit(
        method, input, mutation, context, m_epoch, foreground, std::move(success), std::move(failure), Uuid,
        [this](const std::string& frame)
        {
            return m_client.Send(frame);
        },
        Clock::now());
    if (submitted == Studio::RequestDispatcher::SubmitResult::Full)
    {
        Failure("Unexpected concurrent GUI request queue overflow.", true);
    }
    else if (submitted == Studio::RequestDispatcher::SubmitResult::TransportClosed)
    {
        Failure("Cannot queue service request. No automatic retry is performed.", true);
    }
}

Json StudioFrame::Context() const
{
    return Json{{"project_id", m_project}};
}

void StudioFrame::WaitJob(const Json& task, std::function<void(const Json&)> completed)
{
    m_foregroundTask.Assign(task.at("job_id").get<std::string>());
    m_jobComplete = std::move(completed);
    SetStatusText(Display("작업 처리 중"), 0);
}

void StudioFrame::OnTimer(wxTimerEvent&)
{
    if ((m_finishing && !m_waitingClose) || m_restarting || m_closing)
    {
        return;
    }
    try
    {
        for (auto& incoming : m_client.Drain())
        {
            if (!incoming.protocol)
            {
                Log(incoming.text);
                continue;
            }
            const Json response = Json::parse(incoming.text);
            auto pending = m_requests.Take(response);
            if (!pending)
            {
                continue;
            }
            auto callback = std::move(pending->success);
            auto rejected = std::move(pending->failure);
            const bool foreground = pending->foreground;
            if (response.contains("error"))
            {
                const Json& error = response.at("error");
                std::string field;
                const Json data = error.value("data", Json::object());
                for (const auto& diagnostic : data.value("diagnostics", Json::array()))
                {
                    const Json details = diagnostic.value("details", Json::object());
                    field = details.value("field_path", std::string());
                    if (!field.empty())
                    {
                        break;
                    }
                }
                const std::string message = error.value("message", std::string("Service error"));
                if (foreground)
                {
                    m_busy = false;
                    UpdateControls();
                }
                const std::string readable = foreground ? m_editorPanel->ShowDiagnostic(field, message) : message;
                if (rejected)
                {
                    rejected(error);
                }
                else
                {
                    Failure(readable);
                }
                if (m_finishing || m_restarting || m_closing || !m_connected)
                {
                    return;
                }
                continue;
            }
            callback(response.at("result"));
            if (m_finishing || m_restarting || m_closing)
            {
                return;
            }
        }
        const std::string transportError = m_client.Error();
        if (!transportError.empty() && !m_transportFailed)
        {
            m_transportFailed = true;
            Failure(transportError, true);
            return;
        }
        const auto now = Clock::now();
        PollCad(now);
        PollSolver(now);
        m_smoke->CadSmokeTick();
        m_smoke->SolverSmokeTick();
        m_smoke->StudySmokeTick();
        m_smoke->PrimitivesSmokeTick();
        m_smoke->PcbSmokeTick();
        m_smoke->SetupSmokeTick();
        if (m_waitingClose &&
            ((!m_solverWorkflow.Active() && m_cadTask.Id().empty() && !m_cadPreparing) || now >= m_closeDeadline))
        {
            Close();
            return;
        }
        if (m_restarting || m_finishing)
        {
            return;
        }
        if (m_requests.Expired(now))
        {
            Failure("Service response timeout. Reopen and inspect durable state before resubmitting.", true);
            return;
        }
        if (m_foregroundTask.BeginPoll(now, std::chrono::milliseconds(100)))
        {
            const std::string job = m_foregroundTask.Id();
            Send(
                "job.status", Json{{"job_id", job}}, false, Json::object(),
                [this, job](const Json& result)
                {
                    if (!m_foregroundTask.EndPoll(job))
                    {
                        return;
                    }
                    const std::string state = result.at("state").get<std::string>();
                    if (state == "completed")
                    {
                        const Json finalResult = result.at("events").back().at("operation_result");
                        auto callback = std::move(m_jobComplete);
                        m_foregroundTask.Reset();
                        callback(finalResult);
                    }
                    else if (state == "failed" || state == "interrupted" || state == "cancelled")
                    {
                        Failure("작업이 완료되지 않았습니다: " + state + " / " + result.at("events").back().dump());
                    }
                },
                [this, job](const Json& error)
                {
                    if (m_foregroundTask.EndPoll(job))
                    {
                        Log("작업 상태 조회 실패: " + DiagnosticMessage(error));
                    }
                });
        }
        if (m_options.smoke &&
            now - m_started >
                std::chrono::seconds(
                    m_options.studySmoke
                        ? 1200
                        : (m_options.solverSmoke ? 600 : (m_options.cadSmoke || m_options.setupSmoke ? 180 : 60))))
        {
            m_smoke->FinishSmoke(false, "GUI smoke timeout");
        }
    }
    catch (const std::exception& error)
    {
        Failure(std::string("Protocol/UI error: ") + error.what(), true);
    }
}
