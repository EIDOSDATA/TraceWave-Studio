/** @file @brief 원문 청크와 원자 적용의 같은 요청 영수증을 영속 보존한다. */
#include "studio_internal.h"
#include "editor_sync.h"
#include "pcb_import_dialog.h"
#include "pcb_import_model.h"
#include "reviewed_request_store.h"
#include <set>

namespace
{
const std::set<std::string> ImportMethods{"pcb.import.begin", "pcb.import.chunk", "pcb.import.parse",
                                          "pcb.import.apply", "pcb.import.abandon"};

bool Definitive(const Json& error)
{
    const auto code = error.value("data", Json::object()).value("domain_code", error.value("code", Json(nullptr)));
    const std::set<std::string> rejected{"E_SCHEMA",      "E_CONFLICT",  "E_UNIT",    "E_RESOURCE",
                                         "E_UNSUPPORTED", "E_NOT_FOUND", "E_VERSION", "E_LIMIT"};
    return code.is_string() && rejected.count(code.get<std::string>()) != 0;
}
}

void StudioFrame::ReadPcbImportRecovery()
{
    m_pcbImportUncertain = false;
    try
    {
        const auto request =
            ReviewedRequestStore::Read("pcb_import", Utf8(m_options.workspace), m_project, ImportMethods);
        m_pcbImportUncertain = request.is_object() && !request.value("confirmed", false);
    }
    catch (const std::exception& error)
    {
        m_pcbImportUncertain = true;
        Log(error.what());
    }
}

void StudioFrame::OpenPcbImport()
{
    if (m_closing || !m_connected || m_busy || m_setupDialog || !m_pcbImportSupported || m_project.empty() ||
        m_pcbFeatureUncertain)
    {
        return;
    }
    if (!m_pcbImportUncertain && (!Studio::EditableProject(m_editor, m_scene, m_project, m_revision) || HasDraft()))
    {
        Log("미적용 속성 초안을 먼저 적용하거나 취소하고 현재 편집 원본을 확인한 뒤 가져오기를 여세요.");
        return;
    }
    m_canvas->CancelGesture();
    m_busy = true;
    UpdateControls();
    const auto project = m_project, revision = m_revision;
    Send(
        "pcb.import.context", Json::object(), false, Context(),
        [this, project, revision](const Json& context)
        {
            CallAfter(
                [this, project, revision, context]()
                {
                    if (!m_closing && m_connected && m_project == project && m_revision == revision &&
                        context.value("project_id", "") == project && context.value("revision_id", "") == revision)
                    {
                        ShowPcbImport(context);
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
            Log(DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::ShowPcbImport(const Json& context)
{
    try
    {
        const auto project = m_project;
        const auto workspace = Utf8(m_options.workspace);
        auto recovery = std::make_shared<PcbImportRecovery>();
        recovery->checkpoint = ReviewedRequestStore::Read("pcb_import", workspace, project, ImportMethods);
        m_pcbImportUncertain = recovery->checkpoint.is_object() && !recovery->checkpoint.value("confirmed", false);
        std::weak_ptr<PcbImportRecovery> weakRecovery(recovery);
        recovery->confirmed = [this, workspace, project, weakRecovery](const Json& result)
        {
            const auto state = weakRecovery.lock();
            if (!state || !state->checkpoint.is_object())
            {
                throw std::runtime_error("확인할 원래 가져오기 요청이 없습니다.");
            }
            if (!PcbImportUi::MatchesResponse(state->checkpoint, result, project))
            {
                throw std::runtime_error("보존한 원문 요청과 권위 응답이 다릅니다. 기존 요청 키를 유지합니다.");
            }
            Json confirmed = state->checkpoint;
            confirmed["confirmed"] = true;
            confirmed["response"] = result;
            ReviewedRequestStore::Write("pcb_import", workspace, project, ImportMethods, confirmed);
            state->checkpoint = confirmed;
            if (m_project == project)
            {
                m_pcbImportUncertain = false;
            }
        };
        recovery->clear = [this, workspace, project]()
        {
            ReviewedRequestStore::Clear("pcb_import", workspace, project);
            if (m_project == project)
            {
                m_pcbImportUncertain = false;
            }
        };
        DialogGateway gateway = [this, workspace, project, recovery](
                                    const std::string& method, const Json& input, bool mutation,
                                    std::function<void(const Json&)> success, std::function<void(const Json&)> failure)
        {
            if (m_closing || !m_connected || m_project != project)
            {
                failure({{"code", "E_CONNECTION"},
                         {"message", "프로젝트 연결이 바뀌었습니다. 같은 프로젝트에서 이전 요청 결과를 확인하세요."}});
                return;
            }
            std::string key, epoch;
            const auto previous = recovery->checkpoint;
            if (mutation)
            {
                if (ImportMethods.count(method) == 0 || (previous.is_object() && !previous.value("confirmed", false)))
                {
                    failure({{"code", "E_UNCERTAIN"},
                             {"message", "이전 가져오기 요청이 확정되기 전에는 새 변경을 보낼 수 없습니다."}});
                    return;
                }
                key = Uuid();
                epoch = m_epoch;
                Json request{{"method", method},
                             {"input", input},
                             {"request_key", key},
                             {"request_key_epoch", epoch},
                             {"confirmed", false}};
                ReviewedRequestStore::Write("pcb_import", workspace, project, ImportMethods, request);
                recovery->checkpoint = request;
                m_pcbImportUncertain = true;
            }
            Send(
                method, input, mutation, Context(),
                [recovery, mutation, success, failure](const Json& response)
                {
                    if (mutation)
                    {
                        try
                        {
                            recovery->confirmed(response);
                        }
                        catch (const std::exception& error)
                        {
                            failure({{"code", "E_UNCERTAIN"}, {"message", error.what()}});
                            return;
                        }
                    }
                    success(response);
                },
                [this, workspace, project, recovery, previous, mutation, failure](const Json& error)
                {
                    if (mutation && Definitive(error))
                    {
                        try
                        {
                            if (previous.is_object())
                            {
                                ReviewedRequestStore::Write("pcb_import", workspace, project, ImportMethods, previous);
                            }
                            else
                            {
                                ReviewedRequestStore::Clear("pcb_import", workspace, project);
                            }
                            recovery->checkpoint = previous;
                            if (m_project == project)
                            {
                                m_pcbImportUncertain = false;
                            }
                        }
                        catch (const std::exception& cleanup)
                        {
                            failure({{"code", "E_UNCERTAIN"}, {"message", cleanup.what()}});
                            return;
                        }
                    }
                    failure(error);
                },
                key, epoch);
        };
        ShowObjectTool(std::make_unique<PcbImportDialog>(this, context, gateway, recovery),
                       {{"kind", "project"}, {"id", project}});
    }
    catch (const std::exception& error)
    {
        m_busy = false;
        Log(error.what());
        UpdateControls();
    }
}
