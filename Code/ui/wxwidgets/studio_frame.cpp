/** @file @brief 주 창의 frame 책임을 구현한다. */
#include "studio_internal.h"
#include "startup_probe.h"
#include "studio_shell.h"
#include "studio_theme.h"
#include "result_workspace.h"
#include "rf_validation_controller.h"
#include "output_controller.h"

StudioFrame::StudioFrame(Options options)
    : wxFrame(nullptr, wxID_ANY, Display("TraceWave Studio"), wxDefaultPosition, wxSize(1360, 860)),
      m_options(std::move(options)), m_timer(this, IdTimer), m_started(Clock::now())
{
    StudioTheme::ApplyTypography(*this);
    m_smoke = std::make_unique<StudioSmokeDriver>(*this);
    BuildInterface();
    Bind(wxEVT_TIMER, [this](wxTimerEvent&) { PollService(); }, IdTimer);
    Bind(wxEVT_THREAD, [this](wxThreadEvent&) { PollService(); }, IdProtocolReady);
    Bind(wxEVT_CLOSE_WINDOW, &StudioFrame::OnClose, this);
    Bind(wxEVT_THREAD, &StudioFrame::OnShutdown, this, IdShutdown);
    m_timer.Start(50);
    CallAfter(
        [this]()
        {
            Connect();
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

void StudioFrame::Log(const std::string& text)
{
    wxWindow* focused = wxWindow::FindFocus();
    m_log->AppendText(Display(text) + "\n");
    if (m_log->GetLastPosition() > 20000)
    {
        m_log->Remove(0, m_log->GetLastPosition() - 16000);
    }
    if (focused != nullptr && focused != m_log && focused->IsEnabled() && focused->IsShownOnScreen())
    {
        focused->SetFocus();
    }
}
