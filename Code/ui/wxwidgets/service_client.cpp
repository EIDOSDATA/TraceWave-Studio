#include "service_client.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <exception>

namespace
{
constexpr std::size_t MaxFrameBytes = 1024 * 1024;
constexpr std::size_t MaxQueueMessages = 64;

/** @brief 유효한 Win32 handle만 해제한다. */
void Close(HANDLE& handle)
{
    if (handle != nullptr && handle != INVALID_HANDLE_VALUE)
    {
        CloseHandle(handle);
    }
    handle = nullptr;
}

/** @brief 표준 라이브러리의 native_handle 형식에 의존하지 않는 Win32 thread handle을 보존한다. */
void RememberThread(std::atomic<HANDLE>& target)
{
    HANDLE handle = nullptr;
    DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &handle, 0, FALSE,
                    DUPLICATE_SAME_ACCESS);
    target.store(handle);
}

/** @brief 해당 reader 또는 writer의 동기 파이프 대기만 취소한다. */
void CancelThread(std::atomic<HANDLE>& target)
{
    const HANDLE handle = target.load();
    if (handle != nullptr)
    {
        CancelSynchronousIo(handle);
    }
}

/** @brief 종료한 thread의 보존 handle을 닫는다. */
void CloseThread(std::atomic<HANDLE>& target)
{
    HANDLE handle = target.exchange(nullptr);
    Close(handle);
}

/** @brief 초기화 코드에 해당하는 고정 안내만 사용자에게 전달한다. */
const char* WorkspaceStartupError(const std::string& line)
{
    if (line == "RFAD_WORKSPACE_START:E_HASH")
    {
        return "E_HASH: 작업 영역의 저장 자료를 검증하지 못했습니다. 원본을 보존하고 보존 사본을 확인하세요.";
    }
    if (line == "RFAD_WORKSPACE_START:E_DISK")
    {
        return "E_DISK: 작업 영역을 읽거나 쓸 수 없습니다. 경로, 권한과 저장 공간을 확인하세요.";
    }
    if (line == "RFAD_WORKSPACE_START:E_CONFLICT")
    {
        return "E_CONFLICT: 작업 영역이 잠겨 있습니다. 같은 작업 영역을 사용하는 창을 확인하세요.";
    }
    if (line == "RFAD_WORKSPACE_START:E_SCHEMA")
    {
        return "E_SCHEMA: 작업 영역이나 실행 환경의 설정을 읽을 수 없습니다. 경로와 지원 형식을 확인하세요.";
    }
    return nullptr;
}
}

ServiceClient::~ServiceClient()
{
    Stop();
}

std::wstring ServiceClient::Quote(const std::wstring& argument)
{
    std::wstring result = L"\"";
    std::size_t slashes = 0;
    for (wchar_t character : argument)
    {
        if (character == L'\\')
        {
            ++slashes;
        }
        else
        {
            result.append(character == L'"' ? 2 * slashes + 1 : slashes, L'\\');
            result += character;
            slashes = 0;
        }
    }
    result.append(2 * slashes, L'\\');
    result += L'"';
    return result;
}

