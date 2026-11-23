/** @file @brief 측정 기록 편집을 현재 프로젝트 소유권과 영속 요청 복구에 연결한다. */
#include "studio_internal.h"
#include "measurement_record_dialog.h"
#include "measurement_operation_dialog.h"
#include "measurement_history_dialog.h"
#include "measurement_recovery.h"
#include "reviewed_request_store.h"
#include "result_workspace.h"
#include "editor_sync.h"
#include "network_panel.h"
#include <set>

namespace
{
const std::set<std::string> Methods{"measurement.apply", "measurement.align", "measurement.attachment.add"};
bool Definitive(const Json& error)
{
    const auto code = error.value("data", Json::object()).value("domain_code", error.value("code", Json(nullptr)));
    const std::set<std::string> rejected{"E_SCHEMA",      "E_CONFLICT",  "E_UNIT",    "E_RESOURCE",
                                         "E_UNSUPPORTED", "E_NOT_FOUND", "E_VERSION", "E_LIMIT"};
    return code.is_string() && rejected.count(code.get<std::string>()) != 0;
}
}

void StudioFrame::BuildMeasurementInterface()
{
    m_views->AddDeferredPage(Display("측정 비교"), [this](wxWindow* parent)
    {
        return m_results->BuildMeasurementPage(parent);
    });
    m_results->onMeasurementTool = [this](const std::string& operation, const Json& record, const Json& selection)
    {
        OpenMeasurementTool(operation, record, selection);
    };
}

void StudioFrame::ReadMeasurementRecovery()
{
    m_measurementUncertain = false;
    try
    {
        m_measurementUncertain =
            ReviewedRequestStore::Read("measurement", Utf8(m_options.workspace), m_project, Methods).is_object();
    }
    catch (const std::exception& error)
    {
        m_measurementUncertain = true;
        Log(error.what());
    }
}

std::shared_ptr<MeasurementRecovery> StudioFrame::MeasurementRecoveryState()
{
    auto recovery = std::make_shared<MeasurementRecovery>();
    const auto project = m_project, workspace = Utf8(m_options.workspace);
    recovery->pending = ReviewedRequestStore::Read("measurement", workspace, project, Methods);
    m_measurementUncertain = recovery->pending.is_object();
    recovery->resolved = [this, project, workspace]()
    {
        ReviewedRequestStore::Clear("measurement", workspace, project);
        if (m_project == project)
        {
            m_measurementUncertain = false;
        }
    };
    return recovery;
}

DialogGateway StudioFrame::MeasurementGateway(std::shared_ptr<MeasurementRecovery> recovery)
{
    const auto project = m_project, workspace = Utf8(m_options.workspace);
    return [this, project, workspace, recovery](const std::string& method, const Json& input, bool mutation,
                                                std::function<void(const Json&)> success,
                                                std::function<void(const Json&)> failure)
    {
        if (m_closing || !m_connected || m_project != project)
        {
            failure({{"code", "E_CONNECTION"},
                     {"message", "프로젝트 연결이 바뀌었습니다. 같은 프로젝트에서 원래 요청 결과를 확인하세요."}});
            return;
        }
        std::string key, epoch;
        if (mutation && method.rfind("measurement.", 0) == 0)
        {
            if (Methods.count(method) == 0 || recovery->pending.is_object())
            {
                failure({{"code", "E_UNCERTAIN"},
                         {"message", "이전 측정 변경의 결과를 확인하기 전에는 새 변경을 보내지 않습니다."}});
                return;
            }
            key = Uuid();
            epoch = m_epoch;
            const Json pending{
                {"method", method}, {"request_key", key}, {"request_key_epoch", epoch}, {"input", input}};
            ReviewedRequestStore::Write("measurement", workspace, project, Methods, pending);
            recovery->pending = pending;
            m_measurementUncertain = true;
        }
        Send(
            method, input, mutation, Context(), std::move(success),
            [this, workspace, project, recovery, mutation, method, failure](const Json& error)
            {
                if (mutation && Methods.count(method) != 0 && Definitive(error))
                {
                    try
                    {
                        ReviewedRequestStore::Clear("measurement", workspace, project);
                        recovery->pending = nullptr;
                        if (project == m_project)
                        {
                            m_measurementUncertain = false;
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
}

void StudioFrame::OpenMeasurementTool(const std::string& operation, const Json& record, const Json& selection)
{
    if (m_closing || !m_connected || m_busy || m_setupDialog || m_project.empty() || !m_measurementSupported ||
        m_pcbFeatureUncertain || m_pcbImportUncertain)
    {
        return;
    }
    if (!m_measurementUncertain && (!Studio::EditableProject(m_editor, m_scene, m_project, m_revision) || HasDraft()))
    {
        Log("현재 속성 초안을 적용하거나 취소한 뒤 측정 기록 도구를 여세요.");
        return;
    }
    if (operation == "import_record" && !m_measurementUncertain)
    {
        OpenNetworkAction(NetworkAction::Import);
        return;
    }
    const auto project = m_project, revision = m_revision;
    m_busy = true;
    UpdateControls();
    const auto failed = [this](const Json& error)
    {
        m_busy = false;
        Log(DiagnosticMessage(error));
        UpdateControls();
    };
    Send(
        "measurement.context", {{"revision_id", nullptr}, {"offset", 0}, {"limit", 32}}, false, Context(),
        [this, project, revision, operation, record, selection, failed](const Json& context)
        {
            const auto show = [this, project, revision, operation, context](const Json& selected)
            {
                CallAfter(
                    [this, project, revision, operation, context, selected]()
                    {
                        if (m_closing || !m_connected || m_project != project || m_revision != revision)
                        {
                            if (!m_closing)
                            {
                                m_busy = false;
                                UpdateControls();
                            }
                            return;
                        }
                        try
                        {
                            auto recovery = MeasurementRecoveryState();
                            auto gateway = MeasurementGateway(recovery);
                            if (operation == "history")
                            {
                                ShowObjectTool(
                                    std::make_unique<MeasurementHistoryDialog>(this, context, selected, gateway),
                                    m_selection);
                            }
                            else if (!recovery->pending.is_object() &&
                                     (operation == "align" || operation == "compare_record"))
                            {
                                ShowObjectTool(std::make_unique<MeasurementOperationDialog>(
                                                   this, context, selected, operation, gateway, recovery),
                                               m_selection);
                            }
                            else
                            {
                                ShowObjectTool(std::make_unique<MeasurementRecordDialog>(this, context, selected,
                                                                                         gateway, recovery),
                                               m_selection);
                            }
                        }
                        catch (const std::exception& error)
                        {
                            m_busy = false;
                            Log(error.what());
                            UpdateControls();
                        }
                    });
            };
            const auto reference = record.is_object() ? record.value("record_ref", Json(nullptr)) : Json(nullptr);
            if (reference.is_object() && operation != "history" && operation != "compare_record")
            {
                Send(
                    "measurement.get", {{"record", reference}}, false, Context(),
                    [show, reference](const Json& response)
                    {
                        if (response.value("record_ref", Json(nullptr)) != reference ||
                            !response.value("pin", Json(nullptr)).is_object())
                        {
                            throw std::runtime_error("측정 기록의 고정 개정과 원본 해시가 요청과 다릅니다.");
                        }
                        show(response);
                    },
                    failed);
            }
            else
            {
                show(selection);
            }
        },
        failed);
}
