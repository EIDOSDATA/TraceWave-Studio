/** @file @brief 주 창의 frame 책임을 구현한다. */
#include "studio_internal.h"

StudioFrame::StudioFrame(Options options)
    : wxFrame(nullptr, wxID_ANY, Display("TraceWave Studio"), wxDefaultPosition, wxSize(1360, 860)),
      m_options(std::move(options)), m_timer(this, IdTimer), m_started(Clock::now())
{
    m_smoke = std::make_unique<StudioSmokeDriver>(*this);
    BuildInterface();
    Bind(wxEVT_TIMER, &StudioFrame::OnTimer, this, IdTimer);
    Bind(wxEVT_CLOSE_WINDOW, &StudioFrame::OnClose, this);
    Bind(wxEVT_THREAD, &StudioFrame::OnShutdown, this, IdShutdown);
    m_timer.Start(50);
    CallAfter(
        [this]()
        {
            Connect();
        });
}

StudioFrame::~StudioFrame()
{
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
