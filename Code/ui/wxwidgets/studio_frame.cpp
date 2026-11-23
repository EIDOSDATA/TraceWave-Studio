/** @file @brief 주 창의 frame 책임을 구현한다. */
#include "studio_internal.h"
#include "startup_probe.h"
#include "studio_shell.h"
#include "studio_theme.h"
#include "result_workspace.h"
#include "rf_validation_controller.h"
#include "output_controller.h"
#include <wx/datetime.h>
#include <wx/filename.h>
#include <wx/iconbndl.h>

StudioFrame::StudioFrame(Options options)
    : wxFrame(nullptr, wxID_ANY, Display("TraceWave Studio"), wxDefaultPosition, wxSize(1360, 860)),
      m_options(std::move(options)), m_timer(this, IdTimer), m_started(Clock::now())
{
    SetIcons(wxIconBundle(wxS("TRACEWAVE_STUDIO_ICON"), nullptr));
    try
    {
        m_initialService = std::async(std::launch::async, [this]() { return StartServiceConnection(); });
    }
    catch (const std::system_error&)
    {
        // @brief 시작 스레드를 만들 수 없으면 기존 UI 준비 후 연결 경로를 사용한다.
    }
    StudioTheme::ApplyTypography(*this);
    m_smoke = std::make_unique<StudioSmokeDriver>(*this);
    BuildInterface();
    Bind(wxEVT_TIMER, [this](wxTimerEvent&) { PollService(); }, IdTimer);
    Bind(wxEVT_THREAD, [this](wxThreadEvent&) { PollService(); }, IdProtocolReady);
    Bind(wxEVT_CLOSE_WINDOW, &StudioFrame::OnClose, this);
    Bind(wxEVT_THREAD, &StudioFrame::OnShutdown, this, IdShutdown);
    m_timer.Start(50);
    CallAfter(
        [this, parallel = m_initialService.valid()]()
        {
            if (!parallel || m_initialService.valid())
            {
                Connect();
            }
        });
}

void StudioFrame::EnableStartupProbe()
{
    m_startupProbe = std::make_unique<StartupProbe>(*this);
    m_canvas->onFirstVisiblePaint = [this]()
    {
        m_startupProbe->CanvasPainted();
    };
}

StudioFrame::~StudioFrame()
{
    m_output.reset();
    m_validation.reset();
    m_results.reset();
    m_shell.reset();
    m_manager->UnInit();
    delete m_manager;
}

/** @brief 사건의 첫 문장과 시간, 상세 기술 기록을 동일한 순서로 남긴다. */
void StudioFrame::Log(const std::string& text)
{
    wxWindow* focused = wxWindow::FindFocus();
    const auto raw = Display(text);
    auto headline = raw.BeforeFirst('\n').Trim();
    const auto pathLabel = Display("해석 결과 파일: ");
    if (headline.StartsWith(pathLabel))
    {
        headline = pathLabel + wxFileName(headline.Mid(pathLabel.length())).GetFullName();
    }
    if (headline.length() > 150)
    {
        headline = headline.Left(147) + "...";
    }
    const auto stamp = wxDateTime::Now().FormatISOTime() + "  ";
    m_logSummary->AppendText(stamp + headline + "\n");
    m_log->AppendText(stamp + raw + "\n");
    for (auto* control : {m_logSummary, m_log})
    {
        if (control->GetLastPosition() > 20000)
        {
            control->Remove(0, control->GetLastPosition() - 16000);
        }
    }
    if (focused != nullptr && focused != m_log && focused != m_logSummary &&
        focused->IsEnabled() && focused->IsShownOnScreen())
    {
        focused->SetFocus();
    }
}
