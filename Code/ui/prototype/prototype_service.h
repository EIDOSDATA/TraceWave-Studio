#pragma once

#include "../wxwidgets/service_client.h"

#include <chrono>
#include <string>

#include <nlohmann/json.hpp>

/** @brief 시제품이 연결할 기존 Python 서비스의 실행 경로다. */
struct PrototypeServiceOptions
{
    const char* python = nullptr;
    const char* source = nullptr;
    const char* workspace = nullptr;
    const char* cadPython = nullptr;
};

/** @brief 기존 Windows 서비스 전송을 사용하고 공개 계약 응답을 검증한다. */
class PrototypeService
{
public:
    void start(const PrototypeServiceOptions& options);
    void poll();
    /** @brief 한 번에 한 요청을 공개 API에 보내고 응답 ID를 추적한다. */
    bool request(const char* method, const nlohmann::json& context, const nlohmann::json& input,
        bool mutation = false);
    nlohmann::json takeReply();
    static std::string newCommandId();

    /** @brief 시작 상태를 GUI와 명령행 검수에서 함께 사용한다. */
    enum class State { inactive, connecting, connected, failed };
    State state() const { return state_; }
    const std::string& status() const { return status_; }
    bool cadReady() const { return state_ == State::connected && cadReady_; }
    bool solverReady() const { return state_ == State::connected && solverReady_; }

private:
    void fail(std::string message);
    ServiceClient transport_;
    State state_ = State::inactive;
    std::chrono::steady_clock::time_point deadline_;
    std::string status_;
    std::string requestKeyEpoch_;
    unsigned nextId_ = 2;
    unsigned inFlight_ = 0;
    nlohmann::json reply_;
    bool cadReady_ = false;
    bool solverReady_ = false;
};

/** @brief 한 줄씩 공개 요청을 재생하고 같은 ID의 응답을 표준 출력으로 보낸다. */
int runPrototypeServiceReplay(const PrototypeServiceOptions& options);
