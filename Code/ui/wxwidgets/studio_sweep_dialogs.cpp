/** @file @brief 원본 개정을 바꾸지 않는 연구 설정 창의 수명과 저장 후 권위 조회를 연결한다. */
#include "studio_internal.h"
#include "sweep_dialog.h"
#include "sweep_panel.h"
#include "sweep_result_dialog.h"

void StudioFrame::OpenSweepSetup()
{
    if (!m_connected || !m_sweepSupported || m_closing || m_project.empty() || m_busy || m_sweepPending ||
        m_setupDialog)
    {
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this]()
            {
                OpenSweepSetup();
            });
        return;
    }
    const auto project = m_project;
    const auto revision = m_revision;
    m_busy = true;
    UpdateControls();
    Send(
        "sweep.context", Json::object(), false, Context(),
        [this, project, revision](const Json& context)
        {
            CallAfter(
                [this, project, revision, context]()
                {
                    if (!m_closing && m_connected && project == m_project && revision == m_revision &&
                        context.at("revision_id") == revision)
                    {
                        ShowSweepSetup(context);
                    }
                    else if (!m_closing)
                    {
                        m_busy = false;
                        UpdateControls();
                    }
                });
        },
        [this](const Json& error)
        {
            m_busy = false;
            m_sweepPanel->SetStatus(DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::ShowSweepSetup(const Json& context)
{
    try
    {
        auto dialog = std::make_unique<SweepDialog>(this, context, ObjectToolGateway());
        m_setupDialog = dialog.get();
        m_canvas->CancelGesture();
        UpdateControls();
        dialog->ShowModal();
        const auto result = dialog->GetAppliedResult();
        const bool reload = dialog->NeedsReload();
        m_setupDialog = nullptr;
        m_busy = false;
        if (m_closeAfterSetup)
        {
            const bool force = m_forceCloseAfterSetup;
            m_closeAfterSetup = false;
            m_forceCloseAfterSetup = false;
            CallAfter(
                [this, force]()
                {
                    Close(force);
                });
            return;
        }
        if (reload && m_connected && !m_closing)
        {
            m_scene = Json::object();
            OpenProject("open", m_path);
        }
        else if (m_connected && !m_closing)
        {
            m_views->SetSelection(8);
            RefreshSweeps(result.is_object() ? result.value("study_id", "") : m_sweepPanel->StudyId());
        }
        UpdateControls();
    }
    catch (const std::exception& error)
    {
        m_setupDialog = nullptr;
        Failure(error.what());
    }
}

void StudioFrame::OpenSweepResult(int index)
{
    if (!m_connected || m_closing || m_busy || m_sweepPending || m_setupDialog || m_sweepPanel->StudyId().empty())
    {
        return;
    }
    const auto project = m_project;
    const auto id = m_sweepPanel->StudyId();
    m_busy = true;
    UpdateControls();
    CallAfter(
        [this, project, id, index]()
        {
            if (m_closing || project != m_project || !m_connected)
            {
                m_busy = false;
                UpdateControls();
                return;
            }
            try
            {
                const Json context{{"project_id", project}, {"revision_id", m_revision}};
                auto dialog = std::make_unique<SweepResultDialog>(this, context, id, index, ObjectToolGateway());
                m_setupDialog = dialog.get();
                UpdateControls();
                dialog->ShowModal();
                m_setupDialog = nullptr;
                m_busy = false;
                if (m_closeAfterSetup)
                {
                    const bool force = m_forceCloseAfterSetup;
                    m_closeAfterSetup = false;
                    m_forceCloseAfterSetup = false;
                    CallAfter(
                        [this, force]()
                        {
                            Close(force);
                        });
                    return;
                }
                UpdateControls();
            }
            catch (const std::exception& error)
            {
                m_setupDialog = nullptr;
                Failure(error.what());
            }
        });
}
