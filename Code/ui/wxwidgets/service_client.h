#pragma once

#include <windows.h>
#include <atomic>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

/** @brief Python 서비스의 전용 파이프를 소유하는 제한된 비동기 클라이언트다. */
class ServiceClient
{
public:
    struct Message
    {
        bool protocol;
        std::string text;
    };

    ServiceClient() = default;
    ~ServiceClient();
    ServiceClient(const ServiceClient&) = delete;
    ServiceClient& operator=(const ServiceClient&) = delete;

    /** @brief 셸을 거치지 않고 호스트가 지정한 서비스/CAD Python과 작업 영역으로 서비스를 시작한다. */
    bool Start(const std::wstring& python, const std::wstring& source, const std::wstring& workspace,
        std::string& error, const std::wstring& cadPython = L"");
    /** @brief 한 프레임을 제한된 쓰기 큐에 넣고 즉시 반환한다. */
    bool Send(const std::string& frame);
    /** @brief GUI가 현재 도착한 메시지를 제한된 개수만 가져온다. */
    std::vector<Message> Drain();
    /** @brief 최초 연결 오류 또는 파이프 종료 상태를 반환한다. */
    std::string Error();
    /** @brief 자신이 시작한 서비스만 종료하고 모든 reader와 handle을 회수한다. */
    void Stop();

private:
    void ReadLoop(HANDLE pipe, bool protocol);
    void WriteLoop();
    void Fail(const std::string& message);
    bool Push(bool protocol, std::string text);
    static std::wstring Quote(const std::wstring& argument);

    HANDLE m_process = nullptr;
    HANDLE m_job = nullptr;
    HANDLE m_input = nullptr;
    HANDLE m_output = nullptr;
    HANDLE m_log = nullptr;
    std::thread m_reader;
    std::thread m_logger;
    std::thread m_writer;
    std::atomic<HANDLE> m_readerHandle{nullptr};
    std::atomic<HANDLE> m_loggerHandle{nullptr};
    std::atomic<HANDLE> m_writerHandle{nullptr};
    std::atomic<bool> m_stopping{true};
    std::mutex m_mutex;
    std::condition_variable m_ready;
    std::deque<std::string> m_outgoing;
    std::deque<Message> m_incoming;
    std::deque<Message> m_logs;
    std::size_t m_droppedLogs = 0;
    std::string m_error;
};
