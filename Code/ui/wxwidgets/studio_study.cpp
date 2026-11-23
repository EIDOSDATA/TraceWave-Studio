/** @file @brief 주 창과 일반 프로젝트 연구 창을 공개 서비스 경계로 연결한다. */
#include "studio_internal.h"
#include "project_study_dialog.h"

void StudioFrame::OpenProjectStudy(const std::string& identity)
{
    if (m_studyDialog != nullptr)
    {
        m_studyDialog->SelectStudy(identity);
        m_studyDialog->Raise();
        return;
    }
    if (!m_connected || m_busy || m_project.empty() || !m_studySupported)
    {
        return;
    }
    if (identity.empty() && HasDraft())
    {
        ApplyCurrent([this, identity]() { OpenProjectStudy(identity); });
        return;
    }
    const std::string project = m_project;
    Send("study.context", Json::object(), false, Context(), [this, project, identity](const Json& context)
    {
        if (m_closing || project != m_project || m_studyDialog != nullptr)
        {
            return;
        }
        m_studyDialog = new ProjectStudyDialog(this, context,
            [this, project](const std::string& method, const Json& input, bool mutation,
                            std::function<void(const Json&)> success, std::function<void(const Json&)> rejected)
            {
                if (!m_connected || m_closing || project != m_project)
                {
                    rejected(Json{{"message", "프로젝트 연결이 바뀌었습니다. 연구 창을 다시 여십시오."}});
                    return;
                }
                Send(method, input, mutation, Context(), std::move(success), std::move(rejected));
            }, [this]()
            {
                m_studyDialog = nullptr;
                if (!m_closing)
                {
                    UpdateControls();
                }
            });
        m_studyDialog->SelectStudy(identity);
        m_studyDialog->Show();
        UpdateControls();
    });
}
