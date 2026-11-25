#include "prototype_cad_job.h"

#include <algorithm>
#include <cstdio>
#include <stdexcept>
#include <utility>

namespace
{
using nlohmann::json;

std::string diagnostic(const json& error)
{
    const auto details = error.value("data", json::object());
    return details.value("message_ko", error.value("message", std::string("서비스 응답을 확인하세요.")));
}
}

void PrototypeCadJob::start(const std::string& project, const std::string& revision, Output output)
{
    if (active())
    {
        return;
    }
    project_ = project;
    revision_ = revision;
    output_ = output;
    phase_ = Phase::seal;
    status_ = "CAD 입력 개정을 봉인하는 중";
}

void PrototypeCadJob::cancel()
{
    if (canCancel())
    {
        cancelRequested_ = true;
        status_ = "CAD 취소 요청 중";
    }
}

/** @brief 서비스 파이프를 공유하고 작업 응답이 도착할 때까지 중복 요청을 보류한다. */
bool PrototypeCadJob::send(PrototypeService& service)
{
    using namespace std::chrono_literals;
    if (!active() || pending_ != Request::none)
    {
        return false;
    }
    const json context{{"project_id", project_}};
    bool sent = false;
    switch (phase_)
    {
        case Phase::seal:
            if (cancelRequested_)
            {
                finish("CAD 실행 전 취소했습니다.");
                return false;
            }
            sent = service.request("snapshot.create", context,
                {{"expected_revision", revision_},
                 {"description", output_ == Output::geometry ? "시제품 3D 형상 입력" : "시제품 STEP 출력 입력"}}, true);
            pending_ = Request::seal;
            break;
        case Phase::submit:
        {
            if (cancelRequested_)
            {
                finish("CAD 실행 전 취소했습니다.");
                return false;
            }
            const bool geometry = output_ == Output::geometry;
            json input{{"profile", "rfad.step.mechanical/0.1"},
                {"snapshot", {{"snapshot_id", snapshot_.at("snapshot_id")}, {"content_hash", snapshot_.at("content_hash")}}}};
            input[geometry ? "projection_kind" : "format"] = geometry ? "brep" : "step";
            sent = service.request(geometry ? "geometry.build" : "export.build", context, input, true);
            pending_ = Request::submit;
            break;
        }
        case Phase::sealStatus:
        case Phase::monitor:
            if (phase_ == Phase::monitor && cancelRequested_ && !cancelSent_)
            {
                sent = service.request("job.cancel", json::object(),
                    {{"job_id", job_.Id()}, {"reason", "GUI 사용자 취소"}}, true);
                pending_ = Request::cancel;
            }
            else
            {
                const auto interval = cancelSent_ ? 50ms : 100ms;
                if (!job_.BeginPoll(Studio::Clock::now(), interval))
                {
                    return false;
                }
                sent = service.request("job.status", json::object(), {{"job_id", job_.Id()}});
                pending_ = Request::status;
            }
            break;
        case Phase::idle:
            return false;
    }
    if (!sent)
    {
        finish("CAD 서비스 요청을 보내지 못했습니다. 게시 상태를 다시 확인하세요.");
    }
    return sent;
}

bool PrototypeCadJob::readReply(PrototypeService& service, PrototypeCad& cad)
{
    if (pending_ == Request::none)
    {
        return true;
    }
    const auto reply = service.takeReply();
    if (reply.is_null())
    {
        return false;
    }
    const auto request = std::exchange(pending_, Request::none);
    try
    {
        receive(reply, request, cad);
    }
    catch (const std::exception& error)
    {
        const auto message = std::string("CAD 응답을 확인할 수 없습니다. ") + error.what();
        if (request == Request::status && phase_ == Phase::monitor)
        {
            job_.AbandonPoll();
            status_ = message;
        }
        else if (request == Request::cancel)
        {
            cancelRequested_ = false;
            cancelSent_ = false;
            status_ = message;
        }
        else
        {
            finish(message);
        }
    }
    return true;
}

void PrototypeCadJob::receive(const json& reply, Request request, PrototypeCad& cad)
{
    if (reply.contains("error"))
    {
        throw std::runtime_error(diagnostic(reply.at("error")));
    }
    const auto& result = reply.at("result");
    switch (request)
    {
        case Request::seal:
        case Request::submit:
            job_.Assign(result.at("job_id").get<std::string>());
            phase_ = request == Request::seal ? Phase::sealStatus : Phase::monitor;
            if (phase_ == Phase::monitor)
            {
                std::printf("CAD accepted: job=%s revision=%s snapshot=%s output=%s\n", job_.Id().c_str(), revision_.c_str(),
                    snapshot_.at("snapshot_id").get_ref<const std::string&>().c_str(),
                    output_ == Output::geometry ? "geometry" : "step");
                if (!cancelRequested_)
                {
                    status_ = "CAD 작업 대기 중";
                }
            }
            break;
        case Request::status:
            receiveStatus(result, cad);
            break;
        case Request::cancel:
            if (result.at("job_id") != job_.Id())
            {
                throw std::runtime_error("CAD 취소 영수증의 작업 ID가 다릅니다.");
            }
            cancelSent_ = true;
            status_ = "CAD 작업 종료를 확인하는 중";
            std::printf("CAD cancel receipt: job=%s state=%s\n", job_.Id().c_str(),
                result.at("state").get_ref<const std::string&>().c_str());
            break;
        case Request::none:
            break;
    }
}