bool ServiceClient::Start(const std::wstring& python, const std::wstring& source, const std::wstring& workspace,
                          std::string& error, const std::wstring& cadPython, bool openEmsWsl,
                          const std::wstring& catalog, const std::wstring& exchangePython,
                          std::function<void()> protocolReady)
{
    Stop();
    SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    HANDLE childInput = nullptr;
    HANDLE childOutput = nullptr;
    HANDLE childLog = nullptr;
    if (!CreatePipe(&childInput, &m_input, &security, 0) || !CreatePipe(&m_output, &childOutput, &security, 0) ||
        !CreatePipe(&m_log, &childLog, &security, 0))
    {
        error = "Cannot create service pipes.";
        Close(childInput);
        Close(childOutput);
        Close(childLog);
        Stop();
        return false;
    }
    if (!SetHandleInformation(m_input, HANDLE_FLAG_INHERIT, 0) ||
        !SetHandleInformation(m_output, HANDLE_FLAG_INHERIT, 0) || !SetHandleInformation(m_log, HANDLE_FLAG_INHERIT, 0))
    {
        error = "Cannot restrict pipe handle inheritance.";
        Close(childInput);
        Close(childOutput);
        Close(childLog);
        Stop();
        return false;
    }
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_HIDE;
    startup.hStdInput = childInput;
    startup.hStdOutput = childOutput;
    startup.hStdError = childLog;
    const std::wstring bootstrap =
        L"import sys,runpy;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('rfad',run_name='__main__')";
    std::wstring command = Quote(python) + L" -X utf8 -u -c " + Quote(bootstrap) + L" " + Quote(source) +
                           L" serve --workspace " + Quote(workspace);
    if (!cadPython.empty())
    {
        command += L" --cad-python " + Quote(cadPython);
    }
    if (!exchangePython.empty())
    {
        command += L" --exchange-python " + Quote(exchangePython);
    }
    if (openEmsWsl)
    {
        command += L" --openems-wsl";
    }
    if (!catalog.empty())
    {
        command += L" --catalog " + Quote(catalog);
    }
    PROCESS_INFORMATION process{};
    const BOOL created = CreateProcessW(python.c_str(), command.data(), nullptr, nullptr, TRUE,
                                        CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr, nullptr, &startup, &process);
    const DWORD createError = created ? ERROR_SUCCESS : GetLastError();
    Close(childInput);
    Close(childOutput);
    Close(childLog);
    if (!created)
    {
        error = "Cannot start Python service: " + std::to_string(createError);
        Stop();
        return false;
    }
    m_process = process.hProcess;
    m_job = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (m_job == nullptr ||
        !SetInformationJobObject(m_job, JobObjectExtendedLimitInformation, &limits, sizeof(limits)) ||
        !AssignProcessToJobObject(m_job, m_process))
    {
        error = "Cannot isolate Python service process.";
        TerminateProcess(m_process, 2);
        Close(process.hThread);
        Stop();
        return false;
    }
    {
        std::lock_guard<std::mutex> guard(m_mutex);
        m_error.clear();
        m_outgoing.clear();
        m_incoming.clear();
        m_logs.clear();
        m_droppedLogs = 0;
        m_logDrained = false;
        m_receivedProtocol = false;
        m_startupError.clear();
        m_protocolReady = std::move(protocolReady);
    }
    m_stopping = false;
    if (ResumeThread(process.hThread) == static_cast<DWORD>(-1))
    {
        error = "Cannot resume Python service.";
        Close(process.hThread);
        Stop();
        return false;
    }
    Close(process.hThread);
    try
    {
        m_reader = std::thread(&ServiceClient::ReadLoop, this, m_output, true);
        m_logger = std::thread(&ServiceClient::ReadLoop, this, m_log, false);
        m_writer = std::thread(&ServiceClient::WriteLoop, this);
    }
    catch (const std::exception& exception)
    {
        error = std::string("Cannot create service threads: ") + exception.what();
        Stop();
        return false;
    }
    return true;
}

bool ServiceClient::Send(const std::string& frame)
{
    std::lock_guard<std::mutex> guard(m_mutex);
    if (m_stopping || !m_error.empty() || frame.size() > MaxFrameBytes || m_outgoing.size() >= MaxQueueMessages)
    {
        return false;
    }
    m_outgoing.push_back(frame + "\n");
    m_ready.notify_one();
    return true;
}

void ServiceClient::Fail(const std::string& message)
{
    std::lock_guard<std::mutex> guard(m_mutex);
    if (!m_stopping && m_error.empty())
    {
        m_error = message;
    }
}

/** @brief 첫 응답 전 종료에서만, 독립 stderr 읽기가 초기화 진단을 받을 때까지 잠깐 기다린다. */
void ServiceClient::ReportPipeClosure(const std::string& message)
{
    std::unique_lock<std::mutex> guard(m_mutex);
    if (!m_receivedProtocol)
    {
        m_logClosed.wait_for(guard, std::chrono::milliseconds(250), [this]()
        {
            return m_stopping || m_logDrained;
        });
    }
    if (!m_stopping && m_error.empty())
    {
        if (!m_receivedProtocol && !m_startupError.empty())
        {
            m_error = m_startupError;
            return;
        }
        m_error = message;
        // @brief 파이프 단절과 실제 프로세스 종료를 구분하고 확인된 코드만 진단에 남긴다.
        DWORD exitCode = 0;
        if (m_process != nullptr && WaitForSingleObject(m_process, 100) == WAIT_OBJECT_0 &&
            GetExitCodeProcess(m_process, &exitCode))
        {
            m_error += " (종료 코드 " + std::to_string(exitCode) + ")";
        }
    }
}

bool ServiceClient::Push(bool protocol, std::string text)
{
    std::lock_guard<std::mutex> guard(m_mutex);
    if (m_stopping)
    {
        return false;
    }
    if (protocol)
    {
        m_receivedProtocol = true;
    }
    else if (!m_receivedProtocol)
    {
        if (const auto* startupError = WorkspaceStartupError(text))
        {
            m_startupError = startupError;
            return true;
        }
    }
    auto& queue = protocol ? m_incoming : m_logs;
    if (queue.size() >= MaxQueueMessages)
    {
        if (protocol)
        {
            m_error = "Protocol receive queue exhausted; reconnect and inspect durable state.";
        }
        else
        {
            ++m_droppedLogs;
        }
        return !protocol;
    }
    const bool notify = protocol && queue.empty() && static_cast<bool>(m_protocolReady);
    queue.push_back({protocol, std::move(text)});
    if (notify)
    {
        m_protocolReady();
    }
    return true;
}

