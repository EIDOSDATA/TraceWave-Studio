/** @file @brief 화면과 독립적인 비동기 요청과 작업 조회 상태를 정의한다. */
#pragma once
#include <chrono>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <nlohmann/json.hpp>

namespace Studio
{
using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

/** @brief 요청 등록/응답 회수/시간 제한을 담당하며 화면 콜백은 호출자가 실행한다. */
class RequestDispatcher final
{
public:
    using Callback = std::function<void(const Json&)>;
    enum class SubmitResult
    {
        Queued,
        Full,
        TransportClosed
    };
    struct Pending
    {
        Clock::time_point sent;
        Callback success;
        Callback failure;
        bool foreground;
    };

    /** @brief 전송 전에 콜백을 등록하고 전송 실패 시 정확히 해당 요청만 회수한다. */
    SubmitResult Submit(const std::string& method, const Json& input, bool mutation, const Json& context,
                        const std::string& epoch, bool foreground, Callback success, Callback failure,
                        const std::function<std::string()>& identifier,
                        const std::function<bool(const std::string&)>& transport, Clock::time_point now);
    /** @brief 같은 응답을 두 번 전달하지 않도록 콜백을 먼저 소유권 이동한다. */
    std::optional<Pending> Take(const Json& response);
    /** @brief 시간 초과는 재전송하지 않고 호출자에게 연결 확인 필요를 알린다. */
    bool Expired(Clock::time_point now) const;
    /** @brief 연결 종료 시 과거 세션의 콜백을 해제한다. */
    void Clear();
    /** @brief 대기 요청 수를 반환한다. */
    std::size_t Size() const;

private:
    std::map<std::string, Pending> m_pending;
};

/** @brief CAD/해석/일반 작업이 공유하는 중복 조회와 지연 응답 차단 상태다. */
class JobTracker final
{
public:
    /** @brief 새 작업 식별자를 받으면 이전 조회 상태를 초기화한다. */
    void Assign(const std::string& identifier);
    /** @brief 조회 간격과 미응답 조회를 함께 검사한다. */
    bool BeginPoll(Clock::time_point now, std::chrono::milliseconds interval);
    /** @brief 이전 작업의 응답은 현재 작업의 조회 잠금에도 영향을 주지 않는다. */
    bool EndPoll(const std::string& identifier);
    /** @brief 작업은 유지하고 끊어진 전송의 조회 상태만 해제한다. */
    void AbandonPoll();
    /** @brief 확인된 종료 또는 명시적 상위 오류 처리에서 작업을 비운다. */
    void Reset();
    const std::string& Id() const;
    bool Empty() const;

private:
    std::string m_identifier;
    bool m_polling = false;
    Clock::time_point m_lastPoll{};
};
}
