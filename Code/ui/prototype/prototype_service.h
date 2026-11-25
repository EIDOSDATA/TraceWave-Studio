#pragma once

#include "../wxwidgets/service_client.h"

#include <chrono>
#include <string>

/** @brief 시제품이 연결할 기존 Python 서비스의 실행 경로다. */
struct PrototypeServiceOptions
{
    const char* python = nullptr;
    const char* source = nullptr;
    const char* workspace = nullptr;
};

/** @brief 기존 Windows 서비스 전송을 사용하고 공개 계약 응답을 검증한다. */
class PrototypeService
{
public:
    void start(const PrototypeServiceOptions& options);
    void poll();

    /** @brief 시작 상태를 GUI와 명령행 검수에서 함께 사용한다. */
    enum class State { inactive, connecting, connected, failed };
    State state() const { return state_; }
    const std::string& status() const { return status_; }

private:
    void fail(std::string message);
    ServiceClient transport_;
    State state_ = State::inactive;
    std::chrono::steady_clock::time_point deadline_;
    std::string status_;
};
