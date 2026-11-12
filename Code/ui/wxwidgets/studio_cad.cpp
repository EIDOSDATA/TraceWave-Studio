/** @file @brief 주 창의 cad 책임을 구현한다. */
#include "studio_internal.h"

/** @brief CAD는 별도 작업으로 추적하여 편집/저장 작업의 callback을 보존한다. */
void StudioFrame::BindCad()
{
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            StartCad(true);
        },
        IdExportStep);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            StartCad(false);
        },
        IdBuild3D);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            CancelCad();
        },
        IdCancelCad);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            m_modelView->FitView();
        },
        IdFit3D);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            m_modelView->SetView("top");
        },
        IdTop3D);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            m_modelView->SetView("isometric");
        },
        IdIso3D);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (m_cadResult.empty())
            {
                return;
            }
            for (const auto& artifact : m_cadResult.at("artifacts"))
            {
                if (artifact.value("role", "") == "step")
                {
                    const auto relative = std::filesystem::u8path(artifact.at("uri").get<std::string>());
                    if (relative.is_absolute() || relative.has_root_name())
                    {
                        throw std::runtime_error("Invalid STEP artifact path.");
                    }
                    for (const auto& part : relative)
                    {
                        if (part == "..")
                        {
                            throw std::runtime_error("Invalid STEP artifact path.");
                        }
                    }
                    const auto directory =
                        std::filesystem::path(m_options.workspace.ToStdWstring()) / relative.parent_path();
                    if (!wxLaunchDefaultApplication(wxString(directory.wstring())))
                    {
                        CadStatus(m_cadState, "출력 폴더를 열 수 없습니다. CAD 출력 기록의 경로를 확인하세요.");
                    }
                    return;
                }
            }
        },
        IdOutputFolder);
    m_modelView->onStatus = [this](const std::string& message)
    {
        m_modelHint->SetLabel(Display(message));
    };
    m_modelView->onSelection = [this](const std::string& identity)
    {
        if (m_busy)
        {
            m_modelView->SetSelection(m_selection.value("id", ""));
            return;
        }
        if (m_displayResult.empty() || m_displayResult.at("snapshot").at("revision_id") != m_revision)
        {
            m_modelHint->SetLabel(Display("이전 결과의 선택은 현재 설계에 적용하지 않습니다. 3D를 갱신하세요."));
            return;
        }
        if (!ConfirmDiscard())
        {
            m_modelView->SetSelection(m_selection.value("id", ""));
            return;
        }
        if (identity.empty())
        {
            SelectObject(Json{{"kind", "project"}, {"id", m_project}});
            return;
        }
        for (const auto& item : m_editor.value("items", Json::array()))
        {
            if (item.value("id", "") == identity)
            {
                SelectObject(Json{{"kind", item.at("kind")}, {"id", identity}});
                return;
            }
        }
    };
}

/** @brief 완료 상태와 입력 개정, 출력 위치를 사용자가 확인할 수 있게 유지한다. */
void StudioFrame::CadStatus(const std::string& state, const std::string& message)
{
    ShowWorkspaceJob(0, state, message);
    m_cadState = state;
    m_cadStatus->SetLabel(Display(message));
    m_cadStatus->SetToolTip(Display(message));
    m_cadStatus->Wrap(std::max(FromDIP(220), m_bottom->GetClientSize().GetWidth() - FromDIP(260)));
    m_cadDetails->ChangeValue(Display(message));
    m_cadStatus->GetParent()->Layout();
    Log(message);
}

/** @brief 파일에 기록된 입력과 현재 편집 개정을 구분하며 이전 형상을 숨기지 않는다. */
void StudioFrame::UpdateModelState()
{
    if (!m_cadResult.empty() &&
        m_modelView->LoadedSnapshotId() == m_cadResult.at("snapshot").value("snapshot_id", "") &&
        (m_displayResult.empty() ||
         m_displayResult.at("snapshot").at("snapshot_id") != m_cadResult.at("snapshot").at("snapshot_id")))
    {
        m_displayResult = m_cadResult;
    }
    std::string text = "아직 생성한 3D 형상이 없습니다. 층 위치와 두께를 입력한 뒤 갱신하세요.";
    if (!m_displayResult.empty())
    {
        const auto& snapshot = m_displayResult.at("snapshot");
        const std::string revision = snapshot.at("revision_id");
        const bool stale = revision != m_revision;
        text = std::string(stale ? "이전 설계의 형상 - 3D 갱신 필요" : "현재 적용된 설계의 형상") + " / " +
               std::to_string(m_modelView->TriangleCount()) + "개 삼각형 / 실제 두께";
        m_modelState->SetToolTip(
            Display("입력 설계 버전: " + revision + "\n스냅샷: " + snapshot.at("snapshot_id").get<std::string>()));
    }
    if (m_modelView->IsLoading())
    {
        text = "새 3D 파일 확인 중 / " + text;
    }
    if (HasDraft())
    {
        text += " / 미적용 입력은 아직 포함되지 않음";
    }
    if (m_modelState->GetLabel() != Display(text))
    {
        m_modelState->SetLabel(Display(text));
    }
}