void PrototypeCadJob::receiveStatus(const json& result, PrototypeCad& cad)
{
    if (!job_.EndPoll(result.at("job_id").get<std::string>()))
    {
        throw std::runtime_error("CAD 상태 응답의 작업 ID가 다릅니다.");
    }
    const auto state = result.at("state").get<std::string>();
    const auto& events = result.at("events");
    if (!events.is_array() || events.empty() || events.back().at("state") != state)
    {
        throw std::runtime_error("CAD 상태 이력이 올바르지 않습니다.");
    }

    const bool attached = result.value("native_worker_attached", false);
    if (phase_ == Phase::monitor && (observedState_ != state || observedWorker_ != attached))
    {
        std::printf("CAD job: job=%s state=%s native=%d\n", job_.Id().c_str(), state.c_str(), attached ? 1 : 0);
        observedState_ = state;
        observedWorker_ = attached;
    }
    const auto& event = events.back();
    if (state == "completed")
    {
        try
        {
            completed(event.at("operation_result"), cad);
        }
        catch (const std::exception& error)
        {
            finish(std::string("CAD 산출물 확인 실패. ") + error.what());
        }
    }
    else if (state == "cancelled")
    {
        const bool ran = std::any_of(events.begin(), events.end(),
            [](const json& entry)
            {
                return entry.at("state") == "running";
            });
        const bool confirmed = event.value("termination_confirmed", false);
        if (phase_ == Phase::monitor)
        {
            std::printf("CAD cancellation: job=%s ran=%d termination_confirmed=%d\n", job_.Id().c_str(),
                ran ? 1 : 0, confirmed ? 1 : 0);
        }
        finish(confirmed ? "CAD 취소 완료. 작업자 종료를 확인했습니다."
                         : ran ? "CAD 취소 상태입니다. 작업자 종료를 확인할 수 없습니다." : "CAD 실행 전 취소했습니다.");
    }
    else if (state == "failed" || state == "interrupted" || state == "timeout")
    {
        const bool unknown = event.value("outcome_unknown", false);
        const auto error = event.value("error", json::object());
        finish(unknown ? "CAD 작업이 중단됐습니다. 작업자 종료 확인이 필요합니다."
                       : "CAD 작업 실패. " + error.value("message_ko", error.value("message", state)));
    }
    else if (phase_ == Phase::monitor)
    {
        if (cancelRequested_ || state == "cancel_requested")
        {
            status_ = "CAD 작업 종료를 확인하는 중";
        }
        else if (state == "running")
        {
            status_ = attached ? "CAD 작업자 실행 중" : "CAD 작업자 시작 중";
        }
        else
        {
            status_ = "CAD 작업 대기 중";
        }
    }
}

/** @brief 새 작업의 성공 응답에서 봉인된 입력과 성공 산출물이 같을 때만 표시를 갱신한다. */
void PrototypeCadJob::completed(const json& result, PrototypeCad& cad)
{
    if (phase_ == Phase::sealStatus)
    {
        if (result.at("project_id") != project_ || result.at("revision_id") != revision_)
        {
            finish("봉인된 CAD 입력이 요청한 개정과 다릅니다.");
            return;
        }
        DisplayMesh::Identity(result.at("snapshot_id"));
        DisplayMesh::Identity(result.at("content_hash"));
        job_.Reset();
        snapshot_ = result;
        phase_ = Phase::submit;
        return;
    }
    if (result.at("snapshot") != snapshot_ || result.at("status") != "generated_unverified")
    {
        finish("CAD 작업의 게시 개정과 입력 스냅샷이 다릅니다.");
        return;
    }
    if (output_ == Output::geometry)
    {
        if (cad.load(result, project_))
        {
            finish({});
        }
        else
        {
            finish("완료된 CAD 작업에 표시 형상이 없습니다.");
        }
        return;
    }
    const auto& artifacts = result.at("artifacts");
    if (!artifacts.is_array())
    {
        finish("STEP 산출물 목록이 올바르지 않습니다.");
        return;
    }
    const auto step = std::find_if(artifacts.begin(), artifacts.end(),
        [](const json& artifact)
        {
            return artifact.at("role") == "step";
        });
    if (step == artifacts.end())
    {
        finish("완료된 CAD 작업에 STEP 파일이 없습니다.");
        return;
    }
    step_ = PublishedStep{revision_, step->at("uri").get<std::string>(), step->at("sha256").get<std::string>()};
    finish("AP242 STEP 게시 완료");
}

void PrototypeCadJob::disconnected()
{
    if (active())
    {
        finish("CAD 서비스 연결이 끊겼습니다. 작업의 최종 게시 상태는 다시 열어 확인하세요.");
    }
}

void PrototypeCadJob::finish(std::string status)
{
    status_ = std::move(status);
    phase_ = Phase::idle;
    pending_ = Request::none;
    job_.Reset();
    snapshot_ = nullptr;
    observedState_.clear();
    observedWorker_ = false;
    cancelRequested_ = false;
    cancelSent_ = false;
}
