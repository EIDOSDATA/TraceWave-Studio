#include "prototype_study.h"

#include <utility>

namespace
{
using Request = PrototypeStudy::Request;
using Clock = std::chrono::steady_clock;
}

const char* PrototypeStudy::method(Request request)
{
    switch (request)
    {
        case Request::context: return "study.context";
        case Request::list: return "study.list";
        case Request::detail: return "study.get";
        case Request::create: return "study.create";
        case Request::start: return "study.start";
        case Request::cancel: return "study.cancel";
        case Request::resume: return "study.resume";
    }
    throw std::logic_error("지원한 연구 작업이 아닙니다.");
}

bool PrototypeStudy::mutation(Request request)
{
    return request == Request::create || request == Request::start || request == Request::cancel || request == Request::resume;
}

bool PrototypeStudy::canCreate(const std::string& revision) const
{
    return context.is_object() && context.at("revision_id") == revision && context.at("runtime_configured") == true;
}

bool PrototypeStudy::canControl(Request request) const
{
    return detail.is_object() && Studio::StudyActionAllowed(detail, method(request) + sizeof("study.") - 1, false);
}

/** @brief 현재 개정과 고른 연구를 검증하고 공개 요청만 만든다. */
bool PrototypeStudy::request(Request request, const std::string& project, const std::string& revision, const std::string& identity)
{
    auto payload = nlohmann::json::object();
    if (request == Request::create)
    {
        if (!canCreate(revision))
        {
            return false;
        }
        try
        {
            payload = {{"expected_revision", revision}, {"specification",
                Studio::StudySpecification(context.at("initial_specification"), fields, radiation, losses, true)}};
        }
        catch (const Studio::StudyFieldError& error)
        {
            status = std::string(error.what()) + " (" + error.key + ")";
            return false;
        }
        catch (const std::exception& error)
        {
            status = error.what();
            return false;
        }
    }
    else if (request != Request::context && request != Request::list)
    {
        const auto target = identity.empty() ? chosen : identity;
        if (target.empty() || (mutation(request) && (target != chosen || !canControl(request))))
        {
            return false;
        }
        payload["study_id"] = target;
    }
    input = std::move(payload);
    pending = request;
    project_ = project;
    revision_ = revision;
    nextPoll_ = Clock::now() + std::chrono::seconds(2);
    status = mutation(request) ? "연구 요청을 처리하는 중" : "연구 자료를 읽는 중";
    return true;
}

/** @brief 연구 소유자와 상태를 확인한 뒤 이미 읽은 자료를 새 결과로 교체한다. */
void PrototypeStudy::accept(const nlohmann::json& result)
{
    if (pending == Request::context)
    {
        if (result.at("project_id") != project_ || result.at("revision_id") != revision_)
        {
            throw std::runtime_error("연구 조건의 프로젝트 또는 개정이 다릅니다.");
        }
        if (!context.is_object() || context.at("revision_id") != revision_)
        {
            fields = Studio::StudyDraft(result.at("initial_specification"));
            radiation = losses = false;
        }
        context = result;
    }
    else if (pending == Request::list)
    {
        const auto& studies = result.at("studies");
        if (!studies.is_array() || studies.size() > 32)
        {
            throw std::runtime_error("연구 목록을 읽을 수 없습니다.");
        }
        rows = studies;
    }
    else if (pending == Request::detail)
    {
        if (result.at("schema") != "rfad.project-study-view/0.1" || result.at("project_id") != project_ ||
            result.at("study_id") != input.at("study_id"))
        {
            throw std::runtime_error("선택한 연구와 조회 결과가 다릅니다.");
        }
        summary = Studio::StudySummary(result);
        chosen = result.at("study_id").get<std::string>();
        detail = result;
    }
    else
    {
        if (pending == Request::create)
        {
            if (result.at("snapshot").at("revision_id") != revision_ || result.at("state") != "ready")
            {
                throw std::runtime_error("생성한 연구의 봉인 개정 또는 상태가 다릅니다.");
            }
            rows = nullptr;
        }
        else if (result.at("study_id") != chosen)
        {
            throw std::runtime_error("연구 작업 응답의 소유 연구가 다릅니다.");
        }
        chosen = result.at("study_id").get<std::string>();
        detail = nullptr;
        summary.clear();
    }
    status.clear();
}

void PrototypeStudy::failed(std::string message)
{
    status = std::move(message);
    nextPoll_ = Clock::now() + std::chrono::seconds(5);
}

bool PrototypeStudy::shouldPoll() const
{
    if (!detail.is_object() || Clock::now() < nextPoll_)
    {
        return false;
    }
    const auto& state = detail.at("state");
    return state == "running" || state == "resuming" || state == "cancel_requested";
}