/** @brief 적용 후 불변 스냅샷을 접수하고 native 작업 중에는 편집 잠금을 해제한다. */
void StudioFrame::StartCad(bool step)
{
    if (m_busy || m_project.empty() || !m_cadConfigured || m_cadPreparing || m_cadRestoring ||
        !m_cadTask.Id().empty() || m_modelView->IsLoading())
    {
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this, step]()
            {
                StartCad(step);
            });
        return;
    }
    m_canvas->CancelGesture();
    m_cadPreparing = true;
    m_cadCancelRequested = false;
    m_busy = true;
    m_bottom->SetSelection(2);
    CadStatus("preparing", "출력 입력을 스냅샷으로 고정하고 있습니다.");
    UpdateControls();
    Send(
        "snapshot.create", Json{{"expected_revision", m_revision}, {"description", "GUI CAD 출력 입력"}}, true,
        Context(),
        [this, step](const Json& task)
        {
            WaitJob(task,
                    [this, step](const Json& snapshot)
                    {
                        m_snapshot = snapshot.at("snapshot_id");
                        m_cadSnapshot = snapshot;
                        if (m_cadCancelRequested)
                        {
                            m_cadPreparing = false;
                            CadStatus("cancelled", "CAD 실행 전 취소했습니다. 기존 출력은 보존했습니다.");
                            Ready("출력 준비를 취소했습니다.");
                            return;
                        }
                        Json input{{"snapshot", Json{{"snapshot_id", snapshot.at("snapshot_id")},
                                                     {"content_hash", snapshot.at("content_hash")}}},
                                   {"profile", "rfad.step.mechanical/0.1"}};
                        input[step ? "format" : "projection_kind"] = step ? "step" : "brep";
                        Send(
                            step ? "export.build" : "geometry.build", input, true, Context(),
                            [this](const Json& accepted)
                            {
                                m_cadTask.Assign(accepted.at("job_id").get<std::string>());
                                m_cadPreparing = false;
                                CadStatus("queued", "CAD 작업 대기 중. 편집과 저장을 계속할 수 있습니다.");
                                Ready("고정된 스냅샷으로 CAD 작업을 접수했습니다.");
                                if (m_cadCancelRequested)
                                {
                                    m_cadCancelRequested = false;
                                    CancelCad();
                                }
                            },
                            [this](const Json& error)
                            {
                                CadRejected(error);
                            });
                    });
        },
        [this](const Json& error)
        {
            CadRejected(error);
        });
}

/** @brief 접수 실패를 기존 정상 출력과 분리하여 사용자에게 알린다. */
void StudioFrame::CadRejected(const Json& error)
{
    m_cadPreparing = false;
    m_cadTask.Reset();
    m_cadTask.AbandonPoll();
    m_busy = false;
    CadStatus("failed", "CAD 출력 실패: " + error.value("message", std::string("입력을 확인하세요.")));
    m_bottom->SetSelection(2);
    UpdateControls();
}

/** @brief 취소 요청과 실제 프로세스 종료를 구분하여 완료 상태를 기다린다. */
void StudioFrame::CancelCad()
{
    if (m_cadCancelRequested || (!m_cadPreparing && m_cadTask.Id().empty()))
    {
        return;
    }
    m_cadCancelRequested = true;
    CadStatus("cancel_requested", "취소 요청 중. worker 종료 확인을 기다립니다.");
    UpdateControls();
    if (!m_cadTask.Id().empty())
    {
        const std::string job = m_cadTask.Id();
        Send(
            "job.cancel", Json{{"job_id", job}, {"reason", "GUI 사용자 취소"}}, true, Json::object(),
            [](const Json&)
            {
            },
            [this, job](const Json& error)
            {
                if (m_cadTask.Id() != job)
                {
                    return;
                }
                m_cadCancelRequested = false;
                CadStatus(m_cadState, "취소 요청 오류: " + error.value("message", ""));
                UpdateControls();
            });
    }
}

