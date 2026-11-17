/** @file @brief 출력 생성 요청과 고정 키 영수증 및 작업 종료를 분리한다. */
#include "output_controller.h"
#include "output_workspace.h"
#include "output_model.h"
#include "output_pending_store.h"
#include "studio_support.h"
#include <stdexcept>

namespace
{
bool Definitive(const Json& error)
{
    const auto code = error.value("code", "");
    return code == "E_SCHEMA" || code == "E_VERSION" || code == "E_CONFLICT" || code == "E_HASH" ||
           code == "E_UNSUPPORTED" || code == "E_GEOMETRY" || code == "E_RESOURCE" || code == "E_LIMIT";
}

bool SameSnapshot(const Json& value, const Json& input)
{
    return value.is_object() && input.is_object() && value.value("snapshot_id", Json(nullptr)).is_string() &&
           value.value("snapshot_id", Json(nullptr)) == input.value("snapshot_id", Json(nullptr)) &&
           value.value("content_hash", Json(nullptr)).is_string() &&
           value.value("content_hash", Json(nullptr)) == input.value("content_hash", Json(nullptr));
}
}

void OutputController::Start(const std::string& method, const Json& input)
{
    if (!m_available || Active() || m_reads > 0)
    {
        return;
    }
    const auto serial = m_serial;
    const std::weak_ptr<int> lifetime = m_lifetime;
    try
    {
        m_pending = {{"method", method}, {"input", input}, {"request_key", Uuid()}, {"request_key_epoch", m_epoch}};
        OutputPendingStore::Write(m_workspace, m_project, m_pending);
    }
    catch (const std::exception& error)
    {
        m_pending = nullptr;
        Status("failed", std::string("복구 정보를 저장하지 못해 요청하지 않았습니다: ") + error.what());
        return;
    }
    m_mutating = true;
    Actions();
    if (onStateChanged)
    {
        onStateChanged();
    }
    m_gateway(
        method, input, true,
        [this, lifetime, serial](const Json& value)
        {
            if (lifetime.expired() || serial != m_serial)
            {
                return;
            }
            m_mutating = false;
            try
            {
                AcceptTask(value);
            }
            catch (const std::exception& error)
            {
                m_uncertain = true;
                Status("unresolved", std::string("출력 접수 결과 확인 필요: ") + error.what());
            }
            Actions();
            if (onStateChanged)
            {
                onStateChanged();
            }
        },
        [this, lifetime, serial](const Json& error)
        {
            if (lifetime.expired() || serial != m_serial)
            {
                return;
            }
            m_mutating = false;
            m_uncertain = !Definitive(error);
            if (!m_uncertain)
            {
                try
                {
                    OutputPendingStore::Clear(m_workspace, m_project);
                    m_pending = nullptr;
                }
                catch (const std::exception&)
                {
                    m_uncertain = true;
                }
            }
            Status(m_uncertain ? "unresolved" : "failed",
                   DiagnosticMessage(error) + (m_uncertain ? " / 새 생성은 잠겼습니다. 같은 요청의 결과를 조회하세요."
                                                           : " / 입력을 수정한 뒤 다시 검토하세요."));
            Actions();
            if (onStateChanged)
            {
                onStateChanged();
            }
        },
        m_pending.at("request_key"), m_pending.at("request_key_epoch"));
}

void OutputController::AcceptTask(const Json& task)
{
    if (!task.is_object() || !task.value("job_id", Json(nullptr)).is_string() ||
        task.at("job_id").get<std::string>().empty())
    {
        throw std::runtime_error("접수 작업 식별자가 없습니다.");
    }
    m_pending["job_id"] = task.at("job_id");
    OutputPendingStore::Write(m_workspace, m_project, m_pending);
    m_task.Assign(task.at("job_id"));
    m_uncertain = false;
    m_cancelRequested = false;
    Status("queued", "고정한 입력의 출력 작업을 접수했습니다. 완료 전 파일 검수를 확정하지 않습니다.");
}

void OutputController::Poll(Clock::time_point now)
{
    if (!m_available || m_uncertain || !m_task.BeginPoll(now, std::chrono::milliseconds(200)))
    {
        return;
    }
    const auto job = m_task.Id();
    Read(
        "job.status", {{"job_id", job}},
        [this, job](const Json& value)
        {
            if (!m_task.EndPoll(job))
            {
                return;
            }
            const auto state = value.at("state").get<std::string>();
            if (state == "completed")
            {
                try
                {
                    const auto& events = value.at("events");
                    if (!events.is_array() || events.empty())
                    {
                        throw std::runtime_error("완료 응답의 결과가 없습니다.");
                    }
                    Complete(events.back().at("operation_result"));
                }
                catch (const std::exception& error)
                {
                    m_task.Reset();
                    m_uncertain = true;
                    Status("unresolved", std::string("생성 여부를 다시 확인해야 합니다: ") + error.what());
                }
            }
            else if (state == "failed" || state == "cancelled" || state == "interrupted")
            {
                const auto terminal = value.at("events").back();
                m_task.Reset();
                m_uncertain = terminal.value("outcome_unknown", false);
                if (!m_uncertain)
                {
                    OutputPendingStore::Clear(m_workspace, m_project);
                    m_pending = nullptr;
                }
                Status(state,
                       OutputUi::State(state) + " / " +
                           OutputUi::Issues(Json::array({terminal.value("error", "기존 출력은 보존했습니다.")})));
                Catalog(0, job);
            }
            else
            {
                Status(state, "출력 작업: " + OutputUi::State(state) + (m_cancelRequested ? " / 취소 확인 대기" : ""));
            }
            if (onStateChanged)
            {
                onStateChanged();
            }
        },
        [this, job](const Json& error)
        {
            if (!m_task.EndPoll(job))
            {
                return;
            }
            m_task.Reset();
            m_uncertain = true;
            Status("unresolved", DiagnosticMessage(error) + " / 같은 요청의 결과를 다시 조회하세요.");
            if (onStateChanged)
            {
                onStateChanged();
            }
        });
}

