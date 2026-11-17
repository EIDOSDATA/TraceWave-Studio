/** @file @brief 객체 편집 대화상자의 수명과 개정 갱신을 기존 연결 경계에 결합한다. */
#include "studio_internal.h"
#include "project_setup_dialog.h"

DialogGateway StudioFrame::ObjectToolGateway()
{
    const std::string project = m_project;
    return [this, project](const std::string& method, const Json& input, bool mutation,
                           std::function<void(const Json&)> success, std::function<void(const Json&)> rejected)
    {
        if (m_closing || !m_connected || project != m_project)
        {
            rejected({{"code", "E_CONNECTION"}, {"message", "프로젝트 연결이 바뀌었습니다. 다시 열어 확인하세요."}});
            return;
        }
        Send(method, input, mutation, Context(), std::move(success), std::move(rejected));
    };
}

void StudioFrame::ShowObjectTool(std::unique_ptr<ProjectSetupDialog> dialog, const Json& selection)
{
    m_canvas->CancelGesture();
    m_setupDialog = dialog.get();
    UpdateControls();
    try
    {
        dialog->ShowModal();
        const Json result = dialog->GetAppliedResult();
        const bool needsReload = dialog->NeedsReload();
        m_setupDialog = nullptr;
        if (!result.is_null())
        {
            m_revision = result.at("new_revision");
            const std::string operation = result.value("operation", "");
            if (result.contains("record_id") && (operation == "import" || operation == "solver" ||
                                                 operation == "transform" || operation == "circuit_apply"))
            {
                m_networkPreferredId = result.at("record_id");
            }
            else if (result.contains("record_id") && operation == "evaluate")
            {
                m_networkAssessmentPreferredId = result.at("record_id");
                if (m_views->GetSelection() == 6 || m_views->GetSelection() == 7)
                {
                    m_views->SetSelection(7);
                }
            }
        }
        if (m_closeAfterSetup)
        {
            const bool force = m_forceCloseAfterSetup;
            m_closeAfterSetup = false;
            m_forceCloseAfterSetup = false;
            m_busy = false;
            CallAfter(
                [this, force]()
                {
                    Close(force);
                });
            return;
        }
        if (needsReload && m_connected && !m_closing)
        {
            m_scene = Json::object();
            OpenProject("open", m_path);
        }
        else if (!result.is_null() && m_connected && !m_closing)
        {
            Json target = selection;
            if (result.value("selection", Json(nullptr)).is_object())
            {
                target = result.at("selection");
            }
            else if (result.contains("selection_ids") && !result.at("selection_ids").empty())
            {
                target = {{"kind", "geometry"}, {"id", result.at("selection_ids").front()}};
            }
            RefreshEditor(target,
                          [this]()
                          {
                              Ready("편집을 적용했습니다. 저장으로 현재 개정을 확정할 수 있습니다.");
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
        m_setupDialog = nullptr;
        Failure(error.what());
    }
}