void ServiceClient::ReadLoop(HANDLE pipe, bool protocol)
{
    RememberThread(protocol ? m_readerHandle : m_loggerHandle);
    std::array<char, 4096> buffer{};
    std::string line;
    bool discardingLog = false;
    while (!m_stopping)
    {
        DWORD received = 0;
        if (!ReadFile(pipe, buffer.data(), static_cast<DWORD>(buffer.size()), &received, nullptr) || received == 0)
        {
            if (protocol)
            {
                ReportPipeClosure("Python service output closed.");
            }
            break;
        }
        for (DWORD index = 0; index < received; ++index)
        {
            const char character = buffer[index];
            if (character == '\n')
            {
                if (!line.empty() && line.back() == '\r')
                {
                    line.pop_back();
                }
                if (discardingLog)
                {
                    line += " [log line truncated]";
                }
                if (!Push(protocol, std::move(line)))
                {
                    return;
                }
                line.clear();
                discardingLog = false;
            }
            else if (!discardingLog)
            {
                line += character;
                if (line.size() > (protocol ? MaxFrameBytes : 2048))
                {
                    if (protocol)
                    {
                        Fail("Python service frame exceeds 1 MiB.");
                        return;
                    }
                    discardingLog = true;
                }
            }
        }
    }
    if (!protocol)
    {
        if (!line.empty())
        {
            Push(false, std::move(line));
        }
        {
            std::lock_guard<std::mutex> guard(m_mutex);
            m_logDrained = true;
        }
        m_logClosed.notify_all();
    }
}

void ServiceClient::WriteLoop()
{
    RememberThread(m_writerHandle);
    while (!m_stopping)
    {
        std::string frame;
        {
            std::unique_lock<std::mutex> guard(m_mutex);
            m_ready.wait(guard,
                         [this]()
                         {
                             return m_stopping || !m_outgoing.empty();
                         });
            if (m_stopping)
            {
                return;
            }
            frame = std::move(m_outgoing.front());
            m_outgoing.pop_front();
        }
        std::size_t offset = 0;
        while (offset < frame.size() && !m_stopping)
        {
            DWORD written = 0;
            if (!WriteFile(m_input, frame.data() + offset, static_cast<DWORD>(frame.size() - offset), &written,
                           nullptr) ||
                written == 0)
            {
                ReportPipeClosure("Cannot write to Python service.");
                return;
            }
            offset += written;
        }
    }
}

std::vector<ServiceClient::Message> ServiceClient::Drain()
{
    std::lock_guard<std::mutex> guard(m_mutex);
    std::vector<Message> result;
    while (!m_incoming.empty() && result.size() < 16)
    {
        result.push_back(std::move(m_incoming.front()));
        m_incoming.pop_front();
    }
    if (m_droppedLogs > 0 && result.size() < 16)
    {
        result.push_back({false, "[service log messages dropped: " + std::to_string(m_droppedLogs) + "]"});
        m_droppedLogs = 0;
    }
    while (!m_logs.empty() && result.size() < 16)
    {
        result.push_back(std::move(m_logs.front()));
        m_logs.pop_front();
    }
    return result;
}

std::string ServiceClient::Error()
{
    std::lock_guard<std::mutex> guard(m_mutex);
    return m_error;
}

void ServiceClient::Stop()
{
    {
        std::lock_guard<std::mutex> guard(m_mutex);
        m_stopping = true;
        m_protocolReady = {};
    }
    m_ready.notify_all();
    m_logClosed.notify_all();
    if (m_writer.joinable())
    {
        CancelThread(m_writerHandle);
        const HANDLE writer = m_writerHandle.load();
        if (writer == nullptr || WaitForSingleObject(writer, 500) != WAIT_OBJECT_0)
        {
            if (m_job != nullptr)
            {
                TerminateJobObject(m_job, 2);
            }
            else if (m_process != nullptr)
            {
                TerminateProcess(m_process, 2);
            }
        }
        m_writer.join();
    }
    Close(m_input);
    if (m_process != nullptr && WaitForSingleObject(m_process, 2500) == WAIT_TIMEOUT)
    {
        if (m_job != nullptr)
        {
            TerminateJobObject(m_job, 2);
        }
        else
        {
            TerminateProcess(m_process, 2);
        }
        WaitForSingleObject(m_process, 1000);
    }
    Close(m_job);
    if (m_reader.joinable())
    {
        CancelThread(m_readerHandle);
        m_reader.join();
    }
    if (m_logger.joinable())
    {
        CancelThread(m_loggerHandle);
        m_logger.join();
    }
    Close(m_output);
    Close(m_log);
    Close(m_process);
    Close(m_job);
    CloseThread(m_readerHandle);
    CloseThread(m_loggerHandle);
    CloseThread(m_writerHandle);
}
