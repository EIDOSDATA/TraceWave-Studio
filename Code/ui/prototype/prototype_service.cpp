#include "prototype_service.h"

#include <cstdio>
#include <utility>

#include <nlohmann/json.hpp>

namespace
{
constexpr char contractVersion[] = "rfad.api/2.0";
constexpr char handshake[] = R"({"jsonrpc":"2.0","id":1,"method":"capabilities.get","params":{"contract_version":"rfad.api/2.0","context":{},"input":{}}})";

/** @brief SDL이 넘긴 UTF-8 경로를 기존 Win32 전송에 그대로 전달한다. */
std::wstring widePath(const char* path)
{
    const int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, nullptr, 0);
    if (length <= 1)
    {
        return {};
    }
    std::wstring result(static_cast<std::size_t>(length), L'\0');
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, result.data(), length))
    {
        return {};
    }
    result.pop_back();
    return result;
}
}

/** @brief 이전 제품과 같은 방식으로 서비스 소유권을 만들고 읽기 요청으로 접속한다. */
void PrototypeService::start(const PrototypeServiceOptions& options)
{
    const auto python = widePath(options.python);
    const auto source = widePath(options.source);
    const auto workspace = widePath(options.workspace);
    if (python.empty() || source.empty() || workspace.empty())
    {
        fail("Python 서비스 경로를 읽을 수 없습니다.");
        return;
    }
    std::string error;
    if (!transport_.Start(python, source, workspace, error))
    {
        fail(std::move(error));
        return;
    }
    if (!transport_.Send(handshake))
    {
        fail("서비스 계약 요청을 보내지 못했습니다.");
        return;
    }
    state_ = State::connecting;
    status_ = "Python 서비스 연결 중";
    deadline_ = std::chrono::steady_clock::now() + std::chrono::seconds(10);
}

/** @brief GUI를 막지 않고 대기 응답과 서비스 종료를 확인한다. */
void PrototypeService::poll()
{
    if (state_ == State::inactive || state_ == State::failed)
    {
        return;
    }
    for (const auto& message : transport_.Drain())
    {
        if (!message.protocol)
        {
            std::fprintf(stderr, "rfad: %s\n", message.text.c_str());
            continue;
        }
        const auto response = nlohmann::json::parse(message.text, nullptr, false);
        if (state_ != State::connecting || !response.is_object() ||
            !response.contains("jsonrpc") || response["jsonrpc"] != "2.0" ||
            !response.contains("id") || !response["id"].is_number_integer() || response["id"] != 1 ||
            !response.contains("result") || response.contains("error"))
        {
            fail("서비스의 JSON-RPC 연결 응답이 올바르지 않습니다.");
            return;
        }
        const auto& result = response["result"];
        if (!result.is_object() || !result.contains("contract_version") ||
            result["contract_version"] != contractVersion ||
            !result.contains("methods") || !result["methods"].is_object() ||
            !result["methods"].contains("capabilities.get"))
        {
            fail("서비스 공개 계약이 rfad.api/2.0과 일치하지 않습니다.");
            return;
        }
        state_ = State::connected;
        status_ = "Python 서비스 연결됨";
        std::printf("%s (%s, %zu개 메서드)\n", status_.c_str(), contractVersion, result["methods"].size());
    }
    const auto error = transport_.Error();
    if (!error.empty())
    {
        fail(error);
    }
    else if (state_ == State::connecting && std::chrono::steady_clock::now() >= deadline_)
    {
        fail("서비스 계약 응답 시간이 초과됐습니다.");
    }
}

/** @brief 연결 실패의 진단을 계속 표시하고 명령행에도 같은 결과를 남긴다. */
void PrototypeService::fail(std::string message)
{
    transport_.Stop();
    state_ = State::failed;
    status_ = "Python 서비스 연결 실패";
    std::fprintf(stderr, "%s: %s\n", status_.c_str(), message.c_str());
}
