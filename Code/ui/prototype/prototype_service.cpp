#include "prototype_service.h"

#include <cstdio>
#include <fcntl.h>
#include <io.h>
#include <iostream>
#include <objbase.h>
#include <utility>
#include <vector>

#include <SDL3/SDL.h>

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
/** @brief GUI와 재생 모드에 같은 Python 프로세스 및 경로 처리를 적용한다. */
bool startTransport(ServiceClient& transport, const PrototypeServiceOptions& options, std::string& error)
{
    const auto python = widePath(options.python);
    const auto source = widePath(options.source);
    const auto workspace = widePath(options.workspace);
    if (python.empty() || source.empty() || workspace.empty())
    {
        error = "Python 서비스 경로를 읽을 수 없습니다.";
        return false;
    }
    return transport.Start(python, source, workspace, error);
}

/** @brief 서비스가 수용하는 소문자 UUID 요청 키를 만든다. */
std::string requestKey()
{
    GUID guid{};
    wchar_t buffer[39]{};
    if (FAILED(CoCreateGuid(&guid)) || StringFromGUID2(guid, buffer, 39) != 39)
    {
        return {};
    }
    std::string key;
    for (int index = 1; index < 37; ++index)
    {
        key += static_cast<char>(SDL_tolower(static_cast<int>(buffer[index])));
    }
    return key;
}

/** @brief 도메인 오류 응답을 포함한 원래 JSON-RPC 프레임을 전달한다. */
bool replayRequest(ServiceClient& transport, const std::string& frame, const nlohmann::json& id)
{
    if (!transport.Send(frame))
    {
        return false;
    }
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
    while (std::chrono::steady_clock::now() < deadline)
    {
        for (const auto& message : transport.Drain())
        {
            if (!message.protocol)
            {
                std::fprintf(stderr, "rfad: %s\n", message.text.c_str());
                continue;
            }
            const auto response = nlohmann::json::parse(message.text, nullptr, false);
            if (!response.is_object() || !response.contains("jsonrpc") || response["jsonrpc"] != "2.0" ||
                !response.contains("id") || response["id"] != id ||
                response.contains("result") == response.contains("error"))
            {
                return false;
            }
            std::cout << message.text << '\n' << std::flush;
            return static_cast<bool>(std::cout);
        }
        if (!transport.Error().empty())
        {
            return false;
        }
        SDL_Delay(5);
    }
    return false;
}
}

/** @brief 이전 제품과 같은 방식으로 서비스 소유권을 만들고 읽기 요청으로 접속한다. */
void PrototypeService::start(const PrototypeServiceOptions& options)
{
    std::string error;
    if (!startTransport(transport_, options, error))
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
        auto response = nlohmann::json::parse(message.text, nullptr, false);
        const unsigned expected = state_ == State::connecting ? 1 : inFlight_;
        if (!expected || !response.is_object() || response.value("jsonrpc", nlohmann::json(nullptr)) != "2.0" ||
            !response.contains("id") || !response["id"].is_number_integer() || response["id"] != expected ||
            response.contains("result") == response.contains("error"))
        {
            fail("서비스의 JSON-RPC 응답이 올바르지 않습니다.");
            return;
        }
        if (state_ == State::connected)
        {
            inFlight_ = 0;
            reply_ = std::move(response);
            continue;
        }
        if (!response.contains("result"))
        {
            fail("서비스 공개 계약 요청에 실패했습니다.");
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
        const auto policy = result.find("idempotency_policy");
        if (policy != result.end() && policy->is_object() && policy->contains("request_key_epoch") &&
            (*policy)["request_key_epoch"].is_string())
        {
            requestKeyEpoch_ = (*policy)["request_key_epoch"].get<std::string>();
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
    else if ((state_ == State::connecting || inFlight_) && std::chrono::steady_clock::now() >= deadline_)
    {
        fail("서비스 계약 응답 시간이 초과됐습니다.");
    }
}

/** @brief 호출별 요청 키와 초기화 시 수신한 epoch를 그대로 사용한다. */
bool PrototypeService::request(const char* method, const nlohmann::json& context,
    const nlohmann::json& input, bool mutation)
{
    if (state_ != State::connected || inFlight_ || !reply_.is_null())
    {
        return false;
    }
    nlohmann::json params{{"contract_version", contractVersion}, {"context", context}, {"input", input}};
    if (mutation)
    {
        const auto key = requestKey();
        if (key.empty() || requestKeyEpoch_.empty())
        {
            return false;
        }
        params["request_key"] = key;
        params["request_key_epoch"] = requestKeyEpoch_;
    }
    const auto id = nextId_++;
    const nlohmann::json frame{{"jsonrpc", "2.0"}, {"id", id}, {"method", method}, {"params", params}};
    if (!transport_.Send(frame.dump()))
    {
        return false;
    }
    inFlight_ = id;
    deadline_ = std::chrono::steady_clock::now() + std::chrono::seconds(15);
    return true;
}

std::string PrototypeService::newCommandId()
{
    return requestKey();
}

nlohmann::json PrototypeService::takeReply()
{
    return std::exchange(reply_, nlohmann::json());
}

/** @brief 연결 실패의 진단을 계속 표시하고 명령행에도 같은 결과를 남긴다. */
void PrototypeService::fail(std::string message)
{
    transport_.Stop();
    state_ = State::failed;
    status_ = "Python 서비스 연결 실패";
    std::fprintf(stderr, "%s: %s\n", status_.c_str(), message.c_str());
}

/** @brief 프레임 한도, UTF-8과 자동 종료를 유지하며 테스트 명령을 순서대로 실행한다. */
int runPrototypeServiceReplay(const PrototypeServiceOptions& options)
{
    ServiceClient transport;
    std::string error;
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 || _setmode(_fileno(stdout), _O_BINARY) == -1)
    {
        std::fputs("서비스 재생 스트림을 UTF-8 바이트 모드로 열 수 없습니다.\n", stderr);
        return 1;
    }
    constexpr std::size_t maxFrameBytes = 1024 * 1024;
    std::vector<char> buffer(maxFrameBytes + 2);
    bool started = false;
    while (true)
    {
        std::cin.getline(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        if (std::cin.eof() && std::cin.gcount() == 0)
        {
            return 0;
        }
        if (std::cin.fail())
        {
            std::fputs("서비스 재생 입력을 읽을 수 없거나 프레임 한도를 초과했습니다.\n", stderr);
            return 1;
        }
        const auto length = static_cast<std::size_t>(std::cin.gcount() - (std::cin.eof() ? 0 : 1));
        std::string frame(buffer.data(), length);
        if (!frame.empty() && frame.back() == '\r')
        {
            frame.pop_back();
        }
        const auto request = nlohmann::json::parse(frame, nullptr, false);
        if (frame.size() > maxFrameBytes || !request.is_object() || !request.contains("jsonrpc") ||
            request["jsonrpc"] != "2.0" || !request.contains("id"))
        {
            std::fputs("서비스 재생에는 ID가 있는 한 줄 JSON-RPC 요청이 필요합니다.\n", stderr);
            return 1;
        }
        if (!started)
        {
            if (!startTransport(transport, options, error))
            {
                std::fprintf(stderr, "서비스 실행 실패: %s\n", error.c_str());
                return 1;
            }
            started = true;
        }
        if (!replayRequest(transport, frame, request["id"]))
        {
            error = transport.Error();
            std::fprintf(stderr, "서비스 재생 응답 실패: %s\n",
                error.empty() ? "ID, 응답 형식 또는 응답 시간을 확인하세요." : error.c_str());
            return 1;
        }
    }
}
