/** @file @brief PCB 편집을 현재 개정과 영속 ledger 복구 경계에 연결한다. */
#include "studio_internal.h"
#include "editor_sync.h"
#include "pcb_feature_dialog.h"
#include "reviewed_request_store.h"
#include <set>

namespace
{
const std::set<std::string> FeatureMethods{"pcb.features.apply"};

bool Definitive(const Json& error)
{
    const auto code = error.value("data", Json::object()).value("domain_code", error.value("code", Json(nullptr)));
    const std::set<std::string> rejected{"E_SCHEMA",      "E_CONFLICT",  "E_UNIT",    "E_RESOURCE",
                                         "E_UNSUPPORTED", "E_NOT_FOUND", "E_VERSION", "E_LIMIT"};
    return code.is_string() && rejected.count(code.get<std::string>()) != 0;
}
}

void StudioFrame::ReadPcbFeatureRecovery()
{
    m_pcbFeatureRecoveryProject = m_project;
    m_pcbFeatureUncertain = false;
    try
    {
        m_pcbFeatureUncertain =
            ReviewedRequestStore::Read("pcb_features", Utf8(m_options.workspace), m_project, FeatureMethods)
                .is_object();
    }
    catch (const std::exception& error)
    {
        m_pcbFeatureUncertain = true;
        Log(error.what());
    }
}

void StudioFrame::OpenPcbFeatures(const std::string& section, const Json& identity)
{
    if (m_closing || !m_connected || m_busy || m_setupDialog || !m_pcbFeaturesSupported || m_project.empty() ||
        m_pcbImportUncertain)
    {
        return;
    }
    if (!m_pcbFeatureUncertain && !Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
    {
        return;
    }
    if (HasDraft() && !m_pcbFeatureUncertain)
    {
        Log("미적용 속성 초안을 먼저 적용하거나 취소한 뒤 PCB 형상 편집을 여세요.");
        return;
    }
    m_canvas->CancelGesture();
    const auto project = m_project, revision = m_revision;
    m_busy = true;
    UpdateControls();
    Send(
        "pcb.features.get", {{"expected_revision", revision}, {"section", section}, {"record_id", identity}}, false,
        Context(),
        [this, project, revision](const Json& context)
        {
            CallAfter(
                [this, project, revision, context]()
                {
                    if (!m_closing && m_connected && m_project == project && m_revision == revision &&
                        context.value("project_id", "") == project && context.value("revision_id", "") == revision)
                    {
                        ShowPcbFeatures(context);
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

void StudioFrame::ShowPcbFeatures(const Json& context)
{
    try
    {
        const auto project = m_project;
        const auto workspace = Utf8(m_options.workspace);
        auto recovery = std::make_shared<PcbFeatureRecovery>();
        recovery->pending = ReviewedRequestStore::Read("pcb_features", workspace, project, FeatureMethods);
        m_pcbFeatureUncertain = recovery->pending.is_object();
        recovery->resolved = [this, workspace, project]()
        {
            ReviewedRequestStore::Clear("pcb_features", workspace, project);
            if (m_project == project)
            {
                m_pcbFeatureUncertain = false;
            }
        };
        DialogGateway gateway = [this, workspace, project, recovery](
                                    const std::string& method, const Json& input, bool mutation,
                                    std::function<void(const Json&)> success, std::function<void(const Json&)> failure)
        {
            if (m_closing || !m_connected || project != m_project)
            {
                failure({{"code", "E_CONNECTION"},
                         {"message", "프로젝트 연결이 바뀌었습니다. 같은 프로젝트에서 이전 적용 결과를 확인하세요."}});
                return;
            }
            std::string key, epoch;
            if (mutation)
            {
                if (method != "pcb.features.apply" || recovery->pending.is_object())
                {
                    failure({{"code", "E_UNCERTAIN"},
                             {"message", "이전 PCB 적용 결과를 확인하기 전에는 새 변경을 보내지 않습니다."}});
                    return;
                }
                key = Uuid();
                epoch = m_epoch;
                Json pending{{"method", method}, {"request_key", key}, {"request_key_epoch", epoch}, {"input", input}};
                ReviewedRequestStore::Write("pcb_features", workspace, project, FeatureMethods, pending);
                recovery->pending = pending;
                m_pcbFeatureUncertain = true;
            }
            Send(
                method, input, mutation, Context(), std::move(success),
                [this, workspace, project, recovery, mutation, failure](const Json& error)
                {
                    if (mutation && Definitive(error))
                    {
                        try
                        {
                            ReviewedRequestStore::Clear("pcb_features", workspace, project);
                            recovery->pending = nullptr;
                            m_pcbFeatureUncertain = false;
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
        ShowObjectTool(std::make_unique<PcbFeatureDialog>(this, context, gateway, recovery),
                       {{"kind", "project"}, {"id", project}});
    }
    catch (const std::exception& error)
    {
        m_busy = false;
        Log(error.what());
        UpdateControls();
    }
}
