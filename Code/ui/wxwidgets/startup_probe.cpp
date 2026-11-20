/** @file @brief Windows 시작의 실제 화면과 서비스 준비 이벤트를 기록한다. */
#include "startup_probe.h"
#include "studio_support.h"

#include <wx/frame.h>
#include <wx/msw/wrapwin.h>

namespace
{
/** @brief Windows 런처와 동일한 시스템 전체 성능 카운터를 읽는다. */
std::int64_t Counter()
{
    LARGE_INTEGER value{};
    QueryPerformanceCounter(&value);
    return value.QuadPart;
}
}

StartupProbe::StartupProbe(wxFrame& frame) : m_frame(frame) {}

void StartupProbe::CanvasPainted()
{
    m_painted = Counter();
    FinishIfReady();
}

void StartupProbe::ServiceReady()
{
    m_ready = Counter();
    FinishIfReady();
}

void StartupProbe::Fail(const std::string& message)
{
    Report(false, message);
}

void StartupProbe::FinishIfReady()
{
    if (m_painted > 0 && m_ready > 0)
    {
        Report(true, "");
    }
}

void StartupProbe::Report(bool success, const std::string& message)
{
    if (m_reported)
    {
        return;
    }
    m_reported = true;
    LARGE_INTEGER frequency{};
    QueryPerformanceFrequency(&frequency);
    const auto size = m_frame.GetClientSize();
    const Json report{{"schema", "rfad.windows-startup-probe/0.1"},
                      {"ok", success},
                      {"pid", GetCurrentProcessId()},
                      {"qpc_frequency", frequency.QuadPart},
                      {"canvas_painted_qpc", m_painted},
                      {"service_ready_qpc", m_ready},
                      {"dpi", m_frame.GetDPI().x},
                      {"client_width", size.GetWidth()},
                      {"client_height", size.GetHeight()},
                      {"error", message.substr(0, 512)}};
    const std::string line = report.dump(-1, ' ', true, Json::error_handler_t::replace) + "\n";
    DWORD written = 0;
    if (!WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), line.data(), static_cast<DWORD>(line.size()), &written, nullptr) ||
        written != line.size() || !success)
    {
        ExitCode = 3;
    }
    m_frame.CallAfter(
        [frame = &m_frame]()
        {
            frame->Close();
        });
}
