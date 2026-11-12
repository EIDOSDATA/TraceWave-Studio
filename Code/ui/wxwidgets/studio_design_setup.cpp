/** @file @brief 목표/템플릿 화면을 기존 요청/명령/개정과 연결한다. */
#include "studio_internal.h"
#include "target_editor_dialog.h"
#include "template_dialog.h"

void StudioFrame::OpenDesignSetup(bool templates)
{
    if (!m_connected || m_busy || m_project.empty() || m_setupDialog != nullptr ||
        !(templates ? m_templatesSupported : m_targetsSupported))
    {
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this, templates]()
            {
                OpenDesignSetup(templates);
            });
        return;
    }
    m_canvas->CancelGesture();
    m_busy = true;
    UpdateControls();
    const std::string project = m_project;
    const std::string revision = m_revision;
    Json input{{"expected_revision", revision}};
    if (!templates)
    {
        input["target_id"] = nullptr;
    }
    Send(
        templates ? "template.context" : "target.editor.get", input, false, Context(),
        [this, project, revision, templates](const Json& context)
        {
            if (m_closing || project != m_project || revision != m_revision || context.at("project_id") != project ||
                context.value("revision_id", context.value("expected_revision", std::string())) != revision)
            {
                Failure("프로젝트 개정이 바뀌었습니다. 최신 상태를 다시 읽고 설정을 여세요.");
                return;
            }
            CallAfter(
                [this, context, templates]()
                {
                    ShowDesignSetup(context, templates);
                });
        },
        [this](const Json& error)
        {
            m_busy = false;
            Log("설정 화면을 열지 못했습니다: " + DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::ShowDesignSetup(const Json& context, bool templates)
{
    if (m_closing || !m_connected || context.at("project_id") != m_project ||
        context.value("revision_id", context.value("expected_revision", std::string())) != m_revision)
    {
        m_busy = false;
        UpdateControls();
        return;
    }
    try
    {
        const std::string project = m_project;
        DialogGateway gateway = [this, project](const std::string& method, const Json& input, bool mutation,
                                                std::function<void(const Json&)> success,
                                                std::function<void(const Json&)> rejected)
        {
            if (m_closing || !m_connected || project != m_project)
            {
                rejected(
                    Json{{"code", "E_CONNECTION"}, {"message", "프로젝트 연결이 바뀌었습니다. 다시 열어 확인하세요."}});
                return;
            }
            Send(method, input, mutation, Context(), std::move(success), std::move(rejected));
        };
        std::unique_ptr<ProjectSetupDialog> dialog;
        if (templates)
        {
            dialog = std::make_unique<TemplateDialog>(this, context, gateway);
        }
        else
        {
            dialog = std::make_unique<TargetEditorDialog>(this, context, gateway);
        }
        m_setupDialog = dialog.get();
        UpdateControls();
        dialog->ShowModal();
        const Json result = dialog->GetAppliedResult();
        const bool needsReload = dialog->NeedsReload();
        m_setupDialog = nullptr;
        if (!result.is_null())
        {
            m_revision = result.at("new_revision").get<std::string>();
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
            m_scene = Json::object();
            RefreshEditor(Json{{"kind", "project"}, {"id", m_project}},
                          [this]()
                          {
                              Ready("설정 변경을 적용했습니다. 저장으로 현재 개정을 확정할 수 있습니다.");
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
        Failure(std::string("설정 화면 오류: ") + error.what());
    }
}