/** @brief 재열기 때 게시 완료된 동일 프로젝트의 마지막 결과만 복원한다. */
void StudioFrame::RestoreCad()
{
    m_cadRestoring = true;
    const std::string project = m_project;
    Send(
        "cad.latest", Json::object(), false, Context(),
        [this, project](const Json& response)
        {
            m_cadRestoring = false;
            if (m_project == project && response.contains("result") && !response.at("result").is_null() &&
                m_cadTask.Id().empty() && !m_cadPreparing)
            {
                AcceptCad(response.at("result"), false);
            }
            UpdateControls();
        },
        [this](const Json& error)
        {
            m_cadRestoring = false;
            Log("이전 CAD 결과 조회 실패: " + error.value("message", ""));
            UpdateControls();
        });
}

/** @brief 작은 참조만 GUI로 받아 파일 읽기와 hash 검사를 3D loader에 맡긴다. */
void StudioFrame::AcceptCad(const Json& result, bool show)
{
    if (result.at("snapshot").at("project_id") != m_project || result.value("status", "") != "generated_unverified")
    {
        throw std::runtime_error("CAD output is not bound to this project.");
    }
    m_cadResult = result;
    std::string listing =
        "STEP 생성 완료 / 제조 및 RF 검증 전\n입력 설계: " + result.at("snapshot").at("revision_id").get<std::string>();
    for (const auto& artifact : result.at("artifacts"))
    {
        listing += "\n" + artifact.at("uri").get<std::string>();
        if (artifact.value("role", "") == "display_mesh")
        {
            if (m_modelView->LoadArtifact(m_options.workspace, artifact, result.at("snapshot"),
                                          artifact.at("run_id").get<std::string>()))
            {
                m_modelWasLoading = true;
            }
            else
            {
                m_modelHint->SetLabel(
                    Display("3D 파일 읽기를 시작하지 못했습니다. STEP 출력 파일은 보존되어 있습니다."));
            }
        }
    }
    CadStatus("completed", "STEP 패키지를 생성했습니다. 출력 폴더에서 파일을 확인하세요.");
    m_cadDetails->ChangeValue(Display(listing));
    if (show || m_modelView->IsLoading())
    {
        m_views->SetSelection(1);
    }
    UpdateControls();
}

/** @brief CAD 상태는 제한된 주기로 읽고 일반 편집 응답과 별도로 처리한다. */
void StudioFrame::PollCad(Clock::time_point now)
{
    const bool loading = m_modelView->IsLoading();
    if (m_modelWasLoading != loading)
    {
        m_modelWasLoading = loading;
        UpdateControls();
    }
    UpdateModelState();
    if (!m_connected || !m_cadTask.BeginPoll(now, std::chrono::milliseconds(200)))
    {
        return;
    }
    const std::string job = m_cadTask.Id();
    Send(
        "job.status", Json{{"job_id", job}}, false, Json::object(),
        [this, job](const Json& status)
        {
            if (!m_cadTask.EndPoll(job))
            {
                return;
            }
            const std::string state = status.at("state");
            if (state == "completed")
            {
                m_cadTask.Reset();
                AcceptCad(status.at("events").back().at("operation_result"), true);
            }
            else if (state == "failed" || state == "cancelled" || state == "interrupted")
            {
                m_cadTask.Reset();
                const Json terminal = status.at("events").back();
                const std::string error = terminal.value("error", Json::object()).value("message", "");
                CadStatus(state, state == "cancelled"
                                     ? "CAD 작업이 취소되었습니다. 기존 출력은 보존했습니다."
                                     : "CAD 작업 중단: " + error +
                                           (terminal.value("outcome_unknown", false) ? " / 이전 실행 확인 필요" : ""));
                UpdateControls();
            }
            else if (state != m_cadState)
            {
                CadStatus(state, state == "cancel_requested" ? "취소 요청을 처리하고 있습니다."
                                                             : "CAD 형상 및 STEP 생성 중. 편집과 저장이 가능합니다.");
            }
        },
        [this, job](const Json& error)
        {
            if (!m_cadTask.EndPoll(job))
            {
                return;
            }
            CadStatus("query_error", "CAD 상태 조회 실패: " + error.value("message", ""));
        });
}
