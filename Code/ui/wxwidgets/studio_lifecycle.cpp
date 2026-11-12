/** @file @brief 주 창의 lifecycle 책임을 구현한다. */
#include "studio_internal.h"
#include "pcb_selection_dialog.h"
#include "project_study_dialog.h"
#include "project_setup_dialog.h"

void StudioFrame::Failure(const std::string& message, bool disconnected)
{
    Log(message);
    m_busy = false;
    m_foregroundTask.Reset();
    m_jobComplete = {};
    if (disconnected)
    {
        if (m_setupDialog != nullptr)
        {
            m_setupDialog->ServiceDisconnected(message);
        }
        if (m_studyDialog != nullptr)
        {
            m_studyDialog->ServiceDisconnected(message);
        }
        if (m_pcbDialog != nullptr)
        {
            m_pcbDialog->ServiceDisconnected(message);
        }
        m_requests.Clear();
        m_connected = false;
        m_cadPreparing = false;
        m_cadTask.AbandonPoll();
        if (!m_cadTask.Id().empty())
        {
            CadStatus(
                "disconnected",
                "CAD 서비스 연결이 끊겼습니다. 완료 여부를 추정하지 않습니다. 재열기 후 보존된 결과를 확인하세요.");
        }
        m_solverTask.AbandonPoll();
        if (m_solverWorkflow.Active())
        {
            SolverStatus(
                "disconnected",
                "해석 서비스 연결이 끊겼습니다. guest 종료와 완료 여부를 추정하지 않으며 자동 재실행하지 않습니다.");
        }
    }
    SetStatusText(Display(disconnected ? "서비스 연결 끊김" : "작업 실패"), 0);
    if (m_cadPreparing)
    {
        m_cadPreparing = false;
        CadStatus("failed", message);
    }
    UpdateControls();
    if (m_options.smoke)
    {
        m_smoke->FinishSmoke(false, message);
    }
}

void StudioFrame::Ready(const std::string& message)
{
    m_busy = false;
    SetStatusText(Display("준비됨"), 0);
    Log(message);
    UpdateControls();
}

void StudioFrame::OnClose(wxCloseEvent& event)
{
    if (m_closing)
    {
        return;
    }
    if (m_studyDialog != nullptr)
    {
        m_studyDialog->Close();
    }
    if (m_setupDialog != nullptr)
    {
        const bool force = !event.CanVeto();
        if (force)
        {
            m_setupDialog->ServiceDisconnected("프로그램 종료 요청으로 적용 결과를 다시 확인해야 합니다.");
        }
        if (m_setupDialog->Close(force))
        {
            m_closeAfterSetup = true;
            m_forceCloseAfterSetup = force;
        }
        if (event.CanVeto())
        {
            event.Veto();
        }
        return;
    }
    /** @brief 스택 소유 대화상자가 반환되기 전에 부모와 자식을 파괴하지 않는다. */
    if (m_pcbDialog != nullptr)
    {
        const bool force = !event.CanVeto();
        if (force)
        {
            m_pcbDialog->ServiceDisconnected("프로그램 종료 요청으로 적용 결과를 다시 확인해야 합니다.");
        }
        if (m_pcbDialog->Close(force))
        {
            m_closeAfterPcb = true;
            m_forceCloseAfterPcb = force;
        }
        if (event.CanVeto())
        {
            event.Veto();
        }
        return;
    }
    if (!m_waitingClose && !m_finishing && !m_options.smoke && !ConfirmDiscard())
    {
        if (event.CanVeto())
        {
            event.Veto();
        }
        return;
    }
    if (!m_waitingClose && m_connected && (m_solverWorkflow.Active() || m_cadPreparing || !m_cadTask.Id().empty()) &&
        event.CanVeto())
    {
        m_waitingClose = true;
        m_closeDeadline = Clock::now() + std::chrono::seconds(30);
        CancelSolver();
        CancelCad();
        SetStatusText(Display("작업 취소와 실제 종료를 확인한 뒤 창을 닫습니다."), 0);
        Disable();
        event.Veto();
        return;
    }
    m_closing = true;
    m_timer.Stop();
    Disable();
    Hide();
    if (!m_restarting)
    {
        BeginShutdown();
    }
}

/** @brief 화면 수명을 유지한 채 서비스 종료와 pipe join을 UI 밖에서 수행한다. */
void StudioFrame::BeginShutdown()
{
    try
    {
        m_shutdown = std::thread(
            [this]()
            {
                m_client.Stop();
                wxQueueEvent(this, new wxThreadEvent(wxEVT_THREAD, IdShutdown));
            });
    }
    catch (const std::exception& error)
    {
        m_client.Stop();
        if (m_closing)
        {
            Destroy();
        }
        else
        {
            m_restarting = false;
            Failure(std::string("Cannot start shutdown thread: ") + error.what(), true);
        }
    }
}

/** @brief 종료 thread가 pipe를 모두 회수한 뒤 창을 파괴하거나 smoke 연결을 재개한다. */
void StudioFrame::OnShutdown(wxThreadEvent&)
{
    m_shutdown.join();
    if (m_closing)
    {
        m_smoke->OnPcbShutdownComplete();
        Destroy();
    }
    else
    {
        m_restarting = false;
        Connect();
    }
}