void OutputController::Complete(const Json& result)
{
    const auto method = m_pending.at("method").get<std::string>();
    const auto input = m_pending.at("input");
    const auto job = m_task.Id();
    if (method == "snapshot.create")
    {
        if (result.at("project_id") != m_project || result.at("revision_id") != input.at("expected_revision"))
        {
            throw std::runtime_error("고정 입력의 프로젝트 또는 개정이 다릅니다.");
        }
        m_view->SelectSnapshot(result);
    }
    else
    {
        if (result.at("snapshot").at("project_id") != m_project ||
            (method != "export.verify" && !SameSnapshot(result.at("snapshot"), input.at("snapshot"))))
        {
            throw std::runtime_error("출력의 고정 원본이 요청과 다릅니다.");
        }
        if (method != "export.verify" && result.value("profile", "") != input.at("profile"))
        {
            throw std::runtime_error("출력 결과의 형식 계약이 다릅니다.");
        }
        if (method == "export.preview")
        {
            if (result.value("profile", "") != input.at("profile"))
            {
                throw std::runtime_error("검토 형식 계약이 다릅니다.");
            }
            if (input.at("format") != "step" && result.value("can_build", false) &&
                !OutputUi::MatchesPreview(result, input))
            {
                throw std::runtime_error("검토 옵션 또는 해시가 다릅니다.");
            }
            m_previewInput = input;
            m_view->SetPreview(result);
        }
        else if (method == "export.verify" &&
                 (result.value("original_job_id", "") != input.at("job_id") ||
                  result.value("source_manifest_sha256", "") != input.at("manifest_sha256")))
        {
            throw std::runtime_error("재검수 대상 작업이 다릅니다.");
        }
    }
    OutputPendingStore::Clear(m_workspace, m_project);
    m_pending = nullptr;
    m_task.Reset();
    m_cancelRequested = false;
    m_uncertain = false;
    if (method == "snapshot.create")
    {
        Context(0, true);
        Status("completed", "현재 개정의 출력 입력을 고정했습니다. 형식과 포함 범위를 검토하세요.");
    }
    else if (method == "export.preview")
    {
        Status("completed", "포함/제외와 종이 배치를 검토하세요. 생성과 다시 읽기 검수는 별도 단계입니다.");
    }
    else
    {
        Catalog(0, job);
        Record(job);
        if (onCadResult && result.value("profile", "") == "rfad.step.mechanical/0.1" && method == "export.build")
        {
            onCadResult(result);
        }
    }
}

void OutputController::Recover()
{
    if (!m_available || !m_uncertain || m_reads > 0 || !m_pending.is_object())
    {
        return;
    }
    Read("export.receipt",
         {{"request_key", m_pending.at("request_key")}, {"request_key_epoch", m_pending.at("request_key_epoch")}},
         [this](const Json& value)
         {
             if (value.value("status", "") == "found" && value.value("authoritative", false))
             {
                 AcceptTask(value.at("response"));
             }
             else
             {
                 Status("unresolved", OutputUi::Text(value.value("reason", Json(nullptr))) +
                                          " / 생성되지 않았다는 뜻이 아닙니다. 새 요청 잠금을 유지합니다.");
             }
             if (onStateChanged)
             {
                 onStateChanged();
             }
         });
}

void OutputController::Cancel()
{
    if (!m_available || m_task.Empty() || m_cancelRequested)
    {
        return;
    }
    const auto serial = m_serial;
    const auto job = m_task.Id();
    const std::weak_ptr<int> lifetime = m_lifetime;
    m_cancelRequested = true;
    Actions();
    m_gateway(
        "job.cancel", {{"job_id", job}}, true,
        [this, lifetime, serial, job](const Json&)
        {
            if (lifetime.expired() || serial != m_serial || job != m_task.Id())
            {
                return;
            }
            Status("cancel_requested", "취소를 요청했습니다. 실제 작업 종료를 기다립니다.");
        },
        [this, lifetime, serial, job](const Json& error)
        {
            if (lifetime.expired() || serial != m_serial || job != m_task.Id())
            {
                return;
            }
            m_cancelRequested = false;
            Status("failed", DiagnosticMessage(error) + " / 작업 상태를 계속 조회합니다.");
            Actions();
        },
        "", "");
}
