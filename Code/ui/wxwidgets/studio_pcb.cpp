/** @file @brief PCB 설정 화면을 기존 비동기 서비스와 프로젝트 갱신 경계에 연결한다. */
#include "studio_internal.h"
#include "pcb_selection_dialog.h"

void StudioFrame::OpenPcbSelection()
{
    if (!m_connected || m_busy || m_project.empty() || m_pcbDialog != nullptr || !m_pcbSelectionSupported)
    {
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this]()
            {
                OpenPcbSelection();
            });
        return;
    }
    m_canvas->CancelGesture();
    m_busy = true;
    UpdateControls();
    const std::string project = m_project;
    Send(
        "pcb.selection.context", Json::object(), false, Context(),
        [this, project](const Json& context)
        {
            if (project != m_project || context.at("project_id") != project || context.at("revision_id") != m_revision)
            {
                Failure("설계 개정이 바뀌었습니다. 저장된 상태를 다시 읽고 기판 설정을 여십시오.");
                return;
            }
            CallAfter(
                [this, context]()
                {
                    ShowPcbSelection(context);
                });
        },
        [this](const Json& error)
        {
            m_busy = false;
            Log("기판 설정을 열지 못했습니다: " + DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::ShowPcbSelection(const Json& context)
{
    if (m_closing || !m_connected)
    {
        m_busy = false;
        UpdateControls();
        return;
    }
    try
    {
        const std::string project = context.at("project_id").get<std::string>();
        if (project != m_project || context.at("revision_id") != m_revision)
        {
            throw std::runtime_error("프로젝트가 바뀌었습니다. 기판 설정을 다시 여십시오.");
        }
        PcbSelectionDialog dialog(
            this, context,
            [this, project](const std::string& method, const Json& input, bool mutation,
                            std::function<void(const Json&)> success, std::function<void(const Json&)> rejected)
            {
                if (!m_connected || project != m_project || m_closing)
                {
                    rejected(Json{{"code", "E_CONFLICT"},
                                  {"message", "프로젝트 연결이 바뀌었습니다. 다시 열어 확인하십시오."}});
                    return;
                }
                Send(method, input, mutation, method.rfind("catalog.", 0) == 0 ? Json::object() : Context(),
                     std::move(success), std::move(rejected));
            });
        m_pcbDialog = &dialog;
        UpdateControls();
        dialog.ShowModal();
        m_pcbDialog = nullptr;
        const Json result = dialog.GetAppliedResult();
        if (m_closeAfterPcb)
        {
            const bool force = m_forceCloseAfterPcb;
            m_closeAfterPcb = false;
            m_forceCloseAfterPcb = false;
            m_busy = false;
            if (!result.empty())
            {
                m_revision = result.at("new_revision").get<std::string>();
            }
            CallAfter(
                [this, force]()
                {
                    Close(force);
                });
            return;
        }
        if (!result.empty() && m_connected && !m_closing)
        {
            m_revision = result.at("new_revision").get<std::string>();
            m_scene = Json::object();
            RefreshEditor(Json{{"kind", "project"}, {"id", m_project}},
                          [this]()
                          {
                              Ready("기판 설정을 적용했습니다. 저장으로 현재 개정을 확정할 수 있습니다.");
                          });
        }
        else
        {
            m_busy = false;
            UpdateControls();
        }
    }
    catch (const std::exception& error)
    {
        m_pcbDialog = nullptr;
        Failure(std::string("기판 설정 화면 오류: ") + error.what());
    }
}
