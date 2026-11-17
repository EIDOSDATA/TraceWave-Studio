/** @file @brief 원본 개정을 유지한 채 후보 채택과 새 프로젝트 열기를 연결한다. */
#include "studio_internal.h"
#include "sweep_panel.h"
#include "sweep_selection_dialog.h"
#include "sweep_selection_model.h"
#include "sweep_selection_recovery.h"

void StudioFrame::OpenSweepSelection(int index)
{
    if (!m_connected || !m_sweepSelectionSupported || m_closing || m_busy || m_sweepPending || m_setupDialog ||
        m_sweepPanel->StudyId().empty())
    {
        return;
    }
    if (HasDraft())
    {
        m_sweepPanel->SetStatus("현재 편집 초안이 있습니다. 후보 채택은 원본에 초안을 자동 적용하지 않습니다. 초안을 "
                                "명시적으로 적용하거나 취소한 뒤 다시 여세요.");
        return;
    }
    const auto project = m_project;
    const auto revision = m_revision;
    try
    {
        const auto recovery = SweepSelectionStore::Read(Utf8(m_options.workspace), project);
        if (recovery->uncertain)
        {
            m_busy = true;
            UpdateControls();
            CallAfter(
                [this, project, recovery]()
                {
                    if (!m_closing && m_connected && project == m_project)
                    {
                        ShowSweepSelection(recovery->context);
                    }
                    else if (!m_closing)
                    {
                        m_busy = false;
                        UpdateControls();
                    }
                });
            return;
        }
    }
    catch (const std::exception& error)
    {
        m_sweepPanel->SetStatus(error.what());
        return;
    }
    m_busy = true;
    UpdateControls();
    Send(
        "sweep.selection.context", {{"study_id", m_sweepPanel->StudyId()}, {"index", index}}, false, Context(),
        [this, project, revision](const Json& context)
        {
            CallAfter(
                [this, project, revision, context]()
                {
                    if (!m_closing && m_connected && project == m_project && revision == m_revision &&
                        context.at("project_id") == project && context.at("revision_id") == revision)
                    {
                        ShowSweepSelection(context);
                    }
                    else if (!m_closing)
                    {
                        m_busy = false;
                        UpdateControls();
                    }
                });
        },
        [this](const Json& error)
        {
            m_busy = false;
            m_sweepPanel->SetStatus(DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::ShowSweepSelection(const Json& context)
{
    try
    {
        const std::string project = context.at("project_id");
        const std::string workspace = Utf8(m_options.workspace);
        auto recovery = SweepSelectionStore::Read(workspace, project);
        const Json originalContext = recovery->uncertain ? recovery->context : context;
        recovery->context = originalContext;
        DialogGateway gateway = [this, project, workspace, recovery](
                                    const std::string& method, const Json& input, bool mutation,
                                    std::function<void(const Json&)> success, std::function<void(const Json&)> failure)
        {
            if (m_closing || !m_connected || m_project != project)
            {
                failure({{"code", "E_DISCONNECTED"},
                         {"message", "서비스 연결을 확인할 수 없습니다. 화면을 닫고 같은 프로젝트에 다시 연결한 뒤 "
                                     "생성 결과를 확인하세요."}});
                return;
            }
            if (method == "sweep.selection.apply")
            {
                if (recovery->uncertain || recovery->response.is_object())
                {
                    failure({{"code", "E_UNCERTAIN"},
                             {"message", "이전 요청의 결과 확인 전에는 새로운 생성 요청을 보내지 않습니다."}});
                    return;
                }
                recovery->requestKey = Uuid();
                recovery->epoch = m_epoch;
                recovery->input = input;
                recovery->uncertain = true;
                try
                {
                    SweepSelectionStore::Write(workspace, project, *recovery);
                }
                catch (const std::exception& error)
                {
                    recovery->uncertain = false;
                    failure({{"code", "E_RESOURCE"}, {"message", error.what()}});
                    return;
                }
            }
            const auto accept = [recovery](const Json& result)
            {
                if (!SweepSelectionUi::MatchesCopy(result, recovery->context) || !recovery->input.is_object() ||
                    result.value("path", Json(nullptr)) != recovery->input.value("path", Json(nullptr)))
                {
                    throw std::runtime_error("원본과 후보가 다른 생성 응답입니다. 보존 요청의 확인 잠금을 유지합니다.");
                }
                recovery->response = result;
                recovery->uncertain = false;
            };
            Send(
                method, input, mutation, {{"project_id", project}},
                [method, accept, success, failure](const Json& result)
                {
                    try
                    {
                        if (method == "sweep.selection.apply")
                        {
                            accept(result);
                        }
                        else if (method == "sweep.selection.receipt" && result.value("authoritative", false) &&
                                 result.value("status", "") == "found" &&
                                 result.value("response", Json(nullptr)).is_object())
                        {
                            accept(result.at("response"));
                        }
                    }
                    catch (const std::exception& error)
                    {
                        failure({{"code", "E_UNCERTAIN"}, {"message", error.what()}});
                        return;
                    }
                    success(result);
                },
                [this, method, project, workspace, recovery, failure](const Json& error)
                {
                    if (method == "sweep.selection.apply" && SweepSelectionUi::Rejected(error))
                    {
                        try
                        {
                            SweepSelectionStore::Clear(workspace, project);
                            recovery->uncertain = false;
                        }
                        catch (const std::exception& clearError)
                        {
                            Log(clearError.what());
                        }
                    }
                    failure(error);
                },
                method == "sweep.selection.apply" ? recovery->requestKey : "",
                method == "sweep.selection.apply" ? recovery->epoch : "");
        };
        auto dialog = std::make_unique<SweepSelectionDialog>(this, originalContext, gateway, recovery);
        m_setupDialog = dialog.get();
        m_canvas->CancelGesture();
        UpdateControls();
        dialog->ShowModal();
        const auto result = dialog->GetAppliedResult();
        const bool open = dialog->OpenRequested();
        if (!open && result.is_object() && SweepSelectionUi::MatchesCopy(result, originalContext))
        {
            try
            {
                // @brief 성공 결과를 확인하고 명시적으로 닫은 뒤에만 복구 키를 회수한다.
                SweepSelectionStore::Clear(workspace, project);
            }
            catch (const std::exception& error)
            {
                Log(error.what());
            }
        }
        m_setupDialog = nullptr;
        m_busy = false;
        if (m_closeAfterSetup)
        {
            const bool force = m_forceCloseAfterSetup;
            m_closeAfterSetup = false;
            m_forceCloseAfterSetup = false;
            CallAfter(
                [this, force]()
                {
                    Close(force);
                });
            return;
        }
        UpdateControls();
        if (open && m_connected && !m_closing && m_project == project &&
            SweepSelectionUi::MatchesCopy(result, originalContext))
        {
            m_views->SetSelection(0);
            m_sweepPanel->SetStatus(
                "새 사본 생성 완료 / 명시 열기 요청 중입니다. 열기가 실패해도 다시 생성하지 않습니다. 생성 위치: " +
                result.at("path").get<std::string>());
            OpenProject("open", result.at("path").get<std::string>(), "",
                        [this, project, workspace, result]()
                        {
                            if (m_project != result.at("new_project_id") || m_path != result.at("path"))
                            {
                                Log("생성한 사본과 열린 프로젝트가 달라 복구 키를 유지합니다.");
                                return;
                            }
                            try
                            {
                                // @brief 새 프로젝트와 편집 상태 조회까지 성공해야 생성 결과 복구 잠금을 회수한다.
                                SweepSelectionStore::Clear(workspace, project);
                            }
                            catch (const std::exception& error)
                            {
                                Log(error.what());
                            }
                        });
        }
        else if (result.is_object() && !m_closing)
        {
            m_sweepPanel->SetStatus(
                "새 작업 사본을 생성했습니다. 현재 원본 프로젝트는 변경하지 않았습니다. 생성 위치: " +
                result.at("path").get<std::string>());
        }
    }
    catch (const std::exception& error)
    {
        m_setupDialog = nullptr;
        m_busy = false;
        m_sweepPanel->SetStatus(error.what());
        UpdateControls();
    }
}
