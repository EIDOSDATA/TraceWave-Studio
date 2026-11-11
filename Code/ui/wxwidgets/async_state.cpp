/** @file @brief 비동기 요청과 작업 조회의 화면 독립 구현이다. */
#include "async_state.h"
#include <stdexcept>
#include <utility>

namespace Studio
{
RequestDispatcher::SubmitResult RequestDispatcher::Submit(const std::string& method, const Json& input, bool mutation,
                                                          const Json& context, const std::string& epoch,
                                                          bool foreground, Callback success, Callback failure,
                                                          const std::function<std::string()>& identifier,
                                                          const std::function<bool(const std::string&)>& transport,
                                                          Clock::time_point now)
{
    if (m_pending.size() >= 16)
    {
        return SubmitResult::Full;
    }
    const std::string id = identifier();
    Json parameters{{"contract_version", "rfad.api/2.0"}, {"context", context}, {"input", input}};
    if (mutation)
    {
        parameters["request_key"] = identifier();
        parameters["request_key_epoch"] = epoch;
    }
    Json request{{"jsonrpc", "2.0"}, {"id", id}, {"method", method}, {"params", parameters}};
    if (id.empty() || !m_pending.emplace(id, Pending{now, std::move(success), std::move(failure), foreground}).second)
    {
        throw std::logic_error("Duplicate or empty GUI request identifier.");
    }
    try
    {
        if (transport(request.dump()))
        {
            return SubmitResult::Queued;
        }
    }
    catch (...)
    {
        m_pending.erase(id);
        throw;
    }
    m_pending.erase(id);
    return SubmitResult::TransportClosed;
}

std::optional<RequestDispatcher::Pending> RequestDispatcher::Take(const Json& response)
{
    if (!response.is_object() || response.value("jsonrpc", "") != "2.0" || !response.contains("id") ||
        !response.at("id").is_string() || response.contains("result") == response.contains("error"))
    {
        throw std::runtime_error("Unexpected service protocol response.");
    }
    auto found = m_pending.find(response.at("id").get<std::string>());
    if (found == m_pending.end())
    {
        return std::nullopt;
    }
    auto pending = std::move(found->second);
    m_pending.erase(found);
    return pending;
}

bool RequestDispatcher::Expired(Clock::time_point now) const
{
    for (const auto& entry : m_pending)
    {
        if (now - entry.second.sent > std::chrono::seconds(30))
        {
            return true;
        }
    }
    return false;
}

void RequestDispatcher::Clear()
{
    m_pending.clear();
}

std::size_t RequestDispatcher::Size() const
{
    return m_pending.size();
}

void JobTracker::Assign(const std::string& identifier)
{
    if (identifier.empty())
    {
        throw std::invalid_argument("Empty job identifier.");
    }
    m_identifier = identifier;
    m_polling = false;
    m_lastPoll = Clock::time_point{};
}

bool JobTracker::BeginPoll(Clock::time_point now, std::chrono::milliseconds interval)
{
    if (m_identifier.empty() || m_polling || now - m_lastPoll < interval)
    {
        return false;
    }
    m_polling = true;
    m_lastPoll = now;
    return true;
}

bool JobTracker::EndPoll(const std::string& identifier)
{
    if (m_identifier != identifier)
    {
        return false;
    }
    m_polling = false;
    return true;
}

void JobTracker::AbandonPoll()
{
    m_polling = false;
}

void JobTracker::Reset()
{
    m_identifier.clear();
    m_polling = false;
    m_lastPoll = Clock::time_point{};
}

const std::string& JobTracker::Id() const
{
    return m_identifier;
}

bool JobTracker::Empty() const
{
    return m_identifier.empty();
}
}
