/** @file @brief 출력 작업 공간을 기존 프로젝트, 서비스 및 CAD View에 연결한다. */
#include "studio_internal.h"
#include "output_controller.h"
#include "output_pending_store.h"
#include "output_workspace.h"
#include "editor_sync.h"

void StudioFrame::BuildOutputInterface()
{
    OutputGateway gateway = [this](const std::string& method, const Json& input, bool mutation,
                                   std::function<void(const Json&)> success, std::function<void(const Json&)> failure,
                                   const std::string& key, const std::string& epoch)
    {
        if (!m_connected || m_closing || m_project.empty())
        {
            failure({{"code", "E_STATE"}, {"message", "현재 프로젝트의 출력 서비스에 연결할 수 없습니다."}});
            return;
        }
        const bool job = method == "job.status" || method == "job.cancel";
        Send(method, input, mutation, job ? Json::object() : Context(), std::move(success), std::move(failure), key,
             epoch);
    };
    m_output = std::make_unique<OutputController>(m_views, m_properties, Utf8(m_options.workspace), std::move(gateway));
    m_output->View()->ConditionsView()->Hide();
    m_views->AddPage(m_output->View(), Display("출력"));
    m_outputSummary = m_output->View()->StatusLabel();
    m_output->View()->onImport = [this]()
    {
        OpenPcbImport();
    };
    m_output->onStatus = [this](const std::string& state, const std::string& message)
    {
        if (m_workspaceJobs != nullptr && m_workspaceJobs->GetItemCount() > 3)
        {
            ShowWorkspaceJob(3, state, message);
        }
    };
    m_output->onStateChanged = [this]()
    {
        UpdateControls();
    };
    m_output->onCadResult = [this](const Json& result)
    {
        AcceptCad(result, false);
    };
}

/** @brief 권위 영수증을 확인할 이전 출력이 있으면 편집 상태에서도 작업 전환 잠금을 복원한다. */
void StudioFrame::PrepareOutputRecovery()
{
    if (m_output)
    {
        return;
    }
    bool pending = false;
    try
    {
        pending = OutputPendingStore::Read(Utf8(m_options.workspace), m_project).is_object();
    }
    catch (const std::exception&)
    {
        pending = true;
    }
    if (pending)
    {
        PrepareExtendedWorkspaces(5);
    }
}

void StudioFrame::UpdateOutputViews()
{
    if (!m_output)
    {
        return;
    }
    const bool active = m_views->GetSelection() == 5;
    const bool available = !m_closing && !m_busy && m_setupDialog == nullptr && m_pcbDialog == nullptr &&
                           !m_pcbFeatureUncertain && !m_pcbImportUncertain &&
                           Studio::EditableProject(m_editor, m_scene, m_project, m_revision);
    m_output->Update(m_project, m_revision, m_epoch, m_connected, m_outputSupported, available, active,
                     m_handoffSupported, m_archiveExportSupported);
    m_output->View()->SetImportAvailable(available && m_connected && m_pcbImportSupported && !m_pcbFeatureUncertain &&
                                         !m_pcbImportUncertain && !m_output->Active());
    m_views->SetTabRowVisible(!active);
    m_properties->Layout();
}

void StudioFrame::OpenOutputStep()
{
    if (!m_outputSupported)
    {
        StartCad(true);
        return;
    }
    m_views->SetSelection(5);
    m_output->OpenStep();
}

void StudioFrame::PollOutput(Clock::time_point now)
{
    if (m_output)
    {
        m_output->Poll(now);
    }
}
